"""SQLAlchemy ORM model for entities (extracted named entities).

Maps to the ``entities`` table in PostgreSQL. Stores entity mentions
with canonical names and pgvector embeddings for entity resolution
across investigations.

Entities are extracted from facts during the sifter pipeline. The
canonical name embedding enables cross-investigation entity matching
via cosine similarity search.
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from osint_system.data_management.models.base import Base, TimestampMixin


class EntityModel(TimestampMixin, Base):
    """ORM model for the ``entities`` table.

    Each entity is a named entity mention (PERSON, ORGANIZATION,
    LOCATION, etc.) extracted from a fact. Entities are scoped to
    investigations and carry a canonical form for normalization.

    The pgvector embedding on the canonical name enables cross-
    investigation entity resolution via cosine similarity.
    """

    __tablename__ = "entities"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # Business keys
    entity_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True,
    )
    investigation_id: Mapped[str] = mapped_column(
        String(64), index=True,
    )

    # Core fields
    name: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True,
    )
    canonical: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
    )

    # Additional metadata as JSONB
    entity_metadata: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
    )

    # pgvector embedding on canonical name (1024 dims for gte-large-en-v1.5)
    embedding = mapped_column(Vector(1024), nullable=True)

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], investigation_id: str,
    ) -> EntityModel:
        """Create an EntityModel from an entity dict.

        Accepts the Entity Pydantic schema dict shape:
        {
            "id": "E1",
            "text": "Putin",
            "type": "PERSON",
            "canonical": "Vladimir Putin",
            "cluster_id": "cluster-putin-001"
        }

        Generates ``entity_id`` as SHA256 of investigation_id + name
        if not provided in data.

        Args:
            data: Entity dict from Entity.model_dump() or raw dict.
            investigation_id: Investigation scope identifier.

        Returns:
            Populated EntityModel instance (not yet added to a session).
        """
        name = data.get("text", data.get("name", ""))
        entity_type = data.get("type", data.get("entity_type"))

        # Generate entity_id if not provided
        entity_id = data.get("entity_id")
        if not entity_id:
            raw_id = data.get("id", "")
            # Use investigation_id + name hash for uniqueness
            hash_input = f"{investigation_id}:{name}:{raw_id}"
            entity_id = hashlib.sha256(
                hash_input.encode("utf-8")
            ).hexdigest()[:64]

        # Collect extra metadata
        metadata: dict[str, Any] = {}
        if data.get("cluster_id"):
            metadata["cluster_id"] = data["cluster_id"]
        if data.get("id"):
            metadata["marker_id"] = data["id"]

        return cls(
            entity_id=entity_id,
            investigation_id=investigation_id,
            name=name,
            entity_type=entity_type,
            canonical=data.get("canonical"),
            entity_metadata=metadata if metadata else None,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to a dict compatible with Entity schema shape.

        Output shape:
        {
            "entity_id": "...",
            "id": "E1",
            "text": "Putin",
            "name": "Putin",
            "type": "PERSON",
            "canonical": "Vladimir Putin",
            "cluster_id": "..."
        }

        Returns:
            Dict with entity data.
        """
        result: dict[str, Any] = {
            "entity_id": self.entity_id,
            "name": self.name,
            "text": self.name,
            "type": self.entity_type,
            "canonical": self.canonical,
        }
        if self.entity_metadata and isinstance(self.entity_metadata, dict):
            if "cluster_id" in self.entity_metadata:
                result["cluster_id"] = self.entity_metadata["cluster_id"]
            if "marker_id" in self.entity_metadata:
                result["id"] = self.entity_metadata["marker_id"]
        return result
