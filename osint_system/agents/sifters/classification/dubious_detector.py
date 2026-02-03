"""Dubious detection using Boolean logic gates per Phase 7 CONTEXT.md.

The Taxonomy of Doubt identifies the SPECIES of doubt, not magnitude.
Each species triggers a specific Phase 8 verification subroutine.

| Species   | Trigger (Logic Gate)                        | Signal             | Phase 8 Action          |
|-----------|---------------------------------------------|--------------------| ------------------------|
| PHANTOM   | hop_count > 2 AND primary_source IS NULL    | Echo without root  | Trace back to find root |
| FOG       | claim_clarity < 0.5 OR vague attribution    | Speaker is mumbling| Find harder claim       |
| ANOMALY   | contradiction_count > 0                     | Sources disagree   | Arbitrate               |
| NOISE     | source_credibility < 0.3                    | Known unreliable   | Batch analysis only     |

CRITICAL: Uses Boolean logic gates, NOT weighted formulas.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger

from osint_system.config.prompts.classification_prompts import VAGUE_ATTRIBUTION_PATTERNS
from osint_system.data_management.schemas import ClassificationReasoning, DubiousFlag


@dataclass
class DubiousResult:
    """Result of dubious detection.

    Attributes:
        flags: List of dubious flags triggered by Boolean logic gates.
        reasoning: Detailed reasoning for each triggered flag.
        fixability_score: How easily this fact can be verified (0.0-1.0).
    """

    flags: List[DubiousFlag] = field(default_factory=list)
    reasoning: List[ClassificationReasoning] = field(default_factory=list)
    fixability_score: float = 0.0  # How easily can this be verified?


class DubiousDetector:
    """
    Detects dubious facts using Boolean logic gates.

    Per CONTEXT.md: Dubious classification identifies the SPECIES of doubt,
    not magnitude. Each species triggers a specific Phase 8 subroutine.

    Flags are independent - a fact can have multiple flags (Phantom + Fog).

    Boolean Logic Gates (NOT weighted formulas):
        - PHANTOM: hop_count > 2 AND primary_source IS NULL
        - FOG: claim_clarity < 0.5 OR attribution contains vague patterns
        - ANOMALY: contradiction_count > 0 (input from external detector)
        - NOISE: source_credibility < 0.3 (batch analysis only)

    Usage:
        detector = DubiousDetector()
        result = detector.detect(fact, credibility_score, contradictions)

    Example:
        >>> detector = DubiousDetector()
        >>> phantom_fact = {
        ...     'fact_id': 'phantom-1',
        ...     'claim': {'text': 'Some claim'},
        ...     'provenance': {'hop_count': 4, 'source_classification': 'tertiary'}
        ... }
        >>> result = detector.detect(phantom_fact, credibility_score=0.5)
        >>> DubiousFlag.PHANTOM in result.flags
        True
    """

    # Default thresholds (from CONTEXT.md)
    PHANTOM_HOP_THRESHOLD = 2
    FOG_CLARITY_THRESHOLD = 0.5
    NOISE_CREDIBILITY_THRESHOLD = 0.3

    def __init__(
        self,
        phantom_hop_threshold: int = PHANTOM_HOP_THRESHOLD,
        fog_clarity_threshold: float = FOG_CLARITY_THRESHOLD,
        noise_credibility_threshold: float = NOISE_CREDIBILITY_THRESHOLD,
    ):
        """
        Initialize dubious detector with configurable thresholds.

        Args:
            phantom_hop_threshold: hop_count above which PHANTOM triggers (default 2)
            fog_clarity_threshold: claim_clarity below which FOG triggers (default 0.5)
            noise_credibility_threshold: credibility below which NOISE triggers (default 0.3)
        """
        self.phantom_hop_threshold = phantom_hop_threshold
        self.fog_clarity_threshold = fog_clarity_threshold
        self.noise_credibility_threshold = noise_credibility_threshold
        self.vague_patterns = [re.compile(p, re.IGNORECASE) for p in VAGUE_ATTRIBUTION_PATTERNS]
        self._logger = logger.bind(component="DubiousDetector")

    def detect(
        self,
        fact: Dict[str, Any],
        credibility_score: float,
        contradictions: Optional[List[Dict[str, Any]]] = None,
    ) -> DubiousResult:
        """
        Detect dubious flags for a fact using Boolean logic gates.

        Each gate is independent - a fact can trigger multiple flags.
        Order of evaluation: PHANTOM -> FOG -> ANOMALY -> NOISE.

        Args:
            fact: ExtractedFact dict with provenance, quality, claim fields.
            credibility_score: Pre-computed credibility score from SourceCredibilityScorer.
            contradictions: List of contradicting facts (from AnomalyDetector).

        Returns:
            DubiousResult with:
                - flags: List[DubiousFlag] triggered by Boolean gates
                - reasoning: List[ClassificationReasoning] explaining each flag
                - fixability_score: How easily this can be verified (0.0-1.0)
        """
        result = DubiousResult()

        # Gate 1: PHANTOM (Structural Failure)
        phantom_result = self._check_phantom(fact)
        if phantom_result:
            result.flags.append(DubiousFlag.PHANTOM)
            result.reasoning.append(phantom_result)

        # Gate 2: FOG (Attribution Failure)
        fog_result = self._check_fog(fact)
        if fog_result:
            result.flags.append(DubiousFlag.FOG)
            result.reasoning.append(fog_result)

        # Gate 3: ANOMALY (Coherence Failure)
        if contradictions:
            anomaly_result = self._check_anomaly(fact, contradictions)
            if anomaly_result:
                result.flags.append(DubiousFlag.ANOMALY)
                result.reasoning.append(anomaly_result)

        # Gate 4: NOISE (Reputation Failure)
        noise_result = self._check_noise(credibility_score)
        if noise_result:
            result.flags.append(DubiousFlag.NOISE)
            result.reasoning.append(noise_result)

        # Calculate fixability
        result.fixability_score = self._calculate_fixability(result.flags, credibility_score)

        self._logger.debug(
            "Dubious detection complete",
            fact_id=fact.get("fact_id", "unknown")[:20],
            flags=[f.value for f in result.flags],
            fixability=result.fixability_score,
        )

        return result

    def _check_phantom(self, fact: Dict[str, Any]) -> Optional[ClassificationReasoning]:
        """
        Gate 1: PHANTOM - Structural Failure.

        Boolean logic: hop_count > 2 AND primary_source IS NULL
        Signal: Echo without speaker - no traceable root source.

        A fact is PHANTOM when it has traveled through multiple intermediaries
        AND we cannot trace it back to its original source. This is the
        "telephone game" problem in journalism.

        Args:
            fact: ExtractedFact dict with provenance field.

        Returns:
            ClassificationReasoning if triggered, None otherwise.
        """
        provenance = fact.get("provenance", {})
        if isinstance(provenance, dict):
            hop_count = provenance.get("hop_count", 0)
        else:
            # Handle Provenance Pydantic model
            hop_count = getattr(provenance, "hop_count", 0)

        # Condition 1: hop_count > threshold
        if hop_count <= self.phantom_hop_threshold:
            return None

        # Condition 2: no primary source
        has_primary = self._has_primary_source(provenance)
        if has_primary:
            return None

        # Both conditions met: PHANTOM triggered
        return ClassificationReasoning(
            flag=DubiousFlag.PHANTOM,
            reason=f"hop_count={hop_count} > {self.phantom_hop_threshold} AND no primary source found",
            trigger_values={
                "hop_count": hop_count,
                "primary_source": None,
                "threshold": self.phantom_hop_threshold,
            },
        )

    def _has_primary_source(self, provenance: Any) -> bool:
        """
        Check if provenance has a traceable primary source.

        A primary source is one of:
        - source_classification == "primary"
        - attribution_chain has hop=0 entry
        - hop_count == 0 (direct source)

        Args:
            provenance: Provenance dict or Pydantic model.

        Returns:
            True if primary source exists, False otherwise.
        """
        if isinstance(provenance, dict):
            # Check source classification
            if provenance.get("source_classification") == "primary":
                return True

            # Check attribution chain for hop=0 entity
            attribution_chain = provenance.get("attribution_chain", [])
            for hop in attribution_chain:
                if isinstance(hop, dict):
                    if hop.get("hop", 999) == 0:
                        return True
                else:
                    if getattr(hop, "hop", 999) == 0:
                        return True

            # Check if hop_count is 0 (direct source)
            if provenance.get("hop_count", 1) == 0:
                return True
        else:
            # Handle Pydantic model
            if getattr(provenance, "source_classification", None) == "primary":
                return True

            attribution_chain = getattr(provenance, "attribution_chain", [])
            for hop in attribution_chain:
                if getattr(hop, "hop", 999) == 0:
                    return True

            if getattr(provenance, "hop_count", 1) == 0:
                return True

        return False

    def _check_fog(self, fact: Dict[str, Any]) -> Optional[ClassificationReasoning]:
        """
        Gate 2: FOG - Attribution Failure.

        Boolean logic: claim_clarity < 0.5 OR attribution contains vague patterns
        Signal: Speaker is mumbling - unclear who said what.

        FOG indicates attribution uncertainty: we know something was said,
        but not precisely who said it or what exactly they meant.

        Args:
            fact: ExtractedFact dict with quality and provenance fields.

        Returns:
            ClassificationReasoning if triggered, None otherwise.
        """
        quality = fact.get("quality", {})
        if isinstance(quality, dict):
            claim_clarity = quality.get("claim_clarity", 1.0) if quality else 1.0
        else:
            claim_clarity = getattr(quality, "claim_clarity", 1.0) if quality else 1.0

        provenance = fact.get("provenance", {})
        if isinstance(provenance, dict):
            attribution_phrase = provenance.get("attribution_phrase", "")
        else:
            attribution_phrase = getattr(provenance, "attribution_phrase", "") or ""

        trigger_values: Dict[str, Any] = {}
        reasons = []

        # Condition 1: Low claim clarity
        if claim_clarity < self.fog_clarity_threshold:
            reasons.append(f"claim_clarity={claim_clarity:.2f} < {self.fog_clarity_threshold}")
            trigger_values["claim_clarity"] = claim_clarity
            trigger_values["clarity_threshold"] = self.fog_clarity_threshold

        # Condition 2: Vague attribution patterns
        vague_match = self._check_vague_attribution(attribution_phrase)
        if vague_match:
            reasons.append(f"attribution contains vague pattern: '{vague_match}'")
            trigger_values["attribution_phrase"] = attribution_phrase
            trigger_values["vague_pattern"] = vague_match

        # Also check claim text for hedging
        claim = fact.get("claim", {})
        if isinstance(claim, dict):
            claim_text = claim.get("text", "")
        else:
            claim_text = getattr(claim, "text", "")

        claim_vague = self._check_vague_attribution(claim_text)
        if claim_vague and claim_vague not in trigger_values.get("vague_pattern", ""):
            reasons.append(f"claim contains vague language: '{claim_vague}'")
            trigger_values["claim_vague_pattern"] = claim_vague

        if not reasons:
            return None

        return ClassificationReasoning(
            flag=DubiousFlag.FOG,
            reason=" OR ".join(reasons),
            trigger_values=trigger_values,
        )

    def _check_vague_attribution(self, text: str) -> Optional[str]:
        """
        Check text for vague attribution patterns.

        Patterns include: "sources say", "reportedly", "allegedly",
        "according to officials", hedging language like "may have".

        Args:
            text: Text to check for vague patterns.

        Returns:
            Matched vague phrase if found, None otherwise.
        """
        if not text:
            return None

        for pattern in self.vague_patterns:
            match = pattern.search(text)
            if match:
                return match.group(0)

        return None

    def _check_anomaly(
        self,
        fact: Dict[str, Any],
        contradictions: List[Dict[str, Any]],
    ) -> Optional[ClassificationReasoning]:
        """
        Gate 3: ANOMALY - Coherence Failure.

        Boolean logic: contradiction_count > 0
        Signal: Trusted systems disagree - needs arbitration.

        ANOMALY is triggered when external contradiction detection (e.g.,
        AnomalyDetector in Plan 04) finds conflicting facts. The DubiousDetector
        receives contradictions as input; it does NOT detect them itself.

        Args:
            fact: ExtractedFact dict (for context/ID).
            contradictions: List of contradicting facts from external detector.

        Returns:
            ClassificationReasoning if triggered, None otherwise.
        """
        if not contradictions:
            return None

        contradiction_count = len(contradictions)
        if contradiction_count == 0:
            return None

        # Build contradiction summary (limit to first 5)
        contradiction_ids = []
        for c in contradictions[:5]:
            if isinstance(c, dict):
                contradiction_ids.append(c.get("fact_id", "unknown"))
            else:
                contradiction_ids.append(getattr(c, "fact_id", "unknown"))

        return ClassificationReasoning(
            flag=DubiousFlag.ANOMALY,
            reason=f"contradiction_count={contradiction_count} > 0",
            trigger_values={
                "contradiction_count": contradiction_count,
                "contradicting_fact_ids": contradiction_ids,
            },
        )

    def _check_noise(self, credibility_score: float) -> Optional[ClassificationReasoning]:
        """
        Gate 4: NOISE - Reputation Failure.

        Boolean logic: source_credibility < 0.3
        Signal: Known unreliable source - batch analysis only.

        Per CONTEXT.md: NOISE does NOT enter individual verification queue.
        Batch analysis only - aggregate for pattern detection.

        NOISE facts are from sources with known low credibility (tabloids,
        known propaganda outlets, anonymous social media). They're not
        worthless - patterns across many NOISE facts can be valuable.

        Args:
            credibility_score: Pre-computed credibility from SourceCredibilityScorer.

        Returns:
            ClassificationReasoning if triggered, None otherwise.
        """
        if credibility_score >= self.noise_credibility_threshold:
            return None

        return ClassificationReasoning(
            flag=DubiousFlag.NOISE,
            reason=f"credibility_score={credibility_score:.2f} < {self.noise_credibility_threshold}",
            trigger_values={
                "credibility_score": credibility_score,
                "threshold": self.noise_credibility_threshold,
            },
        )

    def _calculate_fixability(
        self,
        flags: List[DubiousFlag],
        credibility_score: float,
    ) -> float:
        """
        Calculate how easily this fact can be verified.

        Per CONTEXT.md: Priority = Impact x Fixability
        High-impact fixable claims get priority for Phase 8 verification.

        Fixability by species:
            - FOG: 0.9 (highly fixable - find clearer source)
            - ANOMALY: 0.8 (highly fixable - arbitrate with context)
            - PHANTOM: 0.6 (moderately fixable - trace back to root)
            - NOISE: 0.1 (not individually fixable - batch only)

        Pure NOISE facts (only NOISE flag) get 0.0 fixability - they
        don't enter the individual verification queue.

        Args:
            flags: List of dubious flags triggered.
            credibility_score: Credibility for slight boost calculation.

        Returns:
            Fixability score 0.0-1.0.
        """
        if not flags:
            return 0.0  # Not dubious, no verification needed

        # Pure NOISE is not individually fixable
        if DubiousFlag.NOISE in flags and len(flags) == 1:
            return 0.0

        fixability_scores = {
            DubiousFlag.FOG: 0.9,      # Easy to find clearer source
            DubiousFlag.ANOMALY: 0.8,  # Can arbitrate with context
            DubiousFlag.PHANTOM: 0.6,  # Harder to trace root
            DubiousFlag.NOISE: 0.1,    # Only as part of other flags
        }

        # Take highest fixability (most promising verification route)
        max_fixability = max(fixability_scores.get(f, 0.5) for f in flags)

        # Slightly boost if higher credibility (easier to find corroboration)
        credibility_boost = credibility_score * 0.2

        return min(1.0, max_fixability + credibility_boost)


__all__ = ["DubiousDetector", "DubiousResult"]
