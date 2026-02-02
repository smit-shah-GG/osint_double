"""Fact extraction schema - primary output format.

This module defines ExtractedFact, the core data structure for extracted facts.
Per Phase 6 CONTEXT.md: Facts are single subject-predicate-object assertions,
not maximally decomposed atoms.

Design principles (from CONTEXT.md):
- Detail over compactness: collapsing information is losing intelligence
- Separate confidence dimensions: extraction_confidence vs claim_clarity
- Full provenance chains: source attribution is intelligence
- Explicit metadata: flags rather than implicit assumptions

Hard requirements: fact_id, claim.text
Everything else optional but captured when available.
"""

import hashlib
import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

# CRITICAL: Import Entity and Provenance to wire fact_schema to dependencies
from osint_system.data_management.schemas.entity_schema import Entity, EntityCluster
from osint_system.data_management.schemas.provenance_schema import Provenance

# Schema version - increment on breaking changes
SCHEMA_VERSION = "1.0"


class Claim(BaseModel):
    """The assertion being made.

    Per CONTEXT.md: Facts are single assertions, the natural unit for verification.
    Denials are represented as the underlying claim with assertion_type="denial".

    Attributes:
        text: Claim with entity markers like [E1:Putin] visited [E2:Beijing].
        assertion_type: Nature of the assertion (statement, denial, quote, etc.).
        claim_type: Category of claim (event, state, relationship, prediction).
    """

    text: str = Field(..., description="Claim with entity markers like [E1:Putin]")
    assertion_type: Literal["statement", "denial", "claim", "prediction", "quote"] = (
        "statement"
    )
    claim_type: Literal["event", "state", "relationship", "prediction", "planned"] = (
        "event"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "text": "[E1:Putin] visited [E2:Beijing] in [T1:March 2024]",
                    "assertion_type": "statement",
                    "claim_type": "event",
                },
                {
                    "text": "[E1:Russia] involvement in [E2:the incident]",
                    "assertion_type": "denial",
                    "claim_type": "event",
                },
            ]
        }
    }


class TemporalMarker(BaseModel):
    """Temporal information with precision tracking.

    Per CONTEXT.md: Extract all temporal claims with explicit precision metadata.
    - explicit: stated in text ("March 2024")
    - inferred: from article date
    - unknown: unclear/ambiguous

    Attributes:
        id: Temporal ID (T1, T2, etc) for linking to claim text.
        value: ISO-ish value (2024-03, 2024-03-15, etc.).
        precision: Granularity of the temporal value.
        temporal_precision: Confidence in the temporal value.
    """

    id: str = Field(..., description="Temporal ID (T1, T2, etc)")
    value: str = Field(..., description="ISO-ish value: 2024-03, 2024-03-15, etc")
    precision: Literal["year", "month", "day", "time", "range"] = "day"
    temporal_precision: Literal["explicit", "inferred", "unknown"] = Field(
        ...,
        description="explicit=stated in text, inferred=from article date, unknown=unclear",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": "T1",
                    "value": "2024-03",
                    "precision": "month",
                    "temporal_precision": "explicit",
                }
            ]
        }
    }


class NumericValue(BaseModel):
    """Numerical claims with precision preservation.

    Per CONTEXT.md: Preserve original form AND add precision metadata.
    "thousands" becomes value_original="thousands", value_normalized=[1000,9999],
    numeric_precision="order_of_magnitude".

    Attributes:
        value_original: Original text (e.g., "thousands", "~50").
        value_normalized: [min, max] range if applicable.
        numeric_precision: How precise the numeric claim is.
    """

    value_original: str = Field(..., description="Original text: 'thousands', '~50'")
    value_normalized: Optional[list] = Field(
        None, description="[min, max] range if applicable"
    )
    numeric_precision: Literal["exact", "approximate", "order_of_magnitude"] = "exact"

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "value_original": "thousands",
                    "value_normalized": [1000, 9999],
                    "numeric_precision": "order_of_magnitude",
                },
                {
                    "value_original": "~50",
                    "value_normalized": [45, 55],
                    "numeric_precision": "approximate",
                },
            ]
        }
    }


class ExtractionTrace(BaseModel):
    """Detailed reasoning for debugging/audit.

    Per CONTEXT.md: Full extraction trace, not just scores.
    Enables debugging, audit, and prompt improvement.

    Attributes:
        parsing_notes: Notes on parsing complexity or issues.
        clarity_factors: Factors affecting claim_clarity score.
        entity_resolution: How entities were resolved.
    """

    parsing_notes: Optional[str] = None
    clarity_factors: list[str] = Field(default_factory=list)
    entity_resolution: Optional[str] = None


class QualityMetrics(BaseModel):
    """Separate dimensions per CONTEXT.md: extraction_confidence vs claim_clarity.

    These measure DIFFERENT things:
    - extraction_confidence: Did the LLM correctly parse this from the text? (process quality)
    - claim_clarity: Is the source text itself unambiguous? (input quality)

    A fact can be:
    - High extraction / High clarity: Clear text, correctly parsed
    - High extraction / Low clarity: Vague text ("sources suggest..."), but correctly captured as vague
    - Low extraction / High clarity: Complex sentence made parsing uncertain, but claim itself is precise

    Combining them destroys information Phase 7 needs.

    Attributes:
        extraction_confidence: 0.0-1.0, LLM's parsing accuracy.
        claim_clarity: 0.0-1.0, source text ambiguity.
        extraction_trace: Full reasoning for debugging/audit.
    """

    extraction_confidence: float = Field(
        ..., ge=0.0, le=1.0, description="LLM parsing accuracy"
    )
    claim_clarity: float = Field(
        ..., ge=0.0, le=1.0, description="Source text ambiguity"
    )
    extraction_trace: Optional[ExtractionTrace] = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "extraction_confidence": 0.92,
                    "claim_clarity": 0.88,
                    "extraction_trace": {
                        "parsing_notes": "Direct statement, clear structure",
                        "clarity_factors": [],
                        "entity_resolution": "Putin identified from proper noun",
                    },
                }
            ]
        }
    }


class ExtractionMetadata(BaseModel):
    """Metadata about extraction process.

    Attributes:
        extracted_at: UTC timestamp of extraction.
        model_version: LLM model used for extraction.
        extraction_type: explicit (stated in text) or inferred (obvious implication).
    """

    extracted_at: datetime = Field(default_factory=datetime.utcnow)
    model_version: str = "gemini-1.5-flash"
    extraction_type: Literal["explicit", "inferred"] = "explicit"


class FactRelationship(BaseModel):
    """Relationship hints to other facts.

    Per CONTEXT.md: Extract obvious supports/contradicts/temporal-sequence
    relationships between facts when evident in text. "However, officials
    disputed this" explicitly signals contradiction.

    Attributes:
        type: Relationship type (supports, contradicts, temporal_sequence, elaborates).
        target_fact_id: UUID of the related fact.
        confidence: Confidence in the relationship (0.0-1.0).
    """

    type: Literal["supports", "contradicts", "temporal_sequence", "elaborates"]
    target_fact_id: str
    confidence: float = Field(0.5, ge=0.0, le=1.0)


class ExtractedFact(BaseModel):
    """Complete fact record per Phase 6 CONTEXT.md schema.

    Only hard requirements: fact_id, claim.text
    Everything else optional but captured when available.

    Per CONTEXT.md design decisions:
    - UUID + content hash for dedup (UUIDs for storage, hash for exact-match)
    - Entities appear inline with markers AND as structured objects
    - Quality has separate extraction_confidence and claim_clarity
    - Full provenance chains with hop count AND source type
    - Schema version for forward compatibility

    Usage:
        fact = ExtractedFact(claim=Claim(text="[E1:Putin] visited Beijing"))
        print(fact.fact_id)  # auto-generated UUID
        print(fact.content_hash)  # auto-computed from claim.text

    Attributes:
        schema_version: Schema version for migration paths.
        fact_id: UUID for primary storage identity.
        content_hash: SHA256 of claim.text for exact-match dedup.
        claim: The assertion being made.
        entities: Structured entity objects linked to claim text markers.
        temporal: Temporal information if present.
        numeric: Numeric values if present.
        provenance: Full source attribution.
        quality: Extraction confidence and claim clarity.
        extraction: Process metadata.
        relationships: Links to related facts.
        variants: IDs of semantic duplicates (same claim, different sources).
    """

    schema_version: str = SCHEMA_VERSION
    fact_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    content_hash: str = Field("", description="SHA256 of claim.text for dedup")

    # Core content
    claim: Claim
    entities: list[Entity] = Field(default_factory=list)
    temporal: Optional[TemporalMarker] = None
    numeric: Optional[NumericValue] = None

    # Attribution
    provenance: Optional[Provenance] = None

    # Quality
    quality: Optional[QualityMetrics] = None

    # Process metadata
    extraction: ExtractionMetadata = Field(default_factory=ExtractionMetadata)

    # Relationships
    relationships: list[FactRelationship] = Field(default_factory=list)
    variants: list[str] = Field(
        default_factory=list, description="IDs of semantic duplicates"
    )

    @model_validator(mode="after")
    def compute_content_hash(self) -> "ExtractedFact":
        """Compute content hash from claim text if not provided."""
        if not self.content_hash:
            self.content_hash = hashlib.sha256(
                self.claim.text.encode("utf-8")
            ).hexdigest()
        return self

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "schema_version": "1.0",
                    "fact_id": "uuid-here",
                    "claim": {
                        "text": "[E1:Putin] visited [E2:Beijing] in [T1:March 2024]",
                        "assertion_type": "statement",
                        "claim_type": "event",
                    },
                    "entities": [
                        {
                            "id": "E1",
                            "text": "Putin",
                            "type": "PERSON",
                            "canonical": "Vladimir Putin",
                        }
                    ],
                }
            ]
        }
    }
