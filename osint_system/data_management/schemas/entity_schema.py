"""Entity schemas for fact extraction.

Defines entity models for PERSON, ORGANIZATION, LOCATION, anonymous sources,
and entity clustering without forced resolution per Phase 6 CONTEXT.md decisions.

Design principle: Detail over compactness. Entity mentions contain intelligence
value even without explicit claims. Co-occurrence patterns inform analysis.
"""

from enum import Enum
from typing import Optional, Literal

from pydantic import BaseModel, Field


class EntityType(str, Enum):
    """Entity type classification.

    Standard NER types plus ANONYMOUS_SOURCE for structured representation
    of anonymous sources with available metadata.
    """

    PERSON = "PERSON"
    ORGANIZATION = "ORGANIZATION"
    LOCATION = "LOCATION"
    EVENT = "EVENT"
    DATE = "DATE"
    ANONYMOUS_SOURCE = "ANONYMOUS_SOURCE"


class Entity(BaseModel):
    """Structured entity extracted from text.

    Entities appear in claim text with markers (e.g., [E1:Putin]) AND as
    separate structured objects with IDs. This dual representation enables:
    - Inline markers show entity positions in text
    - Structured objects enable typed reasoning

    Attributes:
        id: Entity ID (E1, E2, etc) for linking to claim text markers.
        text: Original text span as it appears in source.
        type: Entity type classification.
        canonical: Normalized form (e.g., "Vladimir Putin" for "Putin").
            Geographic normalization uses UN/ISO standards (Kyiv not Kiev).
        cluster_id: ID for entity clustering without forced resolution.
            Groups likely-same entities (Putin, Russian President) without
            forcing premature resolution.
    """

    id: str = Field(..., description="Entity ID (E1, E2, etc) for linking to claim text")
    text: str = Field(..., description="Original text span")
    type: EntityType
    canonical: Optional[str] = Field(
        None,
        description="Normalized form (e.g., 'Vladimir Putin', 'Beijing, China')",
    )
    cluster_id: Optional[str] = Field(
        None, description="ID for entity clustering without forced resolution"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": "E1",
                    "text": "Putin",
                    "type": "PERSON",
                    "canonical": "Vladimir Putin",
                    "cluster_id": "cluster-putin-001",
                },
                {
                    "id": "E2",
                    "text": "Beijing",
                    "type": "LOCATION",
                    "canonical": "Beijing, China",
                },
            ]
        }
    }


class AnonymousSource(BaseModel):
    """Structured representation of anonymous sources with available metadata.

    Anonymous sources like "senior US official" contain information even
    though identity is unknown. Capturing available descriptors enables
    pattern analysis (e.g., do "senior US officials" tend to be reliable
    on topic X?).

    Per CONTEXT.md: This is intelligence preservation, not identity inference.

    Attributes:
        entity_type: Fixed as "anonymous_source" for type discrimination.
        descriptors: Available metadata extracted from attribution phrase.
            Keys may include: role, affiliation, department, seniority.
        anonymity_granted_by: Source document ID where anonymity was granted.
    """

    entity_type: Literal["anonymous_source"] = "anonymous_source"
    descriptors: dict = Field(
        default_factory=dict,
        description="Available metadata: role, affiliation, department, seniority",
    )
    anonymity_granted_by: Optional[str] = Field(
        None, description="Source document ID where anonymity was granted"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "entity_type": "anonymous_source",
                    "descriptors": {
                        "role": "official",
                        "affiliation": "US_government",
                        "department": "State Department",
                        "seniority": "senior",
                    },
                    "anonymity_granted_by": "source-doc-uuid",
                }
            ]
        }
    }


class EntityCluster(BaseModel):
    """Group of likely-same entities without forced resolution.

    Per CONTEXT.md: Premature resolution creates false equivalences.
    "Russian President" in 2020 vs 2024 might mean different people.
    Clustering preserves the relationship while allowing downstream
    disambiguation with more context.

    Downstream impact: Knowledge graph (Phase 9) receives clusters,
    not forced resolutions. Entity resolution happens with full context.

    Attributes:
        cluster_id: Unique identifier for this cluster.
        entities: List of Entity IDs belonging to this cluster.
        canonical_suggestion: Suggested canonical form, not enforced.
    """

    cluster_id: str = Field(..., description="Unique cluster identifier")
    entities: list[str] = Field(
        default_factory=list, description="Entity IDs in cluster"
    )
    canonical_suggestion: Optional[str] = Field(
        None, description="Suggested canonical form (not enforced)"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "cluster_id": "cluster-putin-001",
                    "entities": ["E1", "E5", "E12"],
                    "canonical_suggestion": "Vladimir Putin",
                }
            ]
        }
    }
