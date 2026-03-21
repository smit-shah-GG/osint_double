"""Tests for GET /api/v1/investigations/{id}/graph/* endpoints.

Validates graph node listing with type filter, edge listing, query dispatch
for all four patterns, 400 for invalid pattern, and 404 when graph is
unavailable.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
import networkx as nx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from osint_system.api.errors import register_error_handlers
from osint_system.api.routes.graph import router


# -- Fixtures & helpers ----------------------------------------------------


def _build_test_graph() -> nx.MultiDiGraph:
    """Build a small test graph with known structure."""
    g = nx.MultiDiGraph()

    # Nodes
    g.add_node("Entity:Putin", label="Entity", name="Vladimir Putin", entity_type="PERSON")
    g.add_node("Entity:Beijing", label="Entity", name="Beijing", entity_type="LOCATION")
    g.add_node("Fact:f-001", label="Fact", claim_text="Putin visited Beijing", fact_id="f-001")
    g.add_node("Source:reuters", label="Source", name="Reuters", authority_score=0.9)

    # Edges
    g.add_edge("Fact:f-001", "Entity:Putin", rel_type="MENTIONS", weight=1.0)
    g.add_edge("Fact:f-001", "Entity:Beijing", rel_type="MENTIONS", weight=1.0)
    g.add_edge("Fact:f-001", "Source:reuters", rel_type="SOURCED_FROM", weight=0.9)

    return g


class MockAdapter:
    """Mock graph adapter with a real NetworkX graph for node/edge listing."""

    def __init__(self, graph: nx.MultiDiGraph) -> None:
        self._graph = graph

    async def query_entity_network(
        self, entity_id: str, max_hops: int, investigation_id: str | None = None
    ) -> SimpleNamespace:
        """Return mock QueryResult for entity_network."""
        return SimpleNamespace(
            nodes=[
                SimpleNamespace(
                    id="Entity:Putin",
                    label="Entity",
                    properties={"name": "Vladimir Putin"},
                ),
                SimpleNamespace(
                    id="Fact:f-001",
                    label="Fact",
                    properties={"claim_text": "Putin visited Beijing"},
                ),
            ],
            edges=[
                SimpleNamespace(
                    source_id="Fact:f-001",
                    target_id="Entity:Putin",
                    edge_type=SimpleNamespace(value="MENTIONS"),
                    properties={"weight": 1.0},
                ),
            ],
        )

    async def query_corroboration_clusters(
        self, investigation_id: str
    ) -> SimpleNamespace:
        """Return mock QueryResult for corroboration."""
        return SimpleNamespace(nodes=[], edges=[])

    async def query_timeline(
        self, entity_id: str, investigation_id: str | None = None
    ) -> SimpleNamespace:
        """Return mock QueryResult for timeline."""
        return SimpleNamespace(
            nodes=[
                SimpleNamespace(
                    id="Fact:f-001",
                    label="Fact",
                    properties={"temporal_value": "2026-03-15"},
                ),
            ],
            edges=[],
        )

    async def query_shortest_path(
        self, from_id: str, to_id: str, investigation_id: str | None = None
    ) -> SimpleNamespace:
        """Return mock QueryResult for shortest_path."""
        return SimpleNamespace(
            nodes=[
                SimpleNamespace(id="Entity:Putin", label="Entity", properties={}),
                SimpleNamespace(id="Entity:Beijing", label="Entity", properties={}),
            ],
            edges=[
                SimpleNamespace(
                    source_id="Entity:Putin",
                    target_id="Entity:Beijing",
                    edge_type=SimpleNamespace(value="RELATED_TO"),
                    properties={},
                ),
            ],
        )


def _build_app(
    investigation_id: str = "inv-test",
    adapter: Any = None,
    no_graph: bool = False,
) -> FastAPI:
    """Build a minimal FastAPI app with mock graph adapter."""
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router)

    if not no_graph:
        if adapter is None:
            adapter = MockAdapter(_build_test_graph())
        app.state.graph_adapters = {investigation_id: adapter}
    else:
        app.state.graph_adapters = {}

    return app


# -- Tests: Nodes ----------------------------------------------------------


def test_list_nodes_returns_all() -> None:
    """GET /graph/nodes returns all nodes in the graph."""
    app = _build_app()
    client = TestClient(app)

    resp = client.get("/api/v1/investigations/inv-test/graph/nodes")
    assert resp.status_code == 200

    nodes = resp.json()
    assert len(nodes) == 4  # Putin, Beijing, f-001, reuters

    # Check a node has expected structure
    entity_nodes = [n for n in nodes if n["id"] == "Entity:Putin"]
    assert len(entity_nodes) == 1
    assert entity_nodes[0]["label"] == "Entity"
    assert entity_nodes[0]["type"] == "Entity"
    assert entity_nodes[0]["properties"]["name"] == "Vladimir Putin"


def test_list_nodes_filter_by_type() -> None:
    """GET /graph/nodes?node_type=Entity filters correctly."""
    app = _build_app()
    client = TestClient(app)

    resp = client.get(
        "/api/v1/investigations/inv-test/graph/nodes?node_type=Entity"
    )
    assert resp.status_code == 200

    nodes = resp.json()
    assert len(nodes) == 2  # Putin, Beijing
    assert all(n["type"] == "Entity" for n in nodes)


def test_list_nodes_filter_returns_empty_for_unknown_type() -> None:
    """GET /graph/nodes?node_type=Unknown returns empty list."""
    app = _build_app()
    client = TestClient(app)

    resp = client.get(
        "/api/v1/investigations/inv-test/graph/nodes?node_type=Nonexistent"
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_nodes_graph_not_available() -> None:
    """GET /graph/nodes returns 404 when no graph adapter exists."""
    app = _build_app(no_graph=True)
    client = TestClient(app)

    resp = client.get("/api/v1/investigations/inv-test/graph/nodes")
    assert resp.status_code == 404
    assert "Graph data not available" in resp.json()["detail"]


# -- Tests: Edges ----------------------------------------------------------


def test_list_edges_returns_all() -> None:
    """GET /graph/edges returns all edges in the graph."""
    app = _build_app()
    client = TestClient(app)

    resp = client.get("/api/v1/investigations/inv-test/graph/edges")
    assert resp.status_code == 200

    edges = resp.json()
    assert len(edges) == 3  # MENTIONS x2, SOURCED_FROM x1

    mentions_edges = [e for e in edges if e["relationship"] == "MENTIONS"]
    assert len(mentions_edges) == 2

    sourced_edges = [e for e in edges if e["relationship"] == "SOURCED_FROM"]
    assert len(sourced_edges) == 1
    assert sourced_edges[0]["source"] == "Fact:f-001"


# -- Tests: Query endpoint -------------------------------------------------


def test_query_entity_network() -> None:
    """GET /graph/query?pattern=entity_network&entity_id=Putin returns results."""
    app = _build_app()
    client = TestClient(app)

    resp = client.get(
        "/api/v1/investigations/inv-test/graph/query"
        "?pattern=entity_network&entity_id=Putin"
    )
    assert resp.status_code == 200

    body = resp.json()
    assert "nodes" in body
    assert "edges" in body
    assert len(body["nodes"]) == 2
    assert len(body["edges"]) == 1
    assert body["edges"][0]["relationship"] == "MENTIONS"


def test_query_entity_network_missing_entity_id() -> None:
    """GET /graph/query?pattern=entity_network without entity_id returns 400."""
    app = _build_app()
    client = TestClient(app)

    resp = client.get(
        "/api/v1/investigations/inv-test/graph/query?pattern=entity_network"
    )
    assert resp.status_code == 400
    assert "entity_id is required" in resp.json()["detail"]


def test_query_corroboration() -> None:
    """GET /graph/query?pattern=corroboration returns query results."""
    app = _build_app()
    client = TestClient(app)

    resp = client.get(
        "/api/v1/investigations/inv-test/graph/query?pattern=corroboration"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["nodes"] == []
    assert body["edges"] == []


def test_query_timeline() -> None:
    """GET /graph/query?pattern=timeline&entity_id=Putin returns timeline."""
    app = _build_app()
    client = TestClient(app)

    resp = client.get(
        "/api/v1/investigations/inv-test/graph/query"
        "?pattern=timeline&entity_id=Putin"
    )
    assert resp.status_code == 200

    body = resp.json()
    assert len(body["nodes"]) == 1


def test_query_timeline_missing_entity_id() -> None:
    """GET /graph/query?pattern=timeline without entity_id returns 400."""
    app = _build_app()
    client = TestClient(app)

    resp = client.get(
        "/api/v1/investigations/inv-test/graph/query?pattern=timeline"
    )
    assert resp.status_code == 400
    assert "entity_id is required" in resp.json()["detail"]


def test_query_shortest_path() -> None:
    """GET /graph/query?pattern=shortest_path returns path."""
    app = _build_app()
    client = TestClient(app)

    resp = client.get(
        "/api/v1/investigations/inv-test/graph/query"
        "?pattern=shortest_path&from_id=Putin&to_id=Beijing"
    )
    assert resp.status_code == 200

    body = resp.json()
    assert len(body["nodes"]) == 2
    assert len(body["edges"]) == 1


def test_query_shortest_path_missing_params() -> None:
    """GET /graph/query?pattern=shortest_path without from_id/to_id returns 400."""
    app = _build_app()
    client = TestClient(app)

    resp = client.get(
        "/api/v1/investigations/inv-test/graph/query"
        "?pattern=shortest_path&from_id=Putin"
    )
    assert resp.status_code == 400
    assert "from_id and to_id are required" in resp.json()["detail"]


def test_query_invalid_pattern() -> None:
    """GET /graph/query?pattern=invalid returns 400."""
    app = _build_app()
    client = TestClient(app)

    resp = client.get(
        "/api/v1/investigations/inv-test/graph/query?pattern=invalid"
    )
    assert resp.status_code == 400
    assert "Unknown pattern" in resp.json()["detail"]


def test_query_graph_not_available() -> None:
    """GET /graph/query returns 404 when no graph adapter exists."""
    app = _build_app(no_graph=True)
    client = TestClient(app)

    resp = client.get(
        "/api/v1/investigations/inv-test/graph/query"
        "?pattern=entity_network&entity_id=X"
    )
    assert resp.status_code == 404


# -- Tests: Pipeline-based adapter resolution ------------------------------


def test_graph_resolves_from_pipeline() -> None:
    """Graph adapter is resolved via pipeline._adapter."""
    graph = _build_test_graph()
    mock_pipeline = SimpleNamespace(_adapter=MockAdapter(graph))

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router)
    app.state.graph_adapters = {}  # Empty -- force pipeline fallback
    app.state.graph_pipelines = {"inv-test": mock_pipeline}

    client = TestClient(app)
    resp = client.get("/api/v1/investigations/inv-test/graph/nodes")
    assert resp.status_code == 200
    assert len(resp.json()) == 4  # Graph has 4 nodes
