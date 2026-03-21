"""Tests for PipelineEventBus: emit, subscribe, unsubscribe, replay, clear."""

from __future__ import annotations

import asyncio

import pytest

from osint_system.api.events.event_bus import PipelineEventBus
from osint_system.api.events.event_models import EventType


INV_ID = "inv-test0001"


class TestEmit:
    """Event emission and storage."""

    def test_emit_stores_event_and_increments_counter(self) -> None:
        bus = PipelineEventBus()
        e1 = bus.emit(INV_ID, EventType.PHASE_STARTED.value, {"phase": "crawl"})
        e2 = bus.emit(INV_ID, EventType.PHASE_PROGRESS.value, {"articles": 10})

        assert e1.id == 1
        assert e2.id == 2
        assert e1.event_type == "phase_started"
        assert e2.data["articles"] == 10

    def test_emit_separate_investigations_have_independent_counters(self) -> None:
        bus = PipelineEventBus()
        e1 = bus.emit("inv-aaa", "phase_started", {"phase": "crawl"})
        e2 = bus.emit("inv-bbb", "phase_started", {"phase": "crawl"})
        assert e1.id == 1
        assert e2.id == 1  # Independent counter

    def test_emit_returns_event_with_timestamp(self) -> None:
        bus = PipelineEventBus()
        event = bus.emit(INV_ID, "phase_started", {})
        assert event.timestamp is not None


class TestSubscribe:
    """Subscriber queue delivery."""

    @pytest.mark.asyncio
    async def test_subscribe_receives_emitted_events(self) -> None:
        bus = PipelineEventBus()
        queue = bus.subscribe(INV_ID)

        bus.emit(INV_ID, "phase_started", {"phase": "crawl"})
        bus.emit(INV_ID, "phase_completed", {"phase": "crawl"})

        e1 = queue.get_nowait()
        e2 = queue.get_nowait()
        assert e1.event_type == "phase_started"
        assert e2.event_type == "phase_completed"
        assert queue.empty()

    @pytest.mark.asyncio
    async def test_multiple_subscribers_each_receive_same_event(self) -> None:
        bus = PipelineEventBus()
        q1 = bus.subscribe(INV_ID)
        q2 = bus.subscribe(INV_ID)

        bus.emit(INV_ID, "phase_started", {"phase": "extract"})

        e1 = q1.get_nowait()
        e2 = q2.get_nowait()
        assert e1.id == e2.id
        assert e1.event_type == e2.event_type

    @pytest.mark.asyncio
    async def test_subscriber_does_not_receive_other_investigation_events(self) -> None:
        bus = PipelineEventBus()
        queue = bus.subscribe("inv-aaa")

        bus.emit("inv-bbb", "phase_started", {})

        assert queue.empty()


class TestUnsubscribe:
    """Unsubscribe stops event delivery."""

    @pytest.mark.asyncio
    async def test_unsubscribe_stops_delivery(self) -> None:
        bus = PipelineEventBus()
        queue = bus.subscribe(INV_ID)

        bus.emit(INV_ID, "phase_started", {})
        assert not queue.empty()

        # Drain the queue
        queue.get_nowait()

        bus.unsubscribe(INV_ID, queue)
        bus.emit(INV_ID, "phase_completed", {})

        assert queue.empty()

    @pytest.mark.asyncio
    async def test_unsubscribe_idempotent(self) -> None:
        """Unsubscribing a queue that's already removed should not raise."""
        bus = PipelineEventBus()
        queue = bus.subscribe(INV_ID)
        bus.unsubscribe(INV_ID, queue)
        bus.unsubscribe(INV_ID, queue)  # Second call should be safe

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent_investigation(self) -> None:
        """Unsubscribing from an investigation with no subscribers should not raise."""
        bus = PipelineEventBus()
        queue: asyncio.Queue = asyncio.Queue()
        bus.unsubscribe("inv-nonexistent", queue)  # Should not raise


class TestReplay:
    """Event replay via get_events_since and get_all_events."""

    def test_get_events_since_returns_only_events_after_given_id(self) -> None:
        bus = PipelineEventBus()
        bus.emit(INV_ID, "phase_started", {"phase": "crawl"})
        bus.emit(INV_ID, "phase_completed", {"phase": "crawl"})
        bus.emit(INV_ID, "phase_started", {"phase": "extract"})

        events = bus.get_events_since(INV_ID, last_event_id=1)
        assert len(events) == 2
        assert events[0].id == 2
        assert events[1].id == 3

    def test_get_events_since_zero_returns_all(self) -> None:
        bus = PipelineEventBus()
        bus.emit(INV_ID, "phase_started", {})
        bus.emit(INV_ID, "phase_completed", {})

        events = bus.get_events_since(INV_ID, last_event_id=0)
        assert len(events) == 2

    def test_get_events_since_nonexistent_investigation(self) -> None:
        bus = PipelineEventBus()
        events = bus.get_events_since("inv-nonexistent", last_event_id=0)
        assert events == []

    def test_get_all_events_returns_full_history(self) -> None:
        bus = PipelineEventBus()
        bus.emit(INV_ID, "phase_started", {"phase": "crawl"})
        bus.emit(INV_ID, "phase_completed", {"phase": "crawl"})

        events = bus.get_all_events(INV_ID)
        assert len(events) == 2
        assert events[0].id == 1
        assert events[1].id == 2

    def test_get_all_events_returns_copy(self) -> None:
        """Returned list should be a copy, not a reference to internals."""
        bus = PipelineEventBus()
        bus.emit(INV_ID, "phase_started", {})

        events = bus.get_all_events(INV_ID)
        events.clear()  # Mutate the returned list

        assert len(bus.get_all_events(INV_ID)) == 1  # Original intact

    def test_get_all_events_nonexistent_investigation(self) -> None:
        bus = PipelineEventBus()
        assert bus.get_all_events("inv-nonexistent") == []


class TestClear:
    """Clear removes all events and subscribers for an investigation."""

    @pytest.mark.asyncio
    async def test_clear_removes_all_events(self) -> None:
        bus = PipelineEventBus()
        bus.emit(INV_ID, "phase_started", {})
        bus.emit(INV_ID, "phase_completed", {})
        bus.subscribe(INV_ID)

        bus.clear(INV_ID)

        assert bus.get_all_events(INV_ID) == []
        # Counter should also be cleared -- next emit starts from 1
        e = bus.emit(INV_ID, "phase_started", {})
        assert e.id == 1

    @pytest.mark.asyncio
    async def test_clear_nonexistent_investigation(self) -> None:
        """Clearing a nonexistent investigation should not raise."""
        bus = PipelineEventBus()
        bus.clear("inv-nonexistent")
