"""Schema package for fact extraction data structures.

This package provides Pydantic models for structured fact extraction output.
All models follow Phase 6 CONTEXT.md design decisions:
- Detail over compactness
- Separate fields for orthogonal concepts
- Full provenance chains
- Explicit metadata flags

Primary export: ExtractedFact (the main fact record schema)

Usage:
    from osint_system.data_management.schemas import ExtractedFact, Claim
    fact = ExtractedFact(claim=Claim(text="[E1:Putin] visited [E2:Beijing]"))
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

# Fact schemas (lazy import to avoid circular dependencies)
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
]
