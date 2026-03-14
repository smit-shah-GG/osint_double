"""Analysis pipeline: graph.ingested -> analysis -> report generation.

Follows the same lazy-init / event-driven pattern as VerificationPipeline
and GraphPipeline. Extends the pipeline chain:
    classification -> verification -> graph -> analysis

Provides both event-driven (on_graph_ingested) and standalone (run_analysis)
operation modes. Optionally auto-generates Markdown reports via
ReportGenerator and saves to ReportStore when both are provided.

Usage (standalone):
    pipeline = AnalysisPipeline(fact_store=fs, classification_store=cs, verification_store=vs)
    synthesis = await pipeline.run_analysis("inv-123")

Usage (event-driven):
    pipeline = AnalysisPipeline(...)
    pipeline.register_with_pipeline(investigation_pipeline)
    # Triggered automatically on graph.ingested events
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

import structlog

from osint_system.analysis.data_aggregator import DataAggregator
from osint_system.analysis.schemas import AnalysisSynthesis
from osint_system.config.analysis_config import AnalysisConfig
from osint_system.data_management.classification_store import ClassificationStore
from osint_system.data_management.fact_store import FactStore
from osint_system.data_management.verification_store import VerificationStore

if TYPE_CHECKING:
    from osint_system.agents.sifters.analysis_reporting_agent import (
        AnalysisReportingAgent,
    )
    from osint_system.pipeline.graph_pipeline import GraphPipeline

logger = structlog.get_logger(__name__)


class AnalysisPipeline:
    """Orchestrates graph.ingested -> analysis -> report generation.

    Lazy-initializes DataAggregator and AnalysisReportingAgent from shared
    stores. Optionally auto-generates Markdown reports and saves them via
    report_generator and report_store (both typed as Any to avoid hard
    import dependency on the reporting package, which may be built in a
    later plan).

    Attributes:
        _analysis_agent: Lazy-initialized AnalysisReportingAgent.
        _data_aggregator: Lazy-initialized DataAggregator.
        _config: AnalysisConfig for auto-generation toggle and model settings.
    """

    def __init__(
        self,
        analysis_agent: Optional[AnalysisReportingAgent] = None,
        data_aggregator: Optional[DataAggregator] = None,
        fact_store: Optional[FactStore] = None,
        classification_store: Optional[ClassificationStore] = None,
        verification_store: Optional[VerificationStore] = None,
        graph_pipeline: Optional[Any] = None,
        report_generator: Any | None = None,
        report_store: Any | None = None,
        config: Optional[AnalysisConfig] = None,
    ) -> None:
        """Initialize AnalysisPipeline.

        Args:
            analysis_agent: Pre-configured agent. Lazy-initialized if None.
            data_aggregator: Pre-configured aggregator. Lazy-initialized if None.
            fact_store: Shared fact store for aggregation.
            classification_store: Shared classification store.
            verification_store: Shared verification store.
            graph_pipeline: Optional GraphPipeline for graph queries.
            report_generator: Optional ReportGenerator for auto-report generation.
                Typed as Any to avoid hard import dependency on reporting package.
            report_store: Optional ReportStore for saving generated reports.
                Typed as Any for the same reason.
            config: Analysis configuration. Uses from_env() if None.
        """
        self._analysis_agent = analysis_agent
        self._data_aggregator = data_aggregator
        self._fact_store = fact_store
        self._classification_store = classification_store
        self._verification_store = verification_store
        self._graph_pipeline = graph_pipeline
        self._report_generator = report_generator
        self._report_store = report_store
        self._config = config
        self._log = logger.bind(component="AnalysisPipeline")

    @property
    def config(self) -> AnalysisConfig:
        """Lazy-load AnalysisConfig from environment."""
        if self._config is None:
            self._config = AnalysisConfig.from_env()
        return self._config

    def _get_aggregator(self) -> DataAggregator:
        """Lazy-init DataAggregator with shared stores.

        Returns:
            Configured DataAggregator.
        """
        if self._data_aggregator is not None:
            return self._data_aggregator

        self._data_aggregator = DataAggregator(
            fact_store=self._fact_store or FactStore(),
            classification_store=self._classification_store or ClassificationStore(),
            verification_store=self._verification_store or VerificationStore(),
            graph_pipeline=self._graph_pipeline,
        )
        return self._data_aggregator

    def _get_agent(self) -> AnalysisReportingAgent:
        """Lazy-init AnalysisReportingAgent with config.

        Uses runtime import to avoid cascading Settings singleton
        through the agents package init (same pattern as DataAggregator
        TYPE_CHECKING import for GraphPipeline).

        Returns:
            Configured AnalysisReportingAgent.
        """
        if self._analysis_agent is not None:
            return self._analysis_agent

        from osint_system.agents.sifters.analysis_reporting_agent import (
            AnalysisReportingAgent,
        )

        self._analysis_agent = AnalysisReportingAgent(config=self.config)
        return self._analysis_agent

    async def on_graph_ingested(
        self,
        investigation_id: str,
        ingestion_stats: dict[str, Any],
    ) -> dict[str, Any]:
        """Event handler for graph.ingested events.

        Auto-triggers analysis if config.auto_generate_on_complete is True.
        After synthesis, optionally generates a Markdown report and saves
        it to the report store.

        Args:
            investigation_id: Investigation to analyze.
            ingestion_stats: Graph ingestion stats from GraphPipeline.

        Returns:
            Analysis summary dict with key metrics.
        """
        if not self.config.auto_generate_on_complete:
            self._log.info(
                "auto_generate_disabled",
                investigation_id=investigation_id,
            )
            return {
                "investigation_id": investigation_id,
                "skipped": "auto_generate_on_complete is False",
            }

        self._log.info(
            "analysis_triggered",
            investigation_id=investigation_id,
            ingestion_stats=ingestion_stats,
        )

        synthesis = await self._run_full_analysis(investigation_id)

        return self._build_summary(synthesis)

    async def run_analysis(
        self,
        investigation_id: str,
    ) -> AnalysisSynthesis:
        """Standalone mode: run analysis for an investigation.

        Aggregates data, runs synthesis, and optionally generates and
        saves a Markdown report.

        Args:
            investigation_id: Investigation to analyze.

        Returns:
            Populated AnalysisSynthesis.
        """
        self._log.info(
            "standalone_analysis",
            investigation_id=investigation_id,
        )

        return await self._run_full_analysis(investigation_id)

    async def _run_full_analysis(
        self,
        investigation_id: str,
    ) -> AnalysisSynthesis:
        """Core analysis flow shared by event-driven and standalone modes.

        1. Aggregate data from stores into InvestigationSnapshot
        2. Run analysis via AnalysisReportingAgent
        3. Auto-generate report if report_generator and report_store available

        Args:
            investigation_id: Investigation to analyze.

        Returns:
            Populated AnalysisSynthesis.
        """
        # 1. Aggregate
        aggregator = self._get_aggregator()
        snapshot = await aggregator.aggregate(investigation_id)

        # 2. Analyze
        agent = self._get_agent()
        synthesis = await agent.analyze(snapshot)

        # 3. Auto-generate report (if both generator and store are provided)
        if self._report_generator is not None and self._report_store is not None:
            try:
                markdown = self._report_generator.generate_markdown(synthesis)
                await self._report_store.save_report(
                    investigation_id=investigation_id,
                    markdown_content=markdown,
                    synthesis=synthesis,
                )
                self._log.info(
                    "report_auto_generated",
                    investigation_id=investigation_id,
                )
            except Exception as exc:
                self._log.error(
                    "report_generation_failed",
                    investigation_id=investigation_id,
                    error=str(exc),
                )

        self._log.info(
            "analysis_complete",
            investigation_id=investigation_id,
            key_judgments=len(synthesis.key_judgments),
            contradictions=len(synthesis.contradictions),
            confidence_level=synthesis.overall_confidence.level,
        )

        return synthesis

    def register_with_pipeline(
        self,
        investigation_pipeline: Any,
    ) -> None:
        """Register as handler for graph.ingested events.

        Extends the pipeline chain:
            classification -> verification -> graph -> analysis

        Args:
            investigation_pipeline: Pipeline with on_event method.
        """
        if hasattr(investigation_pipeline, "on_event"):
            investigation_pipeline.on_event(
                "graph.ingested",
                self.on_graph_ingested,
            )
            self._log.info("analysis_pipeline_registered")
        else:
            self._log.warning(
                "pipeline_registration_failed",
                msg="Investigation pipeline does not support on_event",
            )

    @staticmethod
    def _build_summary(synthesis: AnalysisSynthesis) -> dict[str, Any]:
        """Build a summary dict from AnalysisSynthesis for event response.

        Args:
            synthesis: Completed analysis synthesis.

        Returns:
            Summary dict with key metrics.
        """
        return {
            "investigation_id": synthesis.investigation_id,
            "key_judgments_count": len(synthesis.key_judgments),
            "alternative_hypotheses_count": len(synthesis.alternative_hypotheses),
            "contradictions_count": len(synthesis.contradictions),
            "overall_confidence_level": synthesis.overall_confidence.level,
            "overall_confidence_numeric": synthesis.overall_confidence.numeric,
            "model_version": synthesis.model_version,
        }
