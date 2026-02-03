"""Source credibility scoring per Phase 7 CONTEXT.md formula.

Core formula: Claim Score = Sum(SourceCred x Proximity x Precision)

Components:
- SourceCred: Source credibility (pre-configured baselines + type defaults)
- Proximity: Exponential decay with hop_count (0.7^hop)
- Precision: Entity count + temporal precision + verifiability signals

This module provides the building blocks. EchoDetector handles
the logarithmic dampening for circular reporting.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from loguru import logger

from osint_system.config.source_credibility import (
    DOMAIN_PATTERN_DEFAULTS,
    PRECISION_WEIGHTS,
    PROXIMITY_DECAY_FACTOR,
    SOURCE_BASELINES,
    SOURCE_TYPE_DEFAULTS,
)
from osint_system.data_management.schemas import CredibilityBreakdown


@dataclass
class SourceScore:
    """Score components for a single source.

    Attributes:
        source_id: Source identifier (often URL or domain)
        source_cred: Base credibility of the source (0.0-1.0)
        proximity: Proximity score based on hop count (0.0-1.0)
        precision: Precision score based on verifiability signals (0.0-1.0)
        combined: Product of source_cred x proximity x precision
        is_root: Whether this is the root source (not an echo)
        details: Debug information about scoring
    """

    source_id: str
    source_cred: float
    proximity: float
    precision: float
    combined: float  # source_cred * proximity * precision
    is_root: bool = False
    details: Dict[str, Any] = field(default_factory=dict)


class SourceCredibilityScorer:
    """
    Computes source credibility scores for facts.

    Per CONTEXT.md:
    - Pre-configured baselines for known sources
    - Type-based defaults for unknown sources
    - Exponential proximity decay (0.7^hop)
    - Precision from entity count, temporal, verifiability

    Usage:
        scorer = SourceCredibilityScorer()
        score, breakdown = scorer.compute_credibility(fact)

    Attributes:
        baselines: Dict mapping source domains to credibility scores
        type_defaults: Dict mapping source types to default scores
        proximity_decay: Exponential decay factor per hop (default 0.7)
    """

    def __init__(
        self,
        baselines: Optional[Dict[str, float]] = None,
        type_defaults: Optional[Dict[str, float]] = None,
        proximity_decay: float = PROXIMITY_DECAY_FACTOR,
    ):
        """
        Initialize scorer with credibility baselines.

        Args:
            baselines: Custom source baselines (uses defaults if None)
            type_defaults: Custom type defaults (uses defaults if None)
            proximity_decay: Decay factor per hop (default 0.7)
        """
        self.baselines = baselines or SOURCE_BASELINES
        self.type_defaults = type_defaults or SOURCE_TYPE_DEFAULTS
        self.proximity_decay = proximity_decay
        self.logger = logger.bind(component="SourceCredibilityScorer")

    def compute_credibility(
        self,
        fact: Dict[str, Any],
    ) -> tuple[float, CredibilityBreakdown]:
        """
        Compute credibility score for a fact.

        Per CONTEXT.md formula:
        - For single source: SourceCred x Proximity x Precision
        - For multiple sources: Handled by EchoDetector (Phase 8)

        Args:
            fact: ExtractedFact dict with provenance

        Returns:
            (credibility_score, breakdown) tuple where:
            - credibility_score: Combined score 0.0-1.0
            - breakdown: CredibilityBreakdown with all component scores
        """
        provenance = fact.get("provenance")
        if not provenance:
            # No provenance = unknown credibility
            self.logger.debug("No provenance, using default 0.3")
            return 0.3, self._empty_breakdown()

        # Score the primary source
        source_score = self._score_source(fact, provenance)

        # Build breakdown
        breakdown = CredibilityBreakdown(
            s_root=source_score.source_cred,
            s_echoes_sum=0.0,  # Single source, no echoes
            proximity_scores=[source_score.proximity],
            precision_scores=[source_score.precision],
            echo_bonus=0.0,
        )

        credibility = source_score.combined
        self.logger.debug(
            f"Credibility computed: {credibility:.3f}",
            source=source_score.source_id[:50] if source_score.source_id else "unknown",
            components=source_score.details,
        )

        return credibility, breakdown

    def _score_source(
        self,
        fact: Dict[str, Any],
        provenance: Dict[str, Any],
    ) -> SourceScore:
        """
        Score a single source.

        Applies the formula: source_cred x proximity x precision

        Args:
            fact: ExtractedFact dict
            provenance: Provenance dict from fact

        Returns:
            SourceScore with all components
        """
        source_id = provenance.get("source_id", "unknown")

        # 1. Source credibility (baseline lookup)
        source_cred = self._get_source_credibility(
            source_id,
            provenance.get("source_type", "unknown"),
        )

        # 2. Proximity (exponential decay with hop count)
        hop_count = provenance.get("hop_count", 1)
        proximity = self._compute_proximity(hop_count)

        # 3. Precision (verifiability signals)
        precision = self._compute_precision(fact, provenance)

        # Combined score
        combined = source_cred * proximity * precision

        return SourceScore(
            source_id=source_id,
            source_cred=source_cred,
            proximity=proximity,
            precision=precision,
            combined=combined,
            is_root=(hop_count == 0),
            details={
                "hop_count": hop_count,
                "source_type": provenance.get("source_type"),
                "baseline_used": self._find_baseline_key(source_id),
            },
        )

    def _get_source_credibility(
        self,
        source_id: str,
        source_type: str,
    ) -> float:
        """
        Get credibility score for a source.

        Priority order:
        1. Exact match in baselines
        2. Domain extraction and baseline lookup
        3. Domain pattern match (.gov, .edu, etc.)
        4. Type-based default
        5. Fallback to 0.3

        Args:
            source_id: Source identifier (often URL)
            source_type: Source type from provenance

        Returns:
            Credibility score 0.0-1.0
        """
        # Try exact match
        source_lower = source_id.lower()
        if source_lower in self.baselines:
            return self.baselines[source_lower]

        # Extract domain from URL
        domain = self._extract_domain(source_id)
        if domain and domain in self.baselines:
            return self.baselines[domain]

        # Try domain patterns
        if domain:
            for pattern, score in DOMAIN_PATTERN_DEFAULTS.items():
                if domain.endswith(pattern):
                    return score

        # Type-based default
        source_type_lower = source_type.lower() if source_type else "unknown"
        return self.type_defaults.get(source_type_lower, 0.3)

    def _extract_domain(self, source_id: str) -> Optional[str]:
        """
        Extract domain from URL or source identifier.

        Handles:
        - Full URLs (https://www.reuters.com/article/123)
        - Domains (reuters.com)
        - Invalid/empty strings

        Args:
            source_id: Source identifier

        Returns:
            Extracted domain (lowercase, without www.), or None
        """
        if not source_id:
            return None

        try:
            # Try as URL
            parsed = urlparse(source_id)
            if parsed.netloc:
                domain = parsed.netloc.lower()
                # Remove www. prefix
                if domain.startswith("www."):
                    domain = domain[4:]
                return domain

            # Not a URL, might be a domain directly
            if "." in source_id and "/" not in source_id:
                return source_id.lower()

        except Exception:
            pass

        return None

    def _find_baseline_key(self, source_id: str) -> Optional[str]:
        """
        Find which baseline key was used (for debugging).

        Args:
            source_id: Source identifier

        Returns:
            Baseline key if found, None otherwise
        """
        source_lower = source_id.lower()
        if source_lower in self.baselines:
            return source_lower

        domain = self._extract_domain(source_id)
        if domain and domain in self.baselines:
            return domain

        return None

    def _compute_proximity(self, hop_count: int) -> float:
        """
        Compute proximity score with exponential decay.

        Per CONTEXT.md: 0.7^hop (moderate decay)
        - hop=0: 1.0 (eyewitness/direct)
        - hop=1: 0.7
        - hop=2: 0.49
        - hop=3: 0.343

        Args:
            hop_count: Number of hops from original source

        Returns:
            Proximity score 0.0-1.0
        """
        return self.proximity_decay ** hop_count

    def _compute_precision(
        self,
        fact: Dict[str, Any],
        provenance: Dict[str, Any],
    ) -> float:
        """
        Compute precision score from verifiability signals.

        Per CONTEXT.md components:
        - Entity count (more named entities = more precise)
        - Temporal precision (explicit dates = more precise)
        - Has quote (direct quotes = more verifiable)
        - Has document citation (more verifiable)

        Args:
            fact: ExtractedFact dict
            provenance: Provenance dict

        Returns:
            Precision score 0.0-1.0
        """
        scores = {}

        # Entity count factor (0-1, scales with entities)
        entities = fact.get("entities", [])
        entity_count = len(entities)
        # Diminishing returns: 1 entity = 0.53, 3 entities = 1.0
        entity_factor = min(1.0, 0.3 + (entity_count * 0.233))
        scores["entity_count"] = entity_factor * PRECISION_WEIGHTS.get("entity_count", 0.3)

        # Temporal precision factor
        temporal = fact.get("temporal")
        if temporal:
            temporal_precision = temporal.get("temporal_precision", "unknown")
            if temporal_precision == "explicit":
                temporal_factor = 1.0
            elif temporal_precision == "inferred":
                temporal_factor = 0.6
            else:
                temporal_factor = 0.3
        else:
            temporal_factor = 0.3  # No temporal info
        scores["temporal_precision"] = temporal_factor * PRECISION_WEIGHTS.get("temporal_precision", 0.3)

        # Quote factor
        quote = provenance.get("quote", "")
        attribution_phrase = provenance.get("attribution_phrase", "")
        has_direct_quote = bool(quote) and (
            '"' in quote or "'" in quote or
            "said" in attribution_phrase.lower()
        )
        quote_factor = 1.0 if has_direct_quote else 0.5
        scores["has_quote"] = quote_factor * PRECISION_WEIGHTS.get("has_quote", 0.2)

        # Document citation factor
        attribution_chain = provenance.get("attribution_chain", [])
        has_document = any(
            hop.get("type") in ("document", "official_statement", "academic")
            for hop in attribution_chain
        )
        doc_factor = 1.0 if has_document else 0.5
        scores["has_document"] = doc_factor * PRECISION_WEIGHTS.get("has_document", 0.2)

        # Total precision (weighted sum, normalized to 0-1)
        total = sum(scores.values())
        # Ensure we're in 0-1 range (weights should sum to 1.0)
        precision = min(1.0, total)

        return precision

    def _empty_breakdown(self) -> CredibilityBreakdown:
        """Create empty breakdown for missing provenance."""
        return CredibilityBreakdown(
            s_root=0.3,
            s_echoes_sum=0.0,
            proximity_scores=[],
            precision_scores=[],
            echo_bonus=0.0,
        )

    def score_multiple_sources(
        self,
        fact: Dict[str, Any],
        additional_provenances: List[Dict[str, Any]],
    ) -> tuple[float, CredibilityBreakdown, List[SourceScore]]:
        """
        Score a fact with multiple sources (for consolidation).

        Used by EchoDetector to handle multiple sources reporting same claim.
        The primary source becomes the root; additional sources become echoes.

        Args:
            fact: ExtractedFact dict (primary provenance)
            additional_provenances: List of additional provenance dicts

        Returns:
            (credibility_score, breakdown, source_scores) tuple
        """
        # Score primary source
        primary_provenance = fact.get("provenance", {})
        source_scores = []

        if primary_provenance:
            primary_score = self._score_source(fact, primary_provenance)
            primary_score.is_root = True
            source_scores.append(primary_score)

        # Score additional sources
        for prov in additional_provenances:
            # Create minimal fact dict for scoring
            minimal_fact = {
                "entities": fact.get("entities", []),
                "temporal": fact.get("temporal"),
            }
            score = self._score_source(minimal_fact, prov)
            source_scores.append(score)

        if not source_scores:
            return 0.3, self._empty_breakdown(), []

        # Root is highest credibility source
        source_scores.sort(key=lambda s: s.combined, reverse=True)
        root = source_scores[0]
        root.is_root = True
        echoes = source_scores[1:]

        # Build breakdown
        breakdown = CredibilityBreakdown(
            s_root=root.source_cred,
            s_echoes_sum=sum(s.combined for s in echoes),
            proximity_scores=[s.proximity for s in source_scores],
            precision_scores=[s.precision for s in source_scores],
            echo_bonus=0.0,  # Calculated by EchoDetector
        )

        # Credibility is root score (echo bonus added by EchoDetector)
        return root.combined, breakdown, source_scores


__all__ = ["SourceCredibilityScorer", "SourceScore"]
