"""SQLAlchemy ORM model for generated reports.

Stub created in Task 1. Full implementation in Task 2.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from osint_system.data_management.models.base import Base, TimestampMixin


class ReportModel(TimestampMixin, Base):
    """ORM model for the ``reports`` table.

    Stores versioned intelligence reports with content hashing
    for change detection. Each report version is scoped to an
    (investigation_id, version) pair.

    Full implementation populated in Task 2.
    """

    __tablename__ = "reports"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # Business keys
    investigation_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)

    # Content
    markdown_content: Mapped[str] = mapped_column(Text, nullable=False)
    markdown_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pdf_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    generated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Summary data as JSONB
    synthesis_summary: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
    )

    # pgvector embedding on executive summary (1024 dims)
    embedding = mapped_column(Vector(1024), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "investigation_id", "version",
            name="uq_reports_inv_version",
        ),
    )

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], investigation_id: str,
    ) -> ReportModel:
        """Stub -- full implementation in Task 2."""
        raise NotImplementedError("Full implementation in Task 2")

    def to_dict(self) -> dict[str, Any]:
        """Stub -- full implementation in Task 2."""
        raise NotImplementedError("Full implementation in Task 2")
