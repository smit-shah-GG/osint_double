"""Neo4j GraphAdapter implementation.

Production graph backend using the official Neo4j async Python driver (v6.1+).
Uses UNWIND batch MERGE for high-performance ingestion, parameterized Cypher
for injection safety, and bounded variable-length paths to prevent OOM.

Per RESEARCH.md anti-patterns:
- NEVER MERGE on full patterns (nodes first, then relationships)
- NEVER share AsyncSession across tasks
- ALWAYS pass database_ to execute_query()
- ALWAYS parameterize values (no string interpolation for values)
- ALWAYS bound variable-length paths

Usage:
    from osint_system.config.graph_config import GraphConfig
    from osint_system.data_management.graph.neo4j_adapter import Neo4jAdapter

    config = GraphConfig.from_env()
    async with Neo4jAdapter(config) as adapter:
        await adapter.merge_node("Fact", {"fact_id": "f-1", "text": "..."}, "fact_id")
"""

from __future__ import annotations

import structlog
from neo4j import AsyncGraphDatabase

from osint_system.config.graph_config import GraphConfig
from osint_system.data_management.graph.cypher_queries import (
    BATCH_MERGE_NODES,
    BATCH_MERGE_RELATIONSHIPS,
    DELETE_NODE,
    MERGE_NODE,
    MERGE_RELATIONSHIP,
    QUERY_CORROBORATION_CLUSTERS,
    QUERY_ENTITY_NETWORK,
    QUERY_SHORTEST_PATH,
    QUERY_TIMELINE,
    SCHEMA_INIT_QUERIES,
)
from osint_system.data_management.graph.schema import (
    EdgeType,
    GraphEdge,
    GraphNode,
    QueryResult,
)

logger = structlog.get_logger(__name__)

# Allowlist for label injection into Cypher templates.
# Only these labels may be substituted -- prevents Cypher injection via labels.
_ALLOWED_LABELS: frozenset[str] = frozenset(
    {"Fact", "Entity", "Source", "Investigation", "Classification"}
)

# Allowlist for relationship types.
_ALLOWED_REL_TYPES: frozenset[str] = frozenset(e.value for e in EdgeType)


def _validate_label(label: str) -> str:
    """Validate that a label is in the allowlist.

    Raises:
        ValueError: If the label is not allowed.
    """
    if label not in _ALLOWED_LABELS:
        raise ValueError(
            f"Label {label!r} not in allowlist: {sorted(_ALLOWED_LABELS)}"
        )
    return label


def _validate_rel_type(rel_type: str) -> str:
    """Validate that a relationship type is in the allowlist.

    Raises:
        ValueError: If the relationship type is not allowed.
    """
    if rel_type not in _ALLOWED_REL_TYPES:
        raise ValueError(
            f"Relationship type {rel_type!r} not in allowlist: "
            f"{sorted(_ALLOWED_REL_TYPES)}"
        )
    return rel_type


def _parse_label_and_key(node_id: str) -> tuple[str, str, str]:
    """Parse a node ID in ``{label}:{key_value}`` format.

    Returns:
        (label, key_property_name, key_value) tuple. The key_property_name
        is inferred from the label (e.g., Fact -> fact_id).
    """
    parts = node_id.split(":", 1)
    if len(parts) != 2:
        raise ValueError(
            f"Invalid node_id format {node_id!r}. Expected '{{label}}:{{key_value}}'."
        )
    label, key_value = parts
    label = _validate_label(label)
    # Infer key property from label convention
    key_map = {
        "Fact": "fact_id",
        "Entity": "entity_id",
        "Source": "source_id",
        "Investigation": "investigation_id",
        "Classification": "classification_id",
    }
    key_property = key_map.get(label, "id")
    return label, key_property, key_value


class Neo4jAdapter:
    """Neo4j graph adapter implementing the GraphAdapter Protocol.

    Wraps the official ``neo4j`` async driver. Creates a single AsyncDriver
    (with its internal connection pool) on construction, and uses per-operation
    sessions. All Cypher queries are parameterized via constants from
    ``cypher_queries.py``.

    Args:
        config: GraphConfig with connection parameters.
    """

    def __init__(self, config: GraphConfig) -> None:
        self._config = config
        self._driver = AsyncGraphDatabase.driver(
            config.neo4j_uri,
            auth=(config.neo4j_user, config.neo4j_password),
        )
        self._database = config.neo4j_database
        self._initialized = False
        self._log = logger.bind(adapter="neo4j", database=self._database)

    # -- Context manager support -------------------------------------------

    async def __aenter__(self) -> Neo4jAdapter:
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: ANN001
        await self.close()

    # -- Lifecycle ---------------------------------------------------------

    async def initialize(self) -> None:
        """Verify connectivity and create schema constraints/indexes.

        Idempotent: all constraints/indexes use IF NOT EXISTS.

        Raises:
            ConnectionError: If Neo4j is unreachable.
        """
        try:
            await self._driver.verify_connectivity()
        except Exception as exc:
            self._log.error("neo4j_connectivity_failed", error=str(exc))
            raise ConnectionError(
                f"Cannot connect to Neo4j at {self._config.neo4j_uri}: {exc}"
            ) from exc

        self._log.info("neo4j_connected", uri=self._config.neo4j_uri)

        async with self._driver.session(database=self._database) as session:
            for query in SCHEMA_INIT_QUERIES:
                await session.run(query)

        self._initialized = True
        self._log.info(
            "neo4j_schema_initialized",
            constraint_count=len(SCHEMA_INIT_QUERIES),
        )

    async def close(self) -> None:
        """Close the Neo4j driver and release connection pool."""
        await self._driver.close()
        self._initialized = False
        self._log.info("neo4j_driver_closed")

    # -- Node operations ---------------------------------------------------

    async def merge_node(
        self, label: str, properties: dict, key_property: str = "id"
    ) -> str:
        """MERGE a single node by key property.

        Returns the node ID in ``{label}:{key_value}`` format.
        """
        label = _validate_label(label)
        if key_property not in properties:
            raise KeyError(
                f"Key property {key_property!r} not found in properties: "
                f"{sorted(properties.keys())}"
            )

        query = MERGE_NODE.format(label=label, key_property=key_property)
        key_value = properties[key_property]

        records, _, _ = await self._driver.execute_query(
            query,
            key_value=key_value,
            props=properties,
            database_=self._database,
        )

        node_id = f"{label}:{key_value}"
        self._log.debug("node_merged", node_id=node_id)
        return node_id

    async def batch_merge_nodes(
        self, label: str, nodes: list[dict], key_property: str = "id"
    ) -> int:
        """Batch MERGE nodes using UNWIND. Chunks by config.batch_size.

        Returns the total count of nodes merged.
        """
        label = _validate_label(label)
        if not nodes:
            return 0

        # Validate all nodes have the key property
        for i, node in enumerate(nodes):
            if key_property not in node:
                raise KeyError(
                    f"Node at index {i} missing key property {key_property!r}: "
                    f"{sorted(node.keys())}"
                )

        query = BATCH_MERGE_NODES.format(label=label, key_property=key_property)
        batch_size = self._config.batch_size
        total = 0

        for i in range(0, len(nodes), batch_size):
            batch = nodes[i : i + batch_size]
            records, _, _ = await self._driver.execute_query(
                query,
                nodes=batch,
                database_=self._database,
            )
            count = records[0]["count"] if records else 0
            total += count
            self._log.debug(
                "batch_nodes_merged",
                label=label,
                batch_index=i // batch_size,
                count=count,
            )

        self._log.info("batch_merge_nodes_complete", label=label, total=total)
        return total

    # -- Relationship operations -------------------------------------------

    async def merge_relationship(
        self, from_id: str, to_id: str, rel_type: str, properties: dict
    ) -> None:
        """MERGE a relationship between two nodes.

        Nodes are MERGEd separately first, then the relationship is MERGEd
        between the bound variables (Pitfall 1 avoidance).
        """
        rel_type = _validate_rel_type(rel_type)
        from_label, from_key, from_val = _parse_label_and_key(from_id)
        to_label, to_key, to_val = _parse_label_and_key(to_id)

        query = MERGE_RELATIONSHIP.format(
            from_label=from_label,
            from_key=from_key,
            to_label=to_label,
            to_key=to_key,
            rel_type=rel_type,
        )

        await self._driver.execute_query(
            query,
            from_id=from_val,
            to_id=to_val,
            props=properties,
            database_=self._database,
        )

        self._log.debug(
            "relationship_merged",
            from_id=from_id,
            to_id=to_id,
            rel_type=rel_type,
        )

    async def batch_merge_relationships(
        self, relationships: list[dict]
    ) -> int:
        """Batch MERGE relationships using UNWIND.

        Each dict in ``relationships`` must contain:
        - from_id: Source node ID ({label}:{key_value} format)
        - to_id: Target node ID ({label}:{key_value} format)
        - rel_type: Relationship type string
        - properties: Relationship properties dict

        Groups relationships by (from_label, to_label, rel_type) for efficient
        UNWIND execution.
        """
        if not relationships:
            return 0

        # Group by (from_label, from_key, to_label, to_key, rel_type) for
        # batched UNWIND execution
        groups: dict[tuple[str, str, str, str, str], list[dict]] = {}
        for rel in relationships:
            from_label, from_key, from_val = _parse_label_and_key(rel["from_id"])
            to_label, to_key, to_val = _parse_label_and_key(rel["to_id"])
            rel_type = _validate_rel_type(rel["rel_type"])
            group_key = (from_label, from_key, to_label, to_key, rel_type)
            groups.setdefault(group_key, []).append(
                {
                    "from_id": from_val,
                    "to_id": to_val,
                    "props": rel.get("properties", {}),
                }
            )

        total = 0
        batch_size = self._config.batch_size

        for (from_label, from_key, to_label, to_key, rel_type), rels in groups.items():
            query = BATCH_MERGE_RELATIONSHIPS.format(
                from_label=from_label,
                from_key=from_key,
                to_label=to_label,
                to_key=to_key,
                rel_type=rel_type,
            )
            for i in range(0, len(rels), batch_size):
                batch = rels[i : i + batch_size]
                records, _, _ = await self._driver.execute_query(
                    query,
                    rels=batch,
                    database_=self._database,
                )
                count = records[0]["count"] if records else 0
                total += count

        self._log.info(
            "batch_merge_relationships_complete",
            groups=len(groups),
            total=total,
        )
        return total

    # -- Delete operations -------------------------------------------------

    async def delete_node(self, node_id: str) -> bool:
        """DETACH DELETE a node and all its relationships.

        Returns True if the node existed and was deleted.
        """
        label, key_property, key_value = _parse_label_and_key(node_id)
        query = DELETE_NODE.format(label=label, key_property=key_property)

        records, _, _ = await self._driver.execute_query(
            query,
            key_value=key_value,
            database_=self._database,
        )

        deleted = records[0]["deleted"] if records else 0
        self._log.debug("node_deleted", node_id=node_id, deleted=deleted)
        return deleted > 0

    # -- Query operations --------------------------------------------------

    async def query_entity_network(
        self,
        entity_id: str,
        max_hops: int = 2,
        investigation_id: str | None = None,
    ) -> QueryResult:
        """Find connected nodes within N hops of an entity."""
        # Bound max_hops to prevent unbounded traversal (Pitfall 4)
        max_hops = min(max(1, max_hops), self._config.max_hops)
        query = QUERY_ENTITY_NETWORK.format(max_hops=max_hops)

        records, _, _ = await self._driver.execute_query(
            query,
            entity_id=entity_id,
            investigation_id=investigation_id,
            database_=self._database,
        )

        nodes, edges = _extract_paths(records)
        return QueryResult(
            nodes=nodes,
            edges=edges,
            query_type="entity_network",
            metadata={
                "entity_id": entity_id,
                "max_hops": max_hops,
                "investigation_id": investigation_id,
            },
        )

    async def query_corroboration_clusters(
        self, investigation_id: str
    ) -> QueryResult:
        """Find groups of corroborating/contradicting facts."""
        records, _, _ = await self._driver.execute_query(
            QUERY_CORROBORATION_CLUSTERS,
            investigation_id=investigation_id,
            database_=self._database,
        )

        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        seen_nodes: set[str] = set()
        node_pairs: list[tuple[str, str]] = []

        for record in records:
            f1_node = _neo4j_node_to_graph_node(record["f1"])
            f2_node = _neo4j_node_to_graph_node(record["f2"])
            edge = _neo4j_rel_to_graph_edge(record["r"])

            if f1_node.id not in seen_nodes:
                nodes.append(f1_node)
                seen_nodes.add(f1_node.id)
            if f2_node.id not in seen_nodes:
                nodes.append(f2_node)
                seen_nodes.add(f2_node.id)
            edges.append(edge)
            node_pairs.append((f1_node.id, f2_node.id))

        # Count clusters using union-find
        cluster_count = _count_clusters(node_pairs) if edges else 0

        return QueryResult(
            nodes=nodes,
            edges=edges,
            query_type="corroboration_clusters",
            metadata={
                "investigation_id": investigation_id,
                "cluster_count": cluster_count,
            },
        )

    async def query_timeline(
        self,
        entity_id: str,
        investigation_id: str | None = None,
    ) -> QueryResult:
        """Get facts mentioning an entity ordered by temporal value."""
        records, _, _ = await self._driver.execute_query(
            QUERY_TIMELINE,
            entity_id=entity_id,
            investigation_id=investigation_id,
            database_=self._database,
        )

        nodes = [_neo4j_node_to_graph_node(record["f"]) for record in records]
        return QueryResult(
            nodes=nodes,
            edges=[],
            query_type="timeline",
            metadata={
                "entity_id": entity_id,
                "investigation_id": investigation_id,
                "fact_count": len(nodes),
            },
        )

    async def query_shortest_path(
        self,
        from_entity_id: str,
        to_entity_id: str,
        investigation_id: str | None = None,
    ) -> QueryResult:
        """Find shortest path between two entities."""
        records, _, _ = await self._driver.execute_query(
            QUERY_SHORTEST_PATH,
            from_id=from_entity_id,
            to_id=to_entity_id,
            database_=self._database,
        )

        nodes, edges = _extract_paths(records)
        path_length = max(0, len(nodes) - 1) if nodes else 0
        return QueryResult(
            nodes=nodes,
            edges=edges,
            query_type="shortest_path",
            metadata={
                "from_entity_id": from_entity_id,
                "to_entity_id": to_entity_id,
                "investigation_id": investigation_id,
                "path_length": path_length,
            },
        )

    # -- Raw Cypher escape hatch -------------------------------------------

    async def execute_cypher(
        self, query: str, parameters: dict | None = None
    ) -> list[dict]:
        """Execute a raw Cypher query with parameters.

        For queries not covered by high-level methods. Parameters must use
        ``$name`` syntax for injection safety.
        """
        params = parameters or {}
        records, _, _ = await self._driver.execute_query(
            query, database_=self._database, **params
        )
        return [dict(record) for record in records]


# ---------------------------------------------------------------------------
# Helpers: Convert neo4j driver objects to Pydantic graph models
# ---------------------------------------------------------------------------


def _count_clusters(pairs: list[tuple[str, str]]) -> int:
    """Count connected components from edge pairs using union-find."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for u, v in pairs:
        parent.setdefault(u, u)
        parent.setdefault(v, v)
        union(u, v)

    roots = {find(n) for n in parent}
    return len(roots)


def _neo4j_node_to_graph_node(neo4j_node) -> GraphNode:  # noqa: ANN001
    """Convert a neo4j.graph.Node to a GraphNode.

    Infers node ID from label and known key property conventions.
    """
    labels = list(neo4j_node.labels)
    label = labels[0] if labels else "Unknown"
    props = dict(neo4j_node)

    # Determine node key from label convention
    key_map = {
        "Fact": "fact_id",
        "Entity": "entity_id",
        "Source": "source_id",
        "Investigation": "investigation_id",
        "Classification": "classification_id",
    }
    key_prop = key_map.get(label, "id")
    key_value = props.get(key_prop, str(neo4j_node.element_id))
    node_id = f"{label}:{key_value}"

    return GraphNode(id=node_id, label=label, properties=props)


def _neo4j_rel_to_graph_edge(neo4j_rel) -> GraphEdge:  # noqa: ANN001
    """Convert a neo4j.graph.Relationship to a GraphEdge.

    Extracts source/target from the relationship's start/end nodes.
    """
    props = dict(neo4j_rel)
    rel_type_str = neo4j_rel.type

    # Extract source/target node IDs from the relationship
    start_node = neo4j_rel.start_node
    end_node = neo4j_rel.end_node
    source_id = _neo4j_node_to_graph_node(start_node).id if start_node else "unknown"
    target_id = _neo4j_node_to_graph_node(end_node).id if end_node else "unknown"

    # Extract weight if present
    weight = props.pop("weight", 0.5)

    # Try to parse as EdgeType, fall back to RELATED_TO
    try:
        edge_type = EdgeType(rel_type_str)
    except ValueError:
        edge_type = EdgeType.RELATED_TO

    return GraphEdge(
        source_id=source_id,
        target_id=target_id,
        edge_type=edge_type,
        weight=weight,
        properties=props,
        cross_investigation=props.get("cross_investigation", False),
    )


def _extract_paths(records: list) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Extract unique nodes and edges from path-returning query results.

    Handles both single-path and multi-path results with deduplication.
    """
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    seen_nodes: set[str] = set()
    seen_edges: set[str] = set()

    for record in records:
        path = record.get("path") if isinstance(record, dict) else record["path"]
        if path is None:
            continue

        for node in path.nodes:
            graph_node = _neo4j_node_to_graph_node(node)
            if graph_node.id not in seen_nodes:
                nodes.append(graph_node)
                seen_nodes.add(graph_node.id)

        for rel in path.relationships:
            graph_edge = _neo4j_rel_to_graph_edge(rel)
            edge_key = f"{graph_edge.source_id}->{graph_edge.target_id}:{graph_edge.edge_type.value}"
            if edge_key not in seen_edges:
                edges.append(graph_edge)
                seen_edges.add(edge_key)

    return nodes, edges
