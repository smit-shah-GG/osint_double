"""Analysis engine for intelligence report generation.

Provides typed output schemas, data aggregation, and synthesis orchestration
for producing IC-style intelligence products from verified facts.

Key exports:
- Schema models: AnalysisSynthesis, KeyJudgment, AlternativeHypothesis, etc.
- DataAggregator: Collects all investigation data into InvestigationSnapshot
"""

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

__all__ = [
    "AnalysisSynthesis",
    "KeyJudgment",
    "AlternativeHypothesis",
    "ConfidenceAssessment",
    "ContradictionEntry",
    "InvestigationSnapshot",
    "SourceInventoryEntry",
    "TimelineEntry",
]
