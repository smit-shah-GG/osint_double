"""Search executor for verification queries using DuckDuckGo.

Executes web searches via the `ddgs` package (no API key required) and
converts results to EvidenceItem objects with authority scoring from
Phase 7 SourceCredibilityScorer baselines.

Snippet stance detection: two-tier approach:
1. Primary: Regex negation patterns (33 patterns, fast, zero-cost).
2. Fallback: LLM stance assessment via OpenRouter when regex is inconclusive
   and snippet is long enough (>100 chars) to contain nuanced refutation.

Usage:
    from osint_system.agents.sifters.verification.search_executor import SearchExecutor

    executor = SearchExecutor()
    evidence = await executor.execute_query(query, claim_text="Russia deployed troops")

    # With injected LLM client for stance fallback
    from osint_system.llm.openrouter_client import OpenRouterClient
    client = OpenRouterClient(api_key="sk-or-...")
    executor = SearchExecutor(llm_client=client)
"""

import asyncio
import json
import re
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

# Compiled negation patterns for snippet stance detection.
# Order matters: more specific multi-word patterns first to avoid
# false positives from single-word matches.
_NEGATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bno evidence\b", re.IGNORECASE),
    re.compile(r"\bno proof\b", re.IGNORECASE),
    re.compile(r"\bno confirmation\b", re.IGNORECASE),
    re.compile(r"\bno credible\b", re.IGNORECASE),
    re.compile(r"\bnot true\b", re.IGNORECASE),
    re.compile(r"\bnot confirmed\b", re.IGNORECASE),
    re.compile(r"\bnot verified\b", re.IGNORECASE),
    re.compile(r"\bnot supported\b", re.IGNORECASE),
    re.compile(r"\bhas denied\b", re.IGNORECASE),
    re.compile(r"\bhave denied\b", re.IGNORECASE),
    re.compile(r"\bwas denied\b", re.IGNORECASE),
    re.compile(r"\bwere denied\b", re.IGNORECASE),
    re.compile(r"\bfirmly denied\b", re.IGNORECASE),
    re.compile(r"\bcategorically denied\b", re.IGNORECASE),
    re.compile(r"\bhas been debunked\b", re.IGNORECASE),
    re.compile(r"\bhas been disproven\b", re.IGNORECASE),
    re.compile(r"\bhas been refuted\b", re.IGNORECASE),
    re.compile(r"\bwas debunked\b", re.IGNORECASE),
    re.compile(r"\bwas disproven\b", re.IGNORECASE),
    re.compile(r"\bwas refuted\b", re.IGNORECASE),
    re.compile(r"\bfalse claim\b", re.IGNORECASE),
    re.compile(r"\bfalse report\b", re.IGNORECASE),
    re.compile(r"\bmisleading claim\b", re.IGNORECASE),
    re.compile(r"\bfact[ -]check.*false\b", re.IGNORECASE),
    re.compile(r"\bcontradicts\b", re.IGNORECASE),
    re.compile(r"\bcontradicted\b", re.IGNORECASE),
    re.compile(r"\bdisproven\b", re.IGNORECASE),
    re.compile(r"\bdebunked\b", re.IGNORECASE),
    re.compile(r"\brefuted\b", re.IGNORECASE),
    re.compile(r"\bdenies\b", re.IGNORECASE),
    re.compile(r"\bdenied\b", re.IGNORECASE),
    re.compile(r"\bmisinformation\b", re.IGNORECASE),
    re.compile(r"\bdisinformation\b", re.IGNORECASE),
]

# Minimum number of negation pattern hits to flip supports_claim
_NEGATION_THRESHOLD = 1


class SearchExecutor:
    """Execute verification searches via DuckDuckGo with stance detection.

    Converts search results to EvidenceItem objects with authority scoring
    from Phase 7's source credibility baselines. Snippet stance detection
    scans for negation signals to set supports_claim appropriately.

    No API key required — uses the ddgs package for free web search.
    """

    def __init__(
        self,
        rate_limiter: Optional[RateLimiter] = None,
        max_results: int = 5,
        llm_client: Optional[Any] = None,
    ) -> None:
        """Initialize SearchExecutor.

        Args:
            rate_limiter: Existing RateLimiter for search throttling.
            max_results: Maximum search results per query.
            llm_client: Optional LLM client for stance fallback.
                        If not provided, lazy-initialized from OPENROUTER_API_KEY.
        """
        self._rate_limiter = rate_limiter
        self._max_results = max_results
        self._llm_client = llm_client
        self._ddgs = None
        self._logger = structlog.get_logger().bind(component="SearchExecutor")

    def _get_ddgs(self):
        """Lazy-init DuckDuckGo search client."""
        if self._ddgs is None:
            try:
                from ddgs import DDGS

                self._ddgs = DDGS()
            except ImportError:
                self._logger.error(
                    "ddgs_not_installed",
                    msg="ddgs package not installed. Run: uv pip install ddgs",
                )
        return self._ddgs

    def _get_llm_client(self) -> Optional[Any]:
        """Lazy-initialize LLM client for stance fallback if not injected.

        Attempts to create an OpenRouterClient from the OPENROUTER_API_KEY
        environment variable. Returns None if key is not set.
        """
        if self._llm_client is None:
            import os

            openrouter_key = os.environ.get("OPENROUTER_API_KEY")
            if openrouter_key:
                from osint_system.llm.openrouter_client import OpenRouterClient

                self._llm_client = OpenRouterClient(api_key=openrouter_key)
        return self._llm_client

    async def execute_query(
        self,
        query: VerificationQuery,
        claim_text: str = "",
    ) -> list[EvidenceItem]:
        """Execute a single verification query and return evidence items.

        Args:
            query: VerificationQuery with search string and metadata.
            claim_text: Original claim text for LLM stance fallback context.

        Returns:
            List of EvidenceItem objects from search results.
        """
        if self._rate_limiter and not self._rate_limiter.can_proceed(1):
            self._logger.debug("rate_limited", query=query.query[:50])
            return []

        ddgs = self._get_ddgs()
        if ddgs is None:
            return []

        try:
            # ddgs.text() is synchronous — run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            raw_results = await loop.run_in_executor(
                None,
                lambda: list(
                    ddgs.text(query.query, max_results=self._max_results)
                ),
            )

            evidence_items: list[EvidenceItem] = []
            seen_urls: set[str] = set()

            for result in raw_results:
                url = result.get("href", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                domain = self._extract_domain(url)
                authority = self._get_authority_score(domain)
                snippet = result.get("body", "")
                relevance = self._calculate_relevance(snippet, query)
                supports = self._detect_stance(snippet)

                # LLM stance fallback for ambiguous snippets:
                # When regex found no negation (supports=True), snippet is
                # long enough for nuanced analysis, and LLM client is available,
                # use LLM to detect subtle refutation that regex misses.
                if (
                    supports
                    and len(snippet) > 100
                    and claim_text
                    and self._get_llm_client() is not None
                ):
                    supports = await self._llm_stance_assessment(
                        snippet, claim_text
                    )

                evidence_items.append(
                    EvidenceItem(
                        source_url=url,
                        source_domain=domain,
                        source_type=self._infer_source_type(domain),
                        authority_score=authority,
                        snippet=snippet,
                        supports_claim=supports,
                        relevance_score=relevance,
                    )
                )

            self._logger.info(
                "search_executed",
                query=query.query[:80],
                variant=query.variant_type,
                results=len(evidence_items),
                refuting=sum(1 for e in evidence_items if not e.supports_claim),
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
        claim_text: str = "",
    ) -> list[EvidenceItem]:
        """Execute multiple queries sequentially with deduplication.

        Args:
            queries: List of VerificationQuery objects.
            claim_text: Original claim text for LLM stance fallback context.

        Returns:
            Deduplicated list of EvidenceItem objects.
        """
        all_evidence: list[EvidenceItem] = []
        seen_urls: set[str] = set()

        for query in queries:
            results = await self.execute_query(query, claim_text=claim_text)
            for item in results:
                if item.source_url not in seen_urls:
                    seen_urls.add(item.source_url)
                    all_evidence.append(item)

        return all_evidence

    # ── Stance Detection ──────────────────────────────────────────────

    def _detect_stance(self, snippet: str) -> bool:
        """Detect whether a snippet supports or refutes the claim.

        Scans for negation patterns (denied, false, disproven, no evidence,
        etc.). If negation signals are found, returns False (refutes).
        Otherwise returns True (supports or neutral).

        Args:
            snippet: Search result snippet text.

        Returns:
            True if snippet appears to support/be neutral toward claim,
            False if negation signals detected.
        """
        if not snippet:
            return True

        hits = sum(1 for p in _NEGATION_PATTERNS if p.search(snippet))
        return hits < _NEGATION_THRESHOLD

    async def _llm_stance_assessment(
        self,
        snippet: str,
        claim_text: str,
    ) -> bool:
        """LLM fallback for stance detection when regex is inconclusive.

        Uses Gemini 3.1 Flash Lite via OpenRouter (~$0.06/500 calls).
        Returns True if snippet supports claim, False if refutes.

        Args:
            snippet: Search result snippet text (>100 chars).
            claim_text: Original claim text for context.

        Returns:
            True if snippet supports/is neutral toward claim,
            False if snippet refutes the claim.
        """
        client = self._get_llm_client()
        if client is None:
            return True  # Default to supporting if no LLM available

        prompt = (
            f"Does the following snippet SUPPORT or REFUTE the claim?\n\n"
            f"CLAIM: {claim_text}\n\n"
            f"SNIPPET: {snippet}\n\n"
            f'Respond with JSON: {{"stance": "supports" | "refutes" | "neutral"}}'
        )
        try:
            response = await client.aio.models.generate_content(
                model="gemini-3.1-flash-lite-preview",
                contents=[prompt],
                config={
                    "temperature": 0.0,
                    "max_output_tokens": 50,
                    "response_format": "json",
                },
            )
            result = json.loads(response.text)
            stance = result.get("stance", "neutral")
            self._logger.debug(
                "llm_stance_result",
                stance=stance,
                snippet=snippet[:80],
            )
            return stance != "refutes"
        except Exception as e:
            self._logger.debug("llm_stance_failed", error=str(e))
            return True  # Default to supporting on failure

    # ── Authority & Relevance ─────────────────────────────────────────

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
        social_media = {
            "twitter.com", "x.com", "reddit.com",
            "facebook.com", "telegram.org",
        }

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
        query_terms -= {
            "site:reuters.com", "site:apnews.com", "or", "and",
            '"', "official", "statement", "press", "release",
        }
        if not query_terms:
            return 0.5

        snippet_lower = snippet.lower()
        matches = sum(1 for term in query_terms if term in snippet_lower)
        return min(1.0, 0.3 + (matches / len(query_terms)) * 0.7)
