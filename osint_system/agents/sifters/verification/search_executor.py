"""Search executor for verification queries using Serper API.

Wraps search execution with rate limiting and converts results to
EvidenceItem objects with authority scoring from Phase 7 SourceCredibilityScorer.

Handles missing SERPER_API_KEY gracefully by returning empty results,
allowing tests and development without API access.

Usage:
    from osint_system.agents.sifters.verification.search_executor import SearchExecutor

    executor = SearchExecutor()
    evidence = await executor.execute_query(query)
"""

import os
from typing import Any, Optional
from urllib.parse import urlparse

import structlog

from osint_system.agents.sifters.verification.schemas import (
    EvidenceItem,
    VerificationQuery,
)
from osint_system.config.source_credibility import (
    DOMAIN_PATTERN_DEFAULTS,
    SOURCE_BASELINES,
)
from osint_system.llm.rate_limiter import RateLimiter


class SearchExecutor:
    """Execute verification searches with Serper API integration.

    Converts search results to EvidenceItem objects with authority scoring
    from Phase 7's source credibility baselines. Rate-limited via existing
    RateLimiter infrastructure.

    Handles missing API key gracefully (mock mode returns empty results).
    """

    def __init__(
        self,
        rate_limiter: Optional[RateLimiter] = None,
        api_key: Optional[str] = None,
        max_results: int = 5,
    ) -> None:
        """Initialize SearchExecutor.

        Args:
            rate_limiter: Existing RateLimiter for API throttling.
            api_key: SERPER_API_KEY. Falls back to env var if not provided.
            max_results: Maximum search results per query.
        """
        self._api_key = api_key or os.environ.get("SERPER_API_KEY")
        self._rate_limiter = rate_limiter
        self._max_results = max_results
        self._search_wrapper = None
        self._logger = structlog.get_logger().bind(component="SearchExecutor")

        if not self._api_key:
            self._logger.warning(
                "serper_api_key_not_set",
                msg="SERPER_API_KEY not set, using mock search mode",
            )

    def _get_search_wrapper(self) -> Any:
        """Lazy-init search wrapper."""
        if self._search_wrapper is None and self._api_key:
            try:
                from langchain_community.utilities import GoogleSerperAPIWrapper

                self._search_wrapper = GoogleSerperAPIWrapper(
                    serper_api_key=self._api_key,
                    k=self._max_results,
                    type="search",
                )
            except ImportError:
                self._logger.warning(
                    "langchain_serper_not_available",
                    msg="langchain-community not installed, using mock mode",
                )
        return self._search_wrapper

    async def execute_query(
        self,
        query: VerificationQuery,
    ) -> list[EvidenceItem]:
        """Execute a single verification query and return evidence items.

        Args:
            query: VerificationQuery with search string and metadata.

        Returns:
            List of EvidenceItem objects from search results.
        """
        # Rate limit check
        if self._rate_limiter and not self._rate_limiter.can_proceed(1):
            self._logger.debug("rate_limited", query=query.query[:50])
            return []

        # Mock mode if no API key
        if not self._api_key:
            self._logger.debug("mock_search", query=query.query[:50])
            return []

        wrapper = self._get_search_wrapper()
        if wrapper is None:
            return []

        try:
            raw_results = await wrapper.aresults(query.query)
            organic = raw_results.get("organic", [])

            evidence_items: list[EvidenceItem] = []
            seen_urls: set[str] = set()

            for result in organic[: self._max_results]:
                url = result.get("link", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                domain = self._extract_domain(url)
                authority = self._get_authority_score(domain)
                snippet = result.get("snippet", "")
                relevance = self._calculate_relevance(snippet, query)

                evidence_items.append(
                    EvidenceItem(
                        source_url=url,
                        source_domain=domain,
                        source_type=self._infer_source_type(domain),
                        authority_score=authority,
                        snippet=snippet,
                        supports_claim=True,  # Default; EvidenceAggregator evaluates
                        relevance_score=relevance,
                    )
                )

            self._logger.info(
                "search_executed",
                query=query.query[:80],
                variant=query.variant_type,
                results=len(evidence_items),
            )
            return evidence_items

        except Exception as e:
            self._logger.error(
                "search_failed",
                query=query.query[:50],
                error=str(e),
            )
            return []

    async def execute_queries(
        self,
        queries: list[VerificationQuery],
    ) -> list[EvidenceItem]:
        """Execute multiple queries sequentially with deduplication.

        Args:
            queries: List of VerificationQuery objects.

        Returns:
            Deduplicated list of EvidenceItem objects.
        """
        all_evidence: list[EvidenceItem] = []
        seen_urls: set[str] = set()

        for query in queries:
            results = await self.execute_query(query)
            for item in results:
                if item.source_url not in seen_urls:
                    seen_urls.add(item.source_url)
                    all_evidence.append(item)

        return all_evidence

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL, stripping www. prefix."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except Exception:
            return ""

    def _get_authority_score(self, domain: str) -> float:
        """Get authority score using Phase 7 source credibility baselines.

        Args:
            domain: Source domain (e.g., reuters.com).

        Returns:
            Authority score 0.0-1.0.
        """
        if domain in SOURCE_BASELINES:
            return SOURCE_BASELINES[domain]

        for pattern, score in DOMAIN_PATTERN_DEFAULTS.items():
            if domain.endswith(pattern):
                return score

        return 0.4

    def _infer_source_type(self, domain: str) -> str:
        """Infer source type from domain."""
        wire_services = {"reuters.com", "apnews.com", "afp.com"}
        social_media = {"twitter.com", "x.com", "reddit.com", "facebook.com", "telegram.org"}

        if domain in wire_services:
            return "wire_service"
        if domain in social_media:
            return "social_media"
        if domain.endswith(".gov") or domain.endswith(".mil") or domain.endswith(".edu"):
            return "official_statement"
        return "news_outlet"

    def _calculate_relevance(self, snippet: str, query: VerificationQuery) -> float:
        """Calculate relevance score based on keyword overlap.

        Args:
            snippet: Search result snippet text.
            query: Original query for keyword comparison.

        Returns:
            Relevance score 0.0-1.0.
        """
        if not snippet or not query.query:
            return 0.3

        query_terms = set(query.query.lower().split())
        # Remove common search operators
        query_terms -= {
            "site:reuters.com", "site:apnews.com", "or", "and",
            '"', "official", "statement", "press", "release",
        }
        if not query_terms:
            return 0.5

        snippet_lower = snippet.lower()
        matches = sum(1 for term in query_terms if term in snippet_lower)
        return min(1.0, 0.3 + (matches / len(query_terms)) * 0.7)
