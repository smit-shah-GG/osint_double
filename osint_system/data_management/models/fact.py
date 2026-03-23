"""SQLAlchemy ORM model for extracted facts.

Maps to the ``facts`` table in PostgreSQL. Uses hybrid column+JSONB
pattern: top-level queryable fields (fact_id, claim_text, assertion_type,
extraction_confidence, claim_clarity) as proper columns; nested Pydantic
objects (entities, provenance, quality_metrics, temporal, numeric,
relationships, variants) as JSONB.

Includes:
- pgvector embedding (1024 dims) with HNSW index for semantic search
- tsvector computed column with GIN index for full-text search on claim_text
- content_hash index for exact-match deduplication

The ``from_dict``/``to_dict`` methods preserve the exact dict shape that
FactStore currently returns, ensuring zero-breakage migration.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, Float, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from osint_system.data_management.models.base import Base, TimestampMixin


class FactModel(TimestampMixin, Base):
    """ORM model for the ``facts`` table.

    Each fact is a single subject-predicate-object assertion extracted
    from a source article. Facts are scoped to investigations and
    deduplicated by content_hash (SHA256 of claim text).

    The ``claim_data`` JSONB column stores the full ``claim`` sub-object
    for fields not promoted to columns (e.g. ``claim_type``). This avoids
    schema proliferation while keeping queryable fields as proper columns.
    """

    __tablename__ = "facts"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # Business keys
    fact_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True,
    )
    investigation_id: Mapped[str] = mapped_column(
        String(64), index=True,
    )
    content_hash: Mapped[str] = mapped_column(
        String(64), index=True,
    )

    # Core claim columns (promoted from nested claim object)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    assertion_type: Mapped[str] = mapped_column(
        String(32), default="statement",
    )

    # Source reference
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Quality scores (promoted from quality sub-object)
    extraction_confidence: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
    )
    claim_clarity: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
    )

    # Storage timestamp from original store format
    stored_at: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True,
    )

    # Nested objects as JSONB
    entities: Mapped[Optional[list]] = mapped_column(
        JSONB, default=list, server_default="[]",
    )
    provenance: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
    )
    quality_metrics: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
    )
    temporal: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
    )
    numeric: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
    )
    relationships: Mapped[Optional[list]] = mapped_column(
        JSONB, default=list, server_default="[]",
    )
    variants: Mapped[Optional[list]] = mapped_column(
        JSONB, default=list, server_default="[]",
    )
    claim_data: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
    )

    # pgvector embedding (1024 dims for gte-large-en-v1.5)
    embedding = mapped_column(Vector(768), nullable=True)

    # tsvector for full-text search (generated column)
    claim_tsvector = mapped_column(
        TSVECTOR(),
        Computed(
            "to_tsvector('english', COALESCE(claim_text, ''))",
            persisted=True,
        ),
        nullable=True,
    )

    __table_args__ = (
        Index(
            "ix_facts_claim_fts",
            "claim_tsvector",
            postgresql_using="gin",
        ),
        Index(
            "ix_facts_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], investigation_id: str,
    ) -> FactModel:
        """Create a FactModel from a FactStore dict.

        FactStore dict shape (per fact_store.py save_facts):
        {
            "fact_id": "...",
            "content_hash": "...",
            "claim": {
                "text": "...",
                "assertion_type": "statement",
                "claim_type": "event"
            },
            "entities": [...],
            "temporal": {...} or None,
            "numeric": {...} or None,
            "provenance": {...} or None,
            "quality": {
                "extraction_confidence": 0.92,
                "claim_clarity": 0.88,
                "extraction_trace": {...}
            },
            "extraction": {...},
            "relationships": [...],
            "variants": [...],
            "stored_at": "..."
        }

        Args:
            data: Fact dict from FactStore / ExtractedFact.model_dump().
            investigation_id: Investigation scope identifier.

        Returns:
            Populated FactModel instance (not yet added to a session).
        """
        claim = data.get("claim", {}) or {}
        quality = data.get("quality", {}) or {}
        provenance = data.get("provenance")

        # Extract source_url from provenance if available
        source_url = None
        if isinstance(provenance, dict):
            source_url = provenance.get("source_id")

        # Compute content_hash if missing
        content_hash = data.get("content_hash", "")
        claim_text = claim.get("text", "") if isinstance(claim, dict) else str(claim)
        if not content_hash and claim_text:
            content_hash = hashlib.sha256(
                claim_text.encode("utf-8")
            ).hexdigest()

        # Build claim_data with fields not promoted to columns
        claim_data: dict[str, Any] = {}
        if isinstance(claim, dict):
            for k, v in claim.items():
                if k not in ("text", "assertion_type"):
                    claim_data[k] = v

        # Serialize entities/relationships/variants as plain dicts/lists
        entities_raw = data.get("entities", [])
        entities_list: list[Any] = []
        for ent in entities_raw:
            if hasattr(ent, "model_dump"):
                entities_list.append(ent.model_dump(mode="json"))
            elif isinstance(ent, dict):
                entities_list.append(ent)

        relationships_raw = data.get("relationships", [])
        relationships_list: list[Any] = []
        for rel in relationships_raw:
            if hasattr(rel, "model_dump"):
                relationships_list.append(rel.model_dump(mode="json"))
            elif isinstance(rel, dict):
                relationships_list.append(rel)

        # Serialize provenance
        provenance_dict: dict[str, Any] | None = None
        if provenance is not None:
            if hasattr(provenance, "model_dump"):
                provenance_dict = provenance.model_dump(mode="json")
            elif isinstance(provenance, dict):
                provenance_dict = provenance

        # Serialize quality metrics
        quality_dict: dict[str, Any] | None = None
        if quality:
            if hasattr(quality, "model_dump"):
                quality_dict = quality.model_dump(mode="json")
            elif isinstance(quality, dict):
                quality_dict = quality

        # Serialize temporal
        temporal_raw = data.get("temporal")
        temporal_dict: dict[str, Any] | None = None
        if temporal_raw is not None:
            if hasattr(temporal_raw, "model_dump"):
                temporal_dict = temporal_raw.model_dump(mode="json")
            elif isinstance(temporal_raw, dict):
                temporal_dict = temporal_raw

        # Serialize numeric
        numeric_raw = data.get("numeric")
        numeric_dict: dict[str, Any] | None = None
        if numeric_raw is not None:
            if hasattr(numeric_raw, "model_dump"):
                numeric_dict = numeric_raw.model_dump(mode="json")
            elif isinstance(numeric_raw, dict):
                numeric_dict = numeric_raw

        return cls(
            fact_id=data.get("fact_id", ""),
            investigation_id=investigation_id,
            content_hash=content_hash,
            claim_text=claim_text,
            assertion_type=(
                claim.get("assertion_type", "statement")
                if isinstance(claim, dict)
                else "statement"
            ),
            source_url=source_url,
            extraction_confidence=(
                quality.get("extraction_confidence")
                if isinstance(quality, dict)
                else None
            ),
            claim_clarity=(
                quality.get("claim_clarity")
                if isinstance(quality, dict)
                else None
            ),
            stored_at=data.get("stored_at"),
            entities=entities_list,
            provenance=provenance_dict,
            quality_metrics=quality_dict,
            temporal=temporal_dict,
            numeric=numeric_dict,
            relationships=relationships_list,
            variants=data.get("variants", []),
            claim_data=claim_data if claim_data else None,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to the exact dict shape FactStore returns.

        Output shape matches FactStore's per-fact format:
        {
            "fact_id": "...",
            "content_hash": "...",
            "claim": {
                "text": "...",
                "assertion_type": "statement",
                "claim_type": "event"
            },
            "entities": [...],
            "temporal": {...} or None,
            "numeric": {...} or None,
            "provenance": {...} or None,
            "quality": {...} or None,
            "extraction": {...},
            "relationships": [...],
            "variants": [...],
            "stored_at": "..."
        }

        Returns:
            Dict matching FactStore's per-fact format.
        """
        # Reconstruct the claim sub-object
        claim: dict[str, Any] = {
            "text": self.claim_text,
            "assertion_type": self.assertion_type or "statement",
        }
        # Merge back any additional claim fields from claim_data
        if self.claim_data and isinstance(self.claim_data, dict):
            for k, v in self.claim_data.items():
                if k not in claim:
                    claim[k] = v

        result: dict[str, Any] = {
            "fact_id": self.fact_id,
            "content_hash": self.content_hash,
            "claim": claim,
            "entities": self.entities or [],
            "temporal": self.temporal,
            "numeric": self.numeric,
            "provenance": self.provenance,
            "quality": self.quality_metrics,
            "relationships": self.relationships or [],
            "variants": self.variants or [],
            "stored_at": self.stored_at or (
                self.created_at.isoformat() if self.created_at else None
            ),
        }
        return result
