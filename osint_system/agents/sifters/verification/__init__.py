"""Verification submodule for resolving dubious facts.

Phase 8: Verification Loop - Processes dubious facts from Phase 7's
classification system through targeted searches, evidence aggregation,
and re-classification.

Core workflow:
1. Priority queue provides dubious facts ordered by impact x fixability
2. Species-specialized queries target specific doubt types (PHANTOM/FOG/ANOMALY)
3. Evidence aggregation with authority-weighted corroboration
4. Re-classification to CONFIRMED/REFUTED/UNVERIFIABLE/SUPERSEDED

Schemas in this module define the data structures consumed by:
- VerificationAgent (orchestrates verification loop)
- QueryGenerator (species-specialized query construction)
- EvidenceAggregator (corroboration and authority weighting)
- Reclassifier (status transitions and confidence updates)
"""

from osint_system.agents.sifters.verification.evidence_aggregator import EvidenceAggregator
from osint_system.agents.sifters.verification.query_generator import QueryGenerator
from osint_system.agents.sifters.verification.reclassifier import Reclassifier
from osint_system.agents.sifters.verification.schemas import (
    VerificationStatus,
    EvidenceItem,
    VerificationQuery,
    EvidenceEvaluation,
    VerificationResult,
)
from osint_system.agents.sifters.verification.search_executor import SearchExecutor
from osint_system.agents.sifters.verification.verification_agent import VerificationAgent

__all__ = [
    "EvidenceAggregator",
    "QueryGenerator",
    "Reclassifier",
    "SearchExecutor",
    "VerificationAgent",
    "VerificationStatus",
    "EvidenceItem",
    "VerificationQuery",
    "EvidenceEvaluation",
    "VerificationResult",
]
