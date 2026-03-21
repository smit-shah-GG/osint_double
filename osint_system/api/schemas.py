"""Pydantic v2 API response and request models.

Flat, JSON-friendly models decoupled from internal pipeline schemas
(ExtractedFact, VerificationResult, FactClassification, etc.).  These
define the API contract that the frontend codegen consumes via OpenAPI.

No internal pipeline schemas are imported here -- API models are mapped
from internal types in route handlers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# ── Request models ───────────────────────────────────────────────────

class LaunchRequest(BaseModel):
    """POST body for creating a new investigation."""

    objective: str = Field(
        ...,
        min_length=3,
        description="Investigation objective or question to research.",
    )
    extraction_model: str | None = Field(
        default=None,
        description="OpenRouter model key for fact extraction (maps to MODEL_MAP).",
    )
    synthesis_model: str | None = Field(
        default=None,
        description="OpenRouter model key for report synthesis.",
    )
    max_sources: int | None = Field(
        default=None,
        ge=1,
        description="Maximum number of sources to crawl.",
    )
    enable_verification: bool = Field(
        default=True,
        description="Whether to run the verification pipeline phase.",
    )
    enable_graph: bool = Field(
        default=True,
        description="Whether to build the knowledge graph.",
    )
    rss_feeds: list[str] | None = Field(
        default=None,
        description="Override feed list (URLs). If None, uses default feeds.",
    )


class RegenerateRequest(BaseModel):
    """POST body for report regeneration."""

    synthesis_model: str | None = Field(
        default=None,
        description="Override model for the regenerated report.",
    )


# ── Response models ──────────────────────────────────────────────────

class InvestigationResponse(BaseModel):
    """API representation of a single investigation."""

    id: str
    objective: str
    status: str = Field(description="pending | running | completed | failed | cancelled")
    params: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime | None = None
    stream_url: str | None = Field(
        default=None,
        description="SSE endpoint URL for real-time pipeline events.",
    )
    stats: dict[str, int] | None = None
    error: str | None = None


class FactResponse(BaseModel):
    """Flat fact representation for API consumers.

    Merges data from FactStore, ClassificationStore, and VerificationStore
    into a single JSON-friendly object.
    """

    fact_id: str
    claim_text: str
    claim_type: str
    source_id: str | None = None
    source_type: str | None = None
    extraction_confidence: float | None = None
    impact_tier: str | None = Field(
        default=None,
        description="From classification: critical | less_critical | noise.",
    )
    verification_status: str | None = Field(
        default=None,
        description="From verification: confirmed | refuted | unverifiable.",
    )
    created_at: str | None = None


class ReportResponse(BaseModel):
    """Full report version with Markdown content."""

    investigation_id: str
    version: int
    content: str
    model_used: str | None = None
    created_at: datetime
    metadata: dict[str, Any] | None = None


class ReportVersionSummary(BaseModel):
    """Lightweight report version entry for listing."""

    version: int
    created_at: datetime
    model_used: str | None = None


class SourceResponse(BaseModel):
    """Source inventory entry derived from ArticleStore data."""

    name: str
    type: str
    authority_score: float
    article_count: int
    domain: str


class GraphNodeResponse(BaseModel):
    """Knowledge graph node."""

    id: str
    label: str
    type: str = Field(description="Fact | Entity | Source | Investigation")
    properties: dict[str, Any] | None = None


class GraphEdgeResponse(BaseModel):
    """Knowledge graph edge."""

    source: str
    target: str
    relationship: str
    properties: dict[str, Any] | None = None


class PaginatedResponse(BaseModel, Generic[T]):
    """Wrapped list response with pagination metadata.

    Use ``from_items`` class method for server-side slicing.
    """

    data: list[T]
    total: int
    page: int
    page_size: int

    @classmethod
    def from_items(
        cls,
        items: list[T],
        page: int,
        page_size: int,
    ) -> PaginatedResponse[T]:
        """Build a paginated response by slicing *items*.

        Args:
            items: Full item list (pre-filter).
            page: 1-based page number.
            page_size: Items per page.

        Returns:
            PaginatedResponse with the correct slice and total count.
        """
        total = len(items)
        start = (page - 1) * page_size
        end = start + page_size
        return cls(
            data=items[start:end],
            total=total,
            page=page,
            page_size=page_size,
        )


# ── Error response model (for OpenAPI documentation) ─────────────────

class ProblemDetail(BaseModel):
    """RFC 7807 Problem Details error response.

    Used as ``response_model`` on error responses so the OpenAPI spec
    documents the error shape.
    """

    type: str = Field(default="about:blank", description="Error type URI.")
    title: str = Field(description="Short human-readable summary.")
    status: int = Field(description="HTTP status code.")
    detail: str = Field(description="Human-readable explanation.")
    instance: str | None = Field(
        default=None,
        description="URI reference identifying the specific occurrence.",
    )
