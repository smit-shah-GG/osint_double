"""Tests for investigation lifecycle endpoints.

Uses httpx.AsyncClient with ASGITransport to test the FastAPI router
with mocked InvestigationRunner to avoid actual pipeline execution.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from osint_system.api.errors import register_error_handlers
from osint_system.api.events.event_bus import PipelineEventBus
from osint_system.api.events.investigation_registry import (
    InvestigationRegistry,
    InvestigationStatus,
)
from osint_system.api.routes.investigations import router


# ── Fixtures ─────────────────────────────────────────────────────────


def _make_app() -> FastAPI:
    """Create a minimal FastAPI app with the investigations router."""
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router)

    # Mount required app.state attributes
    app.state.event_bus = PipelineEventBus()
    app.state.investigation_registry = InvestigationRegistry()
    app.state.active_tasks = {}
    app.state.cancel_flags = {}
    app.state.investigation_stores = {}
    app.state.graph_pipelines = {}

    return app


@pytest.fixture
def app() -> FastAPI:
    return _make_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── Helper: mock InvestigationRunner ─────────────────────────────────


def _mock_runner_class() -> MagicMock:
    """Create a mock InvestigationRunner that resolves phases instantly."""
    mock_cls = MagicMock()
    mock_instance = MagicMock()
    mock_instance.objective = "test objective"
    mock_instance.investigation_id = "inv-test1234"

    # Stores
    mock_instance.fact_store = MagicMock()
    mock_instance.classification_store = MagicMock()
    mock_instance.verification_store = MagicMock()
    mock_instance.report_store = MagicMock()
    mock_instance.article_store = MagicMock()

    # Phase methods return coroutines
    mock_instance._phase_crawl = AsyncMock()
    mock_instance._phase_extract = AsyncMock(return_value={"facts_extracted": 5})
    mock_instance._phase_classify = AsyncMock(return_value={"total": 5})
    mock_instance._phase_verify = AsyncMock(
        return_value={"total_verified": 3, "confirmed": 2}
    )
    mock_instance._phase_graph = AsyncMock(return_value={"nodes_merged": 10})
    mock_instance._phase_analyze = AsyncMock()

    mock_cls.return_value = mock_instance
    return mock_cls


# ── Tests: POST /investigations ──────────────────────────────────────


@pytest.mark.anyio
async def test_create_investigation_returns_202(client: AsyncClient) -> None:
    """POST /investigations should return 202 with investigation entity."""
    with patch(
        "osint_system.runner.InvestigationRunner",
        _mock_runner_class(),
    ):
        resp = await client.post(
            "/api/v1/investigations",
            json={"objective": "Test investigation objective"},
        )

    assert resp.status_code == 202
    data = resp.json()
    assert "id" in data
    assert data["objective"] == "Test investigation objective"
    assert data["status"] in ("pending", "running")
    assert "stream_url" in data
    assert data["stream_url"].startswith("/api/v1/investigations/")
    assert data["stream_url"].endswith("/stream")


@pytest.mark.anyio
async def test_create_investigation_validation_error(client: AsyncClient) -> None:
    """POST with empty objective should return 422."""
    resp = await client.post(
        "/api/v1/investigations",
        json={"objective": ""},
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_create_investigation_missing_objective(client: AsyncClient) -> None:
    """POST without objective should return 422."""
    resp = await client.post(
        "/api/v1/investigations",
        json={},
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_create_investigation_pipeline_runs(app: FastAPI) -> None:
    """POST should launch pipeline as background task."""
    mock_runner_cls = _mock_runner_class()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "osint_system.runner.InvestigationRunner",
            mock_runner_cls,
        ):
            resp = await client.post(
                "/api/v1/investigations",
                json={"objective": "Test pipeline launch"},
            )
            assert resp.status_code == 202

            # Give the background task a moment to run
            await asyncio.sleep(0.1)

    # The mock runner's phases should have been called
    mock_instance = mock_runner_cls.return_value
    mock_instance._phase_crawl.assert_called_once()
    mock_instance._phase_extract.assert_called_once()


# ── Tests: GET /investigations ───────────────────────────────────────


@pytest.mark.anyio
async def test_list_investigations_empty(client: AsyncClient) -> None:
    """GET /investigations should return empty list initially."""
    resp = await client.get("/api/v1/investigations")
    assert resp.status_code == 200
    data = resp.json()
    assert data["data"] == []
    assert data["total"] == 0
    assert data["page"] == 1


@pytest.mark.anyio
async def test_list_investigations_with_data(app: FastAPI) -> None:
    """GET /investigations should return paginated list."""
    registry = app.state.investigation_registry
    registry.create(objective="First investigation")
    registry.create(objective="Second investigation")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/investigations")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["data"]) == 2


@pytest.mark.anyio
async def test_list_investigations_pagination(app: FastAPI) -> None:
    """GET /investigations with page_size=1 should paginate."""
    registry = app.state.investigation_registry
    registry.create(objective="First")
    registry.create(objective="Second")
    registry.create(objective="Third")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/investigations", params={"page": 1, "page_size": 2}
        )

    data = resp.json()
    assert data["total"] == 3
    assert len(data["data"]) == 2
    assert data["page"] == 1
    assert data["page_size"] == 2


# ── Tests: GET /investigations/{id} ─────────────────────────────────


@pytest.mark.anyio
async def test_get_investigation_found(app: FastAPI) -> None:
    """GET /investigations/{id} should return investigation detail."""
    registry = app.state.investigation_registry
    inv = registry.create(objective="Detail test")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/investigations/{inv.id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == inv.id
    assert data["objective"] == "Detail test"
    assert data["status"] == "pending"


@pytest.mark.anyio
async def test_get_investigation_not_found(client: AsyncClient) -> None:
    """GET /investigations/{bad-id} should return 404 with RFC 7807."""
    resp = await client.get("/api/v1/investigations/inv-nonexistent")
    assert resp.status_code == 404
    data = resp.json()
    assert data["status"] == 404
    assert data["title"] == "Not Found"
    assert "type" in data
    assert "detail" in data


# ── Tests: DELETE /investigations/{id} ───────────────────────────────


@pytest.mark.anyio
async def test_delete_investigation_success(app: FastAPI) -> None:
    """DELETE /investigations/{id} should return 204."""
    registry = app.state.investigation_registry
    inv = registry.create(objective="To delete")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete(f"/api/v1/investigations/{inv.id}")

    assert resp.status_code == 204
    assert registry.get(inv.id) is None


@pytest.mark.anyio
async def test_delete_investigation_not_found(client: AsyncClient) -> None:
    """DELETE /investigations/{bad-id} should return 404."""
    resp = await client.delete("/api/v1/investigations/inv-gone")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_delete_investigation_cleans_event_bus(app: FastAPI) -> None:
    """DELETE should clean up event bus data."""
    registry = app.state.investigation_registry
    event_bus = app.state.event_bus

    inv = registry.create(objective="Cleanup test")
    event_bus.emit(inv.id, "test_event", {"data": 1})

    assert len(event_bus.get_all_events(inv.id)) == 1

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete(f"/api/v1/investigations/{inv.id}")

    assert resp.status_code == 204
    assert len(event_bus.get_all_events(inv.id)) == 0


# ── Tests: POST /investigations/{id}/cancel ──────────────────────────


@pytest.mark.anyio
async def test_cancel_running_investigation(app: FastAPI) -> None:
    """POST cancel on running investigation should transition to cancelled."""
    registry = app.state.investigation_registry
    inv = registry.create(objective="Cancel test")
    await registry.transition(
        inv.id,
        expected_status=InvestigationStatus.PENDING,
        new_status=InvestigationStatus.RUNNING,
    )
    # Set up cancel flag
    app.state.cancel_flags[inv.id] = asyncio.Event()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(f"/api/v1/investigations/{inv.id}/cancel")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "cancelled"


@pytest.mark.anyio
async def test_cancel_non_running_returns_409(app: FastAPI) -> None:
    """POST cancel on pending investigation should return 409."""
    registry = app.state.investigation_registry
    inv = registry.create(objective="Not running")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(f"/api/v1/investigations/{inv.id}/cancel")

    assert resp.status_code == 409
    data = resp.json()
    assert data["status"] == 409
    assert data["title"] == "Conflict"


@pytest.mark.anyio
async def test_cancel_nonexistent_returns_404(client: AsyncClient) -> None:
    """POST cancel on nonexistent investigation should return 404."""
    resp = await client.post("/api/v1/investigations/inv-nope/cancel")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_cancel_emits_pipeline_error_event(app: FastAPI) -> None:
    """Cancel should emit pipeline_error event with reason=cancelled."""
    registry = app.state.investigation_registry
    event_bus = app.state.event_bus

    inv = registry.create(objective="Cancel event test")
    await registry.transition(
        inv.id,
        expected_status=InvestigationStatus.PENDING,
        new_status=InvestigationStatus.RUNNING,
    )
    app.state.cancel_flags[inv.id] = asyncio.Event()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(f"/api/v1/investigations/{inv.id}/cancel")

    events = event_bus.get_all_events(inv.id)
    assert len(events) == 1
    assert events[0].event_type == "pipeline_error"
    assert events[0].data["reason"] == "cancelled"


# ── Tests: POST /investigations/{id}/regenerate ──────────────────────


@pytest.mark.anyio
async def test_regenerate_completed_returns_202(app: FastAPI) -> None:
    """POST regenerate on completed investigation should return 202."""
    registry = app.state.investigation_registry
    inv = registry.create(objective="Regen test")
    await registry.transition(
        inv.id,
        expected_status=InvestigationStatus.PENDING,
        new_status=InvestigationStatus.RUNNING,
    )
    await registry.transition(
        inv.id,
        expected_status=InvestigationStatus.RUNNING,
        new_status=InvestigationStatus.COMPLETED,
    )

    # Set up mock stores for regeneration
    app.state.investigation_stores[inv.id] = {
        "fact_store": MagicMock(),
        "classification_store": MagicMock(),
        "verification_store": MagicMock(),
        "report_store": MagicMock(),
        "article_store": MagicMock(),
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "osint_system.config.analysis_config.AnalysisConfig"
        ) as mock_config, patch(
            "osint_system.pipeline.analysis_pipeline.AnalysisPipeline"
        ) as mock_pipeline, patch(
            "osint_system.reporting.ReportGenerator"
        ):
            mock_config.from_env.return_value = MagicMock()
            mock_pipeline_instance = MagicMock()
            mock_pipeline_instance.run_analysis = AsyncMock()
            mock_pipeline.return_value = mock_pipeline_instance

            resp = await client.post(
                f"/api/v1/investigations/{inv.id}/regenerate",
                json={},
            )

    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "running"


@pytest.mark.anyio
async def test_regenerate_non_completed_returns_409(app: FastAPI) -> None:
    """POST regenerate on pending investigation should return 409."""
    registry = app.state.investigation_registry
    inv = registry.create(objective="Not completed")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/investigations/{inv.id}/regenerate",
            json={},
        )

    assert resp.status_code == 409


# ── Tests: Route count ───────────────────────────────────────────────


def test_router_has_correct_route_count() -> None:
    """Router should have 6 routes (POST, GET list, GET detail, DELETE, cancel, regenerate)."""
    assert len(router.routes) >= 6
