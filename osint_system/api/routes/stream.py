"""SSE event streaming endpoint with replay and reconnection support.

Uses FastAPI built-in ``fastapi.sse.EventSourceResponse`` and
``fastapi.sse.ServerSentEvent`` (available since FastAPI 0.135.0).
No ``sse-starlette`` dependency required.

The endpoint supports three modes:
1. **Live streaming**: Subscribe for events as they emit (running investigations).
2. **Replay on reconnect**: ``Last-Event-ID`` header replays missed events.
3. **Post-completion**: Completed investigations replay full history then close.

Per RESEARCH.md Pitfall 2, the generator MUST check for terminal event types
and break, otherwise the SSE connection stays open forever.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated

import structlog
from fastapi import APIRouter, Header, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent

from osint_system.api.events.investigation_registry import InvestigationStatus

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1")

# Terminal event types that signal the SSE stream should close.
_TERMINAL_EVENT_TYPES = frozenset({"pipeline_completed", "pipeline_error"})


@router.get(
    "/investigations/{investigation_id}/stream",
    response_class=EventSourceResponse,
)
async def stream_events(
    request: Request,
    investigation_id: str,
    last_event_id: Annotated[int | None, Header(alias="Last-Event-ID")] = None,
) -> AsyncIterator[ServerSentEvent]:
    """Stream pipeline events via Server-Sent Events.

    Supports ``Last-Event-ID`` header for reconnection replay and
    post-completion access.  The stream closes after delivering a
    terminal event (``pipeline_completed`` or ``pipeline_error``).
    """
    event_bus = request.app.state.event_bus
    registry = request.app.state.investigation_registry

    investigation = registry.get(investigation_id)
    if investigation is None:
        yield ServerSentEvent(
            raw_data=json.dumps({"error": "Investigation not found"}),
            event="error",
        )
        return

    # Replay missed events (reconnection or post-completion)
    start_id = last_event_id or 0
    missed = event_bus.get_events_since(investigation_id, start_id)
    for event in missed:
        yield ServerSentEvent(
            raw_data=json.dumps(event.data, default=str),
            event=event.event_type,
            id=str(event.id),
        )

    # If pipeline already reached a terminal state, close after replay.
    # The client gets the full history and knows the pipeline is done.
    if investigation.status in (
        InvestigationStatus.COMPLETED,
        InvestigationStatus.FAILED,
        InvestigationStatus.CANCELLED,
    ):
        return

    # Subscribe for live events
    queue = event_bus.subscribe(investigation_id)
    try:
        while True:
            # Check for client disconnect
            if await request.is_disconnected():
                logger.debug(
                    "sse_client_disconnected",
                    investigation_id=investigation_id,
                )
                break

            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                # FastAPI built-in EventSourceResponse handles 15s heartbeat
                # pings automatically. This timeout just prevents the queue.get()
                # from blocking indefinitely so we can check is_disconnected().
                continue

            yield ServerSentEvent(
                raw_data=json.dumps(event.data, default=str),
                event=event.event_type,
                id=str(event.id),
            )

            # Break on terminal event (Pitfall 2: must close on completion)
            if event.event_type in _TERMINAL_EVENT_TYPES:
                break

    finally:
        event_bus.unsubscribe(investigation_id, queue)
