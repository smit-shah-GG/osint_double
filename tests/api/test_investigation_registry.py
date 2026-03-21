"""Tests for InvestigationRegistry: create, get, list, transition, delete."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from osint_system.api.errors import ConflictError
from osint_system.api.events.investigation_registry import (
    Investigation,
    InvestigationRegistry,
    InvestigationStatus,
)


class TestCreate:
    """Investigation creation."""

    def test_create_generates_unique_ids(self) -> None:
        registry = InvestigationRegistry()
        inv1 = registry.create("Objective 1")
        inv2 = registry.create("Objective 2")
        assert inv1.id != inv2.id
        assert inv1.id.startswith("inv-")
        assert inv2.id.startswith("inv-")

    def test_create_stores_investigation(self) -> None:
        registry = InvestigationRegistry()
        inv = registry.create("Test objective")
        assert registry.get(inv.id) is inv

    def test_create_with_explicit_id(self) -> None:
        registry = InvestigationRegistry()
        inv = registry.create("Test", investigation_id="inv-explicit")
        assert inv.id == "inv-explicit"

    def test_create_default_status_is_pending(self) -> None:
        registry = InvestigationRegistry()
        inv = registry.create("Test")
        assert inv.status == InvestigationStatus.PENDING

    def test_create_with_params(self) -> None:
        registry = InvestigationRegistry()
        inv = registry.create(
            "Test",
            params={"extraction_model": "gemini-flash", "max_sources": 50},
        )
        assert inv.params["extraction_model"] == "gemini-flash"
        assert inv.params["max_sources"] == 50

    def test_create_sets_created_at(self) -> None:
        registry = InvestigationRegistry()
        before = datetime.now(timezone.utc)
        inv = registry.create("Test")
        after = datetime.now(timezone.utc)
        assert before <= inv.created_at <= after


class TestGet:
    """Investigation retrieval."""

    def test_get_returns_none_for_nonexistent_id(self) -> None:
        registry = InvestigationRegistry()
        assert registry.get("inv-nonexistent") is None

    def test_get_returns_existing_investigation(self) -> None:
        registry = InvestigationRegistry()
        inv = registry.create("Test")
        result = registry.get(inv.id)
        assert result is not None
        assert result.objective == "Test"


class TestListAll:
    """Investigation listing."""

    def test_list_all_returns_sorted_by_created_at_descending(self) -> None:
        registry = InvestigationRegistry()
        # Create in order with explicitly distinct timestamps to avoid
        # sub-microsecond equality on fast machines.
        inv1 = registry.create("First", investigation_id="inv-001")
        inv2 = registry.create("Second", investigation_id="inv-002")
        inv3 = registry.create("Third", investigation_id="inv-003")

        # Force distinct timestamps (the dataclass fields are mutable)
        inv1.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        inv2.created_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
        inv3.created_at = datetime(2026, 1, 3, tzinfo=timezone.utc)

        result = registry.list_all()
        assert len(result) == 3
        # Most recently created first
        assert result[0].id == "inv-003"
        assert result[2].id == "inv-001"

    def test_list_all_empty_registry(self) -> None:
        registry = InvestigationRegistry()
        assert registry.list_all() == []


class TestTransition:
    """Atomic status transitions with compare-and-swap."""

    @pytest.mark.asyncio
    async def test_transition_succeeds_with_correct_expected_status(self) -> None:
        registry = InvestigationRegistry()
        inv = registry.create("Test", investigation_id="inv-t1")

        updated = await registry.transition(
            "inv-t1",
            expected_status=InvestigationStatus.PENDING,
            new_status=InvestigationStatus.RUNNING,
        )
        assert updated.status == InvestigationStatus.RUNNING

    @pytest.mark.asyncio
    async def test_transition_raises_conflict_with_wrong_expected_status(self) -> None:
        registry = InvestigationRegistry()
        registry.create("Test", investigation_id="inv-t2")

        with pytest.raises(ConflictError) as exc_info:
            await registry.transition(
                "inv-t2",
                expected_status=InvestigationStatus.RUNNING,  # Wrong: actual is PENDING
                new_status=InvestigationStatus.COMPLETED,
            )
        assert "pending" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_transition_updates_updated_at_timestamp(self) -> None:
        registry = InvestigationRegistry()
        inv = registry.create("Test", investigation_id="inv-t3")
        assert inv.updated_at is None

        before = datetime.now(timezone.utc)
        updated = await registry.transition(
            "inv-t3",
            expected_status=InvestigationStatus.PENDING,
            new_status=InvestigationStatus.RUNNING,
        )
        after = datetime.now(timezone.utc)

        assert updated.updated_at is not None
        assert before <= updated.updated_at <= after

    @pytest.mark.asyncio
    async def test_transition_sets_error_on_failure(self) -> None:
        registry = InvestigationRegistry()
        registry.create("Test", investigation_id="inv-t4")

        await registry.transition(
            "inv-t4",
            expected_status=InvestigationStatus.PENDING,
            new_status=InvestigationStatus.RUNNING,
        )
        updated = await registry.transition(
            "inv-t4",
            expected_status=InvestigationStatus.RUNNING,
            new_status=InvestigationStatus.FAILED,
            error="Pipeline crashed during extraction",
        )
        assert updated.error == "Pipeline crashed during extraction"

    @pytest.mark.asyncio
    async def test_transition_merges_stats(self) -> None:
        registry = InvestigationRegistry()
        registry.create("Test", investigation_id="inv-t5")

        await registry.transition(
            "inv-t5",
            expected_status=InvestigationStatus.PENDING,
            new_status=InvestigationStatus.RUNNING,
            stats={"articles": 42},
        )
        inv = registry.get("inv-t5")
        assert inv is not None
        assert inv.stats["articles"] == 42

    @pytest.mark.asyncio
    async def test_invalid_transition_completed_to_running_raises_conflict(self) -> None:
        registry = InvestigationRegistry()
        registry.create("Test", investigation_id="inv-t6")

        # PENDING -> RUNNING
        await registry.transition(
            "inv-t6",
            expected_status=InvestigationStatus.PENDING,
            new_status=InvestigationStatus.RUNNING,
        )
        # RUNNING -> COMPLETED
        await registry.transition(
            "inv-t6",
            expected_status=InvestigationStatus.RUNNING,
            new_status=InvestigationStatus.COMPLETED,
        )
        # COMPLETED -> RUNNING (INVALID)
        with pytest.raises(ConflictError) as exc_info:
            await registry.transition(
                "inv-t6",
                expected_status=InvestigationStatus.COMPLETED,
                new_status=InvestigationStatus.RUNNING,
            )
        assert "not allowed" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_transition_nonexistent_investigation_raises_conflict(self) -> None:
        registry = InvestigationRegistry()
        with pytest.raises(ConflictError) as exc_info:
            await registry.transition(
                "inv-nonexistent",
                expected_status=InvestigationStatus.PENDING,
                new_status=InvestigationStatus.RUNNING,
            )
        assert "does not exist" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_valid_cancel_transitions(self) -> None:
        """Both PENDING->CANCELLED and RUNNING->CANCELLED are valid."""
        registry = InvestigationRegistry()

        # PENDING -> CANCELLED
        registry.create("Test A", investigation_id="inv-cancel-a")
        updated = await registry.transition(
            "inv-cancel-a",
            expected_status=InvestigationStatus.PENDING,
            new_status=InvestigationStatus.CANCELLED,
        )
        assert updated.status == InvestigationStatus.CANCELLED

        # RUNNING -> CANCELLED
        registry.create("Test B", investigation_id="inv-cancel-b")
        await registry.transition(
            "inv-cancel-b",
            expected_status=InvestigationStatus.PENDING,
            new_status=InvestigationStatus.RUNNING,
        )
        updated = await registry.transition(
            "inv-cancel-b",
            expected_status=InvestigationStatus.RUNNING,
            new_status=InvestigationStatus.CANCELLED,
        )
        assert updated.status == InvestigationStatus.CANCELLED


class TestDelete:
    """Investigation deletion."""

    def test_delete_removes_investigation(self) -> None:
        registry = InvestigationRegistry()
        inv = registry.create("Test")
        assert registry.delete(inv.id) is True
        assert registry.get(inv.id) is None

    def test_delete_returns_false_for_nonexistent(self) -> None:
        registry = InvestigationRegistry()
        assert registry.delete("inv-nonexistent") is False

    def test_delete_does_not_affect_other_investigations(self) -> None:
        registry = InvestigationRegistry()
        inv1 = registry.create("Keep this")
        inv2 = registry.create("Delete this")
        registry.delete(inv2.id)
        assert registry.get(inv1.id) is not None
