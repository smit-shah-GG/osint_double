"""Integration tests for AnalysisPipeline.

Validates:
- run_analysis returns AnalysisSynthesis
- Returned synthesis has correct investigation_id
- Synthesis includes key_judgments list
- on_graph_ingested triggers analysis
- Lazy initialization of pipeline components
- register_with_pipeline calls on_event with graph.ingested
- Pipeline importable from osint_system.pipeline
- Auto-generates report when report_generator and report_store provided
- Skips report without report_generator
- GraphPipeline emits graph.ingested event via MessageBus
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from osint_system.analysis.schemas import AnalysisSynthesis, InvestigationSnapshot
from osint_system.config.analysis_config import AnalysisConfig
from osint_system.data_management.classification_store import ClassificationStore
from osint_system.data_management.fact_store import FactStore
from osint_system.data_management.verification_store import VerificationStore
from osint_system.data_management.schemas.classification_schema import (
    FactClassification,
    ImpactTier,
)
from osint_system.data_management.schemas.entity_schema import Entity, EntityType
from osint_system.data_management.schemas.fact_schema import (
    Claim,
    ExtractedFact,
    QualityMetrics,
)
from osint_system.data_management.schemas.provenance_schema import (
    Provenance,
    SourceType,
)
from osint_system.data_management.schemas.verification_schema import (
    VerificationResult,
    VerificationStatus,
)
from osint_system.pipeline.analysis_pipeline import AnalysisPipeline


# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

INV_ID = "inv-analysis-test"

MOCK_EXECUTIVE_SUMMARY = (
    "We assess with moderate confidence that the investigation reveals "
    "significant geopolitical activity in the target region."
)

MOCK_KEY_JUDGMENTS_JSON = json.dumps({
    "key_judgments": [
        {
            "judgment": "We assess with high confidence that military escalation is underway",
            "confidence_level": "high",
            "confidence_numeric": 0.85,
            "confidence_reasoning": "Multiple sources confirm",
            "supporting_fact_ids": ["fact-a1"],
            "reasoning": "Troop movements confirmed by wire services",
        },
    ]
})

MOCK_ALT_HYPOTHESES_JSON = json.dumps({"alternative_hypotheses": []})

MOCK_IMPLICATIONS_JSON = json.dumps({
    "implications": ["Risk of escalation"],
    "forecasts": ["Continued tensions through Q2"],
})

MOCK_SOURCE_ASSESSMENT = "Source base is predominantly wire services."


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_fact(fact_id: str, claim_text: str) -> ExtractedFact:
    return ExtractedFact(
        fact_id=fact_id,
        claim=Claim(text=claim_text, assertion_type="statement", claim_type="event"),
        entities=[
            Entity(id="E1", text="Putin", type=EntityType.PERSON, canonical="Vladimir Putin"),
        ],
        provenance=Provenance(
            source_id=f"src-{fact_id}",
            quote=claim_text[:30],
            offsets={"start": 0, "end": len(claim_text)},
            source_type=SourceType.WIRE_SERVICE,
            hop_count=1,
        ),
        quality=QualityMetrics(extraction_confidence=0.9, claim_clarity=0.85),
    )


async def _mock_call_llm(prompt: str, structured: bool = False) -> str:
    """Return canned LLM responses based on prompt content."""
    if "executive" in prompt.lower():
        return MOCK_EXECUTIVE_SUMMARY
    elif "key analytical judgments" in prompt.lower() or "key_judgments" in prompt.lower():
        return MOCK_KEY_JUDGMENTS_JSON
    elif "alternative" in prompt.lower():
        return MOCK_ALT_HYPOTHESES_JSON
    elif "implications" in prompt.lower():
        return MOCK_IMPLICATIONS_JSON
    elif "source" in prompt.lower() and "assessment" in prompt.lower():
        return MOCK_SOURCE_ASSESSMENT
    return "Fallback"


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest_asyncio.fixture
async def populated_stores() -> tuple[FactStore, ClassificationStore, VerificationStore]:
    """Stores populated with test data for an investigation."""
    fs = FactStore()
    cs = ClassificationStore()
    vs = VerificationStore()

    facts = [
        _make_fact("fact-a1", "[E1:Putin] deployed forces to eastern region"),
        _make_fact("fact-a2", "[E1:Putin] met with defense officials"),
        _make_fact("fact-a3", "[E1:NATO] issued statement on security"),
    ]

    await fs.save_facts(INV_ID, [f.model_dump(mode="json") for f in facts])

    for fact in facts:
        await cs.save_classification(
            FactClassification(
                fact_id=fact.fact_id,
                investigation_id=INV_ID,
                impact_tier=ImpactTier.CRITICAL,
                dubious_flags=[],
            )
        )
        await vs.save_result(
            VerificationResult(
                fact_id=fact.fact_id,
                investigation_id=INV_ID,
                status=VerificationStatus.CONFIRMED,
                original_confidence=0.5,
                confidence_boost=0.3,
                final_confidence=0.8,
                reasoning=f"Confirmed for {fact.fact_id}",
                query_attempts=1,
                queries_used=[f"query-{fact.fact_id}"],
            )
        )

    return fs, cs, vs


@pytest.fixture()
def config() -> AnalysisConfig:
    return AnalysisConfig()


@pytest_asyncio.fixture
async def analysis_pipeline(
    populated_stores: tuple[FactStore, ClassificationStore, VerificationStore],
    config: AnalysisConfig,
) -> AnalysisPipeline:
    """AnalysisPipeline with populated stores and mocked Synthesizer."""
    fs, cs, vs = populated_stores
    return AnalysisPipeline(
        fact_store=fs,
        classification_store=cs,
        verification_store=vs,
        config=config,
    )


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


class TestRunAnalysis:
    """run_analysis tests."""

    @pytest.mark.asyncio
    async def test_run_analysis_returns_synthesis(
        self,
        analysis_pipeline: AnalysisPipeline,
    ) -> None:
        """run_analysis returns AnalysisSynthesis."""
        agent = analysis_pipeline._get_agent()
        with patch.object(agent.synthesizer, "_call_llm", side_effect=_mock_call_llm):
            result = await analysis_pipeline.run_analysis(INV_ID)

        assert isinstance(result, AnalysisSynthesis)

    @pytest.mark.asyncio
    async def test_run_analysis_has_investigation_id(
        self,
        analysis_pipeline: AnalysisPipeline,
    ) -> None:
        """Returned synthesis has correct investigation_id."""
        agent = analysis_pipeline._get_agent()
        with patch.object(agent.synthesizer, "_call_llm", side_effect=_mock_call_llm):
            result = await analysis_pipeline.run_analysis(INV_ID)

        assert result.investigation_id == INV_ID

    @pytest.mark.asyncio
    async def test_run_analysis_has_key_judgments(
        self,
        analysis_pipeline: AnalysisPipeline,
    ) -> None:
        """Synthesis includes key_judgments list."""
        agent = analysis_pipeline._get_agent()
        with patch.object(agent.synthesizer, "_call_llm", side_effect=_mock_call_llm):
            result = await analysis_pipeline.run_analysis(INV_ID)

        assert isinstance(result.key_judgments, list)
        assert len(result.key_judgments) >= 1


class TestEventHandler:
    """on_graph_ingested event handler tests."""

    @pytest.mark.asyncio
    async def test_on_graph_ingested_triggers_analysis(
        self,
        analysis_pipeline: AnalysisPipeline,
    ) -> None:
        """on_graph_ingested triggers analysis and returns summary dict."""
        agent = analysis_pipeline._get_agent()
        with patch.object(agent.synthesizer, "_call_llm", side_effect=_mock_call_llm):
            result = await analysis_pipeline.on_graph_ingested(
                INV_ID,
                {"facts_ingested": 3, "nodes_merged": 5},
            )

        assert result["investigation_id"] == INV_ID
        assert "key_judgments_count" in result
        assert result["key_judgments_count"] >= 1


class TestLazyInit:
    """Lazy initialization tests."""

    @pytest.mark.asyncio
    async def test_pipeline_lazy_init(self) -> None:
        """Pipeline with no args lazy-inits components without error."""
        pipeline = AnalysisPipeline()
        agent = pipeline._get_agent()

        # Mock the synthesizer's LLM so we don't need real API
        with patch.object(agent.synthesizer, "_call_llm", side_effect=_mock_call_llm):
            # Empty stores -> synthesis with empty data
            result = await pipeline.run_analysis("nonexistent-inv")

        assert isinstance(result, AnalysisSynthesis)
        assert result.investigation_id == "nonexistent-inv"


class TestPipelineRegistration:
    """register_with_pipeline tests."""

    def test_register_with_pipeline(self) -> None:
        """register_with_pipeline calls on_event with graph.ingested."""
        pipeline = AnalysisPipeline()
        mock_inv_pipeline = MagicMock()
        mock_inv_pipeline.on_event = MagicMock()

        pipeline.register_with_pipeline(mock_inv_pipeline)

        mock_inv_pipeline.on_event.assert_called_once_with(
            "graph.ingested",
            pipeline.on_graph_ingested,
        )


class TestImportability:
    """Import tests."""

    def test_pipeline_importable(self) -> None:
        """AnalysisPipeline importable from osint_system.pipeline."""
        from osint_system.pipeline import AnalysisPipeline as AP
        assert AP is AnalysisPipeline


class TestReportGeneration:
    """Auto-report generation tests."""

    @pytest.mark.asyncio
    async def test_run_analysis_auto_generates_report(
        self,
        populated_stores: tuple[FactStore, ClassificationStore, VerificationStore],
        config: AnalysisConfig,
    ) -> None:
        """report_generator and report_store present -> report auto-generated."""
        fs, cs, vs = populated_stores
        mock_generator = MagicMock()
        mock_generator.generate_markdown = MagicMock(return_value="# Report\n\nContent")
        mock_store = AsyncMock()

        pipeline = AnalysisPipeline(
            fact_store=fs,
            classification_store=cs,
            verification_store=vs,
            config=config,
            report_generator=mock_generator,
            report_store=mock_store,
        )

        agent = pipeline._get_agent()
        with patch.object(agent.synthesizer, "_call_llm", side_effect=_mock_call_llm):
            await pipeline.run_analysis(INV_ID)

        mock_generator.generate_markdown.assert_called_once()
        mock_store.save_report.assert_called_once()
        call_kwargs = mock_store.save_report.call_args
        assert call_kwargs.kwargs["investigation_id"] == INV_ID

    @pytest.mark.asyncio
    async def test_run_analysis_skips_report_without_generator(
        self,
        populated_stores: tuple[FactStore, ClassificationStore, VerificationStore],
        config: AnalysisConfig,
    ) -> None:
        """No report_generator -> completes without error."""
        fs, cs, vs = populated_stores

        pipeline = AnalysisPipeline(
            fact_store=fs,
            classification_store=cs,
            verification_store=vs,
            config=config,
            # No report_generator or report_store
        )

        agent = pipeline._get_agent()
        with patch.object(agent.synthesizer, "_call_llm", side_effect=_mock_call_llm):
            result = await pipeline.run_analysis(INV_ID)

        # Should complete without error
        assert isinstance(result, AnalysisSynthesis)


class TestGraphPipelineEventEmission:
    """Test that GraphPipeline emits graph.ingested event."""

    @pytest.mark.asyncio
    async def test_graph_pipeline_emits_event(self) -> None:
        """GraphPipeline with mock message_bus publishes graph.ingested."""
        from osint_system.pipeline.graph_pipeline import GraphPipeline
        from osint_system.config.graph_config import GraphConfig
        from osint_system.data_management.graph.networkx_adapter import NetworkXAdapter
        from osint_system.data_management.schemas.fact_schema import Claim, ExtractedFact, QualityMetrics
        from osint_system.data_management.schemas.provenance_schema import Provenance, SourceType
        from osint_system.data_management.schemas.entity_schema import Entity, EntityType
        from osint_system.data_management.schemas.verification_schema import VerificationResult, VerificationStatus
        from osint_system.data_management.schemas.classification_schema import FactClassification, ImpactTier

        # Set up stores with one fact
        fs = FactStore()
        vs = VerificationStore()
        cs = ClassificationStore()

        fact = ExtractedFact(
            fact_id="fact-emit-1",
            claim=Claim(text="[E1:Putin] visited Beijing", assertion_type="statement", claim_type="event"),
            entities=[Entity(id="E1", text="Putin", type=EntityType.PERSON, canonical="Vladimir Putin")],
            provenance=Provenance(source_id="src-1", quote="Putin visited", offsets={"start": 0, "end": 10}, source_type=SourceType.WIRE_SERVICE, hop_count=1),
            quality=QualityMetrics(extraction_confidence=0.9, claim_clarity=0.85),
        )
        await fs.save_facts(INV_ID, [fact.model_dump(mode="json")])
        await vs.save_result(VerificationResult(
            fact_id="fact-emit-1", investigation_id=INV_ID,
            status=VerificationStatus.CONFIRMED, original_confidence=0.5,
            confidence_boost=0.3, final_confidence=0.8, reasoning="test",
            query_attempts=1, queries_used=["q1"],
        ))
        await cs.save_classification(FactClassification(
            fact_id="fact-emit-1", investigation_id=INV_ID,
            impact_tier=ImpactTier.CRITICAL, dubious_flags=[],
        ))

        adapter = NetworkXAdapter()
        await adapter.initialize()
        config = GraphConfig(use_networkx_fallback=True, llm_relationship_extraction=False)

        mock_bus = AsyncMock()

        pipeline = GraphPipeline(
            adapter=adapter, fact_store=fs, verification_store=vs,
            classification_store=cs, config=config,
        )
        pipeline.set_message_bus(mock_bus)

        await pipeline.on_verification_complete(INV_ID, {"total_verified": 1})

        mock_bus.publish.assert_called_once()
        call_args = mock_bus.publish.call_args
        assert call_args[0][0] == "graph.ingested"
        assert call_args[0][1]["investigation_id"] == INV_ID
