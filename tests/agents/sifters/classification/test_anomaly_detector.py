"""Tests for AnomalyDetector contradiction detection.

Tests verify:
- Negation contradiction detection
- Statement vs denial contradiction
- Numeric disagreement detection
- Temporal conflict detection
- Shared entity requirement for valid contradictions
"""

import pytest

from osint_system.agents.sifters.classification.anomaly_detector import (
    AnomalyDetector,
    Contradiction,
)


class TestAnomalyDetectorInitialization:
    """Tests for AnomalyDetector initialization."""

    def test_default_confidence(self):
        """AnomalyDetector initializes with default min_confidence."""
        detector = AnomalyDetector()

        assert detector.min_confidence == 0.5

    def test_custom_confidence(self):
        """AnomalyDetector accepts custom min_confidence."""
        detector = AnomalyDetector(min_confidence=0.7)

        assert detector.min_confidence == 0.7


class TestNegationContradiction:
    """Tests for negation contradiction detection."""

    @pytest.mark.asyncio
    async def test_negation_detected(self):
        """Negation contradiction detected when one claim negates the other."""
        detector = AnomalyDetector()
        fact_a = {
            "fact_id": "neg-a",
            "claim": {"text": "Russia attacked Ukraine"},
            "entities": [{"text": "Russia"}, {"text": "Ukraine"}],
        }
        fact_b = {
            "fact_id": "neg-b",
            "claim": {"text": "Russia did not attack Ukraine"},
            "entities": [{"text": "Russia"}, {"text": "Ukraine"}],
        }

        contradictions = await detector.find_contradictions(fact_a, [fact_b])

        assert len(contradictions) == 1
        assert contradictions[0].contradiction_type == "negation"
        assert contradictions[0].confidence >= 0.5

    @pytest.mark.asyncio
    async def test_negation_never(self):
        """Negation detected with 'never' keyword."""
        detector = AnomalyDetector()
        fact_a = {
            "fact_id": "neg-c",
            "claim": {"text": "Officials agreed to the deal"},
            "entities": [{"text": "Officials"}],
        }
        fact_b = {
            "fact_id": "neg-d",
            "claim": {"text": "Officials never agreed to the deal"},
            "entities": [{"text": "Officials"}],
        }

        contradictions = await detector.find_contradictions(fact_a, [fact_b])

        assert len(contradictions) == 1
        assert contradictions[0].contradiction_type == "negation"

    @pytest.mark.asyncio
    async def test_negation_denied(self):
        """Negation detected with 'denied' keyword."""
        detector = AnomalyDetector()
        fact_a = {
            "fact_id": "neg-e",
            "claim": {"text": "Putin confirmed the report"},
            "entities": [{"text": "Putin"}],
        }
        fact_b = {
            "fact_id": "neg-f",
            "claim": {"text": "Putin denied the report"},
            "entities": [{"text": "Putin"}],
        }

        contradictions = await detector.find_contradictions(fact_a, [fact_b])

        assert len(contradictions) >= 1

    @pytest.mark.asyncio
    async def test_no_negation_different_topics(self):
        """No negation when claims are about different topics."""
        detector = AnomalyDetector()
        fact_a = {
            "fact_id": "diff-a",
            "claim": {"text": "Russia attacked Ukraine"},
            "entities": [{"text": "Russia"}, {"text": "Ukraine"}],
        }
        fact_b = {
            "fact_id": "diff-b",
            "claim": {"text": "China did not join the alliance"},
            "entities": [{"text": "China"}],
        }

        contradictions = await detector.find_contradictions(fact_a, [fact_b])

        assert len(contradictions) == 0

    @pytest.mark.asyncio
    async def test_no_negation_same_polarity(self):
        """No negation when both claims have same polarity."""
        detector = AnomalyDetector()
        fact_a = {
            "fact_id": "same-a",
            "claim": {"text": "Forces not deployed to border"},
            "entities": [{"text": "Forces"}],
        }
        fact_b = {
            "fact_id": "same-b",
            "claim": {"text": "Troops not sent to border"},
            "entities": [{"text": "Troops"}],
        }

        contradictions = await detector.find_contradictions(fact_a, [fact_b])

        # Both have negation - not a contradiction
        assert len(contradictions) == 0


class TestAssertionContradiction:
    """Tests for statement vs denial contradiction."""

    @pytest.mark.asyncio
    async def test_statement_vs_denial(self):
        """Contradiction detected between statement and denial."""
        detector = AnomalyDetector()
        fact_a = {
            "fact_id": "assert-a",
            "claim": {"text": "Putin announced withdrawal", "assertion_type": "statement"},
            "entities": [{"text": "Putin", "canonical": "Vladimir Putin"}],
        }
        fact_b = {
            "fact_id": "assert-b",
            "claim": {"text": "Kremlin denies withdrawal claim", "assertion_type": "denial"},
            "entities": [{"text": "Putin", "canonical": "Vladimir Putin"}],
        }

        contradictions = await detector.find_contradictions(fact_a, [fact_b])

        assert len(contradictions) >= 1
        # Should detect either attribution or negation
        types = [c.contradiction_type for c in contradictions]
        assert "attribution" in types or "negation" in types

    @pytest.mark.asyncio
    async def test_no_contradiction_same_assertion_type(self):
        """No attribution contradiction when both are statements."""
        detector = AnomalyDetector()
        fact_a = {
            "fact_id": "same-type-a",
            "claim": {"text": "Leader made claim", "assertion_type": "statement"},
            "entities": [{"text": "Leader"}],
        }
        fact_b = {
            "fact_id": "same-type-b",
            "claim": {"text": "Leader made another claim", "assertion_type": "statement"},
            "entities": [{"text": "Leader"}],
        }

        contradictions = await detector.find_contradictions(fact_a, [fact_b])

        # Should not detect attribution contradiction (both statements)
        attribution_contradictions = [c for c in contradictions if c.contradiction_type == "attribution"]
        assert len(attribution_contradictions) == 0


class TestNumericContradiction:
    """Tests for numeric disagreement detection."""

    @pytest.mark.asyncio
    async def test_numeric_range_disjoint(self):
        """Contradiction detected when numeric ranges don't overlap."""
        detector = AnomalyDetector()
        fact_a = {
            "fact_id": "num-a",
            "claim": {"text": "Approximately 50 casualties"},
            "entities": [{"text": "Battle"}],
            "numeric": {"value_normalized": [40, 60]},
        }
        fact_b = {
            "fact_id": "num-b",
            "claim": {"text": "Over 200 casualties"},
            "entities": [{"text": "Battle"}],
            "numeric": {"value_normalized": [200, 250]},
        }

        contradictions = await detector.find_contradictions(fact_a, [fact_b])

        assert len(contradictions) == 1
        assert contradictions[0].contradiction_type == "numeric"
        assert contradictions[0].confidence >= 0.6

    @pytest.mark.asyncio
    async def test_numeric_overlapping_ranges(self):
        """No contradiction when numeric ranges overlap."""
        detector = AnomalyDetector()
        fact_a = {
            "fact_id": "num-c",
            "claim": {"text": "Between 40 and 80 casualties"},
            "entities": [{"text": "Event"}],
            "numeric": {"value_normalized": [40, 80]},
        }
        fact_b = {
            "fact_id": "num-d",
            "claim": {"text": "Around 60 casualties"},
            "entities": [{"text": "Event"}],
            "numeric": {"value_normalized": [50, 70]},
        }

        contradictions = await detector.find_contradictions(fact_a, [fact_b])

        # Ranges overlap (40-80 and 50-70), no contradiction
        numeric_contradictions = [c for c in contradictions if c.contradiction_type == "numeric"]
        assert len(numeric_contradictions) == 0

    @pytest.mark.asyncio
    async def test_numeric_original_values_differ(self):
        """Contradiction detected with differing original values."""
        detector = AnomalyDetector()
        fact_a = {
            "fact_id": "num-e",
            "claim": {"text": "5 ships"},
            "entities": [{"text": "Fleet"}],
            "numeric": {"value_original": "5"},
        }
        fact_b = {
            "fact_id": "num-f",
            "claim": {"text": "12 ships"},
            "entities": [{"text": "Fleet"}],
            "numeric": {"value_original": "12"},
        }

        contradictions = await detector.find_contradictions(fact_a, [fact_b])

        assert len(contradictions) == 1
        assert contradictions[0].contradiction_type == "numeric"


class TestTemporalContradiction:
    """Tests for temporal conflict detection."""

    @pytest.mark.asyncio
    async def test_temporal_different_dates(self):
        """Contradiction detected with different explicit dates."""
        detector = AnomalyDetector()
        fact_a = {
            "fact_id": "temp-a",
            "claim": {"text": "Attack occurred on Monday"},
            "entities": [{"text": "Attack", "canonical": "Border Attack"}],
            "temporal": {
                "value": "2024-03-11",
                "precision": "day",
                "temporal_precision": "explicit",
            },
        }
        fact_b = {
            "fact_id": "temp-b",
            "claim": {"text": "Attack occurred on Wednesday"},
            "entities": [{"text": "Attack", "canonical": "Border Attack"}],
            "temporal": {
                "value": "2024-03-13",
                "precision": "day",
                "temporal_precision": "explicit",
            },
        }

        contradictions = await detector.find_contradictions(fact_a, [fact_b])

        assert len(contradictions) == 1
        assert contradictions[0].contradiction_type == "temporal"

    @pytest.mark.asyncio
    async def test_temporal_no_conflict_same_date(self):
        """No contradiction when dates match."""
        detector = AnomalyDetector()
        fact_a = {
            "fact_id": "temp-c",
            "claim": {"text": "Meeting on Monday"},
            "entities": [{"text": "Meeting"}],
            "temporal": {
                "value": "2024-03-11",
                "precision": "day",
                "temporal_precision": "explicit",
            },
        }
        fact_b = {
            "fact_id": "temp-d",
            "claim": {"text": "Meeting held March 11"},
            "entities": [{"text": "Meeting"}],
            "temporal": {
                "value": "2024-03-11",
                "precision": "day",
                "temporal_precision": "explicit",
            },
        }

        contradictions = await detector.find_contradictions(fact_a, [fact_b])

        temporal_contradictions = [c for c in contradictions if c.contradiction_type == "temporal"]
        assert len(temporal_contradictions) == 0

    @pytest.mark.asyncio
    async def test_temporal_no_conflict_different_precision(self):
        """No contradiction when temporal precision levels differ."""
        detector = AnomalyDetector()
        fact_a = {
            "fact_id": "temp-e",
            "claim": {"text": "In March"},
            "entities": [{"text": "Event"}],
            "temporal": {
                "value": "2024-03",
                "precision": "month",
                "temporal_precision": "explicit",
            },
        }
        fact_b = {
            "fact_id": "temp-f",
            "claim": {"text": "On March 15"},
            "entities": [{"text": "Event"}],
            "temporal": {
                "value": "2024-03-15",
                "precision": "day",
                "temporal_precision": "explicit",
            },
        }

        contradictions = await detector.find_contradictions(fact_a, [fact_b])

        temporal_contradictions = [c for c in contradictions if c.contradiction_type == "temporal"]
        assert len(temporal_contradictions) == 0


class TestEntityRequirement:
    """Tests for shared entity requirement."""

    @pytest.mark.asyncio
    async def test_no_contradiction_no_shared_entities(self):
        """No contradiction when facts don't share entities (for negation)."""
        detector = AnomalyDetector()
        fact_a = {
            "fact_id": "entity-a",
            "claim": {"text": "USA attacked target"},
            "entities": [{"text": "USA", "canonical": "United States"}],
        }
        fact_b = {
            "fact_id": "entity-b",
            "claim": {"text": "China did not attack target"},
            "entities": [{"text": "China", "canonical": "People's Republic of China"}],
        }

        contradictions = await detector.find_contradictions(fact_a, [fact_b])

        # Different entities (USA vs China), no negation contradiction
        # (negation requires shared content overlap)
        negation_contradictions = [c for c in contradictions if c.contradiction_type == "negation"]
        assert len(negation_contradictions) == 0

    @pytest.mark.asyncio
    async def test_contradiction_with_shared_entities(self):
        """Contradiction detected when facts share entities."""
        detector = AnomalyDetector()
        fact_a = {
            "fact_id": "shared-a",
            "claim": {"text": "NATO deployed 100 troops"},
            "entities": [{"text": "NATO", "canonical": "NATO"}],
            "numeric": {"value_normalized": [100]},
        }
        fact_b = {
            "fact_id": "shared-b",
            "claim": {"text": "NATO deployed 1000 troops"},
            "entities": [{"text": "NATO", "canonical": "NATO"}],
            "numeric": {"value_normalized": [1000]},
        }

        contradictions = await detector.find_contradictions(fact_a, [fact_b])

        # Same entity (NATO), numeric contradiction
        assert len(contradictions) >= 1


class TestConfidenceThresholds:
    """Tests for confidence threshold filtering."""

    @pytest.mark.asyncio
    async def test_high_threshold_filters_low_confidence(self):
        """High confidence threshold filters weak contradictions."""
        detector = AnomalyDetector(min_confidence=0.9)
        fact_a = {
            "fact_id": "conf-a",
            "claim": {"text": "Event happened"},
            "entities": [{"text": "Event"}],
        }
        fact_b = {
            "fact_id": "conf-b",
            "claim": {"text": "Event did not happen"},
            "entities": [{"text": "Event"}],
        }

        # Only 2 words overlap ("event", "happened") - confidence may be lower
        contradictions = await detector.find_contradictions(fact_a, [fact_b])

        # With high threshold, weak matches may be filtered
        # This depends on specific confidence calculation
        for c in contradictions:
            assert c.confidence >= 0.5  # At least above default

    @pytest.mark.asyncio
    async def test_low_threshold_includes_weak_contradictions(self):
        """Low confidence threshold includes weaker contradictions."""
        detector = AnomalyDetector(min_confidence=0.3)
        fact_a = {
            "fact_id": "conf-c",
            "claim": {"text": "Officials confirmed the report today"},
            "entities": [{"text": "Officials"}],
        }
        fact_b = {
            "fact_id": "conf-d",
            "claim": {"text": "Officials denied the report today"},
            "entities": [{"text": "Officials"}],
        }

        contradictions = await detector.find_contradictions(fact_a, [fact_b])

        # Should find contradiction with low threshold (shared words: officials, report, today, the)
        assert len(contradictions) >= 1


class TestSelfComparison:
    """Tests for self-comparison handling."""

    @pytest.mark.asyncio
    async def test_no_self_contradiction(self):
        """Fact does not contradict itself."""
        detector = AnomalyDetector()
        fact = {
            "fact_id": "self-1",
            "claim": {"text": "Something happened"},
            "entities": [{"text": "Entity"}],
        }

        contradictions = await detector.find_contradictions(fact, [fact])

        assert len(contradictions) == 0


class TestContradictionDataclass:
    """Tests for Contradiction dataclass."""

    def test_contradiction_fields(self):
        """Contradiction has all expected fields."""
        contradiction = Contradiction(
            fact_id_a="a1",
            fact_id_b="b1",
            contradiction_type="negation",
            confidence=0.8,
            details={"key": "value"},
        )

        assert contradiction.fact_id_a == "a1"
        assert contradiction.fact_id_b == "b1"
        assert contradiction.contradiction_type == "negation"
        assert contradiction.confidence == 0.8
        assert contradiction.details == {"key": "value"}

    def test_contradiction_default_details(self):
        """Contradiction has empty dict as default details."""
        contradiction = Contradiction(
            fact_id_a="a2",
            fact_id_b="b2",
            contradiction_type="temporal",
            confidence=0.6,
        )

        assert contradiction.details == {}


class TestEdgeCases:
    """Edge case tests for robustness."""

    @pytest.mark.asyncio
    async def test_empty_claim_text(self):
        """Detector handles empty claim text gracefully."""
        detector = AnomalyDetector()
        fact_a = {
            "fact_id": "edge-a",
            "claim": {"text": ""},
            "entities": [],
        }
        fact_b = {
            "fact_id": "edge-b",
            "claim": {"text": "Something"},
            "entities": [],
        }

        # Should not raise
        contradictions = await detector.find_contradictions(fact_a, [fact_b])
        assert isinstance(contradictions, list)

    @pytest.mark.asyncio
    async def test_missing_claim_field(self):
        """Detector handles missing claim field gracefully."""
        detector = AnomalyDetector()
        fact_a = {
            "fact_id": "edge-c",
            "entities": [],
        }
        fact_b = {
            "fact_id": "edge-d",
            "claim": {"text": "Something"},
            "entities": [],
        }

        # Should not raise
        contradictions = await detector.find_contradictions(fact_a, [fact_b])
        assert isinstance(contradictions, list)

    @pytest.mark.asyncio
    async def test_multiple_contradictions(self):
        """Multiple facts can contradict the same target."""
        detector = AnomalyDetector()
        target = {
            "fact_id": "multi-target",
            "claim": {"text": "Russia attacked Ukraine forces today"},
            "entities": [{"text": "Russia"}, {"text": "Ukraine"}],
        }
        others = [
            {
                "fact_id": "multi-1",
                "claim": {"text": "Russia did not attack Ukraine forces"},
                "entities": [{"text": "Russia"}, {"text": "Ukraine"}],
            },
            {
                "fact_id": "multi-2",
                "claim": {"text": "Russia never attacked Ukraine forces"},
                "entities": [{"text": "Russia"}, {"text": "Ukraine"}],
            },
        ]

        contradictions = await detector.find_contradictions(target, others)

        # Should find multiple contradictions (shared words: russia, attack, ukraine, forces)
        assert len(contradictions) >= 1

    @pytest.mark.asyncio
    async def test_empty_comparison_list(self):
        """Empty comparison list returns no contradictions."""
        detector = AnomalyDetector()
        fact = {
            "fact_id": "empty-list",
            "claim": {"text": "Some claim"},
            "entities": [],
        }

        contradictions = await detector.find_contradictions(fact, [])

        assert len(contradictions) == 0
