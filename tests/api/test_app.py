"""Tests for the API app factory (create_api_app).

Validates that the factory produces a fully configured FastAPI app with
all route modules mounted, CORS middleware active, RFC 7807 error handlers
registered, and app.state properly initialized.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from osint_system.api.app import create_api_app
from osint_system.api.events.event_bus import PipelineEventBus
from osint_system.api.events.investigation_registry import InvestigationRegistry


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def app() -> FastAPI:
    return create_api_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── App factory tests ────────────────────────────────────────────────


def test_create_api_app_returns_fastapi_instance() -> None:
    app = create_api_app()
    assert isinstance(app, FastAPI)


def test_app_metadata() -> None:
    app = create_api_app()
    assert app.title == "OSINT Intelligence System API"
    assert app.version == "2.0.0"


def test_app_state_event_bus_initialized(app: FastAPI) -> None:
    assert isinstance(app.state.event_bus, PipelineEventBus)


def test_app_state_registry_initialized(app: FastAPI) -> None:
    assert isinstance(app.state.investigation_registry, InvestigationRegistry)


def test_app_state_active_tasks_initialized(app: FastAPI) -> None:
    assert isinstance(app.state.active_tasks, dict)
    assert len(app.state.active_tasks) == 0


def test_app_state_cancel_flags_initialized(app: FastAPI) -> None:
    assert isinstance(app.state.cancel_flags, dict)
    assert len(app.state.cancel_flags) == 0


def test_app_state_investigation_stores_initialized(app: FastAPI) -> None:
    assert isinstance(app.state.investigation_stores, dict)
    assert len(app.state.investigation_stores) == 0


def test_app_state_graph_pipelines_initialized(app: FastAPI) -> None:
    assert isinstance(app.state.graph_pipelines, dict)


def test_app_state_graph_adapters_initialized(app: FastAPI) -> None:
    assert isinstance(app.state.graph_adapters, dict)


# ── Health endpoint ──────────────────────────────────────────────────


@pytest.mark.anyio
async def test_health_endpoint_returns_200(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ── CORS ─────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_cors_headers_on_preflight(client: AsyncClient) -> None:
    """OPTIONS preflight from a known origin returns CORS headers."""
    resp = await client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "GET" in resp.headers.get("access-control-allow-methods", "")


@pytest.mark.anyio
async def test_cors_rejected_for_unknown_origin(client: AsyncClient) -> None:
    """Origins not in the allow list do not get CORS headers."""
    resp = await client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # Starlette CORS middleware returns 400 for disallowed origins
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.anyio
async def test_cors_vite_origin(client: AsyncClient) -> None:
    """Vite dev server origin (5173) is also allowed."""
    resp = await client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5173"


# ── RFC 7807 error format ────────────────────────────────────────────


@pytest.mark.anyio
async def test_404_returns_rfc7807_format(client: AsyncClient) -> None:
    """Requesting a nonexistent investigation returns RFC 7807 JSON."""
    resp = await client.get("/api/v1/investigations/nonexistent-id")
    assert resp.status_code == 404
    assert resp.headers["content-type"] == "application/problem+json"

    body = resp.json()
    assert "type" in body
    assert "title" in body
    assert "status" in body
    assert body["status"] == 404
    assert "detail" in body
    assert "instance" in body


# ── Route module mounting ────────────────────────────────────────────


def test_all_route_modules_mounted(app: FastAPI) -> None:
    """All 6 route modules are mounted on the app."""
    route_paths = {route.path for route in app.routes if hasattr(route, "path")}

    # Spot-check key paths from each module
    expected_paths = {
        "/api/v1/investigations",                               # investigations
        "/api/v1/investigations/{investigation_id}",            # investigations
        "/api/v1/investigations/{investigation_id}/stream",     # stream
        "/api/v1/investigations/{investigation_id}/facts",      # facts
        "/api/v1/investigations/{investigation_id}/reports",    # reports
        "/api/v1/investigations/{investigation_id}/sources",    # sources
        "/api/v1/investigations/{investigation_id}/graph/nodes",  # graph
        "/api/v1/health",                                       # health
    }

    for expected in expected_paths:
        assert expected in route_paths, (
            f"Expected route '{expected}' not found. "
            f"Available: {sorted(route_paths)}"
        )


def test_route_count_at_least_17(app: FastAPI) -> None:
    """At minimum 17 routes: 6 investigations + 1 stream + 2 facts +
    3 reports + 1 sources + 3 graph + 1 health = 17, plus OpenAPI routes."""
    route_paths = [
        route.path for route in app.routes
        if hasattr(route, "path") and route.path.startswith("/api/v1")
    ]
    # 17 API routes expected (some may share paths with different methods)
    assert len(route_paths) >= 17, (
        f"Expected >= 17 API routes, found {len(route_paths)}: {route_paths}"
    )
