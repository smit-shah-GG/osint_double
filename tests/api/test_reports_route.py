"""Tests for GET /api/v1/investigations/{id}/reports endpoints.

Validates latest report retrieval, version listing, specific version access,
and 404 handling.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from osint_system.api.errors import register_error_handlers
from osint_system.api.routes.reports import router


# -- Fixtures & helpers ----------------------------------------------------


def _make_report_record(
    investigation_id: str = "inv-test",
    version: int = 1,
    content: str = "# Report\n\nSample content.",
    model_version: str | None = "gemini-2.0-flash",
) -> SimpleNamespace:
    """Build a mock ReportRecord."""
    return SimpleNamespace(
        investigation_id=investigation_id,
        version=version,
        markdown_content=content,
        generated_at=datetime(2026, 3, 21, 12, 0, 0, tzinfo=timezone.utc),
        synthesis_summary={
            "model_version": model_version,
            "judgment_count": 3,
            "fact_count": 42,
        },
    )


def _build_app(
    records: list | None = None,
    latest_record: Any = None,
    investigation_id: str = "inv-test",
    use_direct_stores: bool = False,
) -> FastAPI:
    """Build a minimal FastAPI app with mocked report store."""
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router)

    report_store = AsyncMock()

    # get_latest
    report_store.get_latest.return_value = latest_record

    # list_versions
    report_store.list_versions.return_value = records or []

    # get_version
    async def mock_get_version(inv_id: str, version: int) -> Any:
        for r in (records or []):
            if r.version == version:
                return r
        return None

    report_store.get_version = AsyncMock(side_effect=mock_get_version)

    if use_direct_stores:
        app.state.report_store = report_store
    else:
        app.state.investigation_stores = {
            investigation_id: {
                "report_store": report_store,
            }
        }

    return app


# -- Tests: Latest report --------------------------------------------------


def test_get_latest_report_success() -> None:
    """GET /reports/latest returns the most recent report."""
    record = _make_report_record(version=2, content="# V2 Report")
    app = _build_app(latest_record=record)
    client = TestClient(app)

    resp = client.get("/api/v1/investigations/inv-test/reports/latest")
    assert resp.status_code == 200

    body = resp.json()
    assert body["investigation_id"] == "inv-test"
    assert body["version"] == 2
    assert body["content"] == "# V2 Report"
    assert body["model_used"] == "gemini-2.0-flash"
    assert body["metadata"]["judgment_count"] == 3


def test_get_latest_report_not_found() -> None:
    """GET /reports/latest returns 404 when no reports exist."""
    app = _build_app(latest_record=None)
    client = TestClient(app)

    resp = client.get("/api/v1/investigations/inv-test/reports/latest")
    assert resp.status_code == 404
    assert "No reports found" in resp.json()["detail"]


def test_get_latest_report_unknown_investigation() -> None:
    """GET /reports/latest returns 404 for non-existent investigation."""
    app = _build_app(investigation_id="inv-real")
    client = TestClient(app)

    resp = client.get("/api/v1/investigations/inv-unknown/reports/latest")
    assert resp.status_code == 404


# -- Tests: Version listing ------------------------------------------------


def test_list_report_versions_success() -> None:
    """GET /reports returns paginated version list."""
    records = [
        _make_report_record(version=1),
        _make_report_record(version=2),
        _make_report_record(version=3),
    ]
    app = _build_app(records=records)
    client = TestClient(app)

    resp = client.get("/api/v1/investigations/inv-test/reports")
    assert resp.status_code == 200

    body = resp.json()
    assert body["total"] == 3
    assert len(body["data"]) == 3
    assert body["data"][0]["version"] == 1
    assert body["data"][2]["version"] == 3
    assert body["data"][0]["model_used"] == "gemini-2.0-flash"


def test_list_report_versions_empty() -> None:
    """GET /reports returns empty paginated response when no versions exist."""
    app = _build_app(records=[])
    client = TestClient(app)

    resp = client.get("/api/v1/investigations/inv-test/reports")
    assert resp.status_code == 200

    body = resp.json()
    assert body["total"] == 0
    assert body["data"] == []


def test_list_report_versions_pagination() -> None:
    """GET /reports?page=2&page_size=1 returns correct slice."""
    records = [
        _make_report_record(version=1),
        _make_report_record(version=2),
    ]
    app = _build_app(records=records)
    client = TestClient(app)

    resp = client.get(
        "/api/v1/investigations/inv-test/reports?page=2&page_size=1"
    )
    assert resp.status_code == 200

    body = resp.json()
    assert body["total"] == 2
    assert body["page"] == 2
    assert len(body["data"]) == 1
    assert body["data"][0]["version"] == 2


# -- Tests: Specific version -----------------------------------------------


def test_get_report_version_success() -> None:
    """GET /reports/{version} returns the specified version."""
    records = [
        _make_report_record(version=1, content="# V1"),
        _make_report_record(version=2, content="# V2"),
    ]
    app = _build_app(records=records)
    client = TestClient(app)

    resp = client.get("/api/v1/investigations/inv-test/reports/2")
    assert resp.status_code == 200

    body = resp.json()
    assert body["version"] == 2
    assert body["content"] == "# V2"


def test_get_report_version_not_found() -> None:
    """GET /reports/{version} returns 404 for non-existent version."""
    records = [_make_report_record(version=1)]
    app = _build_app(records=records)
    client = TestClient(app)

    resp = client.get("/api/v1/investigations/inv-test/reports/99")
    assert resp.status_code == 404
    assert "version 99" in resp.json()["detail"]


# -- Tests: Direct store fallback ------------------------------------------


def test_reports_fallback_to_direct_store() -> None:
    """GET /reports/latest resolves store from app.state directly."""
    record = _make_report_record(version=1)
    app = _build_app(latest_record=record, use_direct_stores=True)
    client = TestClient(app)

    resp = client.get("/api/v1/investigations/inv-test/reports/latest")
    assert resp.status_code == 200
    assert resp.json()["version"] == 1
