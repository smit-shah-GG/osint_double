"""Graph data and query endpoints.

Exposes knowledge graph nodes, edges, and query patterns (entity_network,
corroboration, timeline, shortest_path) via the ``NetworkXAdapter``.

Graph adapters are stored per-investigation in ``app.state.graph_adapters``
(a dict keyed by investigation_id). The adapter's ``_graph`` attribute is a
``networkx.MultiDiGraph``.

Endpoints:
    GET /investigations/{investigation_id}/graph/nodes
    GET /investigations/{investigation_id}/graph/edges
    GET /investigations/{investigation_id}/graph/query
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from osint_system.api.errors import NotFoundError, ProblemDetailError
from osint_system.api.schemas import GraphEdgeResponse, GraphNodeResponse

router = APIRouter(prefix="/api/v1")

# Valid query patterns for dispatch
_VALID_PATTERNS = frozenset({
    "entity_network",
    "corroboration",
    "timeline",
    "shortest_path",
})


# -- Helpers ---------------------------------------------------------------


def _get_graph_adapter(request: Request, investigation_id: str) -> Any:
    """Resolve the graph adapter for an investigation.

    Checks ``app.state.graph_adapters[investigation_id]`` first
    (direct adapter dict), then ``app.state.graph_pipelines[investigation_id]``
    and extracts ``pipeline._adapter``.

    Raises:
        NotFoundError: If no graph data is available for the investigation.
    """
    # Direct adapter storage
    adapters = getattr(request.app.state, "graph_adapters", {})
    if investigation_id in adapters:
        return adapters[investigation_id]

    # Pipeline-based storage (adapter accessible via pipeline._adapter)
    pipelines = getattr(request.app.state, "graph_pipelines", {})
    if investigation_id in pipelines:
        pipeline = pipelines[investigation_id]
        adapter = getattr(pipeline, "_adapter", None)
        if adapter is not None:
            return adapter

    raise NotFoundError(
        detail=(
            f"Graph data not available for investigation '{investigation_id}'. "
            f"The graph phase may not have run."
        ),
    )


def _graph_node_to_response(node: Any) -> GraphNodeResponse:
    """Convert an internal GraphNode to GraphNodeResponse.

    Filters out ``label`` and ``type`` from properties to avoid duplication.
    """
    props = dict(node.properties) if node.properties else {}
    # Remove fields already exposed as top-level attributes
    props.pop("label", None)
    props.pop("type", None)

    return GraphNodeResponse(
        id=node.id,
        label=node.label,
        type=node.label,  # GraphNode.label IS the type (Fact, Entity, etc.)
        properties=props if props else None,
    )


def _graph_edge_to_response(edge: Any) -> GraphEdgeResponse:
    """Convert an internal GraphEdge to GraphEdgeResponse."""
    props = dict(edge.properties) if edge.properties else {}
    relationship = (
        edge.edge_type.value
        if hasattr(edge.edge_type, "value")
        else str(edge.edge_type)
    )

    return GraphEdgeResponse(
        source=edge.source_id,
        target=edge.target_id,
        relationship=relationship,
        properties=props if props else None,
    )


# -- Endpoints -------------------------------------------------------------


@router.get(
    "/investigations/{investigation_id}/graph/nodes",
    response_model=list[GraphNodeResponse],
)
async def list_graph_nodes(
    request: Request,
    investigation_id: str,
    node_type: str | None = Query(
        None,
        description="Filter by node type (e.g. Entity, Fact, Source).",
    ),
) -> list[GraphNodeResponse]:
    """List all graph nodes, optionally filtered by type."""
    adapter = _get_graph_adapter(request, investigation_id)
    graph = adapter._graph

    result: list[GraphNodeResponse] = []
    for node_id, attrs in graph.nodes(data=True):
        node_label = attrs.get("label", "Unknown")

        if node_type is not None and node_label != node_type:
            continue

        props = {k: v for k, v in attrs.items() if k != "label"}

        result.append(
            GraphNodeResponse(
                id=str(node_id),
                label=node_label,
                type=node_label,
                properties=props if props else None,
            )
        )

    return result


@router.get(
    "/investigations/{investigation_id}/graph/edges",
    response_model=list[GraphEdgeResponse],
)
async def list_graph_edges(
    request: Request,
    investigation_id: str,
) -> list[GraphEdgeResponse]:
    """List all graph edges."""
    adapter = _get_graph_adapter(request, investigation_id)
    graph = adapter._graph

    result: list[GraphEdgeResponse] = []
    for u, v, data in graph.edges(data=True):
        relationship = data.get("rel_type", "RELATED_TO")
        props = {k: v_val for k, v_val in data.items() if k != "rel_type"}

        result.append(
            GraphEdgeResponse(
                source=str(u),
                target=str(v),
                relationship=relationship,
                properties=props if props else None,
            )
        )

    return result


@router.get(
    "/investigations/{investigation_id}/graph/query",
)
async def query_graph(
    request: Request,
    investigation_id: str,
    pattern: str = Query(
        ...,
        description="Query pattern: entity_network, corroboration, timeline, shortest_path.",
    ),
    entity_id: str | None = Query(None, description="Entity ID (for entity_network, timeline)."),
    from_id: str | None = Query(None, description="Source entity ID (for shortest_path)."),
    to_id: str | None = Query(None, description="Target entity ID (for shortest_path)."),
    max_hops: int = Query(2, ge=1, le=5, description="Max traversal depth (entity_network)."),
) -> dict[str, list[GraphNodeResponse] | list[GraphEdgeResponse]]:
    """Execute a graph query pattern.

    Dispatches to the appropriate adapter query method based on ``pattern``.
    Returns ``{"nodes": [...], "edges": [...]}``.
    """
    if pattern not in _VALID_PATTERNS:
        raise ProblemDetailError(
            status=400,
            title="Invalid Query Pattern",
            detail=(
                f"Unknown pattern: '{pattern}'. "
                f"Valid patterns: {', '.join(sorted(_VALID_PATTERNS))}."
            ),
        )

    adapter = _get_graph_adapter(request, investigation_id)

    if pattern == "entity_network":
        if entity_id is None:
            raise ProblemDetailError(
                status=400,
                title="Missing Parameter",
                detail="entity_id is required for entity_network queries.",
            )
        query_result = await adapter.query_entity_network(
            entity_id, max_hops, investigation_id
        )

    elif pattern == "corroboration":
        query_result = await adapter.query_corroboration_clusters(
            investigation_id
        )

    elif pattern == "timeline":
        if entity_id is None:
            raise ProblemDetailError(
                status=400,
                title="Missing Parameter",
                detail="entity_id is required for timeline queries.",
            )
        query_result = await adapter.query_timeline(
            entity_id, investigation_id
        )

    elif pattern == "shortest_path":
        if from_id is None or to_id is None:
            raise ProblemDetailError(
                status=400,
                title="Missing Parameter",
                detail="from_id and to_id are required for shortest_path queries.",
            )
        query_result = await adapter.query_shortest_path(
            from_id, to_id, investigation_id
        )

    # Map QueryResult nodes/edges to API response types
    nodes = [_graph_node_to_response(n) for n in query_result.nodes]
    edges = [_graph_edge_to_response(e) for e in query_result.edges]

    return {"nodes": nodes, "edges": edges}
