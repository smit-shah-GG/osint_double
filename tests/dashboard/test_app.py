"""Tests for FastAPI app factory, health check, and static file serving."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from osint_system.dashboard import create_app


def test_create_app_returns_fastapi_instance() -> None:
    """create_app() returns a FastAPI instance with correct title."""
    app = create_app()
    assert isinstance(app, FastAPI)
    assert app.title == "OSINT Dashboard"


def test_health_check() -> None:
    """GET /health returns 200 with {"status": "ok"}."""
    app = create_app()
    client = TestClient(app)

    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_static_files_mounted() -> None:
    """GET /static/styles.css returns 200 with CSS content."""
    app = create_app()
    client = TestClient(app)

    response = client.get("/static/styles.css")
    assert response.status_code == 200
    assert "text/css" in response.headers.get("content-type", "")


def test_stores_on_app_state() -> None:
    """Default stores are created and available on app.state."""
    app = create_app()
    assert app.state.fact_store is not None
    assert app.state.classification_store is not None
    assert app.state.verification_store is not None
    assert app.state.report_store is not None
    assert app.state.templates is not None
    # Optional deps default to None
    assert app.state.report_generator is None
    assert app.state.analysis_pipeline is None
