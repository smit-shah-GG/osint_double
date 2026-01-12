"""NewsFeedAgent: Async news crawler with rate limiting and RSS feed integration."""

import asyncio
import time
from datetime import datetime, timezone
from typing import Optional, Any
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, AsyncRetrying
from loguru import logger

from osint_system.agents.crawlers.base_crawler import BaseCrawler


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

        self.logger.info(
            "NewsFeedAgent initialized",
            default_rate_limit=default_rate_limit,
            http_timeout=http_timeout,
            max_retries=max_retries,
            num_sources=len(self.source_configs),
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
        """Async context manager entry - initialize HTTP client and MCP."""
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

    def get_capabilities(self) -> list[str]:
        """
        Return NewsFeedAgent capabilities.

        Returns:
            List of capability identifiers
        """
        capabilities = super().get_capabilities()
        capabilities.extend([
            "rss_feed_crawling",
            "async_http_fetching",
            "rate_limiting",
            "retry_with_backoff",
        ])
        return capabilities
