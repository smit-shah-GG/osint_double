"""SQLAlchemy ORM model for verification results.

Stub created in Task 1. Full implementation in Task 2.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Float, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from osint_system.data_management.models.base import Base, TimestampMixin


class VerificationModel(TimestampMixin, Base):
    """ORM model for the ``verifications`` table.

    Stores verification results with status, evidence, queries,
    and confidence tracking. Each verification is scoped to an
    (investigation_id, fact_id) pair.

    Full implementation populated in Task 2.
    """

    __tablename__ = "verifications"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # Business keys
    fact_id: Mapped[str] = mapped_column(String(64), index=True)
    investigation_id: Mapped[str] = mapped_column(String(64), index=True)

    # Verification output
    status: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True,
    )
    original_status: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True,
    )
    confidence: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
    )
    search_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0",
    )

    # Nested objects as JSONB
    evidence: Mapped[Optional[list]] = mapped_column(
        JSONB, default=list, server_default="[]",
    )
    queries_used: Mapped[Optional[list]] = mapped_column(
        JSONB, default=list, server_default="[]",
    )
    verification_data: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "investigation_id", "fact_id",
            name="uq_verifications_inv_fact",
        ),
    )

    @classmethod
    def from_dict(
        cls, data: Any, investigation_id: str,
    ) -> VerificationModel:
        """Stub -- full implementation in Task 2."""
        raise NotImplementedError("Full implementation in Task 2")

    def to_dict(self) -> dict[str, Any]:
        """Stub -- full implementation in Task 2."""
        raise NotImplementedError("Full implementation in Task 2")
