"""Tests for analysis output Pydantic schemas.

Validates construction, field validation, and helper methods
for all analysis schema models.
"""

import pytest
from pydantic import ValidationError

from osint_system.analysis.schemas import (
    AlternativeHypothesis,
    AnalysisSynthesis,
    ConfidenceAssessment,
    ContradictionEntry,
    InvestigationSnapshot,
    KeyJudgment,
    SourceInventoryEntry,
    TimelineEntry,
)


def _make_confidence(**overrides) -> ConfidenceAssessment:
    """Helper to build a ConfidenceAssessment with defaults."""
    defaults = {
        "level": "high",
        "numeric": 0.9,
        "reasoning": "Multiple wire services confirm",
        "source_count": 3,
        "highest_authority": 0.9,
    }
    defaults.update(overrides)
    return ConfidenceAssessment(**defaults)


def _make_snapshot(**overrides) -> InvestigationSnapshot:
    """Helper to build a minimal InvestigationSnapshot."""
    defaults = {
        "investigation_id": "inv-test",
        "facts": [{"fact_id": "f1", "claim": {"text": "test claim"}}],
        "fact_count": 1,
    }
    defaults.update(overrides)
    return InvestigationSnapshot(**defaults)


class TestKeyJudgment:
    """Tests for KeyJudgment model."""

    def test_construction_with_valid_data(self) -> None:
        """KeyJudgment can be constructed with valid fields."""
        judgment = KeyJudgment(
            judgment="Russia escalated operations in eastern Ukraine",
            confidence=_make_confidence(),
            supporting_fact_ids=["fact-001", "fact-003"],
            reasoning="Corroborated by AP, Reuters, and AFP wire service reports",
        )
        assert judgment.judgment == "Russia escalated operations in eastern Ukraine"
        assert judgment.confidence.level == "high"
        assert len(judgment.supporting_fact_ids) == 2
        assert "fact-001" in judgment.supporting_fact_ids

    def test_empty_supporting_facts(self) -> None:
        """KeyJudgment allows empty supporting_fact_ids."""
        judgment = KeyJudgment(
            judgment="Assessment without direct fact links",
            confidence=_make_confidence(level="low", numeric=0.3),
            reasoning="Based on pattern analysis across multiple sources",
        )
        assert judgment.supporting_fact_ids == []


class TestConfidenceAssessment:
    """Tests for ConfidenceAssessment model."""

    def test_numeric_must_be_in_range(self) -> None:
        """Numeric score must be between 0.0 and 1.0."""
        with pytest.raises(ValidationError) as exc_info:
            ConfidenceAssessment(
                level="high",
                numeric=1.5,
                reasoning="Invalid score",
            )
        assert "numeric" in str(exc_info.value)

    def test_numeric_lower_bound(self) -> None:
        """Numeric score rejects negative values."""
        with pytest.raises(ValidationError):
            ConfidenceAssessment(
                level="low",
                numeric=-0.1,
                reasoning="Negative score",
            )

    def test_valid_levels(self) -> None:
        """All three confidence levels are accepted."""
        for level in ("low", "moderate", "high"):
            assessment = ConfidenceAssessment(
                level=level,
                numeric=0.5,
                reasoning=f"{level} confidence test",
            )
            assert assessment.level == level

    def test_invalid_level_rejected(self) -> None:
        """Non-standard confidence levels are rejected."""
        with pytest.raises(ValidationError):
            ConfidenceAssessment(
                level="very_high",
                numeric=0.99,
                reasoning="Invalid level",
            )

    def test_source_count_defaults_to_zero(self) -> None:
        """source_count defaults to 0 when not provided."""
        assessment = _make_confidence()
        assert assessment.source_count >= 0


class TestAnalysisSynthesis:
    """Tests for AnalysisSynthesis model."""

    def test_full_construction(self) -> None:
        """AnalysisSynthesis can be constructed with all fields populated."""
        snapshot = _make_snapshot(fact_count=10, confirmed_count=7)
        judgment = KeyJudgment(
            judgment="Key finding",
            confidence=_make_confidence(),
            supporting_fact_ids=["f1"],
            reasoning="Evidence-based reasoning",
        )
        alt = AlternativeHypothesis(
            hypothesis="Alternative reading",
            likelihood="possible",
            supporting_evidence=["Some data point"],
            weaknesses=["Contradicted by primary source"],
        )
        contradiction = ContradictionEntry(
            description="Casualty figures differ",
            fact_ids=["f1", "f2"],
            resolution_status="unresolved",
        )

        synthesis = AnalysisSynthesis(
            investigation_id="inv-test",
            executive_summary="We assess with high confidence that the situation has escalated.",
            key_judgments=[judgment],
            alternative_hypotheses=[alt],
            contradictions=[contradiction],
            implications=["Strategic implication 1"],
            forecasts=["Forecast for Q2"],
            overall_confidence=_make_confidence(level="moderate", numeric=0.65),
            source_assessment="12 sources: 3 wire, 5 news, 4 social",
            snapshot=snapshot,
            model_version="gemini-1.5-pro",
            version=2,
        )

        assert synthesis.investigation_id == "inv-test"
        assert len(synthesis.key_judgments) == 1
        assert len(synthesis.alternative_hypotheses) == 1
        assert len(synthesis.contradictions) == 1
        assert synthesis.version == 2
        assert synthesis.model_version == "gemini-1.5-pro"
        assert synthesis.generated_at is not None

    def test_defaults_populated(self) -> None:
        """AnalysisSynthesis populates defaults for optional list fields."""
        synthesis = AnalysisSynthesis(
            investigation_id="inv-test",
            executive_summary="Brief summary",
            overall_confidence=_make_confidence(),
            snapshot=_make_snapshot(),
        )
        assert synthesis.key_judgments == []
        assert synthesis.alternative_hypotheses == []
        assert synthesis.contradictions == []
        assert synthesis.implications == []
        assert synthesis.forecasts == []
        assert synthesis.version == 1
        assert synthesis.model_version == ""


class TestInvestigationSnapshot:
    """Tests for InvestigationSnapshot model."""

    def test_token_estimate_positive(self) -> None:
        """token_estimate returns a positive integer for non-empty snapshots."""
        snapshot = _make_snapshot(
            facts=[
                {"fact_id": f"f{i}", "claim": {"text": f"Claim number {i}"}}
                for i in range(10)
            ],
            fact_count=10,
        )
        estimate = snapshot.token_estimate()
        assert isinstance(estimate, int)
        assert estimate > 0

    def test_token_estimate_scales_with_data(self) -> None:
        """Larger snapshots produce larger token estimates."""
        small = _make_snapshot(facts=[{"fact_id": "f1", "claim": {"text": "short"}}])
        large = _make_snapshot(
            facts=[
                {"fact_id": f"f{i}", "claim": {"text": f"A much longer claim text for fact number {i} with extra details"}}
                for i in range(50)
            ],
            fact_count=50,
        )
        assert large.token_estimate() > small.token_estimate()

    def test_counts_stored(self) -> None:
        """Count fields store the provided values."""
        snapshot = InvestigationSnapshot(
            investigation_id="inv-test",
            fact_count=25,
            confirmed_count=15,
            refuted_count=3,
            unverifiable_count=4,
            dubious_count=3,
        )
        assert snapshot.fact_count == 25
        assert snapshot.confirmed_count == 15
        assert snapshot.refuted_count == 3
        assert snapshot.unverifiable_count == 4
        assert snapshot.dubious_count == 3

    def test_empty_snapshot(self) -> None:
        """InvestigationSnapshot with no data has zero counts and empty lists."""
        snapshot = InvestigationSnapshot(investigation_id="inv-empty")
        assert snapshot.fact_count == 0
        assert snapshot.confirmed_count == 0
        assert snapshot.facts == []
        assert snapshot.classifications == []
        assert snapshot.verification_results == []
        assert snapshot.graph_summary == {}
        assert snapshot.source_inventory == []
        assert snapshot.timeline_entries == []


class TestAlternativeHypothesis:
    """Tests for AlternativeHypothesis model."""

    def test_valid_likelihood_values(self) -> None:
        """All three likelihood values are accepted."""
        for likelihood in ("unlikely", "possible", "plausible"):
            alt = AlternativeHypothesis(
                hypothesis="Test hypothesis",
                likelihood=likelihood,
            )
            assert alt.likelihood == likelihood

    def test_invalid_likelihood_rejected(self) -> None:
        """Non-standard likelihood values are rejected."""
        with pytest.raises(ValidationError):
            AlternativeHypothesis(
                hypothesis="Test",
                likelihood="certain",
            )

    def test_evidence_and_weaknesses_populated(self) -> None:
        """supporting_evidence and weaknesses can be populated."""
        alt = AlternativeHypothesis(
            hypothesis="Alternative reading of events",
            likelihood="plausible",
            supporting_evidence=["Evidence A", "Evidence B"],
            weaknesses=["Weakness 1"],
        )
        assert len(alt.supporting_evidence) == 2
        assert len(alt.weaknesses) == 1


class TestContradictionEntry:
    """Tests for ContradictionEntry model."""

    def test_valid_resolution_statuses(self) -> None:
        """All three resolution statuses are accepted."""
        for status in ("resolved", "unresolved", "partially_resolved"):
            entry = ContradictionEntry(
                description="Test contradiction",
                fact_ids=["f1", "f2"],
                resolution_status=status,
            )
            assert entry.resolution_status == status

    def test_invalid_resolution_status_rejected(self) -> None:
        """Non-standard resolution statuses are rejected."""
        with pytest.raises(ValidationError):
            ContradictionEntry(
                description="Test",
                fact_ids=["f1"],
                resolution_status="unknown",
            )

    def test_resolution_notes_default_empty(self) -> None:
        """resolution_notes defaults to empty string."""
        entry = ContradictionEntry(
            description="Test",
            fact_ids=["f1", "f2"],
            resolution_status="unresolved",
        )
        assert entry.resolution_notes == ""
