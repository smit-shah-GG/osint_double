"""Verification domain schemas for Phase 8 verification loop.

Re-exports core verification schemas from the data layer
(data_management.schemas.verification_schema) for convenient access
from the agent layer.

The canonical definitions live in data_management/schemas/verification_schema.py
to avoid circular imports between the agent and data layers. This module
provides the import path specified in the plan:

    from osint_system.agents.sifters.verification.schemas import (
        VerificationStatus, VerificationResult, EvidenceItem,
        VerificationQuery, EvidenceEvaluation,
    )

All schemas are re-exported without modification.
"""

from osint_system.data_management.schemas.verification_schema import (
    VerificationStatus,
    EvidenceItem,
    VerificationQuery,
    EvidenceEvaluation,
    VerificationResult,
    VerificationResultRecord,
)

# Re-export DubiousFlag for convenient co-located imports
from osint_system.data_management.schemas.classification_schema import DubiousFlag

__all__ = [
    "VerificationStatus",
    "EvidenceItem",
    "VerificationQuery",
    "EvidenceEvaluation",
    "VerificationResult",
    "VerificationResultRecord",
    "DubiousFlag",
]
