"""Pipeline orchestration for automatic phase-to-phase data flow.

Provides automatic triggering between system phases:
- VerificationPipeline: classification.complete -> verification.start
- GraphPipeline: verification.complete -> graph ingestion
- AnalysisPipeline: graph.ingested -> analysis -> report generation

Full pipeline chain:
    classification.complete -> verification -> verification.complete
    -> graph ingestion -> graph.ingested -> analysis -> report
"""

from osint_system.pipeline.analysis_pipeline import AnalysisPipeline
from osint_system.pipeline.graph_pipeline import GraphPipeline
from osint_system.pipeline.verification_pipeline import VerificationPipeline

__all__ = ["AnalysisPipeline", "GraphPipeline", "VerificationPipeline"]
