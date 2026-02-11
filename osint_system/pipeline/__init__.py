"""Pipeline orchestration for automatic phase-to-phase data flow.

Provides automatic triggering between system phases:
- VerificationPipeline: classification.complete → verification.start
"""

from osint_system.pipeline.verification_pipeline import VerificationPipeline

__all__ = ["VerificationPipeline"]
