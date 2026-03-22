"""Investigation lifecycle tracking with PostgreSQL persistence.

The ``InvestigationRegistry`` tracks investigation status, parameters,
and timestamps. Backed by the ``investigations`` table in PostgreSQL
so data survives server restarts.

In-memory cache keeps the hot path fast; PostgreSQL is the source of
truth. On startup, ``hydrate_from_db()`` loads all investigations.
Mutations (create, transition, delete) write-through to both.

Status transitions use compare-and-swap with ``asyncio.Lock`` to prevent
race conditions between concurrent API calls (e.g. cancel + regenerate).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import structlog

from osint_system.api.errors import ConflictError

logger = structlog.get_logger(__name__)


class InvestigationStatus(str, Enum):
    """Investigation lifecycle states."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Valid state transitions.  Key = from, value = set of allowed targets.
_VALID_TRANSITIONS: dict[InvestigationStatus, set[InvestigationStatus]] = {
    InvestigationStatus.PENDING: {
        InvestigationStatus.RUNNING,
        InvestigationStatus.CANCELLED,
    },
    InvestigationStatus.RUNNING: {
        InvestigationStatus.COMPLETED,
        InvestigationStatus.FAILED,
        InvestigationStatus.CANCELLED,
    },
    # Terminal states -- no outgoing transitions.
    InvestigationStatus.COMPLETED: set(),
    InvestigationStatus.FAILED: set(),
    InvestigationStatus.CANCELLED: set(),
}


@dataclass
class Investigation:
    """Investigation entity (cached in-memory, persisted in PostgreSQL).

    Attributes:
        id: Unique identifier (``inv-{hex[:8]}``).
        objective: User-supplied investigation objective.
        status: Current lifecycle state.
        params: Launch parameters (extraction_model, max_sources, etc.).
        created_at: UTC creation timestamp.
        updated_at: UTC timestamp of last status transition.
        error: Error message if status is FAILED.
        stats: Aggregate counts (articles, facts, verified, etc.).
    """

    id: str
    objective: str
    status: InvestigationStatus = InvestigationStatus.PENDING
    params: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime | None = None
    error: str | None = None
    stats: dict[str, int] = field(default_factory=dict)


class InvestigationRegistry:
    """PostgreSQL-backed investigation registry with in-memory cache.

    All investigations are keyed by ID. Status transitions use
    compare-and-swap semantics guarded by ``asyncio.Lock``.
    Mutations write-through to PostgreSQL via ``session_factory``.
    """

    def __init__(self, session_factory: Any | None = None) -> None:
        self._investigations: dict[str, Investigation] = {}
        self._lock = asyncio.Lock()
        self._session_factory = session_factory

    async def hydrate_from_db(self) -> int:
        """Load all investigations from PostgreSQL into memory cache.

        Call once on server startup after init_db(). Returns count loaded.
        """
        if self._session_factory is None:
            return 0

        from osint_system.data_management.models.investigation import (
            InvestigationModel,
        )
        from sqlalchemy import select

        count = 0
        try:
            async with self._session_factory() as session:
                result = await session.execute(
                    select(InvestigationModel).order_by(
                        InvestigationModel.created_at.desc()
                    )
                )
                for row in result.scalars().all():
                    try:
                        status = InvestigationStatus(row.status)
                    except ValueError:
                        status = InvestigationStatus.COMPLETED

                    inv = Investigation(
                        id=row.investigation_id,
                        objective=row.objective,
                        status=status,
                        params=row.params or {},
                        created_at=row.started_at or row.created_at or datetime.now(timezone.utc),
                        updated_at=row.completed_at,
                        error=row.error,
                        stats=row.stats or {},
                    )
                    self._investigations[inv.id] = inv
                    count += 1

            logger.info("registry_hydrated", count=count)
        except Exception as e:
            logger.warning("registry_hydration_failed", error=str(e))

        return count

    def create(
        self,
        objective: str,
        params: dict[str, Any] | None = None,
        investigation_id: str | None = None,
    ) -> Investigation:
        """Create a new investigation in PENDING state.

        Persists to PostgreSQL if session_factory is available.
        """
        inv_id = investigation_id or f"inv-{uuid.uuid4().hex[:8]}"
        investigation = Investigation(
            id=inv_id,
            objective=objective,
            params=params or {},
        )
        self._investigations[inv_id] = investigation

        # Fire-and-forget persist (will be awaited by caller if needed)
        if self._session_factory is not None:
            asyncio.ensure_future(self._persist_create(investigation))

        return investigation

    async def _persist_create(self, inv: Investigation) -> None:
        """Write new investigation to PostgreSQL."""
        from osint_system.data_management.models.investigation import (
            InvestigationModel,
        )

        try:
            async with self._session_factory() as session:
                async with session.begin():
                    model = InvestigationModel.from_investigation(inv)
                    session.add(model)
            logger.debug("investigation_persisted", id=inv.id)
        except Exception as e:
            logger.warning("investigation_persist_failed", id=inv.id, error=str(e))

    def get(self, investigation_id: str) -> Investigation | None:
        """Retrieve an investigation by ID.

        Returns None if not found (caller decides whether to raise 404).
        """
        return self._investigations.get(investigation_id)

    def list_all(self) -> list[Investigation]:
        """Return all investigations sorted by created_at descending."""
        return sorted(
            self._investigations.values(),
            key=lambda inv: inv.created_at,
            reverse=True,
        )

    async def transition(
        self,
        investigation_id: str,
        expected_status: InvestigationStatus,
        new_status: InvestigationStatus,
        error: str | None = None,
        stats: dict[str, int] | None = None,
    ) -> Investigation:
        """Atomically transition investigation status with compare-and-swap.

        Writes through to PostgreSQL after in-memory update.
        """
        async with self._lock:
            investigation = self._investigations.get(investigation_id)
            if investigation is None:
                raise ConflictError(
                    detail=f"Investigation '{investigation_id}' does not exist.",
                )

            if investigation.status != expected_status:
                raise ConflictError(
                    detail=(
                        f"Expected status '{expected_status.value}' but "
                        f"current status is '{investigation.status.value}'."
                    ),
                )

            allowed = _VALID_TRANSITIONS.get(expected_status, set())
            if new_status not in allowed:
                raise ConflictError(
                    detail=(
                        f"Transition from '{expected_status.value}' to "
                        f"'{new_status.value}' is not allowed."
                    ),
                )

            investigation.status = new_status
            investigation.updated_at = datetime.now(timezone.utc)

            if error is not None:
                investigation.error = error

            if stats is not None:
                investigation.stats.update(stats)

        # Persist outside lock
        await self._persist_transition(investigation)

        return investigation

    async def _persist_transition(self, inv: Investigation) -> None:
        """Update investigation in PostgreSQL after status transition."""
        if self._session_factory is None:
            return

        from osint_system.data_management.models.investigation import (
            InvestigationModel,
        )
        from sqlalchemy import update

        try:
            async with self._session_factory() as session:
                async with session.begin():
                    await session.execute(
                        update(InvestigationModel)
                        .where(
                            InvestigationModel.investigation_id == inv.id
                        )
                        .values(
                            status=inv.status.value,
                            completed_at=inv.updated_at,
                            error=inv.error,
                            stats=inv.stats,
                        )
                    )
        except Exception as e:
            logger.warning(
                "investigation_transition_persist_failed",
                id=inv.id,
                error=str(e),
            )

    def delete(self, investigation_id: str) -> bool:
        """Remove an investigation from the registry and PostgreSQL."""
        if investigation_id in self._investigations:
            del self._investigations[investigation_id]

            if self._session_factory is not None:
                asyncio.ensure_future(
                    self._persist_delete(investigation_id)
                )
            return True
        return False

    async def _persist_delete(self, investigation_id: str) -> None:
        """Delete investigation from PostgreSQL."""
        from osint_system.data_management.models.investigation import (
            InvestigationModel,
        )
        from sqlalchemy import delete

        try:
            async with self._session_factory() as session:
                async with session.begin():
                    await session.execute(
                        delete(InvestigationModel).where(
                            InvestigationModel.investigation_id
                            == investigation_id
                        )
                    )
        except Exception as e:
            logger.warning(
                "investigation_delete_persist_failed",
                id=investigation_id,
                error=str(e),
            )
