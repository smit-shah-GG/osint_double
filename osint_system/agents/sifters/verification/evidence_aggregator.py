"""Authority-weighted evidence aggregation per CONTEXT.md decisions.

Evaluates collected evidence to determine if facts are confirmed, refuted,
or still pending. Uses Phase 7 SourceCredibilityScorer for consistent
authority scoring and graduated confidence boosts by source type.

Confirmation thresholds:
- 1 high-authority source (>=0.85) single-handedly confirms
- 2+ independent lower-authority sources required otherwise
- Refutation requires authority >= 0.7

Graduated confidence boosts:
- Wire service: +0.3
- Official statement: +0.25
- News outlet: +0.2
- Social media: +0.1
- Cumulative, capped at 1.0

Usage:
    from osint_system.agents.sifters.verification.evidence_aggregator import EvidenceAggregator

    aggregator = EvidenceAggregator()
    evaluation = await aggregator.evaluate_evidence(fact, evidence_items)
"""

from typing import Any, Optional
from urllib.parse import urlparse

import structlog

from osint_system.agents.sifters.credibility.source_scorer import (
    SourceCredibilityScorer,
)
from osint_system.agents.sifters.verification.schemas import (
    EvidenceEvaluation,
    EvidenceItem,
    VerificationStatus,
)
from osint_system.config.source_credibility import (
    SOURCE_BASELINES,
)

# Graduated confidence boosts per CONTEXT.md
CONFIDENCE_BOOSTS: dict[str, float] = {
    "wire_service": 0.3,
    "official_statement": 0.25,
    "news_outlet": 0.2,
    "social_media": 0.1,
}

# Known wire service domains for source type inference
_WIRE_SERVICE_DOMAINS = {"reuters.com", "apnews.com", "afp.com"}

# Social media domains for source type inference
_SOCIAL_MEDIA_DOMAINS = {"twitter.com", "x.com", "reddit.com", "facebook.com", "telegram.org"}


class EvidenceAggregator:
    """Authority-weighted evidence aggregation per CONTEXT.md.

    Confirmation thresholds:
    - 1 high-authority source (>=0.85) OR
    - 2+ independent lower-authority sources

    Graduated confidence boosts:
    - Wire service: +0.3
    - Official statement: +0.25
    - News outlet: +0.2
    - Social media: +0.1
    """

    def __init__(
        self,
        high_authority_threshold: float = 0.85,
        refutation_threshold: float = 0.7,
        source_scorer: Optional[SourceCredibilityScorer] = None,
    ) -> None:
        """Initialize EvidenceAggregator.

        Args:
            high_authority_threshold: Minimum authority for single-source confirmation.
            refutation_threshold: Minimum authority for refuting evidence.
            source_scorer: Phase 7 scorer for consistent authority scoring.
                          Lazy-initialized if not provided.
        """
        self.high_authority_threshold = high_authority_threshold
        self.refutation_threshold = refutation_threshold
        self._source_scorer = source_scorer
        self._logger = structlog.get_logger().bind(component="EvidenceAggregator")

    def _get_source_scorer(self) -> SourceCredibilityScorer:
        """Lazy-init SourceCredibilityScorer from Phase 7."""
        if self._source_scorer is None:
            self._source_scorer = SourceCredibilityScorer()
        return self._source_scorer

    async def evaluate_evidence(
        self,
        fact: dict[str, Any],
        evidence_items: list[EvidenceItem],
    ) -> EvidenceEvaluation:
        """Evaluate if evidence is sufficient for confirmation/refutation.

        Per CONTEXT.md:
        1. Check for high-authority single-source confirmation
        2. Check for 2+ independent lower-authority confirmation
        3. Check for refutation (requires authority >= 0.7)
        4. Otherwise, PENDING (insufficient evidence)

        Args:
            fact: Fact dict with claim, entities, provenance fields.
            evidence_items: List of EvidenceItem objects from search.

        Returns:
            EvidenceEvaluation with status, evidence lists, and confidence boost.
        """
        if not evidence_items:
            return EvidenceEvaluation(
                status=VerificationStatus.PENDING,
                reasoning="No evidence collected",
            )

        # Score each evidence item's authority
        scored_items = [
            (item, self._get_authority_score(item.source_url))
            for item in evidence_items
        ]

        # Partition into supporting and refuting
        supporting = [(item, score) for item, score in scored_items if item.supports_claim]
        refuting = [
            (item, score)
            for item, score in scored_items
            if not item.supports_claim and item.relevance_score >= 0.7
        ]

        supporting_items = [item for item, _ in supporting]
        refuting_items = [item for item, _ in refuting]

        # 1. Check high-authority single-source confirmation
        high_authority_supporting = [
            (item, score)
            for item, score in supporting
            if score >= self.high_authority_threshold
        ]
        if high_authority_supporting:
            boost = self._calculate_confidence_boost(supporting)
            self._logger.info(
                "high_authority_confirmation",
                source=high_authority_supporting[0][0].source_domain,
                authority=high_authority_supporting[0][1],
                boost=boost,
            )
            return EvidenceEvaluation(
                status=VerificationStatus.CONFIRMED,
                confidence_boost=boost,
                supporting_evidence=supporting_items,
                refuting_evidence=refuting_items,
                reasoning=f"High-authority source ({high_authority_supporting[0][0].source_domain}, "
                f"authority={high_authority_supporting[0][1]:.2f}) confirms claim",
            )

        # 2. Check 2+ independent lower-authority confirmation
        independent_supporting = self._filter_independent_sources(supporting)
        if len(independent_supporting) >= 2:
            boost = self._calculate_confidence_boost(independent_supporting)
            domains = [item.source_domain for item, _ in independent_supporting[:3]]
            self._logger.info(
                "multi_source_confirmation",
                independent_count=len(independent_supporting),
                domains=domains,
                boost=boost,
            )
            return EvidenceEvaluation(
                status=VerificationStatus.CONFIRMED,
                confidence_boost=boost,
                supporting_evidence=supporting_items,
                refuting_evidence=refuting_items,
                reasoning=f"{len(independent_supporting)} independent sources confirm "
                f"({', '.join(domains)})",
            )

        # 3. Check for refutation (authority >= 0.7)
        high_authority_refuting = [
            (item, score)
            for item, score in refuting
            if score >= self.refutation_threshold
        ]
        if high_authority_refuting:
            boost = 0.0  # No boost for refutation
            self._logger.info(
                "refutation_detected",
                source=high_authority_refuting[0][0].source_domain,
                authority=high_authority_refuting[0][1],
            )
            return EvidenceEvaluation(
                status=VerificationStatus.REFUTED,
                confidence_boost=boost,
                supporting_evidence=supporting_items,
                refuting_evidence=refuting_items,
                reasoning=f"Refuted by {high_authority_refuting[0][0].source_domain} "
                f"(authority={high_authority_refuting[0][1]:.2f})",
            )

        # 4. Insufficient evidence → PENDING
        self._logger.debug(
            "insufficient_evidence",
            supporting_count=len(supporting),
            refuting_count=len(refuting),
        )
        return EvidenceEvaluation(
            status=VerificationStatus.PENDING,
            supporting_evidence=supporting_items,
            refuting_evidence=refuting_items,
            reasoning=f"Insufficient evidence: {len(supporting)} supporting, "
            f"{len(refuting)} refuting (none meet thresholds)",
        )

    def _get_authority_score(self, source_url: str) -> float:
        """Get authority score for a source URL using Phase 7 scorer.

        Uses SourceCredibilityScorer's domain lookup for consistent scoring.

        Args:
            source_url: Full URL of the source.

        Returns:
            Authority score 0.0-1.0.
        """
        scorer = self._get_source_scorer()
        domain = scorer._extract_domain(source_url)
        if not domain:
            return 0.4

        return scorer._get_source_credibility(domain, "unknown")

    def _get_source_type(self, source_url: str) -> str:
        """Infer source type from URL domain.

        Args:
            source_url: Full URL of the source.

        Returns:
            One of: wire_service, official_statement, news_outlet, social_media.
        """
        scorer = self._get_source_scorer()
        domain = scorer._extract_domain(source_url) or ""

        if domain in _WIRE_SERVICE_DOMAINS:
            return "wire_service"
        if domain in _SOCIAL_MEDIA_DOMAINS:
            return "social_media"
        if domain.endswith(".gov") or domain.endswith(".mil") or domain.endswith(".edu"):
            return "official_statement"
        return "news_outlet"

    def _filter_independent_sources(
        self,
        scored_items: list[tuple[EvidenceItem, float]],
    ) -> list[tuple[EvidenceItem, float]]:
        """Filter to independent sources (different domains).

        Per CONTEXT.md: "Different domains AND different parent companies."
        For MVP: different domains is sufficient.

        Args:
            scored_items: List of (EvidenceItem, authority_score) tuples.

        Returns:
            Filtered list with one entry per unique domain.
        """
        seen_domains: set[str] = set()
        independent: list[tuple[EvidenceItem, float]] = []

        # Sort by authority descending to keep highest-authority per domain
        sorted_items = sorted(scored_items, key=lambda x: x[1], reverse=True)

        for item, score in sorted_items:
            domain = item.source_domain
            if domain not in seen_domains:
                seen_domains.add(domain)
                independent.append((item, score))

        return independent

    def _calculate_confidence_boost(
        self,
        scored_items: list[tuple[EvidenceItem, float]],
    ) -> float:
        """Calculate cumulative confidence boost from supporting evidence.

        Per CONTEXT.md: Graduated boosts by source type, cumulative, capped at 1.0.

        Args:
            scored_items: List of (EvidenceItem, authority_score) tuples.

        Returns:
            Total confidence boost, capped at 1.0.
        """
        total_boost = 0.0

        for item, _ in scored_items:
            source_type = item.source_type or self._get_source_type(item.source_url)
            boost = CONFIDENCE_BOOSTS.get(source_type, 0.1)
            total_boost += boost

        return min(1.0, total_boost)
