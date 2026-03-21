"""Graph layer package for knowledge graph storage and querying.

Provides the GraphAdapter Protocol, Pydantic graph schemas, EdgeType enum,
and adapter implementations (Memgraph for production, Neo4j legacy,
NetworkX for tests/CI).

Primary exports:
- GraphAdapter: Protocol defining the graph interface
- MemgraphAdapter: Production graph backend using Memgraph via Bolt protocol
- Neo4jAdapter: Legacy adapter (preserved until wiring plan 13-07 updates consumers)
- NetworkXAdapter: In-memory graph backend for tests/CI (no Docker dependency)
- GraphNode, GraphEdge: Typed node/edge models for query results
- QueryResult: Container for structured graph query results
- EdgeType: Enum of semantic relationship types (13 types)
- compute_edge_weight: Formula for deriving edge weight from properties

Usage:
    from osint_system.data_management.graph import (
        GraphAdapter, MemgraphAdapter, NetworkXAdapter,
        GraphNode, GraphEdge, QueryResult, EdgeType,
        compute_edge_weight,
    )

    # Production: Memgraph backend
    config = GraphConfig.from_env()
    async with MemgraphAdapter(config) as adapter:
        await adapter.merge_node("Fact", {"fact_id": "f-1"}, "fact_id")

    # Tests/CI: NetworkX backend (no Docker)
    async with NetworkXAdapter() as adapter:
        await adapter.merge_node("Fact", {"fact_id": "f-1"}, "fact_id")
"""

from osint_system.data_management.graph.adapter import GraphAdapter
from osint_system.data_management.graph.memgraph_adapter import MemgraphAdapter
from osint_system.data_management.graph.neo4j_adapter import Neo4jAdapter
from osint_system.data_management.graph.networkx_adapter import NetworkXAdapter
from osint_system.data_management.graph.schema import (
    EdgeType,
    GraphEdge,
    GraphNode,
    QueryResult,
    compute_edge_weight,
)

__all__ = [
    "GraphAdapter",
    "MemgraphAdapter",
    "Neo4jAdapter",
    "NetworkXAdapter",
    "GraphNode",
    "GraphEdge",
    "QueryResult",
    "EdgeType",
    "compute_edge_weight",
]
