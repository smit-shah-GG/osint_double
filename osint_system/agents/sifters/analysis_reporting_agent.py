"""AnalysisReportingAgent: BaseSifter subclass for intelligence product generation.

Orchestrates the full analysis flow: LLM synthesis via Synthesizer,
rule-based pattern detection via PatternDetector, and contradiction
identification via ContradictionAnalyzer. Produces AnalysisSynthesis
objects ready for report rendering.

Satisfies the BaseSifter contract: sift() accepts a content dict and
returns a list of result dicts. Also provides a direct analyze() method
that bypasses the sift() content wrapping for pipeline use.

Usage:
    from osint_system.agents.sifters.analysis_reporting_agent import AnalysisReportingAgent

    agent = AnalysisReportingAgent()
    synthesis = await agent.analyze(snapshot)
    print(synthesis.executive_summary)
"""

from __future__ import annotations

from typing import Any, Optional

import structlog

from osint_system.agents.sifters.base_sifter import BaseSifter
from osint_system.analysis.contradiction_analyzer import ContradictionAnalyzer
from osint_system.analysis.pattern_detector import PatternDetector
from osint_system.analysis.schemas import (
    AnalysisSynthesis,
    InvestigationSnapshot,
)
from osint_system.analysis.synthesizer import Synthesizer
from osint_system.config.analysis_config import AnalysisConfig

logger = structlog.get_logger(__name__)


class AnalysisReportingAgent(BaseSifter):
    """Generates intelligence products from verified investigation data.

    Orchestrates:
    1. LLM synthesis (executive summary, key judgments, alt hypotheses)
    2. Rule-based pattern detection (recurring entities, temporal clusters)
    3. Contradiction identification (explicit, refuted, conflicting claims)

    All components are lazy-initialized on first use via property accessors,
    following the established agent pattern.

    Attributes:
        _config: AnalysisConfig for model and limit settings.
        _synthesizer: Lazy-initialized Synthesizer instance.
        _pattern_detector: Lazy-initialized PatternDetector instance.
        _contradiction_analyzer: Lazy-initialized ContradictionAnalyzer instance.
    """

    def __init__(
        self,
        name: str = "AnalysisReportingAgent",
        description: str = "Generates intelligence products from verified investigation data",
        config: Optional[AnalysisConfig] = None,
        synthesizer: Optional[Synthesizer] = None,
        pattern_detector: Optional[PatternDetector] = None,
        contradiction_analyzer: Optional[ContradictionAnalyzer] = None,
    ) -> None:
        """Initialize AnalysisReportingAgent.

        Args:
            name: Agent name for registration and logging.
            description: Agent description.
            config: AnalysisConfig (lazy-loaded from env if None).
            synthesizer: Pre-configured Synthesizer (lazy-initialized if None).
            pattern_detector: Pre-configured PatternDetector (lazy-initialized if None).
            contradiction_analyzer: Pre-configured ContradictionAnalyzer (lazy-initialized if None).
        """
        super().__init__(name=name, description=description)
        self._config = config
        self._synthesizer = synthesizer
        self._pattern_detector = pattern_detector
        self._contradiction_analyzer = contradiction_analyzer
        self._log = logger.bind(component="AnalysisReportingAgent")

    @property
    def config(self) -> AnalysisConfig:
        """Lazy-load AnalysisConfig from environment."""
        if self._config is None:
            self._config = AnalysisConfig.from_env()
        return self._config

    @property
    def synthesizer(self) -> Synthesizer:
        """Lazy-init Synthesizer with config."""
        if self._synthesizer is None:
            self._synthesizer = Synthesizer(config=self.config)
        return self._synthesizer

    @property
    def pattern_detector(self) -> PatternDetector:
        """Lazy-init PatternDetector (stateless)."""
        if self._pattern_detector is None:
            self._pattern_detector = PatternDetector()
        return self._pattern_detector

    @property
    def contradiction_analyzer(self) -> ContradictionAnalyzer:
        """Lazy-init ContradictionAnalyzer (stateless)."""
        if self._contradiction_analyzer is None:
            self._contradiction_analyzer = ContradictionAnalyzer()
        return self._contradiction_analyzer

    async def sift(self, content: dict) -> list[dict]:
        """Process content and produce structured analysis output.

        Implementation of BaseSifter.sift(). Expects content dict with
        a "snapshot" key containing either an InvestigationSnapshot object
        or a dict that can be parsed into one.

        Args:
            content: Dict with "snapshot" key.

        Returns:
            List containing a single AnalysisSynthesis dict.
        """
        raw_snapshot = content.get("snapshot")
        if raw_snapshot is None:
            self._log.error("sift_missing_snapshot")
            return []

        if isinstance(raw_snapshot, InvestigationSnapshot):
            snapshot = raw_snapshot
        elif isinstance(raw_snapshot, dict):
            snapshot = InvestigationSnapshot(**raw_snapshot)
        else:
            self._log.error(
                "sift_invalid_snapshot_type",
                snapshot_type=type(raw_snapshot).__name__,
            )
            return []

        synthesis = await self.analyze(snapshot)
        return [synthesis.model_dump(mode="json")]

    async def analyze(
        self,
        snapshot: InvestigationSnapshot,
    ) -> AnalysisSynthesis:
        """Run full analysis pipeline on an InvestigationSnapshot.

        Direct analysis method that bypasses sift() content wrapping.
        Called by AnalysisPipeline for event-driven and standalone use.

        Steps:
        1. Run LLM synthesis via Synthesizer
        2. Detect patterns via PatternDetector
        3. Find contradictions via ContradictionAnalyzer
        4. Merge contradictions into synthesis

        Args:
            snapshot: Pre-aggregated investigation data.

        Returns:
            Populated AnalysisSynthesis with contradictions merged.
        """
        self._log.info(
            "analysis_start",
            investigation_id=snapshot.investigation_id,
            fact_count=snapshot.fact_count,
        )

        # 1. LLM synthesis
        synthesis = await self.synthesizer.synthesize(snapshot)

        # 2. Pattern detection (non-LLM)
        patterns = self.pattern_detector.detect_patterns(snapshot)
        self._log.info(
            "patterns_detected",
            recurring_entities=len(patterns.get("recurring_entities", [])),
            temporal_clusters=len(patterns.get("temporal_clusters", [])),
            escalation_indicators=len(patterns.get("escalation_indicators", [])),
        )

        # 3. Contradiction analysis (non-LLM)
        contradictions = self.contradiction_analyzer.find_contradictions(snapshot)

        # 4. Merge contradictions into synthesis
        if contradictions:
            synthesis.contradictions = list(synthesis.contradictions) + contradictions

        self._log.info(
            "analysis_complete",
            investigation_id=snapshot.investigation_id,
            key_judgments=len(synthesis.key_judgments),
            contradictions=len(synthesis.contradictions),
            confidence_level=synthesis.overall_confidence.level,
        )

        return synthesis

    def get_capabilities(self) -> list[str]:
        """Return analysis agent capabilities.

        Returns:
            List of capability identifiers.
        """
        return ["analysis", "synthesis", "reporting", "pattern_detection"]
