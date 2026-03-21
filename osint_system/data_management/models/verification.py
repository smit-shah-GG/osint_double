"""SQLAlchemy ORM model for verification results.

Maps to the ``verifications`` table in PostgreSQL. Stores verification
output (status, evidence, queries, confidence tracking) as hybrid
column+JSONB. Each verification is scoped to a unique
(investigation_id, fact_id) pair.

The ``from_dict``/``to_dict`` methods preserve the exact dict shape
that VerificationStore currently returns (VerificationResultRecord),
ensuring zero-breakage migration.
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

    VerificationStore saves VerificationResultRecord objects which extend
    VerificationResult with created_at/updated_at timestamps. Key fields:
    - fact_id, investigation_id (identity)
    - status (confirmed/refuted/unverifiable/etc.)
    - original_confidence, confidence_boost, final_confidence
    - supporting_evidence, refuting_evidence (lists of EvidenceItem dicts)
    - query_attempts, queries_used
    - origin_dubious_flags (preserved from classification)
    - reasoning (explanation string)
    """

    __tablename__ = "verifications"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # Business keys
    fact_id: Mapped[str] = mapped_column(String(64), index=True)
    investigation_id: Mapped[str] = mapped_column(String(64), index=True)

    # Verification output -- promoted to columns for querying
    status: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True,
    )
    original_confidence: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
    )
    confidence_boost: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
    )
    final_confidence: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
    )
    search_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0",
    )

    # Nested objects as JSONB
    supporting_evidence: Mapped[Optional[list]] = mapped_column(
        JSONB, default=list, server_default="[]",
    )
    refuting_evidence: Mapped[Optional[list]] = mapped_column(
        JSONB, default=list, server_default="[]",
    )
    queries_used: Mapped[Optional[list]] = mapped_column(
        JSONB, default=list, server_default="[]",
    )
    origin_dubious_flags: Mapped[Optional[list]] = mapped_column(
        JSONB, default=list, server_default="[]",
    )
    reasoning: Mapped[Optional[str]] = mapped_column(
        String(2048), nullable=True,
    )

    # Full verification data (stores the complete VerificationResultRecord
    # dict for any fields not promoted to columns)
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
        """Create a VerificationModel from a VerificationResultRecord.

        Accepts both VerificationResultRecord Pydantic objects and
        plain dicts. The full record is stored in ``verification_data``
        JSONB; key fields are promoted to columns for indexed querying.

        Args:
            data: VerificationResultRecord or dict from model_dump().
            investigation_id: Investigation scope (overrides data value).

        Returns:
            Populated VerificationModel instance.
        """
        # Handle Pydantic objects
        data_dict: dict[str, Any]
        if hasattr(data, "model_dump"):
            data_dict = data.model_dump(mode="json")
        elif isinstance(data, dict):
            data_dict = data
        else:
            raise TypeError(
                f"Expected dict or Pydantic model, got {type(data).__name__}"
            )

        return cls(
            fact_id=data_dict.get("fact_id", ""),
            investigation_id=investigation_id,
            status=data_dict.get("status"),
            original_confidence=data_dict.get("original_confidence"),
            confidence_boost=data_dict.get("confidence_boost"),
            final_confidence=data_dict.get("final_confidence"),
            search_count=data_dict.get("query_attempts", 0),
            supporting_evidence=data_dict.get("supporting_evidence", []),
            refuting_evidence=data_dict.get("refuting_evidence", []),
            queries_used=data_dict.get("queries_used", []),
            origin_dubious_flags=data_dict.get("origin_dubious_flags", []),
            reasoning=data_dict.get("reasoning"),
            verification_data=data_dict,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to VerificationResultRecord-compatible dict.

        Output matches VerificationResultRecord.model_dump(mode="json").

        Returns:
            Dict matching VerificationResultRecord serialized format.
        """
        # Start from full verification_data if available
        result: dict[str, Any] = {}
        if self.verification_data and isinstance(self.verification_data, dict):
            result = dict(self.verification_data)

        # Override with column values (columns are authoritative)
        result["fact_id"] = self.fact_id
        result["investigation_id"] = self.investigation_id
        result["status"] = self.status
        result["original_confidence"] = self.original_confidence or 0.0
        result["confidence_boost"] = self.confidence_boost or 0.0
        result["final_confidence"] = self.final_confidence or 0.0
        result["query_attempts"] = self.search_count
        result["supporting_evidence"] = self.supporting_evidence or []
        result["refuting_evidence"] = self.refuting_evidence or []
        result["queries_used"] = self.queries_used or []
        result["origin_dubious_flags"] = self.origin_dubious_flags or []
        result["reasoning"] = self.reasoning or ""

        # Timestamps
        if self.created_at:
            result["created_at"] = self.created_at.isoformat()
        if self.updated_at:
            result["updated_at"] = self.updated_at.isoformat()
        elif self.created_at:
            result["updated_at"] = self.created_at.isoformat()

        return result
