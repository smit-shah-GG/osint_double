"""SQLAlchemy ORM model for fact classifications.

Maps to the ``classifications`` table in PostgreSQL. Stores
classification output (impact tier, dubious flags, credibility scores)
as hybrid column+JSONB. Each classification is scoped to a unique
(investigation_id, fact_id) pair.

The ``from_dict``/``to_dict`` methods preserve the exact dict shape
that ClassificationStore currently returns (FactClassification.model_dump),
ensuring zero-breakage migration.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Float, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from osint_system.data_management.models.base import Base, TimestampMixin


class ClassificationModel(TimestampMixin, Base):
    """ORM model for the ``classifications`` table.

    Stores fact classifications with impact tiers, dubious flags,
    credibility scores, and full classification reasoning. Each
    classification is scoped to an (investigation_id, fact_id) pair.

    The ClassificationStore saves FactClassification.model_dump(mode="json")
    as the dict shape. Key fields are:
    - fact_id, investigation_id (identity)
    - impact_tier (critical/less_critical)
    - dubious_flags (list of DubiousFlag values)
    - priority_score, credibility_score (floats)
    - credibility_breakdown (nested dict)
    - classification_reasoning (list of reasoning dicts)
    - impact_reasoning (string)
    - history (list of history entries)
    - classified_at, updated_at (timestamps)
    """

    __tablename__ = "classifications"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # Business keys
    fact_id: Mapped[str] = mapped_column(String(64), index=True)
    investigation_id: Mapped[str] = mapped_column(String(64), index=True)

    # Classification output -- promoted to columns for querying
    tier: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True,
    )
    priority_score: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
    )
    credibility_score: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
    )

    # Nested objects as JSONB
    credibility_breakdown: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
    )
    dubious_flags: Mapped[Optional[list]] = mapped_column(
        JSONB, default=list, server_default="[]",
    )
    classification_reasoning: Mapped[Optional[list]] = mapped_column(
        JSONB, default=list, server_default="[]",
    )
    impact_reasoning: Mapped[Optional[str]] = mapped_column(
        String(1024), nullable=True,
    )
    history: Mapped[Optional[list]] = mapped_column(
        JSONB, default=list, server_default="[]",
    )

    # Full classification data (stores the complete FactClassification dict
    # for any fields not promoted to columns)
    classification_data: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "investigation_id", "fact_id",
            name="uq_classifications_inv_fact",
        ),
    )

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], investigation_id: str,
    ) -> ClassificationModel:
        """Create a ClassificationModel from a FactClassification dict.

        ClassificationStore stores FactClassification.model_dump(mode="json"):
        {
            "fact_id": "...",
            "investigation_id": "...",
            "impact_tier": "critical",
            "dubious_flags": ["phantom", "fog"],
            "priority_score": 0.85,
            "credibility_score": 0.45,
            "credibility_breakdown": {...},
            "classification_reasoning": [...],
            "impact_reasoning": "...",
            "history": [...],
            "classified_at": "...",
            "updated_at": "..."
        }

        Args:
            data: Classification dict from FactClassification.model_dump().
            investigation_id: Investigation scope (overrides data value).

        Returns:
            Populated ClassificationModel instance.
        """
        # Handle both Pydantic objects and plain dicts
        if hasattr(data, "model_dump"):
            data = data.model_dump(mode="json")

        return cls(
            fact_id=data.get("fact_id", ""),
            investigation_id=investigation_id,
            tier=data.get("impact_tier"),
            priority_score=data.get("priority_score"),
            credibility_score=data.get("credibility_score"),
            credibility_breakdown=data.get("credibility_breakdown"),
            dubious_flags=data.get("dubious_flags", []),
            classification_reasoning=data.get("classification_reasoning", []),
            impact_reasoning=data.get("impact_reasoning"),
            history=data.get("history", []),
            classification_data=data,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to the exact dict shape ClassificationStore returns.

        Output matches FactClassification.model_dump(mode="json") format.

        Returns:
            Dict matching FactClassification serialized format.
        """
        # Start from full classification_data if available
        result: dict[str, Any] = {}
        if self.classification_data and isinstance(self.classification_data, dict):
            result = dict(self.classification_data)

        # Override with column values (columns are authoritative)
        result["fact_id"] = self.fact_id
        result["investigation_id"] = self.investigation_id
        result["impact_tier"] = self.tier
        result["dubious_flags"] = self.dubious_flags or []
        result["priority_score"] = self.priority_score or 0.0
        result["credibility_score"] = self.credibility_score or 0.0
        result["credibility_breakdown"] = self.credibility_breakdown
        result["classification_reasoning"] = self.classification_reasoning or []
        result["impact_reasoning"] = self.impact_reasoning
        result["history"] = self.history or []

        # Timestamps from mixin or classification_data
        if "classified_at" not in result and self.created_at:
            result["classified_at"] = self.created_at.isoformat()
        if self.updated_at:
            result["updated_at"] = self.updated_at.isoformat()
        elif "updated_at" not in result and self.created_at:
            result["updated_at"] = self.created_at.isoformat()

        return result
