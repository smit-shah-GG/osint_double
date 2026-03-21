"""SQLAlchemy ORM model for generated intelligence reports.

Maps to the ``reports`` table in PostgreSQL. Stores versioned reports
with content hashing for change detection and pgvector embedding on
the executive summary for cross-investigation comparison.

The ``from_dict``/``to_dict`` methods preserve the exact dict shape
that ReportStore currently returns (ReportRecord), ensuring
zero-breakage migration.
"""

from __future__ import annotations

from datetime import datetime, timezone
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

    ReportStore saves ReportRecord Pydantic objects with:
    - investigation_id, version (identity)
    - content_hash (SHA256 for change detection)
    - markdown_content (full report text)
    - markdown_path, pdf_path (file paths)
    - generated_at (timestamp)
    - synthesis_summary (dict from AnalysisSynthesis)
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
        """Create a ReportModel from a ReportRecord dict.

        ReportRecord fields:
        {
            "investigation_id": "...",
            "version": 1,
            "content_hash": "...",
            "markdown_content": "...",
            "markdown_path": "...",
            "pdf_path": "...",
            "generated_at": "...",
            "synthesis_summary": {...}
        }

        Args:
            data: Report dict from ReportRecord.model_dump().
            investigation_id: Investigation scope (overrides data value).

        Returns:
            Populated ReportModel instance.
        """
        # Handle Pydantic objects
        if hasattr(data, "model_dump"):
            data = data.model_dump(mode="json")

        # Parse generated_at
        generated_at = data.get("generated_at")
        if isinstance(generated_at, str):
            try:
                generated_at = datetime.fromisoformat(
                    generated_at.replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                generated_at = datetime.now(timezone.utc)

        return cls(
            investigation_id=investigation_id,
            version=data.get("version", 1),
            content_hash=data.get("content_hash", ""),
            markdown_content=data.get("markdown_content", ""),
            markdown_path=data.get("markdown_path"),
            pdf_path=data.get("pdf_path"),
            generated_at=generated_at,
            synthesis_summary=data.get("synthesis_summary"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to ReportRecord-compatible dict.

        Output matches ReportRecord.model_dump(mode="json").

        Returns:
            Dict matching ReportRecord serialized format.
        """
        return {
            "investigation_id": self.investigation_id,
            "version": self.version,
            "content_hash": self.content_hash,
            "markdown_content": self.markdown_content,
            "markdown_path": self.markdown_path,
            "pdf_path": self.pdf_path,
            "generated_at": (
                self.generated_at.isoformat()
                if self.generated_at
                else None
            ),
            "synthesis_summary": self.synthesis_summary or {},
        }
