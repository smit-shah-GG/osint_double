"""Tests for fact classification schemas.

Tests comprehensive schema validation per Phase 7 CONTEXT.md requirements:
- FactClassification with minimal and full fields
- ImpactTier enum values
- DubiousFlag enum values (taxonomy of doubt)
- CredibilityBreakdown score computation
- ClassificationReasoning for dubious flags
- ClassificationHistory for audit trail
- Property methods: is_dubious, is_critical_dubious, is_noise
- History management via add_history_entry
"""

import pytest
from pydantic import ValidationError

from osint_system.data_management.schemas import (
    FactClassification,
    ImpactTier,
    DubiousFlag,
    CredibilityBreakdown,
    ClassificationReasoning,
    ClassificationHistory,
)


# ============================================================================
# FactClassification Tests
# ============================================================================


class TestFactClassificationMinimal:
    """Test minimal valid FactClassification."""

    def test_minimal_classification_requires_fact_id_and_investigation(self):
        """Minimal classification needs fact_id and investigation_id."""
        classification = FactClassification(
            fact_id="test-fact-123",
            investigation_id="test-inv-456",
        )

        assert classification.fact_id == "test-fact-123"
        assert classification.investigation_id == "test-inv-456"
        assert classification.impact_tier == ImpactTier.LESS_CRITICAL  # default
        assert classification.dubious_flags == []  # default
        assert classification.priority_score == 0.0  # default
        assert classification.credibility_score == 0.0  # default

    def test_classification_without_fact_id_fails(self):
        """Classification without fact_id should fail validation."""
        with pytest.raises(ValidationError):
            FactClassification(investigation_id="test-inv")  # type: ignore

    def test_classification_without_investigation_id_fails(self):
        """Classification without investigation_id should fail validation."""
        with pytest.raises(ValidationError):
            FactClassification(fact_id="test-fact")  # type: ignore


class TestFactClassificationFull:
    """Test FactClassification with all fields."""

    def test_full_classification_serialization(self):
        """Full classification with all fields should serialize correctly."""
        classification = FactClassification(
            fact_id="fact-uuid-123",
            investigation_id="inv-uuid-456",
            impact_tier=ImpactTier.CRITICAL,
            dubious_flags=[DubiousFlag.PHANTOM, DubiousFlag.FOG],
            priority_score=0.85,
            credibility_score=0.45,
            credibility_breakdown=CredibilityBreakdown(
                s_root=0.4,
                s_echoes_sum=0.3,
                proximity_scores=[0.7, 0.49],
                precision_scores=[0.8, 0.6],
                echo_bonus=0.05,
                alpha=0.2,
            ),
            classification_reasoning=[
                ClassificationReasoning(
                    flag=DubiousFlag.PHANTOM,
                    reason="hop_count=4, no primary_source found",
                    trigger_values={"hop_count": 4},
                ),
                ClassificationReasoning(
                    flag=DubiousFlag.FOG,
                    reason="attribution contains 'reportedly'",
                    trigger_values={"claim_clarity": 0.35},
                ),
            ],
            impact_reasoning="Involves world leader and military action",
        )

        # Verify all fields
        assert classification.impact_tier == ImpactTier.CRITICAL
        assert len(classification.dubious_flags) == 2
        assert DubiousFlag.PHANTOM in classification.dubious_flags
        assert DubiousFlag.FOG in classification.dubious_flags
        assert classification.priority_score == 0.85
        assert classification.credibility_score == 0.45
        assert classification.credibility_breakdown is not None
        assert len(classification.classification_reasoning) == 2
        assert classification.impact_reasoning is not None

    def test_classification_json_roundtrip(self):
        """Classification should serialize and deserialize correctly."""
        classification = FactClassification(
            fact_id="test-fact",
            investigation_id="test-inv",
            impact_tier=ImpactTier.CRITICAL,
            dubious_flags=[DubiousFlag.ANOMALY],
            credibility_score=0.7,
        )

        json_data = classification.model_dump_json()
        restored = FactClassification.model_validate_json(json_data)

        assert restored.fact_id == classification.fact_id
        assert restored.impact_tier == classification.impact_tier
        assert restored.dubious_flags == classification.dubious_flags
        assert restored.credibility_score == classification.credibility_score


class TestFactClassificationProperties:
    """Test FactClassification property methods."""

    def test_is_dubious_with_no_flags(self):
        """is_dubious returns False when no flags set."""
        classification = FactClassification(
            fact_id="test-fact",
            investigation_id="test-inv",
        )
        assert classification.is_dubious is False

    def test_is_dubious_with_flags(self):
        """is_dubious returns True when any flag is set."""
        classification = FactClassification(
            fact_id="test-fact",
            investigation_id="test-inv",
            dubious_flags=[DubiousFlag.FOG],
        )
        assert classification.is_dubious is True

    def test_is_critical_dubious_both_conditions(self):
        """is_critical_dubious True only when critical AND dubious."""
        # Critical but not dubious
        critical_clean = FactClassification(
            fact_id="test-fact",
            investigation_id="test-inv",
            impact_tier=ImpactTier.CRITICAL,
            dubious_flags=[],
        )
        assert critical_clean.is_critical_dubious is False

        # Dubious but not critical
        dubious_minor = FactClassification(
            fact_id="test-fact",
            investigation_id="test-inv",
            impact_tier=ImpactTier.LESS_CRITICAL,
            dubious_flags=[DubiousFlag.PHANTOM],
        )
        assert dubious_minor.is_critical_dubious is False

        # Both critical AND dubious
        critical_dubious = FactClassification(
            fact_id="test-fact",
            investigation_id="test-inv",
            impact_tier=ImpactTier.CRITICAL,
            dubious_flags=[DubiousFlag.PHANTOM],
        )
        assert critical_dubious.is_critical_dubious is True

    def test_is_noise_only_noise_flag(self):
        """is_noise True only when NOISE is the only flag."""
        # Only noise
        noise_only = FactClassification(
            fact_id="test-fact",
            investigation_id="test-inv",
            dubious_flags=[DubiousFlag.NOISE],
        )
        assert noise_only.is_noise is True

        # Noise + other flags
        noise_plus = FactClassification(
            fact_id="test-fact",
            investigation_id="test-inv",
            dubious_flags=[DubiousFlag.NOISE, DubiousFlag.FOG],
        )
        assert noise_plus.is_noise is False

        # Other flag only
        other_only = FactClassification(
            fact_id="test-fact",
            investigation_id="test-inv",
            dubious_flags=[DubiousFlag.FOG],
        )
        assert other_only.is_noise is False

    def test_requires_verification(self):
        """requires_verification based on dubious flags."""
        # No flags - doesn't require verification
        clean = FactClassification(
            fact_id="test-fact",
            investigation_id="test-inv",
        )
        assert clean.requires_verification is False

        # Noise only - doesn't require individual verification
        noise_only = FactClassification(
            fact_id="test-fact",
            investigation_id="test-inv",
            dubious_flags=[DubiousFlag.NOISE],
        )
        assert noise_only.requires_verification is False

        # Fixable dubious - requires verification
        fixable = FactClassification(
            fact_id="test-fact",
            investigation_id="test-inv",
            dubious_flags=[DubiousFlag.PHANTOM],
        )
        assert fixable.requires_verification is True


class TestFactClassificationHistory:
    """Test classification history management."""

    def test_add_history_entry(self):
        """add_history_entry preserves current state."""
        classification = FactClassification(
            fact_id="test-fact",
            investigation_id="test-inv",
            impact_tier=ImpactTier.CRITICAL,
            dubious_flags=[DubiousFlag.PHANTOM],
            credibility_score=0.5,
        )

        assert len(classification.history) == 0

        classification.add_history_entry("new corroborating source added")

        assert len(classification.history) == 1
        entry = classification.history[0]
        assert entry.previous_impact_tier == ImpactTier.CRITICAL
        assert entry.previous_dubious_flags == [DubiousFlag.PHANTOM]
        assert entry.previous_credibility_score == 0.5
        assert entry.trigger == "new corroborating source added"
        assert entry.timestamp is not None

    def test_get_flag_reasoning(self):
        """get_flag_reasoning retrieves correct reasoning."""
        classification = FactClassification(
            fact_id="test-fact",
            investigation_id="test-inv",
            classification_reasoning=[
                ClassificationReasoning(
                    flag=DubiousFlag.PHANTOM,
                    reason="Test phantom reason",
                    trigger_values={},
                ),
                ClassificationReasoning(
                    flag=DubiousFlag.FOG,
                    reason="Test fog reason",
                    trigger_values={},
                ),
            ],
        )

        phantom_reason = classification.get_flag_reasoning(DubiousFlag.PHANTOM)
        assert phantom_reason is not None
        assert phantom_reason.reason == "Test phantom reason"

        fog_reason = classification.get_flag_reasoning(DubiousFlag.FOG)
        assert fog_reason is not None
        assert fog_reason.reason == "Test fog reason"

        anomaly_reason = classification.get_flag_reasoning(DubiousFlag.ANOMALY)
        assert anomaly_reason is None


# ============================================================================
# ImpactTier Tests
# ============================================================================


class TestImpactTier:
    """Test ImpactTier enum."""

    def test_impact_tier_values(self):
        """ImpactTier has correct values."""
        assert ImpactTier.CRITICAL.value == "critical"
        assert ImpactTier.LESS_CRITICAL.value == "less_critical"

    def test_all_impact_tiers(self):
        """All impact tiers are valid in classification."""
        for tier in ImpactTier:
            classification = FactClassification(
                fact_id="test-fact",
                investigation_id="test-inv",
                impact_tier=tier,
            )
            assert classification.impact_tier == tier


# ============================================================================
# DubiousFlag Tests
# ============================================================================


class TestDubiousFlag:
    """Test DubiousFlag enum (taxonomy of doubt)."""

    def test_dubious_flag_values(self):
        """DubiousFlag has correct values per CONTEXT.md taxonomy."""
        assert DubiousFlag.PHANTOM.value == "phantom"  # Structural failure
        assert DubiousFlag.FOG.value == "fog"  # Attribution failure
        assert DubiousFlag.ANOMALY.value == "anomaly"  # Coherence failure
        assert DubiousFlag.NOISE.value == "noise"  # Reputation failure

    def test_flags_are_independent(self):
        """Multiple flags can be combined."""
        classification = FactClassification(
            fact_id="test-fact",
            investigation_id="test-inv",
            dubious_flags=[
                DubiousFlag.PHANTOM,
                DubiousFlag.FOG,
                DubiousFlag.ANOMALY,
                DubiousFlag.NOISE,
            ],
        )

        assert len(classification.dubious_flags) == 4
        assert DubiousFlag.PHANTOM in classification.dubious_flags
        assert DubiousFlag.FOG in classification.dubious_flags
        assert DubiousFlag.ANOMALY in classification.dubious_flags
        assert DubiousFlag.NOISE in classification.dubious_flags


# ============================================================================
# CredibilityBreakdown Tests
# ============================================================================


class TestCredibilityBreakdown:
    """Test CredibilityBreakdown score computation."""

    def test_minimal_breakdown(self):
        """Minimal breakdown with defaults."""
        breakdown = CredibilityBreakdown()

        assert breakdown.s_root == 0.0
        assert breakdown.s_echoes_sum == 0.0
        assert breakdown.proximity_scores == []
        assert breakdown.precision_scores == []
        assert breakdown.echo_bonus == 0.0
        assert breakdown.alpha == 0.2

    def test_compute_total_no_echoes(self):
        """compute_total with no echoes."""
        breakdown = CredibilityBreakdown(s_root=0.9, s_echoes_sum=0.0)
        total = breakdown.compute_total()

        # S_root + (alpha * log10(1 + 0)) = 0.9 + 0 = 0.9
        assert total == pytest.approx(0.9, abs=0.001)

    def test_compute_total_with_echoes(self):
        """compute_total with echo sources."""
        import math

        breakdown = CredibilityBreakdown(
            s_root=0.8,
            s_echoes_sum=2.5,
            alpha=0.2,
        )
        total = breakdown.compute_total()

        # S_root + (alpha * log10(1 + echoes_sum))
        # 0.8 + (0.2 * log10(3.5)) = 0.8 + 0.2 * 0.544 = 0.8 + 0.109 = ~0.909
        expected = 0.8 + (0.2 * math.log10(3.5))
        assert total == pytest.approx(expected, abs=0.001)

    def test_compute_total_logarithmic_dampening(self):
        """Echo contribution has diminishing returns."""
        import math

        # Compare echo contribution at different levels
        low_echo = CredibilityBreakdown(s_root=0.5, s_echoes_sum=1.0, alpha=0.2)
        high_echo = CredibilityBreakdown(s_root=0.5, s_echoes_sum=100.0, alpha=0.2)

        low_bonus = low_echo.compute_total() - 0.5
        high_bonus = high_echo.compute_total() - 0.5

        # 100x more echoes should NOT give 100x more bonus (logarithmic)
        assert high_bonus < low_bonus * 10
        # But should still give more
        assert high_bonus > low_bonus


# ============================================================================
# ClassificationReasoning Tests
# ============================================================================


class TestClassificationReasoning:
    """Test ClassificationReasoning for dubious flags."""

    def test_reasoning_creation(self):
        """Create reasoning for a flag."""
        reasoning = ClassificationReasoning(
            flag=DubiousFlag.PHANTOM,
            reason="hop_count=4, no primary_source found",
            trigger_values={"hop_count": 4, "primary_source": None},
        )

        assert reasoning.flag == DubiousFlag.PHANTOM
        assert "hop_count" in reasoning.reason
        assert reasoning.trigger_values["hop_count"] == 4

    def test_reasoning_with_empty_trigger_values(self):
        """Reasoning works with empty trigger values."""
        reasoning = ClassificationReasoning(
            flag=DubiousFlag.FOG,
            reason="Vague attribution detected",
        )

        assert reasoning.flag == DubiousFlag.FOG
        assert reasoning.trigger_values == {}


# ============================================================================
# ClassificationHistory Tests
# ============================================================================


class TestClassificationHistory:
    """Test ClassificationHistory for audit trail."""

    def test_history_entry_creation(self):
        """Create history entry."""
        entry = ClassificationHistory(
            previous_impact_tier=ImpactTier.LESS_CRITICAL,
            previous_dubious_flags=[DubiousFlag.PHANTOM],
            previous_credibility_score=0.45,
            trigger="new corroborating source",
        )

        assert entry.previous_impact_tier == ImpactTier.LESS_CRITICAL
        assert entry.previous_dubious_flags == [DubiousFlag.PHANTOM]
        assert entry.previous_credibility_score == 0.45
        assert entry.trigger == "new corroborating source"
        assert entry.timestamp is not None

    def test_history_entry_minimal(self):
        """History entry with only trigger."""
        entry = ClassificationHistory(trigger="initial classification")

        assert entry.previous_impact_tier is None
        assert entry.previous_dubious_flags == []
        assert entry.previous_credibility_score is None
        assert entry.trigger == "initial classification"


# ============================================================================
# Score Validation Tests
# ============================================================================


class TestScoreValidation:
    """Test score field validation."""

    def test_credibility_score_bounds(self):
        """Credibility score must be 0.0-1.0."""
        # Valid
        FactClassification(
            fact_id="test",
            investigation_id="test",
            credibility_score=0.0,
        )
        FactClassification(
            fact_id="test",
            investigation_id="test",
            credibility_score=1.0,
        )

        # Invalid: out of bounds
        with pytest.raises(ValidationError):
            FactClassification(
                fact_id="test",
                investigation_id="test",
                credibility_score=1.5,
            )

        with pytest.raises(ValidationError):
            FactClassification(
                fact_id="test",
                investigation_id="test",
                credibility_score=-0.1,
            )

    def test_priority_score_bounds(self):
        """Priority score must be 0.0-1.0."""
        # Valid
        FactClassification(
            fact_id="test",
            investigation_id="test",
            priority_score=0.0,
        )
        FactClassification(
            fact_id="test",
            investigation_id="test",
            priority_score=1.0,
        )

        # Invalid: out of bounds
        with pytest.raises(ValidationError):
            FactClassification(
                fact_id="test",
                investigation_id="test",
                priority_score=1.5,
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
