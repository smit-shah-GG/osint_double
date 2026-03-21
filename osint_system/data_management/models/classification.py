"""SQLAlchemy ORM model for fact classifications.

Stub created in Task 1. Full implementation in Task 2.
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

    Full implementation populated in Task 2.
    """

    __tablename__ = "classifications"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # Business keys
    fact_id: Mapped[str] = mapped_column(String(64), index=True)
    investigation_id: Mapped[str] = mapped_column(String(64), index=True)

    # Classification output
    tier: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True,
    )
    priority_score: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
    )

    # Nested objects as JSONB
    credibility_scores: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
    )
    dubious_flags: Mapped[Optional[list]] = mapped_column(
        JSONB, default=list, server_default="[]",
    )
    impact_assessment: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
    )
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
        """Stub -- full implementation in Task 2."""
        raise NotImplementedError("Full implementation in Task 2")

    def to_dict(self) -> dict[str, Any]:
        """Stub -- full implementation in Task 2."""
        raise NotImplementedError("Full implementation in Task 2")
