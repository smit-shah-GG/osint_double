"""Provenance schemas for fact extraction.

Defines provenance chain and source attribution models per Phase 6 CONTEXT.md.
Full provenance chains capture attribution depth: eyewitness -> local paper -> wire -> our document.

Design principle: Source type and hop count are SEPARATE orthogonal fields.
They measure different dimensions and collapsing them loses intelligence.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    """Source type classification.

    Categorizes the nature of the information source, not its reliability.
    Reliability is a separate dimension tracked via hop count and
    cross-investigation source history.
    """

    WIRE_SERVICE = "wire_service"  # Reuters, AP, AFP, etc.
    OFFICIAL_STATEMENT = "official_statement"  # Government/org press releases
    NEWS_OUTLET = "news_outlet"  # BBC, NYT, etc.
    SOCIAL_MEDIA = "social_media"  # Twitter, Telegram, etc.
    ACADEMIC = "academic"  # Research papers, journals
    DOCUMENT = "document"  # Leaked documents, reports
    EYEWITNESS = "eyewitness"  # Direct observation
    UNKNOWN = "unknown"


class SourceClassification(str, Enum):
    """Journalistic source classification.

    PRIMARY: Direct observation or statement from the source
    SECONDARY: Journalistic reporting on primary sources
    TERTIARY: Aggregation, analysis, or summary of secondary sources

    This is orthogonal to SourceType and hop_count.
    """

    PRIMARY = "primary"  # Direct observation/statement
    SECONDARY = "secondary"  # Journalistic reporting
    TERTIARY = "tertiary"  # Aggregation/analysis


class AttributionHop(BaseModel):
    """Single hop in attribution chain.

    Each hop represents one intermediary in the information flow.
    Full chains enable:
    - Reliability assessment (how many intermediaries?)
    - Pattern detection (which sources cite which?)
    - Error tracing (where did misreporting originate?)

    Attributes:
        entity: Who is being cited at this hop (name or description).
        type: Type of source at this hop.
        hop: Distance from original source (0 = eyewitness/origin).
    """

    entity: str = Field(..., description="Who is being cited")
    type: SourceType
    hop: int = Field(..., ge=0, description="Distance from original (0 = eyewitness)")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"entity": "Kremlin spokesperson", "type": "official_statement", "hop": 0},
                {"entity": "TASS", "type": "wire_service", "hop": 1},
                {"entity": "Reuters", "type": "wire_service", "hop": 2},
            ]
        }
    }


class Provenance(BaseModel):
    """Full provenance tracking for a fact.

    Per CONTEXT.md: Capture complete provenance chain from eyewitness
    to our document. Each hop can introduce distortion; full chains
    enable reliability assessment and error tracing.

    Design decisions:
    - source_type and hop_count are SEPARATE fields (different dimensions)
    - attribution_phrase preserved verbatim (original phrasing has nuance)
    - offsets enable programmatic access to source context

    Attributes:
        source_id: ID of the source document in our storage.
        quote: Exact quoted text span supporting this fact.
        offsets: Character positions in source document.
        attribution_chain: Complete chain from origin to our document.
        attribution_phrase: Original attribution phrasing verbatim.
        hop_count: Total number of intermediaries (0 = eyewitness).
        source_type: Type of the immediate source (not origin).
        source_classification: PRIMARY/SECONDARY/TERTIARY classification.
    """

    source_id: str = Field(..., description="ID of source document")
    quote: str = Field(..., description="Exact quoted text span")
    offsets: dict = Field(
        ..., description="{'start': int, 'end': int} character positions"
    )
    attribution_chain: list[AttributionHop] = Field(
        default_factory=list,
        description="Complete provenance chain from origin",
    )
    attribution_phrase: Optional[str] = Field(
        None, description="Original attribution phrasing (e.g., 'according to Reuters citing officials')"
    )
    hop_count: int = Field(
        0, ge=0, description="Distance from original source (0 = direct)"
    )
    source_type: SourceType = Field(
        SourceType.UNKNOWN, description="Type of immediate source"
    )
    source_classification: SourceClassification = Field(
        SourceClassification.SECONDARY, description="PRIMARY/SECONDARY/TERTIARY"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "source_id": "article-uuid-123",
                    "quote": "Russian President Vladimir Putin visited Beijing in March 2024",
                    "offsets": {"start": 1542, "end": 1601},
                    "attribution_chain": [
                        {"entity": "Kremlin spokesperson", "type": "official_statement", "hop": 0},
                        {"entity": "TASS", "type": "wire_service", "hop": 1},
                        {"entity": "Reuters", "type": "wire_service", "hop": 2},
                    ],
                    "attribution_phrase": "according to Reuters citing TASS",
                    "hop_count": 2,
                    "source_type": "wire_service",
                    "source_classification": "secondary",
                }
            ]
        }
    }
