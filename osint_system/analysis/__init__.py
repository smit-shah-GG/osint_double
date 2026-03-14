"""Analysis engine for intelligence report generation.

Provides typed output schemas, data aggregation, LLM synthesis, pattern
detection, and contradiction analysis for producing IC-style intelligence
products from verified facts.

Key exports:
- Schema models: AnalysisSynthesis, KeyJudgment, AlternativeHypothesis, etc.
- DataAggregator: Collects all investigation data into InvestigationSnapshot
- Synthesizer: LLM-powered synthesis orchestrator
- PatternDetector: Rule-based cross-fact pattern detection
- ContradictionAnalyzer: Rule-based contradiction identification
"""

from osint_system.analysis.contradiction_analyzer import ContradictionAnalyzer
from osint_system.analysis.data_aggregator import DataAggregator
from osint_system.analysis.pattern_detector import PatternDetector
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
from osint_system.analysis.synthesizer import Synthesizer

__all__ = [
    "AnalysisSynthesis",
    "ContradictionAnalyzer",
    "DataAggregator",
    "KeyJudgment",
    "AlternativeHypothesis",
    "ConfidenceAssessment",
    "ContradictionEntry",
    "InvestigationSnapshot",
    "PatternDetector",
    "SourceInventoryEntry",
    "Synthesizer",
    "TimelineEntry",
]
