"""Tests for DubiousDetector Boolean logic gates.

Tests verify the Taxonomy of Doubt implementation:
- PHANTOM: hop_count > 2 AND primary_source IS NULL
- FOG: claim_clarity < 0.5 OR vague attribution patterns
- ANOMALY: contradiction_count > 0
- NOISE: source_credibility < 0.3

CRITICAL: These are Boolean logic gates, NOT weighted formulas.
"""

import pytest

from osint_system.agents.sifters.classification import DubiousDetector, DubiousResult
from osint_system.data_management.schemas import DubiousFlag


class TestDubiousDetectorInitialization:
    """Tests for DubiousDetector initialization."""

    def test_default_thresholds(self):
        """DubiousDetector initializes with default thresholds."""
        detector = DubiousDetector()

        assert detector.phantom_hop_threshold == 2
        assert detector.fog_clarity_threshold == 0.5
        assert detector.noise_credibility_threshold == 0.3

    def test_custom_thresholds(self):
        """DubiousDetector accepts custom thresholds."""
        detector = DubiousDetector(
            phantom_hop_threshold=3,
            fog_clarity_threshold=0.4,
            noise_credibility_threshold=0.2,
        )

        assert detector.phantom_hop_threshold == 3
        assert detector.fog_clarity_threshold == 0.4
        assert detector.noise_credibility_threshold == 0.2

    def test_vague_patterns_compiled(self):
        """DubiousDetector pre-compiles vague attribution patterns."""
        detector = DubiousDetector()

        # Should have compiled regex patterns
        assert len(detector.vague_patterns) > 0
        # Verify they are compiled regex objects
        assert hasattr(detector.vague_patterns[0], "search")


class TestPhantomDetection:
    """Tests for PHANTOM gate: hop_count > 2 AND primary_source IS NULL."""

    def test_phantom_triggered_high_hop_no_primary(self):
        """PHANTOM triggers when hop_count > 2 AND no primary source."""
        detector = DubiousDetector()
        fact = {
            "fact_id": "phantom-1",
            "claim": {"text": "Some unverifiable claim"},
            "provenance": {
                "hop_count": 4,
                "source_classification": "tertiary",
                "attribution_chain": [
                    {"entity": "unnamed source", "hop": 2},
                    {"entity": "news outlet", "hop": 3},
                ],
            },
        }

        result = detector.detect(fact, credibility_score=0.5)

        assert DubiousFlag.PHANTOM in result.flags
        reasoning = result.reasoning[0]
        assert reasoning.flag == DubiousFlag.PHANTOM
        assert "hop_count=4" in reasoning.reason
        assert reasoning.trigger_values["hop_count"] == 4

    def test_phantom_not_triggered_has_primary_source(self):
        """PHANTOM does NOT trigger when primary source exists (even with high hop)."""
        detector = DubiousDetector()
        fact = {
            "fact_id": "phantom-2",
            "claim": {"text": "Verified claim"},
            "provenance": {
                "hop_count": 4,
                "source_classification": "primary",  # Has primary
                "attribution_chain": [
                    {"entity": "Official statement", "hop": 0},
                ],
            },
        }

        result = detector.detect(fact, credibility_score=0.5)

        assert DubiousFlag.PHANTOM not in result.flags

    def test_phantom_not_triggered_low_hop(self):
        """PHANTOM does NOT trigger when hop_count <= 2."""
        detector = DubiousDetector()
        fact = {
            "fact_id": "phantom-3",
            "claim": {"text": "Close to source"},
            "provenance": {
                "hop_count": 2,  # At threshold, not above
                "source_classification": "secondary",
            },
        }

        result = detector.detect(fact, credibility_score=0.5)

        assert DubiousFlag.PHANTOM not in result.flags

    def test_phantom_not_triggered_hop_zero_in_chain(self):
        """PHANTOM does NOT trigger when attribution chain has hop=0 entry."""
        detector = DubiousDetector()
        fact = {
            "fact_id": "phantom-4",
            "claim": {"text": "Some claim"},
            "provenance": {
                "hop_count": 5,  # High hop
                "source_classification": "secondary",
                "attribution_chain": [
                    {"entity": "Original speaker", "hop": 0},  # Has primary
                    {"entity": "Reporter", "hop": 1},
                ],
            },
        }

        result = detector.detect(fact, credibility_score=0.5)

        assert DubiousFlag.PHANTOM not in result.flags

    def test_phantom_custom_threshold(self):
        """PHANTOM respects custom hop threshold."""
        detector = DubiousDetector(phantom_hop_threshold=5)
        fact = {
            "fact_id": "phantom-5",
            "claim": {"text": "Some claim"},
            "provenance": {
                "hop_count": 4,  # Below custom threshold
                "source_classification": "tertiary",
            },
        }

        result = detector.detect(fact, credibility_score=0.5)

        assert DubiousFlag.PHANTOM not in result.flags


class TestFogDetection:
    """Tests for FOG gate: claim_clarity < 0.5 OR vague attribution."""

    def test_fog_triggered_low_clarity(self):
        """FOG triggers when claim_clarity < 0.5."""
        detector = DubiousDetector()
        fact = {
            "fact_id": "fog-1",
            "claim": {"text": "Something happened"},
            "quality": {"claim_clarity": 0.3, "extraction_confidence": 0.9},
            "provenance": {},
        }

        result = detector.detect(fact, credibility_score=0.7)

        assert DubiousFlag.FOG in result.flags
        reasoning = [r for r in result.reasoning if r.flag == DubiousFlag.FOG][0]
        assert "claim_clarity=0.30" in reasoning.reason
        assert reasoning.trigger_values["claim_clarity"] == 0.3

    def test_fog_triggered_vague_attribution_phrase(self):
        """FOG triggers when attribution contains vague patterns."""
        detector = DubiousDetector()
        fact = {
            "fact_id": "fog-2",
            "claim": {"text": "Clear statement"},
            "quality": {"claim_clarity": 0.9, "extraction_confidence": 0.9},
            "provenance": {
                "attribution_phrase": "according to sources familiar with the matter"
            },
        }

        result = detector.detect(fact, credibility_score=0.7)

        assert DubiousFlag.FOG in result.flags
        reasoning = [r for r in result.reasoning if r.flag == DubiousFlag.FOG][0]
        assert "vague pattern" in reasoning.reason

    def test_fog_triggered_reportedly(self):
        """FOG triggers on 'reportedly' pattern."""
        detector = DubiousDetector()
        fact = {
            "fact_id": "fog-3",
            "claim": {"text": "The attack reportedly caused damage"},
            "quality": {"claim_clarity": 0.8, "extraction_confidence": 0.9},
            "provenance": {},
        }

        result = detector.detect(fact, credibility_score=0.7)

        assert DubiousFlag.FOG in result.flags

    def test_fog_triggered_allegedly(self):
        """FOG triggers on 'allegedly' pattern."""
        detector = DubiousDetector()
        fact = {
            "fact_id": "fog-4",
            "claim": {"text": "He allegedly met with officials"},
            "quality": {"claim_clarity": 0.8, "extraction_confidence": 0.9},
            "provenance": {},
        }

        result = detector.detect(fact, credibility_score=0.7)

        assert DubiousFlag.FOG in result.flags

    def test_fog_triggered_sources_say(self):
        """FOG triggers on 'sources say' pattern."""
        detector = DubiousDetector()
        fact = {
            "fact_id": "fog-5",
            "claim": {"text": "Sources say the deal is imminent"},
            "quality": {"claim_clarity": 0.8, "extraction_confidence": 0.9},
            "provenance": {},
        }

        result = detector.detect(fact, credibility_score=0.7)

        assert DubiousFlag.FOG in result.flags

    def test_fog_triggered_hedging_may_have(self):
        """FOG triggers on hedging language like 'may have'."""
        detector = DubiousDetector()
        fact = {
            "fact_id": "fog-6",
            "claim": {"text": "Russia may have violated the treaty"},
            "quality": {"claim_clarity": 0.8, "extraction_confidence": 0.9},
            "provenance": {},
        }

        result = detector.detect(fact, credibility_score=0.7)

        assert DubiousFlag.FOG in result.flags

    def test_fog_not_triggered_clear_attribution(self):
        """FOG does NOT trigger with clear attribution and high clarity."""
        detector = DubiousDetector()
        fact = {
            "fact_id": "fog-7",
            "claim": {"text": "Putin announced the withdrawal"},
            "quality": {"claim_clarity": 0.9, "extraction_confidence": 0.9},
            "provenance": {
                "attribution_phrase": "In a speech, Putin stated"
            },
        }

        result = detector.detect(fact, credibility_score=0.7)

        assert DubiousFlag.FOG not in result.flags

    def test_fog_custom_threshold(self):
        """FOG respects custom clarity threshold."""
        detector = DubiousDetector(fog_clarity_threshold=0.3)
        fact = {
            "fact_id": "fog-8",
            "claim": {"text": "Something happened"},
            "quality": {"claim_clarity": 0.4, "extraction_confidence": 0.9},
            "provenance": {},
        }

        result = detector.detect(fact, credibility_score=0.7)

        # 0.4 is above custom threshold 0.3, should not trigger
        assert DubiousFlag.FOG not in result.flags


class TestAnomalyDetection:
    """Tests for ANOMALY gate: contradiction_count > 0."""

    def test_anomaly_triggered_with_contradictions(self):
        """ANOMALY triggers when contradictions list is non-empty."""
        detector = DubiousDetector()
        fact = {"fact_id": "anomaly-1", "claim": {"text": "Claim A"}}
        contradictions = [
            {"fact_id": "contra-1", "claim": {"text": "Opposing claim"}},
            {"fact_id": "contra-2", "claim": {"text": "Another opposing claim"}},
        ]

        result = detector.detect(fact, credibility_score=0.7, contradictions=contradictions)

        assert DubiousFlag.ANOMALY in result.flags
        reasoning = [r for r in result.reasoning if r.flag == DubiousFlag.ANOMALY][0]
        assert "contradiction_count=2" in reasoning.reason
        assert len(reasoning.trigger_values["contradicting_fact_ids"]) == 2

    def test_anomaly_not_triggered_no_contradictions(self):
        """ANOMALY does NOT trigger when contradictions is None or empty."""
        detector = DubiousDetector()
        fact = {"fact_id": "anomaly-2", "claim": {"text": "Claim B"}}

        result = detector.detect(fact, credibility_score=0.7, contradictions=None)
        assert DubiousFlag.ANOMALY not in result.flags

        result = detector.detect(fact, credibility_score=0.7, contradictions=[])
        assert DubiousFlag.ANOMALY not in result.flags

    def test_anomaly_limits_contradiction_ids(self):
        """ANOMALY reasoning limits contradiction IDs to first 5."""
        detector = DubiousDetector()
        fact = {"fact_id": "anomaly-3", "claim": {"text": "Disputed claim"}}
        contradictions = [
            {"fact_id": f"contra-{i}", "claim": {"text": f"Contra {i}"}}
            for i in range(10)
        ]

        result = detector.detect(fact, credibility_score=0.7, contradictions=contradictions)

        assert DubiousFlag.ANOMALY in result.flags
        reasoning = [r for r in result.reasoning if r.flag == DubiousFlag.ANOMALY][0]
        # Should only include first 5 IDs
        assert len(reasoning.trigger_values["contradicting_fact_ids"]) == 5


class TestNoiseDetection:
    """Tests for NOISE gate: source_credibility < 0.3."""

    def test_noise_triggered_low_credibility(self):
        """NOISE triggers when credibility_score < 0.3."""
        detector = DubiousDetector()
        fact = {"fact_id": "noise-1", "claim": {"text": "Unverified claim"}}

        result = detector.detect(fact, credibility_score=0.2)

        assert DubiousFlag.NOISE in result.flags
        reasoning = [r for r in result.reasoning if r.flag == DubiousFlag.NOISE][0]
        assert "credibility_score=0.20" in reasoning.reason
        assert reasoning.trigger_values["credibility_score"] == 0.2

    def test_noise_not_triggered_high_credibility(self):
        """NOISE does NOT trigger when credibility >= 0.3."""
        detector = DubiousDetector()
        fact = {"fact_id": "noise-2", "claim": {"text": "Credible claim"}}

        result = detector.detect(fact, credibility_score=0.5)

        assert DubiousFlag.NOISE not in result.flags

    def test_noise_not_triggered_at_threshold(self):
        """NOISE does NOT trigger when credibility equals threshold exactly."""
        detector = DubiousDetector()
        fact = {"fact_id": "noise-3", "claim": {"text": "Borderline claim"}}

        result = detector.detect(fact, credibility_score=0.3)

        assert DubiousFlag.NOISE not in result.flags

    def test_noise_custom_threshold(self):
        """NOISE respects custom credibility threshold."""
        detector = DubiousDetector(noise_credibility_threshold=0.5)
        fact = {"fact_id": "noise-4", "claim": {"text": "Some claim"}}

        result = detector.detect(fact, credibility_score=0.4)

        # 0.4 < 0.5 custom threshold
        assert DubiousFlag.NOISE in result.flags


class TestMultipleFlags:
    """Tests for multiple dubious flags on same fact."""

    def test_phantom_and_fog(self):
        """Fact can have both PHANTOM and FOG flags."""
        detector = DubiousDetector()
        fact = {
            "fact_id": "multi-1",
            "claim": {"text": "Sources say something reportedly happened"},
            "quality": {"claim_clarity": 0.3, "extraction_confidence": 0.9},
            "provenance": {
                "hop_count": 5,
                "source_classification": "tertiary",
            },
        }

        result = detector.detect(fact, credibility_score=0.5)

        assert DubiousFlag.PHANTOM in result.flags
        assert DubiousFlag.FOG in result.flags
        assert len(result.flags) == 2

    def test_all_flags_except_anomaly(self):
        """Fact can have PHANTOM, FOG, and NOISE simultaneously."""
        detector = DubiousDetector()
        fact = {
            "fact_id": "multi-2",
            "claim": {"text": "Reportedly something may have happened"},
            "quality": {"claim_clarity": 0.2, "extraction_confidence": 0.9},
            "provenance": {
                "hop_count": 6,
                "source_classification": "tertiary",
            },
        }

        result = detector.detect(fact, credibility_score=0.15)

        assert DubiousFlag.PHANTOM in result.flags
        assert DubiousFlag.FOG in result.flags
        assert DubiousFlag.NOISE in result.flags

    def test_all_four_flags(self):
        """Fact can have all four dubious flags."""
        detector = DubiousDetector()
        fact = {
            "fact_id": "multi-3",
            "claim": {"text": "Sources allegedly say"},
            "quality": {"claim_clarity": 0.2, "extraction_confidence": 0.9},
            "provenance": {
                "hop_count": 6,
                "source_classification": "tertiary",
            },
        }
        contradictions = [{"fact_id": "contra-1", "claim": {"text": "Opposite"}}]

        result = detector.detect(fact, credibility_score=0.1, contradictions=contradictions)

        assert len(result.flags) == 4
        assert DubiousFlag.PHANTOM in result.flags
        assert DubiousFlag.FOG in result.flags
        assert DubiousFlag.ANOMALY in result.flags
        assert DubiousFlag.NOISE in result.flags


class TestCleanFact:
    """Tests for facts that pass all gates (no dubious flags)."""

    def test_clean_fact_no_flags(self):
        """Clean fact with good provenance and clarity has no flags."""
        detector = DubiousDetector()
        fact = {
            "fact_id": "clean-1",
            "claim": {"text": "Putin announced withdrawal of troops"},
            "quality": {"claim_clarity": 0.95, "extraction_confidence": 0.9},
            "provenance": {
                "hop_count": 1,
                "source_classification": "primary",
                "attribution_chain": [
                    {"entity": "Putin", "hop": 0},
                ],
            },
        }

        result = detector.detect(fact, credibility_score=0.85)

        assert len(result.flags) == 0
        assert len(result.reasoning) == 0

    def test_clean_fact_empty_provenance(self):
        """Fact with missing provenance defaults to no PHANTOM (hop_count=0)."""
        detector = DubiousDetector()
        fact = {
            "fact_id": "clean-2",
            "claim": {"text": "Clear statement"},
            "quality": {"claim_clarity": 0.9, "extraction_confidence": 0.9},
            "provenance": {},
        }

        result = detector.detect(fact, credibility_score=0.7)

        # No PHANTOM (hop defaults to 0 which is <= 2)
        # No FOG (clarity 0.9 >= 0.5)
        # No NOISE (cred 0.7 >= 0.3)
        assert len(result.flags) == 0


class TestFixabilityCalculation:
    """Tests for fixability score calculation."""

    def test_fixability_not_dubious(self):
        """Clean facts have 0.0 fixability (no verification needed)."""
        detector = DubiousDetector()
        fact = {
            "fact_id": "fix-1",
            "claim": {"text": "Clear claim"},
            "quality": {"claim_clarity": 0.9},
            "provenance": {"hop_count": 1, "source_classification": "primary"},
        }

        result = detector.detect(fact, credibility_score=0.8)

        assert result.fixability_score == 0.0

    def test_fixability_pure_noise(self):
        """Pure NOISE has 0.0 fixability (batch analysis only)."""
        detector = DubiousDetector()
        fact = {
            "fact_id": "fix-2",
            "claim": {"text": "Clear claim from bad source"},
            "quality": {"claim_clarity": 0.9},
            "provenance": {"hop_count": 1, "source_classification": "primary"},
        }

        result = detector.detect(fact, credibility_score=0.1)

        assert DubiousFlag.NOISE in result.flags
        assert len(result.flags) == 1  # Only NOISE
        assert result.fixability_score == 0.0

    def test_fixability_fog_high(self):
        """FOG has high fixability (0.9 base)."""
        detector = DubiousDetector()
        fact = {
            "fact_id": "fix-3",
            "claim": {"text": "Sources say something"},
            "quality": {"claim_clarity": 0.9},
            "provenance": {},
        }

        result = detector.detect(fact, credibility_score=0.5)

        assert DubiousFlag.FOG in result.flags
        # FOG base is 0.9, plus credibility boost (0.5 * 0.2 = 0.1) = 1.0 capped
        assert result.fixability_score == 1.0

    def test_fixability_phantom_moderate(self):
        """PHANTOM has moderate fixability (0.6 base)."""
        detector = DubiousDetector()
        # Use claim text that won't trigger FOG vague pattern detection
        fact = {
            "fact_id": "fix-4",
            "claim": {"text": "Information from tertiary transmission"},
            "quality": {"claim_clarity": 0.9},
            "provenance": {"hop_count": 5, "source_classification": "tertiary"},
        }

        result = detector.detect(fact, credibility_score=0.5)

        assert DubiousFlag.PHANTOM in result.flags
        assert DubiousFlag.FOG not in result.flags  # Ensure only PHANTOM
        # PHANTOM base 0.6 + cred boost 0.1 = 0.7
        assert 0.65 <= result.fixability_score <= 0.75

    def test_fixability_takes_highest(self):
        """Multiple flags take highest fixability."""
        detector = DubiousDetector()
        fact = {
            "fact_id": "fix-5",
            "claim": {"text": "Sources say distant claim"},
            "quality": {"claim_clarity": 0.3},
            "provenance": {"hop_count": 5, "source_classification": "tertiary"},
        }

        result = detector.detect(fact, credibility_score=0.4)

        # Has both PHANTOM (0.6) and FOG (0.9)
        assert DubiousFlag.PHANTOM in result.flags
        assert DubiousFlag.FOG in result.flags
        # Takes FOG's 0.9 + cred boost = 0.98
        assert result.fixability_score >= 0.95


class TestDubiousResult:
    """Tests for DubiousResult dataclass."""

    def test_dubious_result_defaults(self):
        """DubiousResult initializes with empty defaults."""
        result = DubiousResult()

        assert result.flags == []
        assert result.reasoning == []
        assert result.fixability_score == 0.0

    def test_dubious_result_with_values(self):
        """DubiousResult accepts values."""
        from osint_system.data_management.schemas import ClassificationReasoning

        reasoning = ClassificationReasoning(
            flag=DubiousFlag.PHANTOM,
            reason="test",
            trigger_values={"hop_count": 5},
        )
        result = DubiousResult(
            flags=[DubiousFlag.PHANTOM],
            reasoning=[reasoning],
            fixability_score=0.6,
        )

        assert len(result.flags) == 1
        assert len(result.reasoning) == 1
        assert result.fixability_score == 0.6


class TestEdgeCases:
    """Edge case tests for robustness."""

    def test_missing_quality_field(self):
        """Detector handles missing quality field gracefully."""
        detector = DubiousDetector()
        fact = {
            "fact_id": "edge-1",
            "claim": {"text": "Some claim"},
            "provenance": {},
        }

        # Should not raise, quality defaults to clarity 1.0
        result = detector.detect(fact, credibility_score=0.5)
        assert DubiousFlag.FOG not in result.flags

    def test_missing_provenance_field(self):
        """Detector handles missing provenance field gracefully."""
        detector = DubiousDetector()
        fact = {
            "fact_id": "edge-2",
            "claim": {"text": "Some claim"},
            "quality": {"claim_clarity": 0.9},
        }

        # Should not raise, hop defaults to 0
        result = detector.detect(fact, credibility_score=0.5)
        assert DubiousFlag.PHANTOM not in result.flags

    def test_none_quality(self):
        """Detector handles None quality gracefully."""
        detector = DubiousDetector()
        fact = {
            "fact_id": "edge-3",
            "claim": {"text": "Some claim"},
            "quality": None,
            "provenance": {},
        }

        result = detector.detect(fact, credibility_score=0.5)
        # clarity defaults to 1.0, no FOG
        assert DubiousFlag.FOG not in result.flags

    def test_empty_claim_text(self):
        """Detector handles empty claim text."""
        detector = DubiousDetector()
        fact = {
            "fact_id": "edge-4",
            "claim": {"text": ""},
            "quality": {"claim_clarity": 0.9},
            "provenance": {},
        }

        # Should not raise
        result = detector.detect(fact, credibility_score=0.5)
        assert isinstance(result, DubiousResult)

    def test_credibility_boundary_values(self):
        """Detector handles boundary credibility values."""
        detector = DubiousDetector()
        fact = {"fact_id": "edge-5", "claim": {"text": "test"}}

        # At threshold exactly
        result = detector.detect(fact, credibility_score=0.3)
        assert DubiousFlag.NOISE not in result.flags

        # Just below threshold
        result = detector.detect(fact, credibility_score=0.29)
        assert DubiousFlag.NOISE in result.flags

        # Zero credibility
        result = detector.detect(fact, credibility_score=0.0)
        assert DubiousFlag.NOISE in result.flags

    def test_vague_pattern_case_insensitive(self):
        """Vague attribution patterns are case-insensitive."""
        detector = DubiousDetector()
        fact = {
            "fact_id": "edge-6",
            "claim": {"text": "SOURCES SAY the deal is done"},
            "quality": {"claim_clarity": 0.9},
            "provenance": {},
        }

        result = detector.detect(fact, credibility_score=0.5)
        assert DubiousFlag.FOG in result.flags
