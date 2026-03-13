"""Pipeline orchestration for automatic phase-to-phase data flow.

Provides automatic triggering between system phases:
- VerificationPipeline: classification.complete -> verification.start
- GraphPipeline: verification.complete -> graph ingestion

Full pipeline chain:
    classification.complete -> verification -> verification.complete -> graph ingestion
"""

from osint_system.pipeline.graph_pipeline import GraphPipeline
from osint_system.pipeline.verification_pipeline import VerificationPipeline

__all__ = ["GraphPipeline", "VerificationPipeline"]
