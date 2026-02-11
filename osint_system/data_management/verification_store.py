"""Verification result storage with investigation-scoped persistence.

Follows same patterns as ClassificationStore and FactStore:
- Investigation-based organization (investigation_id as primary key)
- O(1) lookup by fact_id
- Thread-safe operations with asyncio locks
- Optional JSON persistence for beta

Usage:
    from osint_system.data_management.verification_store import VerificationStore

    store = VerificationStore()
    await store.save_result(verification_result)
    result = await store.get_result("inv-1", "fact-001")
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import structlog

from osint_system.data_management.schemas.verification_schema import (
    VerificationResult,
    VerificationResultRecord,
    VerificationStatus,
)


class VerificationStore:
    """Storage for verification results with investigation-scoped access.

    Data structure:
    {
        investigation_id: {
            fact_id: VerificationResultRecord,
            ...
        },
        ...
    }
    """

    def __init__(self, persistence_path: Optional[str] = None) -> None:
        """Initialize VerificationStore.

        Args:
            persistence_path: Optional path to JSON file for persistence.
                            If None, storage is memory-only.
        """
        self._results: dict[str, dict[str, VerificationResultRecord]] = {}
        self._lock = asyncio.Lock()
        self._persistence_path = Path(persistence_path) if persistence_path else None
        self._logger = structlog.get_logger().bind(component="VerificationStore")

    async def save_result(self, result: VerificationResult) -> None:
        """Save a verification result.

        Creates VerificationResultRecord from result and stores by
        investigation_id and fact_id.

        Args:
            result: VerificationResult to store.
        """
        async with self._lock:
            inv_id = result.investigation_id
            if inv_id not in self._results:
                self._results[inv_id] = {}

            record = VerificationResultRecord.from_result(result)
            self._results[inv_id][result.fact_id] = record

            self._logger.debug(
                "result_saved",
                fact_id=result.fact_id,
                investigation_id=inv_id,
                status=result.status.value,
            )

            if self._persistence_path:
                self._save_to_file()

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
        async with self._lock:
            inv = self._results.get(investigation_id, {})
            return inv.get(fact_id)

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
        async with self._lock:
            inv = self._results.get(investigation_id, {})
            return list(inv.values())

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
        async with self._lock:
            inv = self._results.get(investigation_id, {})
            return [r for r in inv.values() if r.status == status]

    async def get_pending_review(
        self,
        investigation_id: str,
    ) -> list[VerificationResultRecord]:
        """Get results pending human review.

        Returns results where requires_human_review=True AND
        human_review_completed=False.

        Args:
            investigation_id: Investigation scope.

        Returns:
            List of VerificationResultRecord objects awaiting review.
        """
        async with self._lock:
            inv = self._results.get(investigation_id, {})
            return [
                r
                for r in inv.values()
                if r.requires_human_review and not r.human_review_completed
            ]

    async def mark_reviewed(
        self,
        investigation_id: str,
        fact_id: str,
        notes: Optional[str] = None,
    ) -> bool:
        """Mark a result as human-reviewed.

        Args:
            investigation_id: Investigation scope.
            fact_id: Fact identifier.
            notes: Optional reviewer notes.

        Returns:
            True if marked, False if result not found.
        """
        async with self._lock:
            inv = self._results.get(investigation_id, {})
            record = inv.get(fact_id)
            if record is None:
                return False

            record.human_review_completed = True
            if notes:
                record.human_reviewer_notes = notes
            record.updated_at = datetime.now(timezone.utc)

            if self._persistence_path:
                self._save_to_file()

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
        async with self._lock:
            inv = self._results.get(investigation_id, {})
            if not inv:
                return {"total": 0, "investigation_id": investigation_id}

            status_counts: dict[str, int] = {}
            for record in inv.values():
                status_val = record.status.value if hasattr(record.status, "value") else str(record.status)
                status_counts[status_val] = status_counts.get(status_val, 0) + 1

            pending_review = sum(
                1
                for r in inv.values()
                if r.requires_human_review and not r.human_review_completed
            )

            return {
                "investigation_id": investigation_id,
                "total": len(inv),
                "status_counts": status_counts,
                "pending_review": pending_review,
            }

    def _save_to_file(self) -> None:
        """Save to JSON file (synchronous)."""
        if not self._persistence_path:
            return
        try:
            self._persistence_path.parent.mkdir(parents=True, exist_ok=True)
            data: dict[str, Any] = {}
            for inv_id, records in self._results.items():
                data[inv_id] = {
                    fid: record.model_dump(mode="json")
                    for fid, record in records.items()
                }
            with open(self._persistence_path, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            self._logger.error("persistence_failed", error=str(e))
