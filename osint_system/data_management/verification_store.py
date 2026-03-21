"""Verification result storage backed by PostgreSQL via SQLAlchemy async sessions.

Follows same patterns as ClassificationStore:
- Investigation-based organization (investigation_id scoping)
- O(1) lookup by (investigation_id, fact_id) via unique constraint
- Concurrency handled by PostgreSQL transactions (no asyncio.Lock)

Migrated from in-memory dict+JSON to PostgreSQL. All public method
signatures and return types are preserved. The broken _load_from_file
method (missing definition in the original) is eliminated structurally.

Usage:
    from osint_system.data_management.database import init_db
    from osint_system.data_management.verification_store import VerificationStore

    session_factory = init_db()
    store = VerificationStore(session_factory)
    await store.save_result(verification_result)
    result = await store.get_result("inv-1", "fact-001")
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from osint_system.data_management.models.verification import VerificationModel
from osint_system.data_management.schemas.verification_schema import (
    VerificationResult,
    VerificationResultRecord,
    VerificationStatus,
)


class VerificationStore:
    """PostgreSQL-backed storage for verification results.

    Replaces in-memory dict storage with async SQLAlchemy sessions.
    Returns VerificationResultRecord Pydantic objects from get methods,
    preserving the exact interface of the original implementation.
    """

    def __init__(
        self,
        session_factory: Optional[async_sessionmaker[AsyncSession]] = None,
    ) -> None:
        """Initialize VerificationStore.

        Args:
            session_factory: SQLAlchemy async session factory from database.py.
                If None, falls back to the module-level factory via init_db().
        """
        if session_factory is None:
            from osint_system.data_management.database import get_session_factory
            session_factory = get_session_factory()

        self._session_factory = session_factory
        self._logger = structlog.get_logger().bind(component="VerificationStore")

    def _model_to_record(self, model: VerificationModel) -> VerificationResultRecord:
        """Convert a VerificationModel ORM instance to a VerificationResultRecord.

        Uses the model's to_dict() which returns the full verification_data
        JSONB merged with authoritative column values, then validates through
        the Pydantic model.

        Args:
            model: The ORM model instance.

        Returns:
            VerificationResultRecord Pydantic model.
        """
        data = model.to_dict()
        return VerificationResultRecord.model_validate(data)

    async def save_result(self, result: VerificationResult) -> None:
        """Save a verification result.

        Creates VerificationResultRecord from result and persists via
        upsert on the (investigation_id, fact_id) unique constraint.

        Args:
            result: VerificationResult to store.
        """
        inv_id = result.investigation_id
        record = VerificationResultRecord.from_result(result)
        record_data = record.model_dump(mode="json")

        async with self._session_factory() as session:
            # Check if exists
            existing = await session.execute(
                select(VerificationModel.id).where(
                    VerificationModel.investigation_id == inv_id,
                    VerificationModel.fact_id == result.fact_id,
                )
            )
            existing_id = existing.scalar_one_or_none()

            if existing_id is not None:
                # Update existing row
                await session.execute(
                    update(VerificationModel)
                    .where(VerificationModel.id == existing_id)
                    .values(
                        status=record_data.get("status"),
                        original_confidence=record_data.get("original_confidence"),
                        confidence_boost=record_data.get("confidence_boost"),
                        final_confidence=record_data.get("final_confidence"),
                        search_count=record_data.get("query_attempts", 0),
                        supporting_evidence=record_data.get("supporting_evidence", []),
                        refuting_evidence=record_data.get("refuting_evidence", []),
                        queries_used=record_data.get("queries_used", []),
                        origin_dubious_flags=record_data.get("origin_dubious_flags", []),
                        reasoning=record_data.get("reasoning"),
                        verification_data=record_data,
                    )
                )
            else:
                model = VerificationModel.from_dict(record, inv_id)
                session.add(model)

            await session.commit()

        self._logger.debug(
            "result_saved",
            fact_id=result.fact_id,
            investigation_id=inv_id,
            status=result.status.value,
        )

    async def get_result(
        self,
        investigation_id: str,
        fact_id: str,
    ) -> Optional[VerificationResultRecord]:
        """Get a verification result by fact_id.

        Args:
            investigation_id: Investigation scope.
            fact_id: Fact identifier.

        Returns:
            VerificationResultRecord if found, None otherwise.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(VerificationModel).where(
                    VerificationModel.investigation_id == investigation_id,
                    VerificationModel.fact_id == fact_id,
                )
            )
            model = result.scalar_one_or_none()
            if model is None:
                return None
            return self._model_to_record(model)

    async def get_all_results(
        self,
        investigation_id: str,
    ) -> list[VerificationResultRecord]:
        """Get all verification results for an investigation.

        Args:
            investigation_id: Investigation scope.

        Returns:
            List of all VerificationResultRecord objects.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(VerificationModel).where(
                    VerificationModel.investigation_id == investigation_id,
                )
            )
            models = result.scalars().all()
            return [self._model_to_record(m) for m in models]

    async def get_by_status(
        self,
        investigation_id: str,
        status: VerificationStatus,
    ) -> list[VerificationResultRecord]:
        """Get results filtered by verification status.

        Args:
            investigation_id: Investigation scope.
            status: VerificationStatus to filter by.

        Returns:
            List of matching VerificationResultRecord objects.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(VerificationModel).where(
                    VerificationModel.investigation_id == investigation_id,
                    VerificationModel.status == status.value,
                )
            )
            models = result.scalars().all()
            return [self._model_to_record(m) for m in models]

    async def get_pending_review(
        self,
        investigation_id: str,
    ) -> list[VerificationResultRecord]:
        """Get results pending human review.

        Returns results where requires_human_review=True AND
        human_review_completed=False. These fields live in the
        verification_data JSONB column.

        Args:
            investigation_id: Investigation scope.

        Returns:
            List of VerificationResultRecord objects awaiting review.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(VerificationModel).where(
                    VerificationModel.investigation_id == investigation_id,
                )
            )
            models = result.scalars().all()

        # Filter in Python using verification_data JSONB fields
        pending = []
        for model in models:
            record = self._model_to_record(model)
            if record.requires_human_review and not record.human_review_completed:
                pending.append(record)
        return pending

    async def mark_reviewed(
        self,
        investigation_id: str,
        fact_id: str,
        notes: Optional[str] = None,
    ) -> bool:
        """Mark a result as human-reviewed.

        Updates the verification_data JSONB to set human_review_completed=True
        and optionally add reviewer notes.

        Args:
            investigation_id: Investigation scope.
            fact_id: Fact identifier.
            notes: Optional reviewer notes.

        Returns:
            True if marked, False if result not found.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(VerificationModel).where(
                    VerificationModel.investigation_id == investigation_id,
                    VerificationModel.fact_id == fact_id,
                )
            )
            model = result.scalar_one_or_none()
            if model is None:
                return False

            # Update verification_data JSONB
            vdata = dict(model.verification_data) if model.verification_data else {}
            vdata["human_review_completed"] = True
            vdata["updated_at"] = datetime.now(timezone.utc).isoformat()
            if notes:
                vdata["human_reviewer_notes"] = notes

            await session.execute(
                update(VerificationModel)
                .where(VerificationModel.id == model.id)
                .values(verification_data=vdata)
            )
            await session.commit()

        self._logger.info(
            "result_reviewed",
            fact_id=fact_id,
            investigation_id=investigation_id,
        )
        return True

    async def get_stats(self, investigation_id: str) -> dict[str, Any]:
        """Get verification statistics for an investigation.

        Args:
            investigation_id: Investigation scope.

        Returns:
            Stats dict with counts by status.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(VerificationModel).where(
                    VerificationModel.investigation_id == investigation_id,
                )
            )
            models = result.scalars().all()

        if not models:
            return {"total": 0, "investigation_id": investigation_id}

        status_counts: dict[str, int] = {}
        pending_review = 0

        for model in models:
            status_val = model.status or "unknown"
            status_counts[status_val] = status_counts.get(status_val, 0) + 1

            record = self._model_to_record(model)
            if record.requires_human_review and not record.human_review_completed:
                pending_review += 1

        return {
            "investigation_id": investigation_id,
            "total": len(models),
            "status_counts": status_counts,
            "pending_review": pending_review,
        }

    async def delete_investigation(self, investigation_id: str) -> bool:
        """Delete all verification results for an investigation.

        Args:
            investigation_id: Investigation scope.

        Returns:
            True if any rows deleted, False if investigation not found.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                delete(VerificationModel).where(
                    VerificationModel.investigation_id == investigation_id,
                )
            )
            await session.commit()

        deleted = result.rowcount > 0
        if deleted:
            self._logger.info(
                "investigation_deleted",
                investigation_id=investigation_id,
            )
        return deleted
