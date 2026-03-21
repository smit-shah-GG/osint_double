"""Tests for SSE event streaming endpoint.

Tests SSE behavior by pre-populating the event bus, setting investigation
status, and parsing the raw ``text/event-stream`` response from httpx.

FastAPI's SSE rendering converts ``ServerSentEvent`` objects into the SSE
wire format:  ``event: <type>\ndata: <json>\nid: <id>\n\n``
"""

from __future__ import annotations

import json
import re

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from osint_system.api.errors import register_error_handlers
from osint_system.api.events.event_bus import PipelineEventBus
from osint_system.api.events.investigation_registry import (
    InvestigationRegistry,
    InvestigationStatus,
)
from osint_system.api.routes.stream import router


# ── Helpers ──────────────────────────────────────────────────────────


def _parse_sse_events(raw: str) -> list[dict[str, str]]:
    """Parse raw SSE text into a list of event dicts.

    Each dict may have keys: ``event``, ``data``, ``id``, ``comment``.
    Handles the standard SSE format: ``field: value`` lines separated
    by double newlines.
    """
    events: list[dict[str, str]] = []
    # Split on double newlines to get individual events
    # Filter out empty strings and ping-only blocks
    blocks = re.split(r"\n\n+", raw.strip())

    for block in blocks:
        if not block.strip():
            continue
        event: dict[str, str] = {}
        for line in block.strip().split("\n"):
            if line.startswith(":"):
                # SSE comment (heartbeat ping)
                event["comment"] = line[1:].strip()
                continue
            if ":" in line:
                field, _, value = line.partition(":")
                value = value.lstrip(" ")  # SSE spec: strip leading space
                if field in event:
                    # Append for multi-line data fields
                    event[field] += "\n" + value
                else:
                    event[field] = value
        if event and any(k in event for k in ("data", "event", "id")):
            events.append(event)

    return events


# ── Fixtures ─────────────────────────────────────────────────────────


def _make_app() -> FastAPI:
    """Create a minimal FastAPI app with the stream router."""
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router)

    app.state.event_bus = PipelineEventBus()
    app.state.investigation_registry = InvestigationRegistry()

    return app


@pytest.fixture
def app() -> FastAPI:
    return _make_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── Tests: Non-existent investigation ────────────────────────────────


@pytest.mark.anyio
async def test_stream_nonexistent_returns_error_event(client: AsyncClient) -> None:
    """Stream for nonexistent investigation should yield error event."""
    resp = await client.get("/api/v1/investigations/inv-nope/stream")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")

    events = _parse_sse_events(resp.text)
    assert len(events) >= 1
    error_events = [e for e in events if e.get("event") == "error"]
    assert len(error_events) == 1
    data = json.loads(error_events[0]["data"])
    assert "not found" in data["error"].lower()


# ── Tests: Replay for completed investigation ────────────────────────


@pytest.mark.anyio
async def test_stream_replays_completed_investigation(app: FastAPI) -> None:
    """Stream for completed investigation should replay all events and close."""
    registry = app.state.investigation_registry
    event_bus = app.state.event_bus

    inv = registry.create(objective="Replay test", investigation_id="inv-replay")
    await registry.transition(
        inv.id,
        expected_status=InvestigationStatus.PENDING,
        new_status=InvestigationStatus.RUNNING,
    )

    # Pre-populate events
    event_bus.emit(inv.id, "phase_started", {"phase": "crawl"})
    event_bus.emit(inv.id, "phase_completed", {"phase": "crawl", "elapsed_ms": 100})
    event_bus.emit(inv.id, "phase_started", {"phase": "extract"})
    event_bus.emit(inv.id, "phase_completed", {"phase": "extract", "elapsed_ms": 200})
    event_bus.emit(inv.id, "pipeline_completed", {"facts": 10})

    # Transition to completed
    await registry.transition(
        inv.id,
        expected_status=InvestigationStatus.RUNNING,
        new_status=InvestigationStatus.COMPLETED,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/investigations/{inv.id}/stream")

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)

    # Should have replayed all 5 events
    assert len(events) >= 5

    # Verify event types are in order
    event_types = [e.get("event") for e in events if e.get("event")]
    assert "phase_started" in event_types
    assert "phase_completed" in event_types
    assert "pipeline_completed" in event_types


@pytest.mark.anyio
async def test_stream_replay_preserves_event_order(app: FastAPI) -> None:
    """Replayed events should maintain emission order."""
    registry = app.state.investigation_registry
    event_bus = app.state.event_bus

    inv = registry.create(objective="Order test", investigation_id="inv-order")
    await registry.transition(
        inv.id,
        expected_status=InvestigationStatus.PENDING,
        new_status=InvestigationStatus.RUNNING,
    )

    for i in range(5):
        event_bus.emit(inv.id, "phase_progress", {"step": i})
    event_bus.emit(inv.id, "pipeline_completed", {"done": True})

    await registry.transition(
        inv.id,
        expected_status=InvestigationStatus.RUNNING,
        new_status=InvestigationStatus.COMPLETED,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/investigations/{inv.id}/stream")

    events = _parse_sse_events(resp.text)
    ids = [int(e["id"]) for e in events if "id" in e]
    assert ids == sorted(ids), f"Event IDs not in order: {ids}"


# ── Tests: Last-Event-ID replay ──────────────────────────────────────


@pytest.mark.anyio
async def test_stream_last_event_id_replays_from_point(app: FastAPI) -> None:
    """Last-Event-ID header should replay only events after that ID."""
    registry = app.state.investigation_registry
    event_bus = app.state.event_bus

    inv = registry.create(objective="Reconnect test", investigation_id="inv-reconnect")
    await registry.transition(
        inv.id,
        expected_status=InvestigationStatus.PENDING,
        new_status=InvestigationStatus.RUNNING,
    )

    # Emit 5 events (IDs 1-5)
    for i in range(5):
        event_bus.emit(inv.id, "phase_progress", {"step": i})
    event_bus.emit(inv.id, "pipeline_completed", {"done": True})

    await registry.transition(
        inv.id,
        expected_status=InvestigationStatus.RUNNING,
        new_status=InvestigationStatus.COMPLETED,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Request replay from event ID 3 (should get events 4, 5, 6)
        resp = await client.get(
            f"/api/v1/investigations/{inv.id}/stream",
            headers={"Last-Event-ID": "3"},
        )

    events = _parse_sse_events(resp.text)
    ids = [int(e["id"]) for e in events if "id" in e]
    assert all(eid > 3 for eid in ids), f"Should only have IDs > 3, got: {ids}"
    assert len(ids) == 3  # Events 4, 5, 6


# ── Tests: Event format ─────────────────────────────────────────────


@pytest.mark.anyio
async def test_stream_event_format_has_correct_fields(app: FastAPI) -> None:
    """Each SSE event should have data, event, and id fields."""
    registry = app.state.investigation_registry
    event_bus = app.state.event_bus

    inv = registry.create(objective="Format test", investigation_id="inv-format")
    await registry.transition(
        inv.id,
        expected_status=InvestigationStatus.PENDING,
        new_status=InvestigationStatus.RUNNING,
    )

    event_bus.emit(inv.id, "phase_started", {"phase": "crawl"})
    event_bus.emit(inv.id, "pipeline_completed", {"facts": 42})

    await registry.transition(
        inv.id,
        expected_status=InvestigationStatus.RUNNING,
        new_status=InvestigationStatus.COMPLETED,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/investigations/{inv.id}/stream")

    events = _parse_sse_events(resp.text)
    for event in events:
        assert "data" in event, f"Event missing 'data': {event}"
        assert "event" in event, f"Event missing 'event': {event}"
        assert "id" in event, f"Event missing 'id': {event}"
        # Data should be valid JSON
        parsed = json.loads(event["data"])
        assert isinstance(parsed, dict)


@pytest.mark.anyio
async def test_stream_event_data_is_json_serializable(app: FastAPI) -> None:
    """Event data containing non-standard types should still serialize."""
    registry = app.state.investigation_registry
    event_bus = app.state.event_bus

    inv = registry.create(objective="Serialization test", investigation_id="inv-serial")
    await registry.transition(
        inv.id,
        expected_status=InvestigationStatus.PENDING,
        new_status=InvestigationStatus.RUNNING,
    )

    # Emit event with data that has nested values
    event_bus.emit(inv.id, "phase_completed", {
        "phase": "extract",
        "elapsed_ms": 1500,
        "facts_extracted": 10,
        "articles_processed": 5,
    })
    event_bus.emit(inv.id, "pipeline_completed", {"total_facts": 10})

    await registry.transition(
        inv.id,
        expected_status=InvestigationStatus.RUNNING,
        new_status=InvestigationStatus.COMPLETED,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/investigations/{inv.id}/stream")

    events = _parse_sse_events(resp.text)
    phase_events = [e for e in events if e.get("event") == "phase_completed"]
    assert len(phase_events) == 1
    data = json.loads(phase_events[0]["data"])
    assert data["phase"] == "extract"
    assert data["elapsed_ms"] == 1500


# ── Tests: Failed investigation replay ───────────────────────────────


@pytest.mark.anyio
async def test_stream_replays_failed_investigation(app: FastAPI) -> None:
    """Stream for failed investigation should replay events and close."""
    registry = app.state.investigation_registry
    event_bus = app.state.event_bus

    inv = registry.create(objective="Failed test", investigation_id="inv-failed")
    await registry.transition(
        inv.id,
        expected_status=InvestigationStatus.PENDING,
        new_status=InvestigationStatus.RUNNING,
    )

    event_bus.emit(inv.id, "phase_started", {"phase": "crawl"})
    event_bus.emit(inv.id, "pipeline_error", {"error": "Something broke"})

    await registry.transition(
        inv.id,
        expected_status=InvestigationStatus.RUNNING,
        new_status=InvestigationStatus.FAILED,
        error="Something broke",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/investigations/{inv.id}/stream")

    events = _parse_sse_events(resp.text)
    assert len(events) >= 2
    error_events = [e for e in events if e.get("event") == "pipeline_error"]
    assert len(error_events) == 1
    data = json.loads(error_events[0]["data"])
    assert data["error"] == "Something broke"


# ── Tests: Route count ───────────────────────────────────────────────


def test_stream_router_has_one_route() -> None:
    """Stream router should have exactly 1 route."""
    assert len(router.routes) == 1
