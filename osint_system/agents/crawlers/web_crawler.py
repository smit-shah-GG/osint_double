"""Hybrid web crawler with httpx-first approach and optional JS rendering.

Implements Pattern 1 from RESEARCH.md: try httpx first (10x faster),
fall back to Playwright for JavaScript-heavy sites.

Uses aiometer for precise rate limiting to prevent overwhelming target servers.
"""

from typing import Optional, Any, Dict, List
from datetime import datetime, timezone
import asyncio
import random
import re
import time

import httpx
import aiometer
from loguru import logger

from osint_system.agents.crawlers.base_crawler import BaseCrawler
from osint_system.agents.communication.bus import MessageBus


# User agents for rotation to avoid blocking
USER_AGENTS: List[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

# JavaScript framework indicators in HTML (simple string matching)
JS_FRAMEWORK_INDICATORS: List[str] = [
    "react",
    "angular",
    "vue",
    "__NEXT_DATA__",
    "__NUXT__",
    "gatsby",
    "_app",
    "data-reactroot",
    "ng-version",
    "v-cloak",
]

# Regex patterns for more precise JS framework detection
JS_FRAMEWORK_PATTERNS: List[re.Pattern] = [
    # React indicators
    re.compile(r'<div\s+id=["\'](?:root|app|__next)["\']>\s*</div>', re.IGNORECASE),
    re.compile(r'__NEXT_DATA__|_reactRoot', re.IGNORECASE),
    # Vue indicators
    re.compile(r'v-cloak|v-if|v-for|__vue__', re.IGNORECASE),
    # Angular indicators
    re.compile(r'ng-app|ng-controller|<app-root>', re.IGNORECASE),
    # Svelte/SvelteKit
    re.compile(r'__sveltekit', re.IGNORECASE),
    # Generic SPA indicators
    re.compile(r'<noscript>.*enable\s+javascript', re.IGNORECASE | re.DOTALL),
]

# Minimum content length to consider page properly loaded
MIN_CONTENT_LENGTH = 500


class HybridWebCrawler(BaseCrawler):
    """
    Hybrid web crawler using httpx with optional Playwright fallback.

    Tries fast httpx requests first. If JavaScript rendering is detected
    as necessary (based on framework indicators in HTML), falls back to
    Playwright for full browser rendering.

    Attributes:
        httpx_timeout: Timeout for httpx requests (default 30s)
        playwright_timeout: Timeout for Playwright rendering (default 60s)
        max_per_second: Rate limit for requests
        use_playwright: Whether Playwright fallback is enabled
    """

    def __init__(
        self,
        name: str = "HybridWebCrawler",
        description: str = "Hybrid web crawler with JS rendering fallback",
        httpx_timeout: float = 30.0,
        playwright_timeout: float = 60.0,
        max_per_second: float = 1.0,
        use_playwright: bool = True,
        message_bus: Optional[MessageBus] = None,
    ):
        """
        Initialize hybrid web crawler.

        Args:
            name: Crawler name
            description: Crawler description
            httpx_timeout: Timeout for httpx requests in seconds
            playwright_timeout: Timeout for Playwright rendering in seconds
            max_per_second: Maximum requests per second (rate limit)
            use_playwright: Whether to enable Playwright fallback
            message_bus: Optional MessageBus for coordination
        """
        super().__init__(name=name, description=description)

        self.httpx_timeout = httpx_timeout
        self.playwright_timeout = playwright_timeout
        self.max_per_second = max_per_second
        self.use_playwright = use_playwright
        self.message_bus = message_bus

        # HTTP client (lazy initialization)
        self._client: Optional[httpx.AsyncClient] = None

        # Metrics
        self.fetch_count = 0
        self.js_render_count = 0
        self._last_request_time = 0.0

        # Playwright availability (checked lazily)
        self._playwright_available: Optional[bool] = None

        self.logger = logger.bind(module="HybridWebCrawler")
        self.logger.info(
            "HybridWebCrawler initialized",
            httpx_timeout=httpx_timeout,
            max_per_second=max_per_second,
            playwright_enabled=use_playwright,
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client with rotation user-agent."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.httpx_timeout),
                limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
                follow_redirects=True,
            )
        return self._client

    def _get_user_agent(self) -> str:
        """Get a random user agent for rotation."""
        return random.choice(USER_AGENTS)

    async def _rate_limit(self) -> None:
        """Apply rate limiting between requests (for single-URL fetches)."""
        now = time.monotonic()
        min_interval = 1.0 / self.max_per_second
        elapsed = now - self._last_request_time

        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)

        self._last_request_time = time.monotonic()

    def _needs_js_rendering(self, html: str) -> bool:
        """
        Check if HTML indicates JavaScript rendering is needed.

        Uses both simple string matching and regex patterns to detect
        common SPA frameworks and empty content indicators.

        Args:
            html: HTML content to analyze

        Returns:
            True if JS rendering appears needed
        """
        # Very short content often means JS-only rendering
        if len(html) < MIN_CONTENT_LENGTH:
            return True

        # Check regex patterns first (more precise)
        for pattern in JS_FRAMEWORK_PATTERNS:
            if pattern.search(html):
                return True

        html_lower = html.lower()

        # Check for framework indicators with body content analysis
        for indicator in JS_FRAMEWORK_INDICATORS:
            if indicator in html_lower:
                # Additional check: is the body mostly empty?
                # If we see framework indicators AND sparse content, JS is needed
                body_start = html_lower.find("<body")
                body_end = html_lower.find("</body>")

                if body_start != -1 and body_end != -1:
                    body_content = html[body_start:body_end]
                    # Very short body with framework indicators = needs JS
                    if len(body_content) < 500 and indicator in body_content.lower():
                        return True

        return False

    async def _check_playwright_available(self) -> bool:
        """Check if Playwright is available for import."""
        if self._playwright_available is None:
            try:
                import playwright  # noqa: F401
                self._playwright_available = True
            except ImportError:
                self._playwright_available = False
                self.logger.warning("Playwright not installed, JS rendering disabled")

        return self._playwright_available

    async def _playwright_fetch(self, url: str) -> dict:
        """
        Fetch URL using Playwright for JavaScript rendering.

        Args:
            url: URL to fetch

        Returns:
            Dict with rendered HTML and metadata
        """
        if not await self._check_playwright_available():
            return {
                "success": False,
                "html": "",
                "url": url,
                "rendered": False,
                "error": "Playwright not available",
            }

        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(
                    user_agent=self._get_user_agent(),
                )

                await page.goto(url, timeout=self.playwright_timeout * 1000)
                # Wait for network idle to ensure JS has loaded
                await page.wait_for_load_state("networkidle")

                html = await page.content()
                await browser.close()

                self.js_render_count += 1

                return {
                    "success": True,
                    "html": html,
                    "url": url,
                    "rendered": True,
                    "error": None,
                }

        except Exception as e:
            error_msg = f"Playwright fetch failed: {e}"
            self.logger.error(error_msg, url=url)
            return {
                "success": False,
                "html": "",
                "url": url,
                "rendered": False,
                "error": error_msg,
            }

    async def fetch(self, url: str) -> dict:
        """
        Fetch URL with httpx, falling back to Playwright if needed.

        This is the main fetch method implementing the hybrid approach:
        1. Try httpx first (fast, lightweight)
        2. Check if JS rendering is needed
        3. Fall back to Playwright if needed and available

        Args:
            url: URL to fetch

        Returns:
            Dict containing:
            - success: bool indicating fetch success
            - html: HTML content
            - url: Original URL
            - rendered: Whether JS rendering was used
            - error: Error message if failed
        """
        await self._rate_limit()
        self.fetch_count += 1

        # Try httpx first
        try:
            client = await self._get_client()
            response = await client.get(
                url,
                headers={"User-Agent": self._get_user_agent()},
            )
            response.raise_for_status()
            html = response.text

            # Check if JS rendering is needed
            if self.use_playwright and self._needs_js_rendering(html):
                self.logger.debug(f"JS rendering detected as needed for {url}")
                return await self._playwright_fetch(url)

            return {
                "success": True,
                "html": html,
                "url": str(response.url),
                "rendered": False,
                "error": None,
            }

        except httpx.TimeoutException:
            # Timeout - try Playwright if available
            if self.use_playwright:
                self.logger.debug(f"httpx timeout, trying Playwright for {url}")
                return await self._playwright_fetch(url)

            return {
                "success": False,
                "html": "",
                "url": url,
                "rendered": False,
                "error": f"Request timeout after {self.httpx_timeout}s",
            }

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP error {e.response.status_code}"
            self.logger.warning(error_msg, url=url)
            return {
                "success": False,
                "html": "",
                "url": url,
                "rendered": False,
                "error": error_msg,
            }

        except Exception as e:
            error_msg = f"Fetch failed: {e}"
            self.logger.error(error_msg, url=url, exc_info=True)
            return {
                "success": False,
                "html": "",
                "url": url,
                "rendered": False,
                "error": error_msg,
            }

    async def fetch_many(self, urls: List[str]) -> List[dict]:
        """
        Fetch multiple URLs with aiometer rate limiting.

        Uses aiometer for precise rate limiting to prevent overwhelming servers.
        More efficient than sequential fetches for batch operations.

        Args:
            urls: List of URLs to fetch

        Returns:
            List of fetch result dicts (same order as input URLs)
        """
        if not urls:
            return []

        self.logger.info(
            f"Batch fetching {len(urls)} URLs at {self.max_per_second} req/sec"
        )

        async def _fetch_single(url: str) -> dict:
            """Wrapper for single fetch without internal rate limiting."""
            # Increment count but skip internal rate limiting (aiometer handles it)
            self.fetch_count += 1

            try:
                client = await self._get_client()
                response = await client.get(
                    url,
                    headers={"User-Agent": self._get_user_agent()},
                )
                response.raise_for_status()
                html = response.text

                # Check if JS rendering is needed
                if self.use_playwright and self._needs_js_rendering(html):
                    self.logger.debug(f"JS rendering detected as needed for {url}")
                    return await self._playwright_fetch(url)

                return {
                    "success": True,
                    "html": html,
                    "url": str(response.url),
                    "rendered": False,
                    "error": None,
                }

            except httpx.TimeoutException:
                if self.use_playwright:
                    return await self._playwright_fetch(url)
                return {
                    "success": False,
                    "html": "",
                    "url": url,
                    "rendered": False,
                    "error": f"Request timeout after {self.httpx_timeout}s",
                }

            except httpx.HTTPStatusError as e:
                return {
                    "success": False,
                    "html": "",
                    "url": url,
                    "rendered": False,
                    "error": f"HTTP error {e.response.status_code}",
                }

            except Exception as e:
                return {
                    "success": False,
                    "html": "",
                    "url": url,
                    "rendered": False,
                    "error": f"Fetch failed: {e}",
                }

        # Use aiometer for precise rate limiting
        results = await aiometer.run_on_each(
            _fetch_single,
            urls,
            max_per_second=self.max_per_second,
        )

        return list(results)

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # BaseCrawler interface implementation

    async def fetch_data(self, source: str, **kwargs) -> dict:
        """
        Fetch data from URL (BaseCrawler interface).

        Args:
            source: URL to fetch
            **kwargs: Additional parameters (unused)

        Returns:
            Fetch result dictionary
        """
        result = await self.fetch(source)

        # Transform to standard format
        return {
            "success": result["success"],
            "raw_content": result["html"],
            "url": result["url"],
            "source": source,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "js_rendered": result["rendered"],
                "crawler": self.name,
            },
            "error": result["error"],
        }

    async def filter_relevance(self, data: dict) -> bool:
        """
        Check if fetched data is relevant (BaseCrawler interface).

        Args:
            data: Fetched data

        Returns:
            True if data has content
        """
        if not data.get("success"):
            return False

        content = data.get("raw_content", "")
        # Minimum content threshold
        return len(content) > 200

    async def extract_metadata(self, data: dict) -> dict:
        """
        Extract metadata from fetched data (BaseCrawler interface).

        Args:
            data: Fetched data

        Returns:
            Metadata dictionary
        """
        return {
            "source_url": data.get("url"),
            "retrieved_at": data.get("retrieved_at"),
            "js_rendered": data.get("metadata", {}).get("js_rendered", False),
            "crawler": self.name,
        }

    def get_capabilities(self) -> List[str]:
        """Return crawler capabilities."""
        capabilities = [
            "data_acquisition",
            "source_crawling",
            "metadata_extraction",
            "web_crawling",
            "rate_limiting",
        ]
        if self.use_playwright:
            capabilities.append("javascript_rendering")
        return capabilities

    def get_metrics(self) -> Dict[str, Any]:
        """Get crawler performance metrics."""
        return {
            "fetch_count": self.fetch_count,
            "js_render_count": self.js_render_count,
            "js_render_ratio": (
                self.js_render_count / self.fetch_count
                if self.fetch_count > 0 else 0
            ),
        }

    async def process(self, input_data: dict) -> dict:
        """
        Process input data (BaseAgent interface).

        Accepts URLs to crawl and returns collected content.

        Args:
            input_data: Dictionary with:
                - urls: List of URLs to crawl
                - url: Single URL to crawl (if urls not provided)

        Returns:
            Dictionary with:
                - success: bool indicating overall success
                - results: List of fetch results
                - failed_count: Number of failed fetches
                - metrics: Crawler metrics
        """
        urls = input_data.get("urls", [])
        if not urls and "url" in input_data:
            urls = [input_data["url"]]

        if not urls:
            return {
                "success": False,
                "error": "No URLs provided",
                "results": [],
                "failed_count": 0,
                "metrics": self.get_metrics(),
            }

        # Fetch all URLs
        if len(urls) == 1:
            results = [await self.fetch(urls[0])]
        else:
            results = await self.fetch_many(urls)

        failed_count = sum(1 for r in results if not r.get("success"))

        return {
            "success": failed_count < len(results),
            "results": results,
            "failed_count": failed_count,
            "total_count": len(results),
            "metrics": self.get_metrics(),
        }
