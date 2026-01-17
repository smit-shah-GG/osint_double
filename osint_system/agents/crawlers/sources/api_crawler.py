"""NewsAPI client for fetching articles via search queries.

This module implements an async NewsAPI client for the NewsAPI.org service,
providing search capabilities to supplement RSS feed data. The NewsAPI is useful
for:
- Targeted searches with specific keywords
- Date-range queries for recent events
- Coverage from sources not in RSS feeds
- Verification of story coverage across multiple outlets

The free tier has rate limits (100 requests/day), which the client respects
through built-in rate limiting.
"""

import os
import asyncio
import httpx
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List, Any
from loguru import logger
from osint_system.config.settings import settings


class NewsAPIClient:
    """
    Async client for NewsAPI.org Everything endpoint.

    Provides search capabilities with filtering by date range, sources, and language.
    Handles free tier rate limiting (100 requests/day = ~4 requests/hour).

    Attributes:
        api_key: NewsAPI API key from environment variable NEWS_API_KEY
        base_url: NewsAPI base URL
        endpoint: API endpoint (everything for article search)
        http_client: httpx AsyncClient for HTTP operations
        rate_limiter: Semaphore for rate limiting (4 req/hour for free tier)
        request_count: Track requests made (for monitoring)
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize NewsAPI client.

        Args:
            api_key: Optional API key override. If not provided, reads from
                    NEWS_API_KEY environment variable.

        Raises:
            ValueError: If no API key provided and NEWS_API_KEY env var not set
        """
        # Get API key from parameter, settings, or environment
        self.api_key = api_key or settings.news_api_key or os.environ.get("NEWS_API_KEY")

        if not self.api_key:
            # Don't raise - allow initialization without key for testing
            # Debug level since it's optional (RSS feeds work without it)
            logger.debug(
                "NewsAPIClient initialized without API key (optional). "
                "Set NEWS_API_KEY environment variable to enable API calls."
            )

        self.base_url = "https://newsapi.org/v2"
        self.endpoint = "everything"

        # Create async HTTP client with proper headers
        self.http_client: Optional[httpx.AsyncClient] = None

        # Rate limiting: Free tier is 100 requests/day = ~4.2/hour
        # Use more conservative 4/hour to stay safely under limits
        self.rate_limiter = asyncio.Semaphore(1)
        self.min_request_interval = 900.0  # 15 minutes between requests (4/hour)
        self.last_request_time = 0.0

        # Request tracking for monitoring
        self.request_count = 0
        self.last_request_at: Optional[str] = None

        self.logger = logger.bind(module="NewsAPIClient")
        self.logger.info("NewsAPIClient initialized", base_url=self.base_url)

    async def __aenter__(self):
        """Async context manager entry - initialize HTTP client."""
        self.http_client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; OSINTBot/1.0; +https://github.com/smit-shah-GG/osint_double)"
            },
        )
        self.logger.debug("HTTP client initialized for NewsAPI")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - close HTTP client."""
        if self.http_client:
            await self.http_client.aclose()
            self.logger.debug("HTTP client closed")

    async def _apply_rate_limit(self) -> None:
        """
        Apply rate limiting to respect free tier limits.

        Free tier: 100 requests/day = 4 requests/hour
        This enforces minimum 15-minute interval between requests.
        """
        async with self.rate_limiter:
            elapsed = asyncio.get_event_loop().time() - self.last_request_time
            if elapsed < self.min_request_interval:
                wait_time = self.min_request_interval - elapsed
                self.logger.debug(
                    f"Rate limit: waiting {wait_time:.1f}s before next request"
                )
                await asyncio.sleep(wait_time)
            self.last_request_time = asyncio.get_event_loop().time()

    async def search_articles(
        self,
        query: str,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        sources: Optional[List[str]] = None,
        language: str = "en",
        sort_by: str = "relevancy",
        page: int = 1,
        page_size: int = 100,
    ) -> Dict[str, Any]:
        """
        Search articles via NewsAPI everything endpoint.

        Args:
            query: Search query string (required)
            from_date: Optional start date for search (default: 30 days ago)
            to_date: Optional end date for search (default: today)
            sources: Optional list of NewsAPI source identifiers to limit search
            language: Language code (default: 'en' for English)
            sort_by: Sort order - 'relevancy', 'popularity', or 'publishedAt' (default: 'relevancy')
            page: Page number for pagination (default: 1)
            page_size: Articles per page, max 100 (default: 100)

        Returns:
            Dictionary containing:
            - status: 'ok' or 'error'
            - totalResults: Total articles matching query
            - articles: List of article dictionaries with:
                - source: Dict with 'id' and 'name'
                - author: Article author
                - title: Article headline
                - description: Article summary
                - url: Article URL
                - urlToImage: Image URL
                - publishedAt: ISO 8601 publication timestamp
                - content: First 200 chars of article content
            - error: Error message if status is 'error'
            - pagination: Metadata about pagination

        Raises:
            ValueError: If query is empty or required API key not set
            httpx.HTTPError: If HTTP request fails
        """
        if not query or not query.strip():
            raise ValueError("Query parameter is required and cannot be empty")

        if not self.api_key:
            raise ValueError("NEWS_API_KEY environment variable must be set to use NewsAPI")

        if not self.http_client:
            raise RuntimeError("HTTP client not initialized. Use 'async with' context manager.")

        # Apply rate limiting before making request
        await self._apply_rate_limit()

        # Set default date range if not provided
        if not from_date:
            from_date = datetime.now(timezone.utc) - timedelta(days=30)
        if not to_date:
            to_date = datetime.now(timezone.utc)

        # Build request parameters
        params = {
            "q": query,
            "language": language,
            "sortBy": sort_by,
            "pageSize": page_size,
            "page": page,
            "apiKey": self.api_key,
        }

        # Add date range
        if from_date:
            params["from"] = from_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        if to_date:
            params["to"] = to_date.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Add source filter if provided
        if sources:
            params["sources"] = ",".join(sources)

        try:
            self.logger.debug(
                "Searching articles via NewsAPI",
                query=query,
                page=page,
                from_date=params.get("from"),
                to_date=params.get("to"),
            )

            # Make API request
            url = f"{self.base_url}/{self.endpoint}"
            response = await self.http_client.get(url, params=params)

            # Track request
            self.request_count += 1
            self.last_request_at = datetime.now(timezone.utc).isoformat()

            # Check for API errors
            if response.status_code == 401:
                error_msg = "Invalid NewsAPI key"
                self.logger.error(error_msg)
                return {
                    "status": "error",
                    "error": error_msg,
                    "code": "invalidApiKey",
                    "articles": [],
                    "totalResults": 0,
                }

            if response.status_code == 429:
                error_msg = "NewsAPI rate limit exceeded (100 requests/day)"
                self.logger.warning(error_msg)
                return {
                    "status": "error",
                    "error": error_msg,
                    "code": "rateLimited",
                    "articles": [],
                    "totalResults": 0,
                }

            # Parse response
            result = response.json()

            # Add pagination metadata
            if result.get("status") == "ok":
                total = result.get("totalResults", 0)
                result["pagination"] = {
                    "page": page,
                    "page_size": page_size,
                    "total_results": total,
                    "total_pages": (total + page_size - 1) // page_size,
                    "has_next_page": page * page_size < total,
                }

                self.logger.info(
                    f"NewsAPI search returned {len(result.get('articles', []))} articles",
                    query=query,
                    total_results=total,
                )
            else:
                # Handle error responses
                error_msg = result.get("message", "Unknown error")
                self.logger.warning(f"NewsAPI error: {error_msg}")

            return result

        except httpx.TimeoutException:
            error_msg = f"NewsAPI request timeout for query: {query}"
            self.logger.error(error_msg)
            return {
                "status": "error",
                "error": error_msg,
                "code": "timeout",
                "articles": [],
                "totalResults": 0,
            }

        except httpx.HTTPError as e:
            error_msg = f"NewsAPI HTTP error: {str(e)}"
            self.logger.error(error_msg)
            return {
                "status": "error",
                "error": error_msg,
                "code": "httpError",
                "articles": [],
                "totalResults": 0,
            }

        except Exception as e:
            error_msg = f"Unexpected error in NewsAPI search: {str(e)}"
            self.logger.exception(error_msg)
            return {
                "status": "error",
                "error": error_msg,
                "code": "unexpectedError",
                "articles": [],
                "totalResults": 0,
            }

    async def search_articles_paginated(
        self,
        query: str,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        sources: Optional[List[str]] = None,
        language: str = "en",
        sort_by: str = "relevancy",
        max_pages: int = 2,
    ) -> List[Dict[str, Any]]:
        """
        Search articles with automatic pagination handling.

        Fetches multiple pages of results up to max_pages, respecting rate limits.

        Args:
            query: Search query string
            from_date: Optional start date
            to_date: Optional end date
            sources: Optional list of source identifiers
            language: Language code
            sort_by: Sort order
            max_pages: Maximum number of pages to fetch (default: 2)

        Returns:
            List of all articles from fetched pages
        """
        all_articles = []
        total_pages = max_pages

        for page in range(1, max_pages + 1):
            result = await self.search_articles(
                query=query,
                from_date=from_date,
                to_date=to_date,
                sources=sources,
                language=language,
                sort_by=sort_by,
                page=page,
                page_size=100,
            )

            if result.get("status") != "ok":
                self.logger.warning(f"Error on page {page}: {result.get('error')}")
                break

            articles = result.get("articles", [])
            if not articles:
                break

            all_articles.extend(articles)

            # Check if there are more pages
            pagination = result.get("pagination", {})
            if not pagination.get("has_next_page"):
                break

        self.logger.info(f"Fetched {len(all_articles)} articles across multiple pages")
        return all_articles

    def normalize_article(self, article: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize NewsAPI article to standard format.

        Converts NewsAPI response format to internal article schema for
        consistency with RSS-parsed articles.

        Args:
            article: NewsAPI article response

        Returns:
            Normalized article dictionary with standard fields
        """
        source = article.get("source", {})

        return {
            "title": article.get("title", ""),
            "url": article.get("url", ""),
            "published_date": article.get("publishedAt", ""),
            "authors": [article.get("author", "")] if article.get("author") else [],
            "content": article.get("content", ""),
            "description": article.get("description", ""),
            "image_url": article.get("urlToImage", ""),
            "source": {
                "id": source.get("id", ""),
                "name": source.get("name", ""),
            },
            "original_response": article,
        }

    async def get_status(self) -> Dict[str, Any]:
        """
        Get current status of the NewsAPI client.

        Returns:
            Status dictionary with API key status, request count, etc.
        """
        return {
            "configured": bool(self.api_key),
            "api_key_present": bool(self.api_key),
            "request_count": self.request_count,
            "last_request_at": self.last_request_at,
            "rate_limit_requests_per_day": 100,
            "rate_limit_interval_seconds": self.min_request_interval,
        }
