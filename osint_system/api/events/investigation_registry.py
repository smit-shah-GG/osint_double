"""Investigation lifecycle tracking with atomic status transitions.

The ``InvestigationRegistry`` is the API-layer entity that tracks
investigation status, parameters, and timestamps.  It is separate from
the store-level data (FactStore, ArticleStore, etc.) -- those track
pipeline artifacts, this tracks the investigation lifecycle.

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

from osint_system.api.errors import ConflictError


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
    """In-memory investigation entity.

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
    """In-memory investigation registry with atomic status transitions.

    All investigations are keyed by ID.  Status transitions use
    compare-and-swap semantics guarded by ``asyncio.Lock`` to prevent
    concurrent mutation races (Pitfall 4 from RESEARCH.md).
    """

    def __init__(self) -> None:
        self._investigations: dict[str, Investigation] = {}
        self._lock = asyncio.Lock()

    def create(
        self,
        objective: str,
        params: dict[str, Any] | None = None,
        investigation_id: str | None = None,
    ) -> Investigation:
        """Create a new investigation in PENDING state.

        Args:
            objective: Investigation objective text.
            params: Optional launch parameters dict.
            investigation_id: Optional explicit ID.  If None, generates
                ``inv-{uuid_hex[:8]}``.

        Returns:
            The created Investigation dataclass.
        """
        inv_id = investigation_id or f"inv-{uuid.uuid4().hex[:8]}"
        investigation = Investigation(
            id=inv_id,
            objective=objective,
            params=params or {},
        )
        self._investigations[inv_id] = investigation
        return investigation

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

        Acquires ``asyncio.Lock``, verifies current status matches
        ``expected_status``, validates the transition is allowed, then
        applies the new status.

        Args:
            investigation_id: Investigation to transition.
            expected_status: The status the investigation MUST currently have.
            new_status: The target status.
            error: Error message (set when transitioning to FAILED).
            stats: Aggregate stats dict to merge.

        Returns:
            The updated Investigation.

        Raises:
            ConflictError: If current status != expected_status, or if the
                transition is not in the valid transition graph.
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

            return investigation

    def delete(self, investigation_id: str) -> bool:
        """Remove an investigation from the registry.

        Returns True if the investigation existed and was deleted.
        """
        if investigation_id in self._investigations:
            del self._investigations[investigation_id]
            return True
        return False
