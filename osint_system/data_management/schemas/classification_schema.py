"""Classification schema for extracted facts.

Per Phase 7 CONTEXT.md: Classifications are SEPARATE records from facts.
- Facts remain immutable (extraction output)
- Classifications are mutable (update as new information arrives)
- Links fact_id to classification data

Design principle: Detail over compactness. Full audit trails enable:
- Debugging classification logic
- Tracking how classifications evolve
- Understanding WHY something is dubious (not just that it is)
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ImpactTier(str, Enum):
    """Impact tier for facts.

    Per CONTEXT.md: Based on geopolitical significance, NOT relevance to objective.
    Both entity significance AND event type contribute.
    Investigation-relative: same fact may be critical in one investigation, less-critical in another.
    """

    CRITICAL = "critical"
    LESS_CRITICAL = "less_critical"


class DubiousFlag(str, Enum):
    """Taxonomy of doubt - species of dubious classification.

    Per CONTEXT.md: Each species triggers a specific Phase 8 subroutine.
    Flags are independent - a fact can have multiple flags.

    PHANTOM: Structural failure - echo without speaker (hop_count > 2 AND no primary)
    FOG: Attribution failure - vague attribution ("sources say", claim_clarity < 0.5)
    ANOMALY: Coherence failure - contradictions between trusted sources
    NOISE: Reputation failure - source_credibility < 0.3 (batch analysis only)
    """

    PHANTOM = "phantom"  # Structural failure: echo without traceable root
    FOG = "fog"  # Attribution failure: vague/unclear attribution
    ANOMALY = "anomaly"  # Coherence failure: contradictions detected
    NOISE = "noise"  # Reputation failure: known unreliable source


class CredibilityBreakdown(BaseModel):
    """Full credibility score breakdown for debugging and evolution.

    Per CONTEXT.md formula: Claim Score = Σ(SourceCred × Proximity × Precision)
    Plus logarithmic echo dampening: Total = S_root + (α · log₁₀(1 + Σ S_echoes))

    Storing components enables:
    - Formula debugging
    - Score evolution without re-computation
    - Understanding WHY a fact has its score
    """

    s_root: float = Field(0.0, ge=0.0, le=1.0, description="Root source credibility")
    s_echoes_sum: float = Field(
        0.0, ge=0.0, description="Sum of echo source credibilities"
    )
    proximity_scores: list[float] = Field(
        default_factory=list, description="Proximity scores per source (0.7^hop)"
    )
    precision_scores: list[float] = Field(
        default_factory=list, description="Precision scores per source"
    )
    echo_bonus: float = Field(
        0.0,
        ge=0.0,
        description="Logarithmic contribution from echoes: α · log₁₀(1 + Σ S_echoes)",
    )
    alpha: float = Field(0.2, description="Echo dampening factor")

    def compute_total(self) -> float:
        """Compute total score from components.

        Formula: S_root + (α · log₁₀(1 + Σ S_echoes))
        This gives diminishing returns for additional echo sources,
        preventing botnet gaming.

        Returns:
            Total credibility score (0.0-1.0+, can exceed 1.0 with echoes)
        """
        import math

        return self.s_root + (self.alpha * math.log10(1 + self.s_echoes_sum))

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "s_root": 0.9,
                    "s_echoes_sum": 2.5,
                    "proximity_scores": [1.0, 0.7, 0.49],
                    "precision_scores": [0.9, 0.85, 0.7],
                    "echo_bonus": 0.11,
                    "alpha": 0.2,
                }
            ]
        }
    }


class ClassificationReasoning(BaseModel):
    """Reasoning for each dubious flag.

    Per CONTEXT.md: Phase 8 needs to know WHY something is dubious
    to select the appropriate verification subroutine.
    """

    flag: DubiousFlag
    reason: str = Field(..., description="Human-readable explanation")
    trigger_values: dict = Field(
        default_factory=dict, description="Values that triggered this flag"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "flag": "phantom",
                    "reason": "hop_count=4, no primary_source found",
                    "trigger_values": {"hop_count": 4, "primary_source": None},
                },
                {
                    "flag": "fog",
                    "reason": "attribution contains 'reportedly'",
                    "trigger_values": {
                        "attribution_phrase": "reportedly",
                        "claim_clarity": 0.4,
                    },
                },
            ]
        }
    }


class ClassificationHistory(BaseModel):
    """Single history entry for classification audit trail.

    Per CONTEXT.md: Full audit trail, not just current state.
    Enables tracking how classifications evolve over investigation lifecycle.
    """

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    previous_impact_tier: Optional[ImpactTier] = None
    previous_dubious_flags: list[DubiousFlag] = Field(default_factory=list)
    previous_credibility_score: Optional[float] = None
    trigger: str = Field(..., description="What caused this re-classification")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "timestamp": "2024-03-15T14:30:00Z",
                    "previous_impact_tier": "less_critical",
                    "previous_dubious_flags": ["phantom"],
                    "previous_credibility_score": 0.45,
                    "trigger": "new corroborating source added",
                }
            ]
        }
    }


class FactClassification(BaseModel):
    """Complete classification record for a fact.

    Per CONTEXT.md: Separate from ExtractedFact to allow:
    - Immutable facts with mutable classifications
    - Dynamic re-classification as new information arrives
    - Full audit trails

    Indexing considerations for Phase 8:
    - Priority queue (ordered by priority_score) for general processing
    - Flag-type indexes (all Phantoms, all Fogs, etc.) for specialized subroutines

    Usage:
        classification = FactClassification(
            fact_id="uuid-here",
            investigation_id="inv-123",
            impact_tier=ImpactTier.CRITICAL,
            credibility_score=0.85
        )
    """

    # Identity - links to ExtractedFact by ID, not embedding
    fact_id: str = Field(..., description="ID of the ExtractedFact being classified")
    investigation_id: str = Field(..., description="Investigation scope")

    # Classification output - impact and dubious are orthogonal
    impact_tier: ImpactTier = Field(
        ImpactTier.LESS_CRITICAL,
        description="critical or less_critical based on geopolitical significance",
    )
    dubious_flags: list[DubiousFlag] = Field(
        default_factory=list,
        description="List of doubt species (can be empty or multiple)",
    )

    # Scores
    priority_score: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Impact × Fixability for Phase 8 queue ordering",
    )
    credibility_score: float = Field(
        0.0, ge=0.0, le=1.0, description="Composite credibility score"
    )
    credibility_breakdown: Optional[CredibilityBreakdown] = Field(
        None, description="Full breakdown for debugging and formula evolution"
    )

    # Reasoning - explains WHY classification was made
    classification_reasoning: list[ClassificationReasoning] = Field(
        default_factory=list, description="Explanation for each dubious flag"
    )
    impact_reasoning: Optional[str] = Field(
        None, description="Why this fact was classified as critical/less_critical"
    )

    # Audit trail
    history: list[ClassificationHistory] = Field(
        default_factory=list, description="Classification history for audit"
    )

    # Timestamps
    classified_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Initial classification timestamp",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Last update timestamp",
    )

    @property
    def is_dubious(self) -> bool:
        """Check if fact has any dubious flags.

        Returns:
            True if at least one dubious flag is set
        """
        return len(self.dubious_flags) > 0

    @property
    def is_critical_dubious(self) -> bool:
        """Check if fact is both critical AND dubious (priority verification).

        Per CONTEXT.md: High-impact dubious facts get priority verification.
        These are the most important facts to fix.

        Returns:
            True if critical tier AND has dubious flags
        """
        return self.impact_tier == ImpactTier.CRITICAL and self.is_dubious

    @property
    def is_noise(self) -> bool:
        """Check if fact is pure noise (batch analysis only, not individual verification).

        Per CONTEXT.md: NOISE does not enter Phase 8 individual verification queue.
        Batch analysis only - aggregate for pattern detection.

        Returns:
            True if NOISE is the only dubious flag
        """
        return (
            DubiousFlag.NOISE in self.dubious_flags and len(self.dubious_flags) == 1
        )

    @property
    def requires_verification(self) -> bool:
        """Check if fact requires Phase 8 verification.

        Returns:
            True if dubious (with flags other than noise-only) or has any dubious flag
            that is not pure noise
        """
        if not self.is_dubious:
            return False
        # Pure noise doesn't require individual verification
        if self.is_noise:
            return False
        return True

    def add_history_entry(self, trigger: str) -> None:
        """Add current state to history before modification.

        Call this BEFORE modifying classification fields to preserve
        the previous state in the audit trail.

        Args:
            trigger: Human-readable explanation of what triggered re-classification
        """
        entry = ClassificationHistory(
            previous_impact_tier=self.impact_tier,
            previous_dubious_flags=list(self.dubious_flags),
            previous_credibility_score=self.credibility_score,
            trigger=trigger,
        )
        self.history.append(entry)
        self.updated_at = datetime.now(timezone.utc)

    def get_flag_reasoning(self, flag: DubiousFlag) -> Optional[ClassificationReasoning]:
        """Get reasoning for a specific dubious flag.

        Args:
            flag: The dubious flag to look up

        Returns:
            ClassificationReasoning if found, None otherwise
        """
        for reasoning in self.classification_reasoning:
            if reasoning.flag == flag:
                return reasoning
        return None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "fact_id": "uuid-fact-123",
                    "investigation_id": "inv-456",
                    "impact_tier": "critical",
                    "dubious_flags": ["phantom", "fog"],
                    "priority_score": 0.85,
                    "credibility_score": 0.45,
                    "credibility_breakdown": {
                        "s_root": 0.4,
                        "s_echoes_sum": 0.3,
                        "proximity_scores": [0.7, 0.49],
                        "precision_scores": [0.8, 0.6],
                        "echo_bonus": 0.05,
                        "alpha": 0.2,
                    },
                    "classification_reasoning": [
                        {
                            "flag": "phantom",
                            "reason": "hop_count=4, no primary_source found",
                            "trigger_values": {"hop_count": 4},
                        },
                        {
                            "flag": "fog",
                            "reason": "attribution contains 'reportedly'",
                            "trigger_values": {"claim_clarity": 0.35},
                        },
                    ],
                    "impact_reasoning": "Involves world leader and military action",
                    "classified_at": "2024-03-15T12:00:00Z",
                    "updated_at": "2024-03-15T12:00:00Z",
                }
            ]
        }
    }
