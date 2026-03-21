"""NetworkX GraphAdapter implementation for tests and CI.

In-memory graph backend using ``networkx.MultiDiGraph``. Provides identical
merge/query semantics to MemgraphAdapter without requiring Docker or a Memgraph
instance. Manually enforces key-property uniqueness since NetworkX has no
native constraint mechanism (Pitfall 6 from RESEARCH.md).

This adapter is NOT suitable for production. It is designed for:
- Unit/integration tests (fast, no infrastructure)
- CI pipelines (no Docker dependency)
- Local development when Memgraph is unavailable

Usage:
    from osint_system.data_management.graph.networkx_adapter import NetworkXAdapter

    adapter = NetworkXAdapter()
    await adapter.initialize()
    await adapter.merge_node("Fact", {"fact_id": "f-1", "text": "..."}, "fact_id")
"""

from __future__ import annotations

from collections import defaultdict

import networkx as nx
import structlog

from osint_system.data_management.graph.schema import (
    EdgeType,
    GraphEdge,
    GraphNode,
    QueryResult,
)

logger = structlog.get_logger(__name__)


class NetworkXAdapter:
    """NetworkX graph adapter implementing the GraphAdapter Protocol.

    Uses ``nx.MultiDiGraph`` for directed multi-edge support. Maintains a
    ``_node_index`` dict for O(1) key-property uniqueness enforcement,
    emulating Memgraph's MERGE + uniqueness constraints.

    Node keys follow the ``{label}:{properties[key_property]}`` convention
    consistent with MemgraphAdapter.
    """

    def __init__(self) -> None:
        self._graph = nx.MultiDiGraph()
        # Maps node_key -> properties dict for uniqueness enforcement
        self._node_index: dict[str, dict] = {}
        self._initialized = False
        self._log = logger.bind(adapter="networkx")

    # -- Context manager support -------------------------------------------

    async def __aenter__(self) -> NetworkXAdapter:
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: ANN001
        await self.close()

    # -- Lifecycle ---------------------------------------------------------

    async def initialize(self) -> None:
        """No-op for NetworkX (no constraints to create).

        Sets internal initialized flag for consistency.
        """
        self._initialized = True
        self._log.info("networkx_adapter_initialized")

    async def close(self) -> None:
        """Clear the in-memory graph and index."""
        self._graph.clear()
        self._node_index.clear()
        self._initialized = False
        self._log.info("networkx_adapter_closed")

    # -- Node operations ---------------------------------------------------

    async def merge_node(
        self, label: str, properties: dict, key_property: str = "id"
    ) -> str:
        """MERGE a single node by key property.

        Emulates Memgraph MERGE semantics:
        - ON CREATE: add new node with all properties
        - ON MATCH: update existing node's properties

        Uniqueness is enforced via ``_node_index`` keyed on
        ``{label}:{properties[key_property]}``.

        Returns the node key string.
        """
        if key_property not in properties:
            raise KeyError(
                f"Key property {key_property!r} not found in properties: "
                f"{sorted(properties.keys())}"
            )

        key_value = properties[key_property]
        node_key = f"{label}:{key_value}"

        if node_key in self._node_index:
            # ON MATCH: update properties (preserve label attribute)
            self._graph.nodes[node_key].update(properties)
            self._node_index[node_key].update(properties)
            self._log.debug("node_updated", node_key=node_key)
        else:
            # ON CREATE: add new node
            self._graph.add_node(node_key, label=label, **properties)
            self._node_index[node_key] = dict(properties)
            self._log.debug("node_created", node_key=node_key)

        return node_key

    async def batch_merge_nodes(
        self, label: str, nodes: list[dict], key_property: str = "id"
    ) -> int:
        """Batch MERGE nodes by iterating merge_node.

        No performance benefit in NetworkX (all in-memory), but maintains
        interface parity with MemgraphAdapter's UNWIND pattern.

        Returns the count of nodes merged.
        """
        count = 0
        for node in nodes:
            await self.merge_node(label, node, key_property)
            count += 1
        return count

    # -- Relationship operations -------------------------------------------

    async def merge_relationship(
        self, from_id: str, to_id: str, rel_type: str, properties: dict
    ) -> None:
        """MERGE a relationship between two nodes.

        Emulates Memgraph relationship MERGE:
        - If an edge with the same rel_type exists between from_id and to_id,
          update its properties (ON MATCH).
        - Otherwise, create a new edge (ON CREATE).

        Nodes do NOT need to pre-exist: if from_id or to_id is not in the
        graph, they are created as stub nodes (matching Memgraph MERGE behavior
        in the MERGE_RELATIONSHIP template which MERGEs nodes first).
        """
        # Ensure both nodes exist (stub if necessary, like Memgraph MERGE)
        if from_id not in self._node_index:
            label = from_id.split(":", 1)[0] if ":" in from_id else "Unknown"
            self._graph.add_node(from_id, label=label)
            self._node_index[from_id] = {}

        if to_id not in self._node_index:
            label = to_id.split(":", 1)[0] if ":" in to_id else "Unknown"
            self._graph.add_node(to_id, label=label)
            self._node_index[to_id] = {}

        # Check for existing edge with same rel_type
        if self._graph.has_edge(from_id, to_id):
            for edge_key, data in self._graph[from_id][to_id].items():
                if data.get("rel_type") == rel_type:
                    # ON MATCH: update properties
                    data.update(properties)
                    data["rel_type"] = rel_type  # Preserve rel_type
                    self._log.debug(
                        "relationship_updated",
                        from_id=from_id,
                        to_id=to_id,
                        rel_type=rel_type,
                    )
                    return

        # ON CREATE: new edge
        self._graph.add_edge(from_id, to_id, rel_type=rel_type, **properties)
        self._log.debug(
            "relationship_created",
            from_id=from_id,
            to_id=to_id,
            rel_type=rel_type,
        )

    async def batch_merge_relationships(
        self, relationships: list[dict]
    ) -> int:
        """Batch MERGE relationships by iterating merge_relationship.

        Each dict must contain: from_id, to_id, rel_type, properties.

        Returns the count of relationships merged.
        """
        count = 0
        for rel in relationships:
            await self.merge_relationship(
                from_id=rel["from_id"],
                to_id=rel["to_id"],
                rel_type=rel["rel_type"],
                properties=rel.get("properties", {}),
            )
            count += 1
        return count

    # -- Delete operations -------------------------------------------------

    async def delete_node(self, node_id: str) -> bool:
        """Remove a node and all its edges.

        Returns True if the node existed and was deleted.
        """
        if node_id not in self._node_index:
            return False

        self._graph.remove_node(node_id)
        del self._node_index[node_id]
        self._log.debug("node_deleted", node_id=node_id)
        return True

    # -- Query operations --------------------------------------------------

    async def query_entity_network(
        self,
        entity_id: str,
        max_hops: int = 2,
        investigation_id: str | None = None,
    ) -> QueryResult:
        """Find connected nodes within N hops of an entity.

        Uses BFS traversal bounded by max_hops. Traverses bidirectionally
        (both successors and predecessors) since entity networks ignore edge
        direction. Filters by investigation_id if provided -- nodes whose
        investigation_id is set but doesn't match are excluded.
        """
        node_key = f"Entity:{entity_id}"
        if node_key not in self._graph:
            return QueryResult(
                nodes=[], edges=[], query_type="entity_network",
                metadata={
                    "entity_id": entity_id,
                    "max_hops": max_hops,
                    "investigation_id": investigation_id,
                },
            )

        max_hops = min(max(1, max_hops), 10)

        # BFS to find all nodes within max_hops (bidirectional traversal)
        visited: set[str] = set()
        collected_edges: list[GraphEdge] = []
        frontier = {node_key}

        for _hop in range(max_hops):
            next_frontier: set[str] = set()
            for current in frontier:
                if current in visited:
                    continue
                visited.add(current)

                # Outgoing edges
                for neighbor in self._graph.successors(current):
                    if neighbor not in visited:
                        next_frontier.add(neighbor)
                    for _ek, data in self._graph[current][neighbor].items():
                        collected_edges.append(
                            self._data_to_graph_edge(current, neighbor, data)
                        )

                # Incoming edges (bidirectional traversal for entity networks)
                for predecessor in self._graph.predecessors(current):
                    if predecessor not in visited:
                        next_frontier.add(predecessor)
                    for _ek, data in self._graph[predecessor][current].items():
                        collected_edges.append(
                            self._data_to_graph_edge(predecessor, current, data)
                        )

            frontier = next_frontier

        # Final frontier nodes are reachable but not yet expanded -- include
        # them in the result set (they are within max_hops distance)
        visited.update(frontier)

        # Convert visited node keys to GraphNodes, filtering by investigation.
        # Nodes whose investigation_id is set but doesn't match are excluded.
        # Nodes with no investigation_id (e.g. stub nodes) pass through.
        result_nodes: list[GraphNode] = []
        included_node_keys: set[str] = set()
        for nk in visited:
            node = self._node_key_to_graph_node(nk)
            if investigation_id is not None:
                node_inv = node.properties.get("investigation_id")
                if node_inv is not None and node_inv != investigation_id:
                    continue
            result_nodes.append(node)
            included_node_keys.add(nk)

        # Deduplicate edges and exclude edges referencing filtered-out nodes
        seen_edges: set[str] = set()
        unique_edges: list[GraphEdge] = []
        for edge in collected_edges:
            if edge.source_id not in included_node_keys:
                continue
            if edge.target_id not in included_node_keys:
                continue
            ek = f"{edge.source_id}->{edge.target_id}:{edge.edge_type.value}"
            if ek not in seen_edges:
                unique_edges.append(edge)
                seen_edges.add(ek)

        return QueryResult(
            nodes=result_nodes,
            edges=unique_edges,
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
        """Find corroborating/contradicting fact clusters in an investigation.

        Scans all edges of type CORROBORATES or CONTRADICTS where at least the
        source node belongs to the given investigation. Collects the connected
        fact nodes and their corroboration/contradiction edges.

        Metadata includes ``cluster_count`` -- the number of distinct connected
        components in the corroboration subgraph (useful for understanding how
        many independent agreement/disagreement groups exist).
        """
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        seen_nodes: set[str] = set()
        corroboration_types = {EdgeType.CORROBORATES.value, EdgeType.CONTRADICTS.value}

        # Collect node pairs for cluster counting via union-find
        cluster_node_pairs: list[tuple[str, str]] = []

        for u, v, data in self._graph.edges(data=True):
            rel_type = data.get("rel_type", "")
            if rel_type not in corroboration_types:
                continue

            # Check that at least the source fact belongs to this investigation
            u_props = self._node_index.get(u, {})
            u_attrs = self._graph.nodes.get(u, {})
            u_inv = u_props.get("investigation_id") or u_attrs.get("investigation_id")
            if u_inv != investigation_id:
                continue

            edge = self._data_to_graph_edge(u, v, data)
            edges.append(edge)
            cluster_node_pairs.append((u, v))

            for nk in (u, v):
                if nk not in seen_nodes:
                    nodes.append(self._node_key_to_graph_node(nk))
                    seen_nodes.add(nk)

        # Sort edges by weight descending
        edges.sort(key=lambda e: e.weight, reverse=True)

        # Count clusters using union-find on collected node pairs
        cluster_count = self._count_clusters(cluster_node_pairs) if edges else 0

        return QueryResult(
            nodes=nodes,
            edges=edges,
            query_type="corroboration_clusters",
            metadata={
                "investigation_id": investigation_id,
                "cluster_count": cluster_count,
            },
        )

    @staticmethod
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

    async def query_timeline(
        self,
        entity_id: str,
        investigation_id: str | None = None,
    ) -> QueryResult:
        """Get facts mentioning an entity ordered by temporal value.

        Finds Fact nodes connected to the entity via incoming MENTIONS edges
        (Fact -MENTIONS-> Entity) that have a non-None ``temporal_value``
        property. Results are sorted ascending by temporal_value (ISO-format
        string sort).

        Metadata includes ``fact_count`` for the number of temporal facts found.
        """
        entity_key = f"Entity:{entity_id}"
        if entity_key not in self._graph:
            return QueryResult(
                nodes=[], edges=[], query_type="timeline",
                metadata={
                    "entity_id": entity_id,
                    "investigation_id": investigation_id,
                    "fact_count": 0,
                },
            )

        fact_nodes: list[GraphNode] = []
        seen_facts: set[str] = set()

        # Find incoming MENTIONS edges (Fact -> Entity means Fact MENTIONS Entity)
        for predecessor in self._graph.predecessors(entity_key):
            if predecessor in seen_facts:
                continue

            for _ek, data in self._graph[predecessor][entity_key].items():
                if data.get("rel_type") != EdgeType.MENTIONS.value:
                    continue

                node_props = self._node_index.get(predecessor, {})
                graph_attrs = self._graph.nodes.get(predecessor, {})

                # Check temporal_value exists
                temporal = node_props.get("temporal_value") or graph_attrs.get("temporal_value")
                if temporal is None:
                    continue

                # Filter by investigation_id
                inv_id = node_props.get("investigation_id") or graph_attrs.get("investigation_id")
                if investigation_id is not None and inv_id != investigation_id:
                    continue

                fact_nodes.append(self._node_key_to_graph_node(predecessor))
                seen_facts.add(predecessor)
                break  # One MENTIONS edge per fact-entity pair is sufficient

        # Sort by temporal_value ascending (ISO-format strings sort correctly)
        fact_nodes.sort(
            key=lambda n: n.properties.get("temporal_value", "")
        )

        return QueryResult(
            nodes=fact_nodes,
            edges=[],
            query_type="timeline",
            metadata={
                "entity_id": entity_id,
                "investigation_id": investigation_id,
                "fact_count": len(fact_nodes),
            },
        )

    async def query_shortest_path(
        self,
        from_entity_id: str,
        to_entity_id: str,
        investigation_id: str | None = None,
    ) -> QueryResult:
        """Find shortest path between two entities.

        Uses NetworkX's shortest_path algorithm on the undirected view
        of the graph (entity networks are traversed bidirectionally).

        Handles same-entity case (from == to) by returning a single-node
        result with path_length=0.

        Metadata includes ``path_length`` (number of edges in the path).
        """
        from_key = f"Entity:{from_entity_id}"
        to_key = f"Entity:{to_entity_id}"

        empty_metadata = {
            "from_entity_id": from_entity_id,
            "to_entity_id": to_entity_id,
            "investigation_id": investigation_id,
            "path_length": 0,
        }

        if from_key not in self._graph or to_key not in self._graph:
            return QueryResult(
                nodes=[], edges=[], query_type="shortest_path",
                metadata=empty_metadata,
            )

        # Same entity: return single-node path
        if from_key == to_key:
            return QueryResult(
                nodes=[self._node_key_to_graph_node(from_key)],
                edges=[],
                query_type="shortest_path",
                metadata={
                    "from_entity_id": from_entity_id,
                    "to_entity_id": to_entity_id,
                    "investigation_id": investigation_id,
                    "path_length": 0,
                },
            )

        try:
            # Use undirected view for path finding
            undirected = self._graph.to_undirected(as_view=True)
            path_nodes = nx.shortest_path(undirected, from_key, to_key)
        except nx.NetworkXNoPath:
            return QueryResult(
                nodes=[], edges=[], query_type="shortest_path",
                metadata=empty_metadata,
            )

        # Build result
        result_nodes = [self._node_key_to_graph_node(nk) for nk in path_nodes]
        result_edges: list[GraphEdge] = []

        for i in range(len(path_nodes) - 1):
            u, v = path_nodes[i], path_nodes[i + 1]
            # Check both directions for edges (undirected path may traverse
            # against the directed edge)
            if self._graph.has_edge(u, v):
                for _ek, data in self._graph[u][v].items():
                    result_edges.append(self._data_to_graph_edge(u, v, data))
                    break  # One edge per hop is sufficient for path
            elif self._graph.has_edge(v, u):
                for _ek, data in self._graph[v][u].items():
                    result_edges.append(self._data_to_graph_edge(v, u, data))
                    break

        return QueryResult(
            nodes=result_nodes,
            edges=result_edges,
            query_type="shortest_path",
            metadata={
                "from_entity_id": from_entity_id,
                "to_entity_id": to_entity_id,
                "investigation_id": investigation_id,
                "path_length": len(path_nodes) - 1,
            },
        )

    # -- Raw Cypher (not supported) ----------------------------------------

    async def execute_cypher(
        self, query: str, parameters: dict | None = None
    ) -> list[dict]:
        """Raise NotImplementedError -- Cypher is Memgraph-specific.

        Use high-level query methods instead.
        """
        raise NotImplementedError(
            "Raw Cypher is not supported by NetworkX adapter. "
            "Use high-level query methods instead."
        )

    # -- Internal helpers --------------------------------------------------

    def _node_key_to_graph_node(self, node_key: str) -> GraphNode:
        """Convert an internal node key to a GraphNode Pydantic model."""
        parts = node_key.split(":", 1)
        label = parts[0] if len(parts) == 2 else "Unknown"

        # Merge properties from both _node_index and graph node attrs
        props = dict(self._node_index.get(node_key, {}))
        graph_attrs = dict(self._graph.nodes.get(node_key, {}))
        # graph_attrs may include 'label' key from add_node; exclude it
        graph_attrs.pop("label", None)
        # Node index properties take precedence
        merged = {**graph_attrs, **props}

        return GraphNode(id=node_key, label=label, properties=merged)

    @staticmethod
    def _data_to_graph_edge(
        from_id: str, to_id: str, data: dict
    ) -> GraphEdge:
        """Convert NetworkX edge data to a GraphEdge Pydantic model.

        Extracts ``rel_type``, ``weight``, and ``cross_investigation`` from the
        raw edge data dict before passing remaining properties to GraphEdge.
        """
        props = dict(data)
        rel_type_str = props.pop("rel_type", EdgeType.RELATED_TO.value)
        weight = props.pop("weight", 0.5)
        cross_inv = props.pop("cross_investigation", False)

        try:
            edge_type = EdgeType(rel_type_str)
        except ValueError:
            edge_type = EdgeType.RELATED_TO

        return GraphEdge(
            source_id=from_id,
            target_id=to_id,
            edge_type=edge_type,
            weight=weight,
            properties=props,
            cross_investigation=cross_inv,
        )
