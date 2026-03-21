"""Tests for OpenAPI spec generation.

Validates that ``/openapi.json`` describes all endpoints with correct
request/response schemas, expected paths exist, and references resolve.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from osint_system.api.app import create_api_app


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def app() -> FastAPI:
    return create_api_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def openapi_spec(app: FastAPI) -> dict:
    """Generate the OpenAPI spec directly from the app."""
    return app.openapi()


# ── Spec retrieval ───────────────────────────────────────────────────


@pytest.mark.anyio
async def test_openapi_json_returns_valid_json(client: AsyncClient) -> None:
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    spec = resp.json()
    assert "openapi" in spec
    assert "info" in spec
    assert "paths" in spec


@pytest.mark.anyio
async def test_openapi_info_metadata(client: AsyncClient) -> None:
    resp = await client.get("/openapi.json")
    spec = resp.json()
    assert spec["info"]["title"] == "OSINT Intelligence System API"
    assert spec["info"]["version"] == "2.0.0"


# ── Expected paths ───────────────────────────────────────────────────


_EXPECTED_PATHS = [
    # Investigations CRUD
    ("/api/v1/investigations", "get"),
    ("/api/v1/investigations", "post"),
    ("/api/v1/investigations/{investigation_id}", "get"),
    ("/api/v1/investigations/{investigation_id}", "delete"),
    ("/api/v1/investigations/{investigation_id}/cancel", "post"),
    ("/api/v1/investigations/{investigation_id}/regenerate", "post"),
    # SSE stream
    ("/api/v1/investigations/{investigation_id}/stream", "get"),
    # Facts
    ("/api/v1/investigations/{investigation_id}/facts", "get"),
    ("/api/v1/investigations/{investigation_id}/facts/{fact_id}", "get"),
    # Reports
    ("/api/v1/investigations/{investigation_id}/reports", "get"),
    ("/api/v1/investigations/{investigation_id}/reports/latest", "get"),
    ("/api/v1/investigations/{investigation_id}/reports/{version}", "get"),
    # Sources
    ("/api/v1/investigations/{investigation_id}/sources", "get"),
    # Graph
    ("/api/v1/investigations/{investigation_id}/graph/nodes", "get"),
    ("/api/v1/investigations/{investigation_id}/graph/edges", "get"),
    ("/api/v1/investigations/{investigation_id}/graph/query", "get"),
    # Health
    ("/api/v1/health", "get"),
]


@pytest.mark.parametrize("path,method", _EXPECTED_PATHS)
def test_expected_path_exists(
    openapi_spec: dict, path: str, method: str
) -> None:
    """Each expected API path/method pair exists in the OpenAPI spec."""
    paths = openapi_spec["paths"]
    assert path in paths, (
        f"Path '{path}' not in spec. Available: {sorted(paths.keys())}"
    )
    assert method in paths[path], (
        f"Method '{method}' not in '{path}'. "
        f"Available: {list(paths[path].keys())}"
    )


def test_total_path_count(openapi_spec: dict) -> None:
    """Spec contains at least 15 distinct paths (some share multiple methods)."""
    paths = openapi_spec["paths"]
    assert len(paths) >= 15, (
        f"Expected >= 15 paths, found {len(paths)}: {sorted(paths.keys())}"
    )


# ── Schema components ────────────────────────────────────────────────


_EXPECTED_SCHEMAS = [
    "InvestigationResponse",
    "FactResponse",
    "LaunchRequest",
    "ReportResponse",
    "SourceResponse",
    "GraphNodeResponse",
    "GraphEdgeResponse",
]


@pytest.mark.parametrize("schema_name", _EXPECTED_SCHEMAS)
def test_expected_schema_exists(openapi_spec: dict, schema_name: str) -> None:
    """Key Pydantic models appear in the components/schemas section."""
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    assert schema_name in schemas, (
        f"Schema '{schema_name}' not in components/schemas. "
        f"Available: {sorted(schemas.keys())}"
    )


def test_paginated_response_schema_exists(openapi_spec: dict) -> None:
    """PaginatedResponse (or a variant) appears in schemas.

    FastAPI may suffix generic types, so we check for any schema
    containing 'PaginatedResponse' in the name.
    """
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    paginated = [s for s in schemas if "PaginatedResponse" in s]
    assert len(paginated) > 0, (
        f"No PaginatedResponse schema found. "
        f"Available: {sorted(schemas.keys())}"
    )


# ── Reference resolution ────────────────────────────────────────────


def test_all_refs_resolve(openapi_spec: dict) -> None:
    """All $ref pointers in the spec resolve to existing definitions.

    Recursively walks the spec tree, collecting every $ref value,
    then verifies each target path exists.
    """
    refs: list[str] = []

    def _collect_refs(obj: object) -> None:
        if isinstance(obj, dict):
            if "$ref" in obj:
                refs.append(obj["$ref"])
            for v in obj.values():
                _collect_refs(v)
        elif isinstance(obj, list):
            for item in obj:
                _collect_refs(item)

    _collect_refs(openapi_spec)

    for ref in refs:
        # $ref format: "#/components/schemas/SomeName"
        assert ref.startswith("#/"), f"Non-local $ref: {ref}"
        parts = ref.lstrip("#/").split("/")
        current: dict = openapi_spec
        for part in parts:
            assert isinstance(current, dict), (
                f"Cannot traverse $ref '{ref}': "
                f"expected dict at '{part}', got {type(current).__name__}"
            )
            assert part in current, (
                f"Broken $ref '{ref}': key '{part}' not found. "
                f"Available keys: {list(current.keys())}"
            )
            current = current[part]


def test_schema_count_reasonable(openapi_spec: dict) -> None:
    """Spec contains a reasonable number of schemas (>= 8)."""
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    assert len(schemas) >= 8, (
        f"Expected >= 8 schemas, found {len(schemas)}: {sorted(schemas.keys())}"
    )
