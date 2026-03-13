"""Graph layer package for knowledge graph storage and querying.

Provides the GraphAdapter Protocol, Pydantic graph schemas, and the EdgeType
enum for semantic relationship types. This package is the type foundation for
Phase 9 (Knowledge Graph Integration).

Primary exports:
- GraphAdapter: Protocol defining the graph interface (Neo4j/NetworkX backends)
- GraphNode, GraphEdge: Typed node/edge models for query results
- QueryResult: Container for structured graph query results
- EdgeType: Enum of semantic relationship types (~13 types)
- compute_edge_weight: Formula for deriving edge weight from properties

Usage:
    from osint_system.data_management.graph import (
        GraphAdapter, GraphNode, GraphEdge, QueryResult, EdgeType,
        compute_edge_weight,
    )

    # Type-check an adapter implementation
    assert isinstance(my_adapter, GraphAdapter)

    # Compute edge weight from relationship properties
    weight = compute_edge_weight(evidence_count=5, authority_score=0.9, recency_days=30)

    # Build a query result
    result = QueryResult(nodes=[], edges=[], query_type="entity_network", metadata={})
"""

from osint_system.data_management.graph.adapter import GraphAdapter
from osint_system.data_management.graph.schema import (
    EdgeType,
    GraphEdge,
    GraphNode,
    QueryResult,
    compute_edge_weight,
)

__all__ = [
    "GraphAdapter",
    "GraphNode",
    "GraphEdge",
    "QueryResult",
    "EdgeType",
    "compute_edge_weight",
]
