"""Echo detection for circular reporting and source diversity.

Per Phase 7 CONTEXT.md:
Root Source Diversity (anti-circular-reporting):
- Detect shared roots via explicit attribution tracking (provenance chain from Phase 6)
- Use logarithmic decay for echo scoring:
  Total Score = S_root + (alpha * log10(1 + sum(S_echoes)))

The logarithmic formula prevents gaming:
- Fact A (Reuters only): Score 0.9
- Fact B (Reuters + 3 Major Papers): Score ~1.1 (verified by editorial review)
- Fact C (Reuters + 10,000 Twitter Bots): Score ~1.15 (effectively capped)

1M low-quality bots get crushed by the log function.
"""

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger

from osint_system.config.source_credibility import ECHO_DAMPENING_ALPHA
from osint_system.data_management.schemas import CredibilityBreakdown


@dataclass
class EchoCluster:
    """A cluster of sources sharing the same root.

    Sources that cite the same original entity are grouped together.
    This enables detection of circular reporting patterns.

    Attributes:
        root_entity: Name/ID of the root source entity
        root_hop: Hop level of the root (0 = eyewitness)
        sources: List of source IDs in this cluster
        combined_score: Sum of credibility scores for cluster members
    """

    root_entity: str
    root_hop: int
    sources: List[str] = field(default_factory=list)
    combined_score: float = 0.0


@dataclass
class EchoScore:
    """Result of echo analysis.

    Contains the root score, echo contributions, and total score
    after applying logarithmic dampening.

    Attributes:
        root_score: S_root - highest quality source score
        echo_sum: Sum of all echo source scores
        echo_bonus: Dampened contribution: alpha * log10(1 + echo_sum)
        total_score: S_root + echo_bonus
        unique_roots: Number of independent root sources
        echo_clusters: Clusters of sources by root
        circular_warning: True if circular reporting pattern detected
    """

    root_score: float           # S_root: highest quality source
    echo_sum: float             # Sum of S_echoes
    echo_bonus: float           # alpha * log10(1 + sum(S_echoes))
    total_score: float          # S_root + echo_bonus
    unique_roots: int           # Number of independent root sources
    echo_clusters: List[EchoCluster] = field(default_factory=list)
    circular_warning: bool = False  # True if circular reporting detected


class EchoDetector:
    """
    Detects echo chambers and computes logarithmic dampening.

    Per CONTEXT.md:
    - Detect shared roots via attribution chain analysis
    - Apply logarithmic dampening to prevent gaming
    - First quality echo adds value, 100th adds near-zero

    The logarithmic formula is specifically designed to be botnet-proof:
    - 1M low-quality bots contribute approximately the same as 10 quality echoes
    - Prevents manipulation by sheer volume

    Usage:
        detector = EchoDetector()
        echo_score = detector.analyze_sources(provenances, source_scores)
        breakdown.echo_bonus = echo_score.echo_bonus

    Attributes:
        alpha: Dampening factor (default 0.2 per CONTEXT.md)
    """

    def __init__(self, alpha: float = ECHO_DAMPENING_ALPHA):
        """
        Initialize echo detector.

        Args:
            alpha: Dampening factor for echo contribution (default 0.2)
                   Higher alpha = more weight to echoes
                   Lower alpha = more emphasis on root source
        """
        self.alpha = alpha
        self.logger = logger.bind(component="EchoDetector")

    def analyze_sources(
        self,
        provenances: List[Dict[str, Any]],
        source_scores: Optional[List[float]] = None,
    ) -> EchoScore:
        """
        Analyze multiple sources for echoes and compute dampened score.

        Takes a list of provenances (from multiple sources reporting the same fact)
        and determines how much credibility should be attributed to each.

        Args:
            provenances: List of provenance dicts from variants/corroborating facts
            source_scores: Pre-computed credibility scores for each source

        Returns:
            EchoScore with root, echo contribution, and total
        """
        if not provenances:
            return EchoScore(
                root_score=0.0,
                echo_sum=0.0,
                echo_bonus=0.0,
                total_score=0.0,
                unique_roots=0,
            )

        # Default scores if not provided
        if source_scores is None:
            source_scores = [0.5] * len(provenances)

        # Ensure we have scores for all provenances
        while len(source_scores) < len(provenances):
            source_scores.append(0.5)

        # Cluster sources by root
        clusters = self._cluster_by_root(provenances, source_scores)

        # Find the highest quality independent root
        root_clusters = [c for c in clusters if c.root_hop == 0 or len(c.sources) == 1]
        if root_clusters:
            root_cluster = max(root_clusters, key=lambda c: c.combined_score)
            root_score = root_cluster.combined_score
        else:
            # No clear root, use highest scoring source
            root_score = max(source_scores) if source_scores else 0.0

        # Compute echo sum (all sources except the root)
        echo_sum = sum(source_scores) - root_score

        # Apply logarithmic dampening
        echo_bonus = self._compute_echo_bonus(echo_sum)

        # Total score
        total_score = root_score + echo_bonus

        # Detect circular reporting
        circular_warning = self._detect_circular_reporting(clusters, provenances)

        unique_roots = len([c for c in clusters if c.root_hop == 0])

        result = EchoScore(
            root_score=root_score,
            echo_sum=echo_sum,
            echo_bonus=echo_bonus,
            total_score=total_score,
            unique_roots=unique_roots,
            echo_clusters=clusters,
            circular_warning=circular_warning,
        )

        self.logger.debug(
            f"Echo analysis: root={root_score:.2f}, echo_bonus={echo_bonus:.3f}, total={total_score:.2f}",
            unique_roots=unique_roots,
            circular=circular_warning,
        )

        return result

    def _cluster_by_root(
        self,
        provenances: List[Dict[str, Any]],
        source_scores: List[float],
    ) -> List[EchoCluster]:
        """
        Cluster sources by their ultimate root in attribution chain.

        Sources citing the same original entity are clustered together.
        This enables detection of circular reporting where multiple outlets
        all trace back to a single original source.

        Args:
            provenances: List of provenance dicts
            source_scores: Corresponding credibility scores

        Returns:
            List of EchoCluster objects
        """
        clusters: Dict[str, EchoCluster] = {}

        for prov, score in zip(provenances, source_scores):
            # Find root entity from attribution chain
            root_entity, root_hop = self._find_root(prov)

            if root_entity not in clusters:
                clusters[root_entity] = EchoCluster(
                    root_entity=root_entity,
                    root_hop=root_hop,
                )

            clusters[root_entity].sources.append(prov.get("source_id", "unknown"))
            clusters[root_entity].combined_score += score

        return list(clusters.values())

    def _find_root(self, provenance: Dict[str, Any]) -> tuple[str, int]:
        """
        Find the root entity in an attribution chain.

        The root is the entity closest to the original source (lowest hop number).

        Args:
            provenance: Provenance dict with attribution_chain

        Returns:
            (root_entity, root_hop): Name of root and its hop level
        """
        attribution_chain = provenance.get("attribution_chain", [])

        if attribution_chain:
            # Find the hop with lowest hop number (closest to origin)
            root_hop = min(attribution_chain, key=lambda h: h.get("hop", 999))
            return root_hop.get("entity", "unknown"), root_hop.get("hop", 0)

        # No chain, use source_id as root
        source_id = provenance.get("source_id", "unknown")
        hop_count = provenance.get("hop_count", 1)
        return source_id, hop_count

    def _compute_echo_bonus(self, echo_sum: float) -> float:
        """
        Compute logarithmic echo bonus.

        Per CONTEXT.md: alpha * log10(1 + sum(S_echoes))

        Logarithmic growth examples (alpha=0.2):
        - echo_sum=0: bonus=0
        - echo_sum=1: bonus=alpha*log10(2) ~ 0.060
        - echo_sum=10: bonus=alpha*log10(11) ~ 0.208
        - echo_sum=100: bonus=alpha*log10(101) ~ 0.401
        - echo_sum=10000: bonus=alpha*log10(10001) ~ 0.800

        Diminishing returns crush botnet spam.

        Args:
            echo_sum: Sum of all echo source scores

        Returns:
            Echo bonus (always >= 0)
        """
        if echo_sum <= 0:
            return 0.0

        return self.alpha * math.log10(1 + echo_sum)

    def _detect_circular_reporting(
        self,
        clusters: List[EchoCluster],
        provenances: List[Dict[str, Any]],
    ) -> bool:
        """
        Detect potential circular reporting patterns.

        Circular reporting is when multiple outlets appear to independently
        confirm a fact, but actually all trace back to the same original source.
        This creates an illusion of corroboration.

        Warnings triggered when:
        - All sources trace back to same root
        - No primary sources (all hop_count > 0)
        - Suspicious cross-citation patterns

        Args:
            clusters: EchoCluster objects from _cluster_by_root
            provenances: Original provenance dicts

        Returns:
            True if circular reporting pattern detected
        """
        if len(provenances) <= 1:
            return False

        # Check if all cluster to single root
        if len(clusters) == 1 and len(provenances) > 2:
            cluster = clusters[0]
            if cluster.root_hop > 0:
                # All sources trace to non-primary root
                self.logger.warning(
                    f"Potential circular reporting: {len(provenances)} sources, "
                    f"single root at hop {cluster.root_hop}"
                )
                return True

        # Check if no primary sources exist
        has_primary = any(
            p.get("hop_count", 1) == 0 or
            p.get("source_classification") == "primary"
            for p in provenances
        )
        if not has_primary and len(provenances) > 3:
            self.logger.warning(
                f"No primary sources among {len(provenances)} sources"
            )
            return True

        return False

    def update_breakdown(
        self,
        breakdown: CredibilityBreakdown,
        echo_score: EchoScore,
    ) -> CredibilityBreakdown:
        """
        Update credibility breakdown with echo analysis results.

        Call this after analyze_sources() to update the breakdown
        with the echo bonus.

        Args:
            breakdown: Existing breakdown from SourceCredibilityScorer
            echo_score: Result from analyze_sources()

        Returns:
            Updated breakdown with echo_bonus set
        """
        breakdown.s_root = echo_score.root_score
        breakdown.s_echoes_sum = echo_score.echo_sum
        breakdown.echo_bonus = echo_score.echo_bonus
        return breakdown

    def compute_corroboration_strength(
        self,
        unique_roots: int,
        root_score: float,
    ) -> float:
        """
        Compute how well a fact is corroborated.

        More independent roots = stronger corroboration.
        Used for impact assessment (well-corroborated critical facts).

        Corroboration strength factors:
        - Number of unique independent sources (roots)
        - Quality of those sources (root_score)

        Args:
            unique_roots: Number of independent root sources
            root_score: Highest quality source score

        Returns:
            Corroboration strength 0.0-1.0
        """
        if unique_roots <= 1:
            return 0.3  # Single source

        # Diminishing returns for more roots
        # 2 roots: 0.475, 3 roots: 0.65, 4 roots: 0.825, 5+: 1.0
        root_factor = min(1.0, 0.3 + (unique_roots - 1) * 0.175)
        return root_factor * min(1.0, root_score + 0.2)

    def analyze_single_source(
        self,
        provenance: Dict[str, Any],
        source_score: float,
    ) -> EchoScore:
        """
        Analyze a single source (convenience method).

        For single-source facts, there are no echoes.
        This provides a consistent interface.

        Args:
            provenance: Single provenance dict
            source_score: Credibility score

        Returns:
            EchoScore with root_score = source_score and no echo bonus
        """
        return EchoScore(
            root_score=source_score,
            echo_sum=0.0,
            echo_bonus=0.0,
            total_score=source_score,
            unique_roots=1,
            echo_clusters=[],
            circular_warning=False,
        )


__all__ = ["EchoDetector", "EchoScore", "EchoCluster"]
