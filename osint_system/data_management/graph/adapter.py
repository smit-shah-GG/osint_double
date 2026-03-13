"""GraphAdapter Protocol definition for graph storage abstraction.

Defines the interface that both Neo4j and NetworkX adapters must implement.
All consumers depend only on this Protocol, never on a concrete backend.

Per Phase 9 CONTEXT.md decisions:
- Python abstraction layer with escape hatch for raw Cypher queries
- High-level methods for four essential query patterns
- Query results returned as typed Pydantic models (QueryResult)

The Protocol is runtime-checkable so adapters can be validated at startup
with ``isinstance(adapter, GraphAdapter)``.

Usage:
    from osint_system.data_management.graph.adapter import GraphAdapter

    def build_graph(adapter: GraphAdapter) -> None:
        # Works with Neo4jAdapter or NetworkXAdapter
        await adapter.merge_node("Fact", {"id": "f1", "text": "..."})
"""

from typing import Protocol, runtime_checkable

from osint_system.data_management.graph.schema import QueryResult


@runtime_checkable
class GraphAdapter(Protocol):
    """Graph storage abstraction. Neo4j or NetworkX backends.

    All methods are async. Implementations must handle their own connection
    lifecycle (pool creation in __init__, cleanup in close()).

    Node IDs follow the format ``{label}:{natural_key}`` for global uniqueness.
    MERGE semantics: if a node/relationship with the key property exists, update
    its properties; otherwise create it. This mirrors Neo4j MERGE + ON CREATE SET
    + ON MATCH SET behavior.

    Batch methods use UNWIND-style ingestion for performance (up to 900x faster
    than individual transactions on Neo4j). The NetworkX adapter emulates this
    with iterative MERGE.
    """

    async def initialize(self) -> None:
        """Create indexes, constraints, and schema setup.

        Idempotent: safe to call on every startup. Uses IF NOT EXISTS for
        all constraint and index creation.

        For Neo4j: creates uniqueness constraints on node key properties
        (fact_id, entity_id, source_id, investigation_id) and range/text
        indexes for common query patterns.

        For NetworkX: no-op (in-memory, no persistent schema).

        Raises:
            ConnectionError: If the database is unreachable (Neo4j only).
        """
        ...

    async def close(self) -> None:
        """Clean shutdown of the graph backend.

        Releases connection pools, flushes pending writes, and closes
        the driver. After calling close(), the adapter must not be reused.

        For Neo4j: closes the AsyncDriver (releases connection pool).
        For NetworkX: clears the in-memory graph.
        """
        ...

    async def merge_node(
        self, label: str, properties: dict, key_property: str = "id"
    ) -> str:
        """MERGE a single node by key property.

        If a node with the given label and key property value exists, update
        its properties (ON MATCH SET). Otherwise, create it (ON CREATE SET).

        Args:
            label: Node label (Fact, Entity, Source, Investigation, Classification).
            properties: Node properties dict. Must contain ``key_property``.
            key_property: Property used for identity matching. Default "id".

        Returns:
            Node ID in ``{label}:{key_value}`` format.

        Raises:
            KeyError: If ``key_property`` is not present in ``properties``.
            ConnectionError: If the database is unreachable (Neo4j only).
        """
        ...

    async def merge_relationship(
        self, from_id: str, to_id: str, rel_type: str, properties: dict
    ) -> None:
        """MERGE a relationship between two existing nodes.

        Nodes must already exist (call merge_node first). If a relationship
        of the same type between the same nodes exists, update its properties.
        Otherwise, create it.

        Per RESEARCH.md anti-pattern guidance: always MERGE nodes first,
        then MERGE relationships separately. Full-pattern MERGE creates
        duplicates when partial matches exist.

        Args:
            from_id: Source node ID (``{label}:{key_value}`` format).
            to_id: Target node ID (``{label}:{key_value}`` format).
            rel_type: Relationship type string (should match EdgeType values).
            properties: Relationship properties (weight, evidence_count, etc.).

        Raises:
            ValueError: If either node does not exist.
            ConnectionError: If the database is unreachable (Neo4j only).
        """
        ...

    async def batch_merge_nodes(
        self, label: str, nodes: list[dict], key_property: str = "id"
    ) -> int:
        """Batch MERGE multiple nodes via UNWIND.

        High-performance bulk ingestion. On Neo4j, uses a single UNWIND
        transaction for up to ``batch_size`` nodes (configured in GraphConfig).
        On NetworkX, iterates and calls merge_node per item.

        Each dict in ``nodes`` must contain ``key_property``.

        Args:
            label: Node label applied to all nodes in the batch.
            nodes: List of property dicts, one per node.
            key_property: Property used for identity matching. Default "id".

        Returns:
            Number of nodes merged (created or updated).

        Raises:
            KeyError: If any node dict is missing ``key_property``.
            ConnectionError: If the database is unreachable (Neo4j only).
        """
        ...

    async def batch_merge_relationships(
        self, relationships: list[dict]
    ) -> int:
        """Batch MERGE multiple relationships.

        Each dict in ``relationships`` must contain:
        - ``from_id``: Source node ID
        - ``to_id``: Target node ID
        - ``rel_type``: Relationship type string
        - ``properties``: Relationship properties dict

        Args:
            relationships: List of relationship dicts.

        Returns:
            Number of relationships merged (created or updated).

        Raises:
            ValueError: If any relationship dict is missing required keys.
            ConnectionError: If the database is unreachable (Neo4j only).
        """
        ...

    async def delete_node(self, node_id: str) -> bool:
        """Delete a node and all its relationships.

        Removes the node identified by ``node_id`` and detaches all
        connected relationships. This is a DETACH DELETE operation.

        Args:
            node_id: Node ID in ``{label}:{key_value}`` format.

        Returns:
            True if the node existed and was deleted, False if not found.

        Raises:
            ConnectionError: If the database is unreachable (Neo4j only).
        """
        ...

    async def query_entity_network(
        self,
        entity_id: str,
        max_hops: int = 2,
        investigation_id: str | None = None,
    ) -> QueryResult:
        """Find connected entities and facts within N hops of an entity.

        Traverses all relationship types up to ``max_hops`` from the given
        entity node. If ``investigation_id`` is provided, only returns nodes
        belonging to that investigation.

        Uses variable-length path patterns bounded by max_hops to prevent
        unbounded traversal (Pitfall 4 from RESEARCH.md).

        Args:
            entity_id: Entity node key (the natural key portion, not the
                full ``Entity:{key}`` ID).
            max_hops: Maximum traversal depth. Default 2, max 10.
            investigation_id: Optional investigation scope filter.

        Returns:
            QueryResult with query_type="entity_network" containing all
            nodes and edges in the neighborhood.
        """
        ...

    async def query_corroboration_clusters(
        self, investigation_id: str
    ) -> QueryResult:
        """Find groups of corroborating and contradicting facts.

        Returns clusters of facts connected by CORROBORATES or CONTRADICTS
        edges within the given investigation. Results are ordered by edge
        weight descending (strongest relationships first).

        Args:
            investigation_id: Investigation to scope the query.

        Returns:
            QueryResult with query_type="corroboration_clusters" containing
            fact nodes and their CORROBORATES/CONTRADICTS edges.
        """
        ...

    async def query_timeline(
        self,
        entity_id: str,
        investigation_id: str | None = None,
    ) -> QueryResult:
        """Get facts mentioning an entity ordered by temporal value.

        Returns facts connected to the entity via MENTIONS edges that have
        a ``temporal_value`` property, ordered ascending by time. Useful
        for constructing event timelines for an entity.

        Args:
            entity_id: Entity node key to build timeline for.
            investigation_id: Optional investigation scope filter.

        Returns:
            QueryResult with query_type="timeline" containing temporally
            ordered fact nodes and their MENTIONS edges.
        """
        ...

    async def query_shortest_path(
        self,
        from_entity_id: str,
        to_entity_id: str,
        investigation_id: str | None = None,
    ) -> QueryResult:
        """Find the shortest connection path between two entities.

        Uses the graph's native shortest path algorithm (Cypher
        ``shortestPath()`` on Neo4j, ``nx.shortest_path()`` on NetworkX).
        Path length is bounded to prevent unbounded traversal.

        Args:
            from_entity_id: Starting entity node key.
            to_entity_id: Target entity node key.
            investigation_id: Optional investigation scope filter.

        Returns:
            QueryResult with query_type="shortest_path" containing all
            nodes and edges along the shortest path. Empty result if no
            path exists.
        """
        ...

    async def execute_cypher(
        self, query: str, parameters: dict | None = None
    ) -> list[dict]:
        """Execute a raw Cypher query (escape hatch).

        Provides direct access to Neo4j's Cypher query language for queries
        not covered by the high-level methods. Parameters must use ``$name``
        syntax for injection safety (Pitfall 5 from RESEARCH.md).

        On NetworkX, this raises NotImplementedError since Cypher is a
        Neo4j-specific query language.

        Args:
            query: Cypher query string with ``$parameter`` placeholders.
            parameters: Optional dict of query parameters.

        Returns:
            List of record dicts, one per result row.

        Raises:
            NotImplementedError: On NetworkX adapter (Cypher not supported).
            ConnectionError: If the database is unreachable (Neo4j only).
        """
        ...
