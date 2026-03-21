"""In-memory pub/sub event bus with per-investigation storage and replay.

The ``PipelineEventBus`` stores all emitted events per investigation so that:
1. SSE clients reconnecting with ``Last-Event-ID`` can replay missed events.
2. Clients connecting after pipeline completion see the full event history.
3. Live subscribers receive events via ``asyncio.Queue.put_nowait``.

Typical event volume is ~20-30 events per investigation run, so in-memory
storage is appropriate.  Phase 13 (SQLite migration) may persist events to
disk if needed.
"""

from __future__ import annotations

import asyncio
from typing import Any

from osint_system.api.events.event_models import PipelineEvent


class PipelineEventBus:
    """In-memory event bus with per-investigation event storage and replay.

    Thread safety: All mutations are synchronous dict operations called from
    a single asyncio event loop.  No lock is needed because ``emit``,
    ``subscribe``, ``unsubscribe``, ``clear`` are all synchronous and the
    GIL protects dict mutations.  ``asyncio.Queue`` is itself thread-safe.
    """

    def __init__(self) -> None:
        self._events: dict[str, list[PipelineEvent]] = {}
        self._subscribers: dict[str, list[asyncio.Queue[PipelineEvent]]] = {}
        self._counters: dict[str, int] = {}

    def emit(
        self,
        investigation_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> PipelineEvent:
        """Emit an event for an investigation.

        Stores the event for replay and pushes it to all active subscriber
        queues via ``put_nowait``.

        Args:
            investigation_id: Investigation scope.
            event_type: Event type string (e.g. ``"phase_started"``).
            data: Event payload.  All values MUST be JSON-serializable
                primitives (str, int, float, bool, None, list, dict).

        Returns:
            The created ``PipelineEvent`` with auto-incremented ID.
        """
        if investigation_id not in self._events:
            self._events[investigation_id] = []
            self._counters[investigation_id] = 0

        self._counters[investigation_id] += 1
        event = PipelineEvent(
            id=self._counters[investigation_id],
            event_type=event_type,
            data=data,
        )
        self._events[investigation_id].append(event)

        # Push to all active subscribers
        for queue in self._subscribers.get(investigation_id, []):
            queue.put_nowait(event)

        return event

    def subscribe(self, investigation_id: str) -> asyncio.Queue[PipelineEvent]:
        """Create a new subscriber queue for an investigation.

        The returned queue receives all events emitted after this call.
        Call ``unsubscribe`` to remove the queue when done.

        Args:
            investigation_id: Investigation to subscribe to.

        Returns:
            An asyncio.Queue that will receive future PipelineEvent instances.
        """
        if investigation_id not in self._subscribers:
            self._subscribers[investigation_id] = []
        queue: asyncio.Queue[PipelineEvent] = asyncio.Queue()
        self._subscribers[investigation_id].append(queue)
        return queue

    def unsubscribe(
        self,
        investigation_id: str,
        queue: asyncio.Queue[PipelineEvent],
    ) -> None:
        """Remove a subscriber queue.

        Safe to call even if the queue was already removed or never added.

        Args:
            investigation_id: Investigation scope.
            queue: The queue to remove.
        """
        if investigation_id in self._subscribers:
            self._subscribers[investigation_id] = [
                q for q in self._subscribers[investigation_id] if q is not queue
            ]

    def get_events_since(
        self,
        investigation_id: str,
        last_event_id: int,
    ) -> list[PipelineEvent]:
        """Return events with ``id > last_event_id`` for replay.

        Used when an SSE client reconnects with ``Last-Event-ID``.

        Args:
            investigation_id: Investigation scope.
            last_event_id: Return events after this ID.

        Returns:
            List of events with id > last_event_id, in emission order.
        """
        events = self._events.get(investigation_id, [])
        return [e for e in events if e.id > last_event_id]

    def get_all_events(self, investigation_id: str) -> list[PipelineEvent]:
        """Return full event history for an investigation.

        Used for post-completion replay when a client connects after the
        pipeline has already finished.

        Args:
            investigation_id: Investigation scope.

        Returns:
            Copy of the full event list (safe to iterate without mutation).
        """
        return list(self._events.get(investigation_id, []))

    def clear(self, investigation_id: str) -> None:
        """Remove all events and subscribers for an investigation.

        Called during investigation cleanup to release memory.

        Args:
            investigation_id: Investigation to clear.
        """
        self._events.pop(investigation_id, None)
        self._subscribers.pop(investigation_id, None)
        self._counters.pop(investigation_id, None)
