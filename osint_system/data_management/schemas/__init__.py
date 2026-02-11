"""Schema package for fact extraction, classification, and verification data structures.

This package provides Pydantic models for structured fact extraction, classification,
and verification. All models follow Phase 6/7/8 CONTEXT.md design decisions:
- Detail over compactness
- Separate fields for orthogonal concepts
- Full provenance chains
- Explicit metadata flags
- Classifications separate from facts (facts immutable, classifications mutable)
- Verification results with evidence trails and origin flag preservation

Primary exports:
- ExtractedFact: The main fact record schema (Phase 6)
- FactClassification: Classification record for facts (Phase 7)
- VerificationResultRecord: Verification result storage schema (Phase 8)

Usage:
    from osint_system.data_management.schemas import ExtractedFact, Claim
    fact = ExtractedFact(claim=Claim(text="[E1:Putin] visited [E2:Beijing]"))

    from osint_system.data_management.schemas import FactClassification, ImpactTier
    classification = FactClassification(fact_id=fact.fact_id, investigation_id="inv-1")

    from osint_system.data_management.schemas import VerificationResultRecord, VerificationStatus
    record = VerificationResultRecord.from_result(verification_result)
"""

# Entity schemas
from osint_system.data_management.schemas.entity_schema import (
    Entity,
    EntityType,
    AnonymousSource,
    EntityCluster,
)

# Provenance schemas
from osint_system.data_management.schemas.provenance_schema import (
    Provenance,
    AttributionHop,
    SourceType,
    SourceClassification,
)

# Fact schemas
from osint_system.data_management.schemas.fact_schema import (
    ExtractedFact,
    Claim,
    TemporalMarker,
    NumericValue,
    QualityMetrics,
    ExtractionMetadata,
    ExtractionTrace,
    FactRelationship,
    SCHEMA_VERSION,
)

# Classification schemas (Phase 7)
from osint_system.data_management.schemas.classification_schema import (
    FactClassification,
    ImpactTier,
    DubiousFlag,
    CredibilityBreakdown,
    ClassificationReasoning,
    ClassificationHistory,
)

# Verification schemas (Phase 8)
# All verification types defined in verification_schema.py (data layer)
# to avoid circular imports with agent layer
from osint_system.data_management.schemas.verification_schema import (
    VerificationStatus,
    VerificationResult,
    EvidenceItem,
    VerificationQuery,
    EvidenceEvaluation,
    VerificationResultRecord,
)

__all__ = [
    # Entity
    "Entity",
    "EntityType",
    "AnonymousSource",
    "EntityCluster",
    # Provenance
    "Provenance",
    "AttributionHop",
    "SourceType",
    "SourceClassification",
    # Fact
    "ExtractedFact",
    "Claim",
    "TemporalMarker",
    "NumericValue",
    "QualityMetrics",
    "ExtractionMetadata",
    "ExtractionTrace",
    "FactRelationship",
    "SCHEMA_VERSION",
    # Classification (Phase 7)
    "FactClassification",
    "ImpactTier",
    "DubiousFlag",
    "CredibilityBreakdown",
    "ClassificationReasoning",
    "ClassificationHistory",
    # Verification (Phase 8)
    "VerificationResultRecord",
    "VerificationStatus",
    "VerificationResult",
    "EvidenceItem",
    "VerificationQuery",
    "EvidenceEvaluation",
]
