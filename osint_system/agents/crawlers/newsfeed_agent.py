"""NewsFeedAgent: Async news crawler with rate limiting and RSS feed integration.

Features:
- Async HTTP client with connection pooling and proper rate limiting
- Token bucket rate limiting with per-source overrides
- RSS feed parsing via RSSCrawler (feedparser)
- NewsAPI search integration for broader coverage
- Investigation-driven fetching with context awareness
- Source rotation to avoid hitting single sources too frequently
- Unified normalization of articles from multiple sources
"""

import asyncio
import time
import random
from datetime import datetime, timezone
from typing import Optional, Any, Dict, List
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, AsyncRetrying
from loguru import logger

from osint_system.agents.crawlers.base_crawler import BaseCrawler
from osint_system.agents.crawlers.sources.rss_crawler import RSSCrawler
from osint_system.agents.crawlers.sources.api_crawler import NewsAPIClient
from osint_system.agents.crawlers.deduplication.dedup_engine import DeduplicationEngine, Article as DedupArticle
from osint_system.agents.crawlers.extractors.metadata_parser import MetadataParser
from osint_system.config.news_sources import NEWS_SOURCES, NEWS_API_CONFIG
from osint_system.data_management.article_store import ArticleStore
from osint_system.agents.communication.bus import MessageBus


class TokenBucketLimiter:
    """Token bucket rate limiter for controlling request rates.

    Implements the token bucket algorithm for smooth request distribution
    while allowing controlled bursts. Each source can have its own rate limit.

    Attributes:
        max_requests_per_second: Maximum sustained request rate
        semaphore: Asyncio semaphore for concurrency control
        last_acquired: Timestamp of last token acquisition
        min_interval: Minimum interval between requests
    """

    def __init__(self, max_requests_per_second: float = 10.0):
        """
        Initialize token bucket limiter.

        Args:
            max_requests_per_second: Maximum number of requests per second.
                                    Default 10 req/sec respects most API limits.
        """
        self.max_requests_per_second = max_requests_per_second
        self.semaphore = asyncio.Semaphore(max(1, int(max_requests_per_second)))
        self.min_interval = 1.0 / max_requests_per_second
        self.last_acquired = time.monotonic()
        logger.debug(
            "TokenBucketLimiter initialized",
            max_requests_per_second=max_requests_per_second,
            min_interval=self.min_interval,
        )

    async def acquire(self) -> None:
        """
        Acquire a token, blocking until one is available.

        Ensures minimum interval between requests to maintain rate limit.
        Uses semaphore for concurrency control.
        """
        async with self.semaphore:
            # Enforce minimum interval between requests
            elapsed = time.monotonic() - self.last_acquired
            if elapsed < self.min_interval:
                await asyncio.sleep(self.min_interval - elapsed)
            self.last_acquired = time.monotonic()


class NewsFeedAgent(BaseCrawler):
    """
    Async news crawler for fetching content from RSS/Atom feeds and web sources.

    Core Features:
    - Async HTTP client with proper connection pooling
    - Token bucket rate limiting with per-source overrides
    - Retry logic with exponential backoff via tenacity
    - Source configuration management
    - Investigation context integration
    - Comprehensive error handling and logging

    Typical usage:
        agent = NewsFeedAgent(
            source_configs={
                'bbc': {'url': 'http://feeds.bbci.co.uk/news/rss.xml', 'rate_limit': 10},
                'reuters': {'url': 'http://feeds.reuters.com/reuters/topNews', 'rate_limit': 5}
            }
        )
        async with agent as agent_instance:
            result = await agent_instance.process({'sources': ['bbc', 'reuters']})

    Attributes:
        http_client: httpx.AsyncClient for HTTP operations
        rate_limiters: Dict mapping source names to TokenBucketLimiter instances
        default_rate_limit: Default requests per second (10 req/sec)
        http_timeout: HTTP request timeout in seconds
        max_retries: Maximum retry attempts for failed requests
    """

    def __init__(
        self,
        source_configs: Optional[dict] = None,
        investigation_context: Optional[dict] = None,
        default_rate_limit: float = 10.0,
        http_timeout: float = 30.0,
        max_retries: int = 3,
        mcp_enabled: bool = False,
        mcp_server_command: Optional[list[str]] = None,
        article_store: Optional[ArticleStore] = None,
        message_bus: Optional[MessageBus] = None,
    ):
        """
        Initialize NewsFeedAgent with async infrastructure.

        Args:
            source_configs: Dictionary of source configurations.
                          Format: {'source_name': {'url': '...', 'rate_limit': N}}
            investigation_context: Optional context about current investigation
            default_rate_limit: Default rate limit in requests per second (default: 10)
            http_timeout: HTTP request timeout in seconds (default: 30)
            max_retries: Maximum retry attempts for transient failures (default: 3)
            mcp_enabled: Whether to enable MCP client for tool access
            mcp_server_command: Command to start MCP server
            article_store: Optional ArticleStore instance for persistence
            message_bus: Optional MessageBus instance for A2A communication
        """
        super().__init__(
            name="NewsFeedAgent",
            description="Async news crawler for RSS feeds and web content",
            source_configs=source_configs,
            investigation_context=investigation_context,
            mcp_enabled=mcp_enabled,
            mcp_server_command=mcp_server_command,
        )

        self.http_client: Optional[httpx.AsyncClient] = None
        self.rate_limiters: dict[str, TokenBucketLimiter] = {}
        self.default_rate_limit = default_rate_limit
        self.http_timeout = http_timeout
        self.max_retries = max_retries

        # Initialize rate limiters for configured sources
        self._init_rate_limiters()

        # Initialize deduplication and metadata extraction components
        self.dedup_engine = DeduplicationEngine(semantic_threshold=0.85)
        self.metadata_parser = MetadataParser()

        # Initialize storage and message bus
        self.article_store = article_store or ArticleStore()
        self.message_bus = message_bus or MessageBus()
        self._message_subscribed = False

        self.logger.info(
            "NewsFeedAgent initialized",
            default_rate_limit=default_rate_limit,
            http_timeout=http_timeout,
            max_retries=max_retries,
            num_sources=len(self.source_configs),
            storage_enabled=article_store is not None,
            message_bus_enabled=message_bus is not None,
        )

    def _init_rate_limiters(self) -> None:
        """Initialize rate limiters for all configured sources."""
        for source_name, config in self.source_configs.items():
            # Use source-specific rate limit or fall back to default
            rate_limit = config.get("rate_limit", self.default_rate_limit)
            self.rate_limiters[source_name] = TokenBucketLimiter(rate_limit)
            self.logger.debug(
                f"Rate limiter initialized for {source_name}",
                rate_limit=rate_limit,
            )

    async def __aenter__(self):
        """Async context manager entry - initialize HTTP client, MCP, and message bus."""
        # Initialize HTTP client with connection pooling and proper headers
        limits = httpx.Limits(max_keepalive_connections=5, max_connections=20)
        self.http_client = httpx.AsyncClient(
            timeout=self.http_timeout,
            limits=limits,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; OSINTBot/1.0; +https://github.com/smit-shah-GG/osint_double)"
            },
        )
        self.logger.debug("HTTP client initialized with connection pooling")

        # Subscribe to message bus topics
        if not self._message_subscribed:
            await self._subscribe_to_topics()
            self._message_subscribed = True

        # Initialize MCP if enabled
        await super().__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - cleanup HTTP client and MCP."""
        # Close HTTP client
        if self.http_client:
            await self.http_client.aclose()
            self.logger.debug("HTTP client closed")

        # Cleanup MCP
        await super().__aexit__(exc_type, exc_val, exc_tb)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def _fetch_with_retry(self, url: str) -> httpx.Response:
        """
        Fetch URL with automatic retry on transient failures.

        Uses exponential backoff: 2s, 4s, 8s, ...

        Args:
            url: URL to fetch

        Returns:
            httpx.Response object

        Raises:
            httpx.HTTPError: If all retries fail
        """
        if not self.http_client:
            raise RuntimeError("HTTP client not initialized")

        response = await self.http_client.get(url, follow_redirects=True)
        response.raise_for_status()
        return response

    async def _get_rate_limiter(self, source: str) -> TokenBucketLimiter:
        """
        Get or create rate limiter for source.

        If source not in configured sources, create a rate limiter using
        the default rate limit.

        Args:
            source: Source identifier

        Returns:
            TokenBucketLimiter instance for this source
        """
        if source not in self.rate_limiters:
            self.rate_limiters[source] = TokenBucketLimiter(self.default_rate_limit)
            self.logger.debug(
                f"Created default rate limiter for {source}",
                rate_limit=self.default_rate_limit,
            )
        return self.rate_limiters[source]

    async def fetch_data(
        self, source: str, url: Optional[str] = None, **kwargs
    ) -> dict:
        """
        Fetch raw data from a news source.

        If source is in source_configs, uses the configured URL. Otherwise,
        expects url parameter.

        Args:
            source: Source identifier (key in source_configs) or source name
            url: Optional URL override (uses configured URL if source in source_configs)
            **kwargs: Additional parameters (preserved in metadata)

        Returns:
            Dictionary containing:
            - raw_content: Raw HTTP response text
            - status_code: HTTP status code
            - headers: Response headers (dict)
            - retrieved_at: UTC timestamp of retrieval
            - source: Source identifier
            - url: URL fetched
            - error: Error message if fetch failed (optional)

        Example:
            result = await agent.fetch_data('bbc')
            # Or with explicit URL:
            result = await agent.fetch_data('custom_source', url='https://example.com/feed')
        """
        # Resolve URL
        if source in self.source_configs:
            fetch_url = self.source_configs[source].get("url", url)
        else:
            fetch_url = url

        if not fetch_url:
            error_msg = f"No URL configured for source {source}"
            self.logger.error(error_msg)
            return {
                "raw_content": None,
                "status_code": None,
                "headers": {},
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "source": source,
                "url": None,
                "error": error_msg,
            }

        # Apply rate limiting
        limiter = await self._get_rate_limiter(source)
        await limiter.acquire()

        try:
            self.logger.debug(f"Fetching data from {source}", url=fetch_url)
            response = await self._fetch_with_retry(fetch_url)

            result = {
                "raw_content": response.text,
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "source": source,
                "url": str(response.url),
                "error": None,
            }

            self.logger.info(
                f"Successfully fetched data from {source}",
                status_code=response.status_code,
                content_length=len(response.text),
            )
            return result

        except httpx.TimeoutException:
            error_msg = f"Timeout fetching from {source}: {fetch_url}"
            self.logger.error(error_msg)
            return {
                "raw_content": None,
                "status_code": None,
                "headers": {},
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "source": source,
                "url": fetch_url,
                "error": error_msg,
            }

        except httpx.HTTPError as e:
            error_msg = f"HTTP error fetching from {source}: {str(e)}"
            self.logger.error(error_msg)
            return {
                "raw_content": None,
                "status_code": None,
                "headers": {},
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "source": source,
                "url": fetch_url,
                "error": error_msg,
            }

    async def filter_relevance(self, data: dict) -> bool:
        """
        Determine if fetched data is relevant to investigation.

        NewsFeedAgent does minimal filtering - returns True for all
        non-error data, letting downstream agents handle prioritization.

        Args:
            data: Fetched data dictionary

        Returns:
            False only if fetch failed or no content, True otherwise
        """
        # Only filter out failures
        if data.get("error") or not data.get("raw_content"):
            return False
        return True

    async def extract_metadata(self, data: dict) -> dict:
        """
        Extract standardized metadata from fetched data.

        Preserves source credibility context and retrieval information.

        Args:
            data: Fetched data with embedded metadata

        Returns:
            Standardized metadata dictionary with:
            - source: Source identifier
            - url: URL fetched
            - retrieved_at: UTC timestamp
            - content_length: Length of raw content
            - status_code: HTTP status code
            - headers: Response headers
            - investigation_context: Context from agent initialization
        """
        return {
            "source": data.get("source"),
            "url": data.get("url"),
            "retrieved_at": data.get("retrieved_at"),
            "content_length": len(data.get("raw_content", "")),
            "status_code": data.get("status_code"),
            "headers": data.get("headers", {}),
            "investigation_context": self.investigation_context,
        }

    async def process(self, input_data: dict) -> dict:
        """
        Process input to fetch news data from specified sources.

        Core execution method that orchestrates fetching from multiple sources
        with rate limiting and error handling.

        Args:
            input_data: Dictionary containing:
            - sources: List of source identifiers to crawl
            - urls: Optional dict mapping source names to URLs
            - investigation_context: Optional updated investigation context

        Returns:
            Dictionary containing:
            - success: Boolean indicating if processing succeeded
            - results: List of fetch results per source
            - failed_sources: List of sources that failed
            - success_count: Number of successful fetches
            - total_count: Total sources attempted
            - error: Error message if critical failure occurred

        Example:
            result = await agent.process({
                'sources': ['bbc', 'reuters'],
                'investigation_context': {'target': 'election_news'}
            })
        """
        try:
            # Update investigation context if provided
            if "investigation_context" in input_data:
                self.investigation_context.update(input_data["investigation_context"])

            sources = input_data.get("sources", [])
            if not sources:
                return {
                    "success": False,
                    "error": "No sources specified",
                    "results": [],
                    "failed_sources": [],
                    "success_count": 0,
                    "total_count": 0,
                }

            self.logger.info(
                "Processing news fetch request",
                sources=sources,
                investigation_context=self.investigation_context,
            )

            # Fetch from all sources concurrently
            fetch_tasks = []
            for source in sources:
                # Check for URL override
                url = None
                if "urls" in input_data and source in input_data["urls"]:
                    url = input_data["urls"][source]

                fetch_tasks.append(self.fetch_data(source, url=url))

            fetch_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

            # Process results
            results = []
            failed_sources = []

            for source, result in zip(sources, fetch_results):
                if isinstance(result, Exception):
                    self.logger.error(
                        f"Exception fetching from {source}",
                        error=str(result),
                    )
                    failed_sources.append(source)
                    results.append(
                        {
                            "source": source,
                            "error": str(result),
                        }
                    )
                elif result.get("error"):
                    failed_sources.append(source)
                    results.append(result)
                else:
                    results.append(result)

            return {
                "success": len(failed_sources) == 0,
                "results": results,
                "failed_sources": failed_sources,
                "success_count": len(results) - len(failed_sources),
                "total_count": len(sources),
                "error": None if failed_sources == [] else f"{len(failed_sources)} sources failed",
            }

        except Exception as e:
            self.logger.exception("Critical error in NewsFeedAgent.process")
            return {
                "success": False,
                "error": f"Critical error: {str(e)}",
                "results": [],
                "failed_sources": input_data.get("sources", []),
                "success_count": 0,
                "total_count": len(input_data.get("sources", [])),
            }

    async def fetch_investigation_data(
        self, query: str, use_api: bool = True, use_rss: bool = True,
        limit_rss_sources: Optional[int] = None,
        exhaustive_mode: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Unified fetcher implementing RSS-first strategy with API supplementation.

        Core workflow for investigation-driven queries:
        1. Fetch from configured RSS feeds first (more reliable/consistent)
        2. Supplement with NewsAPI search for broader coverage
        3. Extract comprehensive metadata for each article
        4. Apply three-layer deduplication (URL, content hash, semantic)
        5. Return deduplicated articles with complete metadata

        Args:
            query: Investigation query/search terms
            use_api: Whether to use NewsAPI supplementation (default: True)
            use_rss: Whether to use RSS feeds (default: True)
            limit_rss_sources: Limit RSS sources to top N (by authority). None = all
            exhaustive_mode: If True, returns all relevant content regardless of age
            **kwargs: Additional context to preserve in articles

        Returns:
            Dictionary containing:
            - success: Boolean indicating if at least some data was fetched
            - articles: List of deduplicated articles with full metadata
            - rss_articles: Count of articles from RSS
            - api_articles: Count of articles from API
            - total_articles: Total unique articles after deduplication
            - dedup_stats: Deduplication statistics
            - source_breakdown: Per-source article counts
            - errors: List of any errors encountered

        Example:
            result = await agent.fetch_investigation_data(
                query="Syria conflict",
                exhaustive_mode=True,
                investigation_context={"target": "middle_east_stability"}
            )
        """
        articles = []
        rss_count = 0
        api_count = 0
        source_breakdown = {}
        errors = []

        self.logger.info(
            "Starting investigation data fetch",
            query=query,
            use_rss=use_rss,
            use_api=use_api,
        )

        try:
            # Step 1: Fetch from RSS feeds first (RSS-first strategy)
            if use_rss:
                try:
                    rss_articles = await self._fetch_from_rss_feeds(
                        query=query,
                        limit_sources=limit_rss_sources,
                        **kwargs
                    )
                    articles.extend(rss_articles)
                    rss_count = len(rss_articles)

                    # Count by source
                    for article in rss_articles:
                        source = article.get("source", {}).get("name", "Unknown")
                        source_breakdown[source] = source_breakdown.get(source, 0) + 1

                    self.logger.info(f"Fetched {rss_count} articles from RSS feeds")

                except Exception as e:
                    error_msg = f"Error fetching RSS feeds: {str(e)}"
                    self.logger.error(error_msg)
                    errors.append(error_msg)

            # Step 2: Supplement with NewsAPI search
            if use_api:
                try:
                    api_articles = await self._fetch_from_news_api(
                        query=query,
                        **kwargs
                    )
                    articles.extend(api_articles)
                    api_count = len(api_articles)

                    # Count by source
                    for article in api_articles:
                        source = article.get("source", {}).get("name", "Unknown")
                        source_breakdown[source] = source_breakdown.get(source, 0) + 1

                    self.logger.info(f"Fetched {api_count} articles from NewsAPI")

                except Exception as e:
                    error_msg = f"Error fetching from NewsAPI: {str(e)}"
                    self.logger.warning(error_msg)
                    errors.append(error_msg)

            # Step 3: Extract comprehensive metadata for each article
            self.logger.debug("Extracting metadata for all articles")
            for article in articles:
                # Parse metadata
                metadata = self.metadata_parser.parse(
                    url=article.get("url", ""),
                    content=article.get("content", ""),
                    html=article.get("html"),  # If available from source
                    published_date=article.get("published_date")
                )

                # Merge metadata into article
                article["metadata"] = {
                    **article.get("metadata", {}),
                    **metadata.to_dict()
                }

            # Step 4: Apply three-layer deduplication
            self.logger.info("Applying three-layer deduplication")

            # Convert to DedupArticle format for deduplication
            dedup_articles = []
            for article in articles:
                dedup_article = DedupArticle(
                    url=article.get("url", ""),
                    title=article.get("title", ""),
                    content=article.get("content", ""),
                    metadata=article.get("metadata", {}),
                    published_date=article.get("published_date"),
                    source=article.get("source", {}).get("name", "Unknown")
                )
                dedup_articles.append(dedup_article)

            # Apply deduplication
            unique_dedup_articles, dedup_stats = self.dedup_engine.deduplicate_articles(dedup_articles)

            # Convert back to dict format with complete metadata
            unique_articles = []
            for dedup_article in unique_dedup_articles:
                # Find original article with all fields
                for orig_article in articles:
                    if orig_article.get("url") == dedup_article.url:
                        unique_articles.append(orig_article)
                        break

            # If exhaustive mode, don't filter by age (returns everything relevant)
            if not exhaustive_mode:
                # In normal mode, could add age filtering here if desired
                pass

            self.logger.info(
                "Investigation data fetch complete",
                total_articles_fetched=len(articles),
                unique_articles=len(unique_articles),
                rss_articles=rss_count,
                api_articles=api_count,
                dedup_stats=dedup_stats.to_dict() if dedup_stats else None,
            )

            return {
                "success": len(unique_articles) > 0,
                "articles": unique_articles,
                "rss_articles": rss_count,
                "api_articles": api_count,
                "total_articles": len(unique_articles),
                "dedup_stats": dedup_stats.to_dict() if dedup_stats else None,
                "source_breakdown": source_breakdown,
                "errors": errors,
                "query": query,
                "exhaustive_mode": exhaustive_mode,
            }

        except Exception as e:
            error_msg = f"Critical error in fetch_investigation_data: {str(e)}"
            self.logger.exception(error_msg)
            return {
                "success": False,
                "articles": [],
                "rss_articles": 0,
                "api_articles": 0,
                "total_articles": 0,
                "source_breakdown": {},
                "errors": [error_msg],
                "query": query,
            }

    async def _fetch_from_rss_feeds(
        self,
        query: str,
        limit_sources: Optional[int] = None,
        **kwargs
    ) -> list[Dict[str, Any]]:
        """
        Fetch articles from configured RSS feeds.

        Implements source rotation to avoid hitting single sources too frequently.

        Args:
            query: Search/investigation query for context
            limit_sources: Limit to top N sources by authority (None = all)
            **kwargs: Context to preserve

        Returns:
            List of normalized articles from RSS feeds
        """
        articles = []
        rss_crawler = RSSCrawler()

        # Select sources with rotation
        sources_to_fetch = self._select_rss_sources(limit=limit_sources)
        self.logger.debug(f"Fetching from {len(sources_to_fetch)} RSS feeds")

        # Fetch from all sources concurrently
        fetch_tasks = []
        for source_name in sources_to_fetch:
            source_config = NEWS_SOURCES.get(source_name, {})
            url = source_config.get("url")
            if url:
                fetch_tasks.append(
                    self._fetch_rss_feed(rss_crawler, source_name, url)
                )

        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        # Process results
        for source_name, result in zip(sources_to_fetch, results):
            if isinstance(result, Exception):
                self.logger.warning(
                    f"Error fetching RSS from {source_name}: {str(result)}"
                )
                continue

            if result.get("error"):
                self.logger.warning(
                    f"Error fetching RSS from {source_name}: {result['error']}"
                )
                continue

            # Normalize articles
            feed_articles = result.get("articles", [])
            for article in feed_articles:
                normalized = self._normalize_article(
                    article,
                    source_name=source_name,
                    source_type="rss",
                    **kwargs
                )
                articles.append(normalized)

        return articles

    async def _fetch_rss_feed(
        self,
        rss_crawler: RSSCrawler,
        source_name: str,
        url: str
    ) -> Dict[str, Any]:
        """
        Fetch and parse a single RSS feed.

        Args:
            rss_crawler: RSSCrawler instance
            source_name: Source identifier
            url: Feed URL

        Returns:
            Result dictionary with parsed articles
        """
        try:
            limiter = await self._get_rate_limiter(source_name)
            await limiter.acquire()

            result = await rss_crawler.parse_feed(url)
            return result

        except Exception as e:
            return {
                "error": str(e),
                "source": source_name,
                "articles": [],
            }

    async def _fetch_from_news_api(
        self,
        query: str,
        **kwargs
    ) -> list[Dict[str, Any]]:
        """
        Fetch articles from NewsAPI using search query.

        Args:
            query: Search query
            **kwargs: Context to preserve

        Returns:
            List of normalized articles from NewsAPI
        """
        articles = []

        try:
            async with NewsAPIClient() as client:
                # Search with pagination (max 2 pages to respect rate limits)
                result = await client.search_articles_paginated(
                    query=query,
                    max_pages=2,
                )

                # Normalize articles
                for article in result:
                    normalized = self._normalize_article(
                        article,
                        source_name=article.get("source", {}).get("name", "NewsAPI"),
                        source_type="api",
                        **kwargs
                    )
                    articles.append(normalized)

        except Exception as e:
            self.logger.warning(f"Error fetching from NewsAPI: {str(e)}")

        return articles

    def _select_rss_sources(self, limit: Optional[int] = None) -> list[str]:
        """
        Select RSS sources with rotation to avoid repeated hits.

        Implements source rotation by randomizing selection.

        Args:
            limit: Limit to top N sources by authority

        Returns:
            List of source names to fetch from
        """
        # Sort by authority level descending
        sorted_sources = sorted(
            NEWS_SOURCES.items(),
            key=lambda x: x[1].get("authority_level", 3),
            reverse=True
        )

        # Select top N if limit specified
        if limit:
            selected = sorted_sources[:limit]
        else:
            selected = sorted_sources

        # Randomize order to rotate through sources
        source_names = [name for name, _ in selected]
        random.shuffle(source_names)

        return source_names

    def _normalize_article(
        self,
        article: Dict[str, Any],
        source_name: str,
        source_type: str,
        **context
    ) -> Dict[str, Any]:
        """
        Normalize article to standard format across RSS and API sources.

        Converts articles from different sources to consistent schema for
        downstream processing.

        Args:
            article: Article from RSS or API
            source_name: Source identifier
            source_type: 'rss' or 'api'
            **context: Additional context to preserve

        Returns:
            Normalized article dictionary
        """
        # Extract common fields
        title = article.get("title", "")
        url = article.get("url", "") or article.get("link", "")
        published = article.get("published_date", "") or article.get("published", "")
        authors = article.get("authors", []) or article.get("author", [])
        if isinstance(authors, str):
            authors = [authors] if authors else []

        content = article.get("content", "")
        if not content:
            # Use description/summary as fallback
            content = article.get("description", "") or article.get("summary", "")

        # Build normalized article
        normalized = {
            "title": title,
            "url": url,
            "published_date": published,
            "authors": authors,
            "content": content,
            "source": {
                "id": source_name,
                "name": article.get("source", {}).get("name", source_name)
                if isinstance(article.get("source"), dict)
                else source_name,
                "type": source_type,
            },
            "metadata": {
                "source_type": source_type,
                "authority_level": NEWS_SOURCES.get(source_name, {}).get("authority_level", 3),
                "topic_specialization": NEWS_SOURCES.get(source_name, {}).get("topic_specialization", ""),
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            },
            **context,
        }

        return normalized

    def _deduplicate_articles(self, articles: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
        """
        Deduplicate articles by URL to remove exact duplicates.

        Simple URL-based deduplication (more sophisticated semantic dedup
        can be added later).

        Args:
            articles: List of articles to deduplicate

        Returns:
            List of unique articles
        """
        seen_urls = set()
        unique = []

        for article in articles:
            url = article.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique.append(article)
            elif not url:
                # Include articles without URLs (they might have other unique identifiers)
                unique.append(article)

        return unique

    async def _subscribe_to_topics(self) -> None:
        """
        Subscribe to message bus topics for investigation requests.

        Subscribes to:
        - investigation.start: New investigation initiated
        - crawler.fetch: Explicit fetch request for this crawler
        """
        # Subscribe to investigation start events
        self.message_bus.subscribe_to_pattern(
            subscriber_name=f"NewsFeedAgent-{self.agent_id}",
            pattern="investigation.start",
            callback=self.handle_investigation_start
        )

        # Subscribe to explicit crawler fetch requests
        self.message_bus.subscribe_to_pattern(
            subscriber_name=f"NewsFeedAgent-{self.agent_id}-fetch",
            pattern="crawler.fetch",
            callback=self.handle_fetch_request
        )

        self.logger.info("Subscribed to message bus topics")

    async def handle_investigation_start(self, message: dict) -> None:
        """
        Handle investigation.start message.

        Automatically triggers fetching when a new investigation starts.

        Args:
            message: Message with investigation details
        """
        try:
            payload = message.get("payload", {})
            investigation_id = payload.get("investigation_id")
            query = payload.get("query")
            objective = payload.get("objective", "")

            if not investigation_id or not query:
                self.logger.warning("Investigation start message missing required fields")
                return

            self.logger.info(
                f"Handling investigation start",
                investigation_id=investigation_id,
                query=query
            )

            # Trigger fetch
            await self._execute_investigation_fetch(
                investigation_id=investigation_id,
                query=query,
                objective=objective
            )

        except Exception as e:
            self.logger.error(f"Error handling investigation start: {e}", exc_info=True)

    async def handle_fetch_request(self, message: dict) -> None:
        """
        Handle crawler.fetch message.

        Explicit request to fetch articles for an investigation.

        Args:
            message: Message with fetch parameters
        """
        try:
            payload = message.get("payload", {})
            investigation_id = payload.get("investigation_id")
            query = payload.get("query")
            agent_filter = payload.get("agent", None)

            # Check if this request is for us (or all crawlers)
            if agent_filter and agent_filter != "NewsFeedAgent":
                return

            if not investigation_id or not query:
                self.logger.warning("Fetch request missing required fields")
                return

            self.logger.info(
                f"Handling explicit fetch request",
                investigation_id=investigation_id,
                query=query
            )

            # Execute fetch
            await self._execute_investigation_fetch(
                investigation_id=investigation_id,
                query=query,
                **payload.get("options", {})
            )

        except Exception as e:
            self.logger.error(f"Error handling fetch request: {e}", exc_info=True)

    async def _execute_investigation_fetch(
        self,
        investigation_id: str,
        query: str,
        objective: str = "",
        **options
    ) -> None:
        """
        Execute investigation fetch and publish results.

        Internal method that orchestrates fetch, storage, and notification.

        Args:
            investigation_id: Investigation identifier
            query: Search query
            objective: Investigation objective
            **options: Additional fetch options
        """
        try:
            # Fetch articles
            result = await self.fetch_investigation_data(
                query=query,
                investigation_context={"investigation_id": investigation_id, "objective": objective},
                **options
            )

            if not result["success"]:
                self.logger.error(f"Fetch failed for investigation {investigation_id}")
                # Publish failure notification
                await self.message_bus.publish(
                    "crawler.failed",
                    {
                        "agent": "NewsFeedAgent",
                        "investigation_id": investigation_id,
                        "errors": result.get("errors", [])
                    }
                )
                return

            # ArticleStore.retrieve_by_investigation() returns a dictionary with 'articles' key,
            # not a list. Always access result['articles'] to get the actual article list.
            articles = result["articles"]

            # Store articles
            if articles:
                store_stats = await self.article_store.save_articles(
                    investigation_id=investigation_id,
                    articles=articles,
                    investigation_metadata={
                        "query": query,
                        "objective": objective,
                        "agent": "NewsFeedAgent"
                    }
                )

                self.logger.info(
                    f"Stored articles for investigation {investigation_id}",
                    **store_stats
                )

            # Publish completion notification
            await self.message_bus.publish(
                "crawler.complete",
                {
                    "agent": "NewsFeedAgent",
                    "investigation_id": investigation_id,
                    "article_count": len(articles),
                    "total_articles": result["total_articles"],
                    "dedup_stats": result.get("dedup_stats"),
                    "source_breakdown": result.get("source_breakdown", {}),
                    "metadata": {
                        "rss_articles": result.get("rss_articles", 0),
                        "api_articles": result.get("api_articles", 0),
                    }
                }
            )

            self.logger.info(
                f"Completed fetch for investigation {investigation_id}",
                article_count=len(articles)
            )

        except Exception as e:
            self.logger.error(
                f"Error executing investigation fetch: {e}",
                exc_info=True,
                investigation_id=investigation_id
            )

            # Publish failure notification
            await self.message_bus.publish(
                "crawler.failed",
                {
                    "agent": "NewsFeedAgent",
                    "investigation_id": investigation_id,
                    "error": str(e)
                }
            )

    def get_capabilities(self) -> list[str]:
        """
        Return NewsFeedAgent capabilities.

        Returns:
            List of capability identifiers
        """
        capabilities = super().get_capabilities()
        capabilities.extend([
            "rss_feed_crawling",
            "news_api_search",
            "investigation_data_fetching",
            "async_http_fetching",
            "rate_limiting",
            "retry_with_backoff",
            "multi_source_integration",
            "article_normalization",
            "message_bus_integration",
            "article_storage",
        ])
        return capabilities
