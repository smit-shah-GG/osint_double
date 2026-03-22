"""SQLAlchemy ORM model for investigations (first-class entity).

Maps to the ``investigations`` table in PostgreSQL. Stores investigation
lifecycle data: objective, status, launch parameters, timestamps, stats.

This is the source of truth for investigation existence — on server
restart, the InvestigationRegistry hydrates from this table.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from osint_system.data_management.models.base import Base, TimestampMixin


class InvestigationModel(TimestampMixin, Base):
    """ORM model for the ``investigations`` table."""

    __tablename__ = "investigations"

    id: Mapped[int] = mapped_column(primary_key=True)

    investigation_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True,
    )
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending",
    )

    params: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    stats: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    @classmethod
    def from_investigation(
        cls, inv: Any,
    ) -> InvestigationModel:
        """Create from an Investigation dataclass."""
        return cls(
            investigation_id=inv.id,
            objective=inv.objective,
            status=inv.status.value if hasattr(inv.status, "value") else str(inv.status),
            params=inv.params or {},
            stats=inv.stats or {},
            error=inv.error,
            started_at=inv.created_at,
            completed_at=inv.updated_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "investigation_id": self.investigation_id,
            "objective": self.objective,
            "status": self.status,
            "params": self.params or {},
            "stats": self.stats or {},
            "error": self.error,
            "created_at": self.started_at.isoformat() if self.started_at else None,
            "updated_at": self.completed_at.isoformat() if self.completed_at else None,
        }
