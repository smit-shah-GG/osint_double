"""Tests for Synthesizer with MOCKED LLM (zero API calls).

Validates:
- synthesize() returns AnalysisSynthesis with all fields populated
- Executive summary is non-empty
- Key judgments parsed correctly from JSON
- Alternative hypotheses generated for uncertain judgments
- Graceful fallback on LLM failure
- Facts context preparation
- Overall confidence computation
- Malformed JSON handling
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from osint_system.analysis.schemas import (
    AnalysisSynthesis,
    ConfidenceAssessment,
    InvestigationSnapshot,
    KeyJudgment,
)
from osint_system.analysis.synthesizer import Synthesizer
from osint_system.config.analysis_config import AnalysisConfig


# ------------------------------------------------------------------
# Canned LLM responses
# ------------------------------------------------------------------

MOCK_EXECUTIVE_SUMMARY = (
    "We assess with moderate confidence that recent military movements in "
    "eastern Ukraine represent a significant escalation. Multiple wire services "
    "confirm troop deployments exceeding routine rotation levels."
)

MOCK_KEY_JUDGMENTS_JSON = json.dumps({
    "key_judgments": [
        {
            "judgment": "We assess with high confidence that Russia has escalated military operations",
            "confidence_level": "high",
            "confidence_numeric": 0.85,
            "confidence_reasoning": "Confirmed by 3 independent wire services",
            "supporting_fact_ids": ["fact-001", "fact-003"],
            "reasoning": "Multiple sources confirm troop movements exceeding historical norms",
        },
        {
            "judgment": "We judge with moderate confidence that diplomatic channels remain open",
            "confidence_level": "moderate",
            "confidence_numeric": 0.55,
            "confidence_reasoning": "Single official statement, not independently verified",
            "supporting_fact_ids": ["fact-002"],
            "reasoning": "Official spokesperson confirmed willingness to negotiate",
        },
    ]
})

MOCK_ALT_HYPOTHESES_JSON = json.dumps({
    "alternative_hypotheses": [
        {
            "hypothesis": "Troop movements represent routine rotation rather than escalation",
            "likelihood": "possible",
            "supporting_evidence": ["Annual rotation cycle matches timeline"],
            "weaknesses": ["Scale exceeds historical rotation sizes by 3x"],
        },
    ]
})

MOCK_IMPLICATIONS_JSON = json.dumps({
    "implications": [
        "The confirmed escalation increases risk of direct confrontation",
    ],
    "forecasts": [
        "If current trends continue, further territorial gains likely by Q2",
    ],
})

MOCK_SOURCE_ASSESSMENT = (
    "The source base consists predominantly of wire services (AP, Reuters) "
    "with high authority scores. Coverage is geographically concentrated on "
    "Eastern Europe with limited Asian-Pacific perspective."
)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture()
def config() -> AnalysisConfig:
    """Default analysis config."""
    return AnalysisConfig()


@pytest.fixture()
def mock_snapshot() -> InvestigationSnapshot:
    """InvestigationSnapshot with 5 test facts."""
    return InvestigationSnapshot(
        investigation_id="inv-test-synth",
        objective="Track Russian military movements in eastern Ukraine",
        facts=[
            {
                "fact_id": "fact-001",
                "claim": {"text": "[E1:Putin] deployed troops to eastern Ukraine", "assertion_type": "statement", "claim_type": "event"},
                "entities": [{"id": "E1", "text": "Putin", "type": "PERSON", "canonical": "Vladimir Putin"}],
                "provenance": {"source_id": "apnews.com", "source_type": "wire_service"},
            },
            {
                "fact_id": "fact-002",
                "claim": {"text": "Kremlin spokesperson confirmed willingness to negotiate", "assertion_type": "statement", "claim_type": "event"},
                "entities": [{"id": "E1", "text": "Kremlin", "type": "ORGANIZATION", "canonical": "Kremlin"}],
                "provenance": {"source_id": "reuters.com", "source_type": "wire_service"},
            },
            {
                "fact_id": "fact-003",
                "claim": {"text": "[E1:NATO] held emergency meeting", "assertion_type": "statement", "claim_type": "event"},
                "entities": [{"id": "E1", "text": "NATO", "type": "ORGANIZATION", "canonical": "NATO"}],
                "provenance": {"source_id": "bbc.com", "source_type": "news_outlet"},
            },
            {
                "fact_id": "fact-004",
                "claim": {"text": "[E1:Zelensky] requested additional weapons", "assertion_type": "statement", "claim_type": "event"},
                "entities": [{"id": "E1", "text": "Zelensky", "type": "PERSON", "canonical": "Volodymyr Zelensky"}],
                "provenance": {"source_id": "apnews.com", "source_type": "wire_service"},
            },
            {
                "fact_id": "fact-005",
                "claim": {"text": "Casualty reports indicate 12 killed", "assertion_type": "statement", "claim_type": "event"},
                "entities": [],
                "provenance": {"source_id": "unknown.com", "source_type": "news_outlet"},
            },
        ],
        classifications=[
            {"fact_id": "fact-001", "impact_tier": "CRITICAL", "dubious_flags": [], "credibility_score": 0.9},
            {"fact_id": "fact-002", "impact_tier": "LESS_CRITICAL", "dubious_flags": [], "credibility_score": 0.7},
            {"fact_id": "fact-003", "impact_tier": "CRITICAL", "dubious_flags": [], "credibility_score": 0.85},
            {"fact_id": "fact-004", "impact_tier": "CRITICAL", "dubious_flags": [], "credibility_score": 0.8},
            {"fact_id": "fact-005", "impact_tier": "LESS_CRITICAL", "dubious_flags": ["PHANTOM"], "credibility_score": 0.4},
        ],
        verification_results=[
            {"fact_id": "fact-001", "status": "confirmed", "final_confidence": 0.9},
            {"fact_id": "fact-002", "status": "confirmed", "final_confidence": 0.7},
            {"fact_id": "fact-003", "status": "confirmed", "final_confidence": 0.85},
            {"fact_id": "fact-004", "status": "confirmed", "final_confidence": 0.8},
            {"fact_id": "fact-005", "status": "unverifiable", "final_confidence": 0.4},
        ],
        fact_count=5,
        confirmed_count=4,
        refuted_count=0,
        unverifiable_count=1,
        dubious_count=1,
    )


@pytest.fixture()
def synthesizer(config: AnalysisConfig) -> Synthesizer:
    """Synthesizer with config (LLM will be mocked)."""
    return Synthesizer(config=config)


def _make_mock_call_llm():
    """Create a mock _call_llm that returns appropriate canned responses."""
    call_count = 0

    async def mock_call_llm(prompt: str, structured: bool = False) -> str:
        nonlocal call_count
        call_count += 1

        # Determine which prompt is being called by content
        if "executive" in prompt.lower() or "executive brief" in prompt.lower():
            return MOCK_EXECUTIVE_SUMMARY
        elif "key analytical judgments" in prompt.lower() or "key_judgments" in prompt.lower():
            return MOCK_KEY_JUDGMENTS_JSON
        elif "alternative" in prompt.lower():
            return MOCK_ALT_HYPOTHESES_JSON
        elif "implications" in prompt.lower():
            return MOCK_IMPLICATIONS_JSON
        elif "source" in prompt.lower() and "assessment" in prompt.lower():
            return MOCK_SOURCE_ASSESSMENT
        else:
            return "Fallback response"

    return mock_call_llm


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


class TestSynthesize:
    """Full synthesize() method tests."""

    @pytest.mark.asyncio
    async def test_synthesize_returns_analysis_synthesis(
        self,
        synthesizer: Synthesizer,
        mock_snapshot: InvestigationSnapshot,
    ) -> None:
        """synthesize() returns AnalysisSynthesis with all fields."""
        with patch.object(synthesizer, "_call_llm", side_effect=_make_mock_call_llm()):
            result = await synthesizer.synthesize(mock_snapshot)

        assert isinstance(result, AnalysisSynthesis)
        assert result.investigation_id == "inv-test-synth"
        assert result.executive_summary != ""
        assert len(result.key_judgments) > 0
        assert result.overall_confidence is not None
        assert result.model_version == "gemini-1.5-pro"

    @pytest.mark.asyncio
    async def test_synthesize_executive_summary(
        self,
        synthesizer: Synthesizer,
        mock_snapshot: InvestigationSnapshot,
    ) -> None:
        """Executive summary is non-empty string."""
        with patch.object(synthesizer, "_call_llm", side_effect=_make_mock_call_llm()):
            result = await synthesizer.synthesize(mock_snapshot)

        assert isinstance(result.executive_summary, str)
        assert len(result.executive_summary) > 20
        assert "military" in result.executive_summary.lower()

    @pytest.mark.asyncio
    async def test_synthesize_key_judgments(
        self,
        synthesizer: Synthesizer,
        mock_snapshot: InvestigationSnapshot,
    ) -> None:
        """Key judgments list has items with valid confidence."""
        with patch.object(synthesizer, "_call_llm", side_effect=_make_mock_call_llm()):
            result = await synthesizer.synthesize(mock_snapshot)

        assert len(result.key_judgments) == 2
        for judgment in result.key_judgments:
            assert isinstance(judgment, KeyJudgment)
            assert judgment.confidence.level in ("low", "moderate", "high")
            assert 0.0 <= judgment.confidence.numeric <= 1.0
            assert len(judgment.judgment) > 0

    @pytest.mark.asyncio
    async def test_synthesize_alternative_hypotheses(
        self,
        synthesizer: Synthesizer,
        mock_snapshot: InvestigationSnapshot,
    ) -> None:
        """Alternative hypotheses generated for uncertain judgments."""
        with patch.object(synthesizer, "_call_llm", side_effect=_make_mock_call_llm()):
            result = await synthesizer.synthesize(mock_snapshot)

        # Should have alternatives since there's a moderate-confidence judgment
        assert len(result.alternative_hypotheses) > 0
        for hyp in result.alternative_hypotheses:
            assert hyp.likelihood in ("unlikely", "possible", "plausible")
            assert len(hyp.hypothesis) > 0

    @pytest.mark.asyncio
    async def test_synthesize_implications_and_forecasts(
        self,
        synthesizer: Synthesizer,
        mock_snapshot: InvestigationSnapshot,
    ) -> None:
        """Synthesis includes implications and forecasts."""
        with patch.object(synthesizer, "_call_llm", side_effect=_make_mock_call_llm()):
            result = await synthesizer.synthesize(mock_snapshot)

        assert len(result.implications) > 0
        assert len(result.forecasts) > 0

    @pytest.mark.asyncio
    async def test_synthesize_handles_llm_failure(
        self,
        synthesizer: Synthesizer,
        mock_snapshot: InvestigationSnapshot,
    ) -> None:
        """LLM failure produces fallback values, not exception."""
        async def failing_llm(prompt: str, structured: bool = False) -> str:
            raise RuntimeError("Gemini API unavailable")

        with patch.object(synthesizer, "_call_llm", side_effect=failing_llm):
            result = await synthesizer.synthesize(mock_snapshot)

        assert isinstance(result, AnalysisSynthesis)
        # Fallback executive summary
        assert "unavailable" in result.executive_summary.lower()
        # Empty lists for structured output
        assert result.key_judgments == []
        assert result.alternative_hypotheses == []
        # Low confidence when no judgments
        assert result.overall_confidence.level == "low"


class TestFactsContext:
    """_prepare_facts_context tests."""

    def test_prepare_facts_context(
        self,
        synthesizer: Synthesizer,
        mock_snapshot: InvestigationSnapshot,
    ) -> None:
        """_prepare_facts_context produces formatted string with fact IDs."""
        context = synthesizer._prepare_facts_context(mock_snapshot)

        assert "FACT-fact-001" in context
        assert "FACT-fact-003" in context
        assert "confidence:" in context
        assert "status:" in context

    def test_prepare_facts_context_empty(
        self,
        synthesizer: Synthesizer,
    ) -> None:
        """Empty snapshot produces fallback text."""
        empty = InvestigationSnapshot(investigation_id="empty")
        context = synthesizer._prepare_facts_context(empty)

        assert context == "No facts available."


class TestConfidenceComputation:
    """_compute_overall_confidence tests."""

    def test_compute_overall_confidence_high(
        self,
        synthesizer: Synthesizer,
    ) -> None:
        """High avg -> high level."""
        judgments = [
            KeyJudgment(
                judgment="Test",
                confidence=ConfidenceAssessment(
                    level="high", numeric=0.85, reasoning="test"
                ),
                reasoning="test",
            ),
            KeyJudgment(
                judgment="Test2",
                confidence=ConfidenceAssessment(
                    level="high", numeric=0.90, reasoning="test"
                ),
                reasoning="test",
            ),
        ]
        result = synthesizer._compute_overall_confidence(judgments)

        assert result.level == "high"
        assert result.numeric > 0.7

    def test_compute_overall_confidence_moderate(
        self,
        synthesizer: Synthesizer,
    ) -> None:
        """Moderate avg -> moderate level."""
        judgments = [
            KeyJudgment(
                judgment="Test",
                confidence=ConfidenceAssessment(
                    level="high", numeric=0.8, reasoning="test"
                ),
                reasoning="test",
            ),
            KeyJudgment(
                judgment="Test2",
                confidence=ConfidenceAssessment(
                    level="low", numeric=0.2, reasoning="test"
                ),
                reasoning="test",
            ),
        ]
        result = synthesizer._compute_overall_confidence(judgments)

        assert result.level == "moderate"
        assert 0.4 <= result.numeric <= 0.7

    def test_compute_overall_confidence_low(
        self,
        synthesizer: Synthesizer,
    ) -> None:
        """Low avg -> low level."""
        judgments = [
            KeyJudgment(
                judgment="Test",
                confidence=ConfidenceAssessment(
                    level="low", numeric=0.2, reasoning="test"
                ),
                reasoning="test",
            ),
            KeyJudgment(
                judgment="Test2",
                confidence=ConfidenceAssessment(
                    level="low", numeric=0.3, reasoning="test"
                ),
                reasoning="test",
            ),
        ]
        result = synthesizer._compute_overall_confidence(judgments)

        assert result.level == "low"
        assert result.numeric < 0.4

    def test_compute_overall_confidence_empty(
        self,
        synthesizer: Synthesizer,
    ) -> None:
        """No judgments -> low with 0.0."""
        result = synthesizer._compute_overall_confidence([])

        assert result.level == "low"
        assert result.numeric == 0.0


class TestParsing:
    """JSON parsing tests."""

    def test_parse_key_judgments_malformed_json(
        self,
        synthesizer: Synthesizer,
    ) -> None:
        """Malformed JSON returns empty list, logs warning."""
        result = synthesizer._parse_key_judgments("not valid json {{{")

        assert result == []

    def test_parse_key_judgments_valid(
        self,
        synthesizer: Synthesizer,
    ) -> None:
        """Valid JSON parses into KeyJudgment objects."""
        result = synthesizer._parse_key_judgments(MOCK_KEY_JUDGMENTS_JSON)

        assert len(result) == 2
        assert result[0].confidence.level == "high"
        assert result[0].confidence.numeric == 0.85
        assert "fact-001" in result[0].supporting_fact_ids

    def test_parse_alternative_hypotheses_malformed(
        self,
        synthesizer: Synthesizer,
    ) -> None:
        """Malformed JSON returns empty list."""
        result = synthesizer._parse_alternative_hypotheses("garbage")
        assert result == []

    def test_parse_alternative_hypotheses_valid(
        self,
        synthesizer: Synthesizer,
    ) -> None:
        """Valid JSON parses into AlternativeHypothesis objects."""
        result = synthesizer._parse_alternative_hypotheses(MOCK_ALT_HYPOTHESES_JSON)

        assert len(result) == 1
        assert result[0].likelihood == "possible"
