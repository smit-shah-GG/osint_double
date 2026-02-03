"""Anomaly detection for fact contradictions per Phase 7 CONTEXT.md.

Per CONTEXT.md:
- Tiered approach: within-investigation for all facts, cross-investigation for critical-tier only
- Contradiction triggers ANOMALY flag for Phase 8 arbitration
- Does NOT attempt premature resolution - Phase 8 handles arbitration

Contradiction types:
- Direct negation: "Russia attacked" vs "Russia did not attack"
- Numeric disagreement: "50 casualties" vs "200 casualties"
- Temporal conflict: "Happened on Monday" vs "Happened on Tuesday"
- Attribution conflict: "Putin said X" vs "Putin denied X"

The AnomalyDetector provides input for the ANOMALY dubious flag in DubiousDetector.
When contradictions are found, the fact gets the ANOMALY flag for Phase 8 arbitration.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from loguru import logger


@dataclass
class Contradiction:
    """A detected contradiction between two facts.

    Attributes:
        fact_id_a: First fact in the contradiction pair
        fact_id_b: Second fact in the contradiction pair
        contradiction_type: Type of contradiction (negation, numeric, temporal, attribution)
        confidence: Confidence score for this contradiction (0.0-1.0)
        details: Additional details about the contradiction
    """

    fact_id_a: str
    fact_id_b: str
    contradiction_type: str  # negation, numeric, temporal, attribution
    confidence: float
    details: Dict[str, Any] = field(default_factory=dict)


class AnomalyDetector:
    """
    Detects contradictions between facts for ANOMALY classification.

    Per CONTEXT.md:
    - Within-investigation detection for all facts
    - Cross-investigation detection for critical-tier only (optional)
    - Tracks conflicts without attempting resolution

    The detector identifies four types of contradictions:
    1. Negation: Direct negation between claims ("did" vs "did not")
    2. Numeric: Disagreement on numeric values ("50" vs "200")
    3. Temporal: Conflicting timestamps for same event
    4. Attribution: Statement vs denial about same content

    Usage:
        detector = AnomalyDetector()
        contradictions = await detector.find_contradictions(
            fact, all_facts_in_investigation
        )
        if contradictions:
            # Fact has ANOMALY flag for Phase 8 arbitration
            pass

    Example:
        >>> detector = AnomalyDetector()
        >>> fact_a = {'fact_id': 'a', 'claim': {'text': 'Russia attacked Ukraine'}}
        >>> fact_b = {'fact_id': 'b', 'claim': {'text': 'Russia did not attack Ukraine'}}
        >>> contradictions = await detector.find_contradictions(fact_a, [fact_b])
        >>> len(contradictions) > 0
        True
    """

    # Negation indicators for detecting contradiction
    NEGATION_WORDS: Set[str] = {
        "not", "no", "never", "denied", "rejected", "refused",
        "false", "untrue", "disputed", "contradicted"
    }
    NEGATION_PREFIXES: Set[str] = {"un", "non", "dis"}

    # Stop words to filter out during content comparison
    STOP_WORDS: Set[str] = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "in", "on", "at", "to", "for", "of", "and", "or", "but",
        "has", "have", "had", "that", "this", "with", "by", "from"
    }

    def __init__(self, min_confidence: float = 0.5):
        """
        Initialize anomaly detector.

        Args:
            min_confidence: Minimum confidence to report contradiction (default 0.5)
        """
        self.min_confidence = min_confidence
        self._logger = logger.bind(component="AnomalyDetector")

    async def find_contradictions(
        self,
        target_fact: Dict[str, Any],
        comparison_facts: List[Dict[str, Any]],
    ) -> List[Contradiction]:
        """
        Find facts that contradict the target fact.

        Compares the target fact against all comparison facts and returns
        any contradictions found. Each contradiction includes the type
        and confidence level.

        Args:
            target_fact: The fact to check for contradictions
            comparison_facts: List of facts to compare against

        Returns:
            List of Contradiction objects for facts that contradict target
        """
        contradictions = []
        target_id = target_fact.get("fact_id", "unknown")

        for other_fact in comparison_facts:
            other_id = other_fact.get("fact_id", "unknown")

            # Skip self-comparison
            if target_id == other_id:
                continue

            # Check for various contradiction types
            contradiction = self._detect_contradiction(target_fact, other_fact)
            if contradiction and contradiction.confidence >= self.min_confidence:
                contradictions.append(contradiction)

        self._logger.debug(
            f"Found {len(contradictions)} contradictions for {target_id[:20]}",
            comparison_count=len(comparison_facts),
        )

        return contradictions

    def _detect_contradiction(
        self,
        fact_a: Dict[str, Any],
        fact_b: Dict[str, Any],
    ) -> Optional[Contradiction]:
        """
        Detect if two facts contradict each other.

        Checks for multiple contradiction types in order of specificity:
        1. Assertion type (statement vs denial)
        2. Direct negation
        3. Numeric disagreement
        4. Temporal conflict

        Args:
            fact_a: First fact to compare
            fact_b: Second fact to compare

        Returns:
            Contradiction if found, None otherwise
        """
        # Get claim texts
        claim_a = fact_a.get("claim", {})
        claim_b = fact_b.get("claim", {})
        text_a = claim_a.get("text", "") if isinstance(claim_a, dict) else ""
        text_b = claim_b.get("text", "") if isinstance(claim_b, dict) else ""

        if not text_a or not text_b:
            return None

        # Check for assertion type contradiction (statement vs denial)
        assertion_result = self._check_assertion_contradiction(fact_a, fact_b)
        if assertion_result:
            return assertion_result

        # Check for direct negation
        negation_result = self._check_negation(text_a, text_b, fact_a, fact_b)
        if negation_result:
            return negation_result

        # Check for numeric disagreement
        numeric_result = self._check_numeric_contradiction(fact_a, fact_b)
        if numeric_result:
            return numeric_result

        # Check for temporal conflict
        temporal_result = self._check_temporal_contradiction(fact_a, fact_b)
        if temporal_result:
            return temporal_result

        return None

    def _check_negation(
        self,
        claim_a: str,
        claim_b: str,
        fact_a: Dict[str, Any],
        fact_b: Dict[str, Any],
    ) -> Optional[Contradiction]:
        """
        Check for direct negation between claims.

        A negation contradiction exists when:
        1. One claim contains negation words the other doesn't
        2. Both claims share significant overlapping content

        Args:
            claim_a: Text of first claim
            claim_b: Text of second claim
            fact_a: First fact dict
            fact_b: Second fact dict

        Returns:
            Contradiction if negation detected, None otherwise
        """
        words_a = set(claim_a.lower().split())
        words_b = set(claim_b.lower().split())

        # Check if one has negation words that the other doesn't
        neg_in_a = bool(words_a & self.NEGATION_WORDS)
        neg_in_b = bool(words_b & self.NEGATION_WORDS)

        # If same negation status, not a direct contradiction
        if neg_in_a == neg_in_b:
            return None

        # Check if claims share significant content (same topic)
        content_a = words_a - self.STOP_WORDS - self.NEGATION_WORDS
        content_b = words_b - self.STOP_WORDS - self.NEGATION_WORDS

        overlap = content_a & content_b
        if len(overlap) < 2:
            # Not enough shared content to be about same thing
            return None

        # More overlap = higher confidence
        confidence = min(0.9, 0.5 + len(overlap) * 0.1)

        return Contradiction(
            fact_id_a=fact_a.get("fact_id", "unknown"),
            fact_id_b=fact_b.get("fact_id", "unknown"),
            contradiction_type="negation",
            confidence=confidence,
            details={
                "negation_in": "claim_a" if neg_in_a else "claim_b",
                "shared_content": list(overlap)[:10],  # Limit for readability
            },
        )

    def _check_assertion_contradiction(
        self,
        fact_a: Dict[str, Any],
        fact_b: Dict[str, Any],
    ) -> Optional[Contradiction]:
        """
        Check for contradiction between statement and denial.

        Per Phase 6 schema, facts have assertion_type field:
        - "statement": Normal claim
        - "denial": Negation of underlying claim

        A contradiction exists when:
        1. One is statement, other is denial
        2. Both involve same entities

        Args:
            fact_a: First fact dict
            fact_b: Second fact dict

        Returns:
            Contradiction if assertion type contradiction found, None otherwise
        """
        claim_a = fact_a.get("claim", {})
        claim_b = fact_b.get("claim", {})

        type_a = claim_a.get("assertion_type", "statement") if isinstance(claim_a, dict) else "statement"
        type_b = claim_b.get("assertion_type", "statement") if isinstance(claim_b, dict) else "statement"

        # One statement, one denial about same entities
        if not ((type_a == "statement" and type_b == "denial") or
                (type_a == "denial" and type_b == "statement")):
            return None

        # Check entity overlap to confirm same topic
        entities_a = self._extract_entity_names(fact_a)
        entities_b = self._extract_entity_names(fact_b)

        overlap = entities_a & entities_b
        if not overlap:
            return None  # Different entities, not a contradiction

        return Contradiction(
            fact_id_a=fact_a.get("fact_id", "unknown"),
            fact_id_b=fact_b.get("fact_id", "unknown"),
            contradiction_type="attribution",
            confidence=0.8,
            details={
                "statement_fact": fact_a.get("fact_id") if type_a == "statement" else fact_b.get("fact_id"),
                "denial_fact": fact_b.get("fact_id") if type_a == "statement" else fact_a.get("fact_id"),
                "shared_entities": list(overlap)[:5],
            },
        )

    def _check_numeric_contradiction(
        self,
        fact_a: Dict[str, Any],
        fact_b: Dict[str, Any],
    ) -> Optional[Contradiction]:
        """
        Check for numeric value disagreement.

        Compares numeric fields in facts. A contradiction exists when:
        1. Both facts have numeric values
        2. The ranges don't overlap
        3. Both facts share entities (same topic)

        Args:
            fact_a: First fact dict
            fact_b: Second fact dict

        Returns:
            Contradiction if numeric disagreement found, None otherwise
        """
        numeric_a = fact_a.get("numeric")
        numeric_b = fact_b.get("numeric")

        if not numeric_a or not numeric_b:
            return None

        # Get normalized ranges if available
        range_a = numeric_a.get("value_normalized") if isinstance(numeric_a, dict) else None
        range_b = numeric_b.get("value_normalized") if isinstance(numeric_b, dict) else None

        if not range_a or not range_b:
            # Compare original values as fallback
            orig_a = numeric_a.get("value_original", "") if isinstance(numeric_a, dict) else ""
            orig_b = numeric_b.get("value_original", "") if isinstance(numeric_b, dict) else ""

            if orig_a and orig_b and orig_a != orig_b:
                # Check entity overlap to confirm same topic
                entities_a = self._extract_entity_names(fact_a)
                entities_b = self._extract_entity_names(fact_b)

                if entities_a & entities_b:
                    return Contradiction(
                        fact_id_a=fact_a.get("fact_id", "unknown"),
                        fact_id_b=fact_b.get("fact_id", "unknown"),
                        contradiction_type="numeric",
                        confidence=0.6,
                        details={
                            "value_a": orig_a,
                            "value_b": orig_b,
                        },
                    )
            return None

        # Check if ranges are disjoint
        min_a = range_a[0] if isinstance(range_a, (list, tuple)) else range_a
        max_a = range_a[1] if isinstance(range_a, (list, tuple)) and len(range_a) > 1 else min_a

        min_b = range_b[0] if isinstance(range_b, (list, tuple)) else range_b
        max_b = range_b[1] if isinstance(range_b, (list, tuple)) and len(range_b) > 1 else min_b

        # Ranges don't overlap = contradiction
        if max_a < min_b or max_b < min_a:
            return Contradiction(
                fact_id_a=fact_a.get("fact_id", "unknown"),
                fact_id_b=fact_b.get("fact_id", "unknown"),
                contradiction_type="numeric",
                confidence=0.8,
                details={
                    "range_a": list(range_a) if isinstance(range_a, (list, tuple)) else [range_a],
                    "range_b": list(range_b) if isinstance(range_b, (list, tuple)) else [range_b],
                },
            )

        return None

    def _check_temporal_contradiction(
        self,
        fact_a: Dict[str, Any],
        fact_b: Dict[str, Any],
    ) -> Optional[Contradiction]:
        """
        Check for temporal conflict between facts.

        A temporal contradiction exists when:
        1. Both facts have explicit temporal values
        2. Both have same precision level
        3. Values differ
        4. Both facts share entities (same event)

        Args:
            fact_a: First fact dict
            fact_b: Second fact dict

        Returns:
            Contradiction if temporal conflict found, None otherwise
        """
        temporal_a = fact_a.get("temporal")
        temporal_b = fact_b.get("temporal")

        if not temporal_a or not temporal_b:
            return None

        if not isinstance(temporal_a, dict) or not isinstance(temporal_b, dict):
            return None

        # Both need explicit precision to compare meaningfully
        if (temporal_a.get("temporal_precision") != "explicit" or
            temporal_b.get("temporal_precision") != "explicit"):
            return None

        value_a = temporal_a.get("value", "")
        value_b = temporal_b.get("value", "")

        if not value_a or not value_b:
            return None

        # Same precision level needed for meaningful comparison
        precision_a = temporal_a.get("precision", "day")
        precision_b = temporal_b.get("precision", "day")

        if precision_a != precision_b:
            return None

        # Different values at same precision = potential conflict
        if value_a != value_b:
            # Check entity overlap to confirm same event
            entities_a = self._extract_entity_names(fact_a)
            entities_b = self._extract_entity_names(fact_b)

            if entities_a & entities_b:
                return Contradiction(
                    fact_id_a=fact_a.get("fact_id", "unknown"),
                    fact_id_b=fact_b.get("fact_id", "unknown"),
                    contradiction_type="temporal",
                    confidence=0.7,
                    details={
                        "temporal_a": value_a,
                        "temporal_b": value_b,
                        "precision": precision_a,
                        "shared_entities": list(entities_a & entities_b)[:5],
                    },
                )

        return None

    def _extract_entity_names(self, fact: Dict[str, Any]) -> Set[str]:
        """
        Extract entity names from a fact for comparison.

        Uses canonical form if available, falls back to text.

        Args:
            fact: Fact dict with entities field

        Returns:
            Set of lowercase entity names
        """
        entities = fact.get("entities", [])
        names = set()

        for entity in entities:
            if isinstance(entity, dict):
                canonical = entity.get("canonical", "")
                text = entity.get("text", "")
                name = canonical or text
                if name:
                    names.add(name.lower())

        return names


__all__ = ["AnomalyDetector", "Contradiction"]
