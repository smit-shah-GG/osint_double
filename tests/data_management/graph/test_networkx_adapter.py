"""Behavioral tests for NetworkXAdapter.

Validates that the NetworkX in-memory adapter exhibits the same merge/query
semantics as MemgraphAdapter without requiring Docker or a Memgraph instance.
Tests cover:

1. MERGE node semantics (create on first call, update on duplicate key)
2. Batch MERGE nodes (count, deduplication)
3. Relationship MERGE (create, update on duplicate)
4. No full-pattern MERGE pitfall (no duplicate nodes from relationship MERGE)
5. Entity network query (N-hop traversal)
6. Corroboration clusters query
7. Timeline query (temporal ordering)
8. Shortest path query
9. Delete node (node + edges removed)
10. execute_cypher raises NotImplementedError
11. Cross-investigation filtering

All tests are async and use pytest-asyncio.
"""

import pytest
import pytest_asyncio

from osint_system.data_management.graph.networkx_adapter import NetworkXAdapter
from osint_system.data_management.graph.schema import EdgeType


@pytest_asyncio.fixture
async def adapter():
    """Create and initialize a fresh NetworkXAdapter for each test."""
    a = NetworkXAdapter()
    await a.initialize()
    yield a
    await a.close()


# ---------------------------------------------------------------------------
# 1. Merge node semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_node_creates_on_first_call(adapter: NetworkXAdapter):
    """First merge_node with a new key creates a node."""
    node_id = await adapter.merge_node(
        "Fact", {"fact_id": "f-1", "claim_text": "Initial claim"}, "fact_id"
    )
    assert node_id == "Fact:f-1"
    assert "Fact:f-1" in adapter._node_index


@pytest.mark.asyncio
async def test_merge_node_updates_on_duplicate_key(adapter: NetworkXAdapter):
    """Second merge_node with the same key updates properties, not duplicates."""
    await adapter.merge_node(
        "Fact", {"fact_id": "f-1", "claim_text": "Original"}, "fact_id"
    )
    await adapter.merge_node(
        "Fact", {"fact_id": "f-1", "claim_text": "Updated"}, "fact_id"
    )

    # Only one node should exist
    assert len(adapter._node_index) == 1
    assert adapter._node_index["Fact:f-1"]["claim_text"] == "Updated"
    # Graph should have exactly one node
    assert adapter._graph.number_of_nodes() == 1


@pytest.mark.asyncio
async def test_merge_node_preserves_properties_on_update(adapter: NetworkXAdapter):
    """Update merges new properties while preserving existing ones."""
    await adapter.merge_node(
        "Entity",
        {"entity_id": "e-1", "name": "Putin", "entity_type": "PERSON"},
        "entity_id",
    )
    await adapter.merge_node(
        "Entity",
        {"entity_id": "e-1", "canonical": "Vladimir Putin"},
        "entity_id",
    )

    props = adapter._node_index["Entity:e-1"]
    assert props["name"] == "Putin"
    assert props["canonical"] == "Vladimir Putin"


@pytest.mark.asyncio
async def test_merge_node_raises_on_missing_key_property(adapter: NetworkXAdapter):
    """merge_node raises KeyError if key_property not in properties."""
    with pytest.raises(KeyError, match="fact_id"):
        await adapter.merge_node("Fact", {"text": "no fact_id"}, "fact_id")


# ---------------------------------------------------------------------------
# 2. Batch merge nodes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_merge_nodes_returns_count(adapter: NetworkXAdapter):
    """batch_merge_nodes returns the number of nodes merged."""
    nodes = [{"fact_id": f"f-{i}", "text": f"Fact {i}"} for i in range(10)]
    count = await adapter.batch_merge_nodes("Fact", nodes, "fact_id")
    assert count == 10
    assert adapter._graph.number_of_nodes() == 10


@pytest.mark.asyncio
async def test_batch_merge_nodes_deduplicates(adapter: NetworkXAdapter):
    """Duplicate nodes in a batch are merged, not duplicated."""
    nodes = [
        {"fact_id": "f-1", "text": "Version 1"},
        {"fact_id": "f-2", "text": "Another fact"},
        {"fact_id": "f-1", "text": "Version 2"},  # Duplicate key
    ]
    count = await adapter.batch_merge_nodes("Fact", nodes, "fact_id")
    assert count == 3  # All processed
    assert adapter._graph.number_of_nodes() == 2  # Only 2 unique
    assert adapter._node_index["Fact:f-1"]["text"] == "Version 2"


@pytest.mark.asyncio
async def test_batch_merge_nodes_empty_list(adapter: NetworkXAdapter):
    """batch_merge_nodes with empty list returns 0."""
    count = await adapter.batch_merge_nodes("Fact", [], "fact_id")
    assert count == 0


# ---------------------------------------------------------------------------
# 3. Relationship merge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_relationship_creates_edge(adapter: NetworkXAdapter):
    """merge_relationship creates an edge between two nodes."""
    await adapter.merge_node("Fact", {"fact_id": "f-1"}, "fact_id")
    await adapter.merge_node("Entity", {"entity_id": "e-1"}, "entity_id")

    await adapter.merge_relationship(
        "Fact:f-1", "Entity:e-1", EdgeType.MENTIONS.value,
        {"entity_marker": "E1"},
    )

    assert adapter._graph.has_edge("Fact:f-1", "Entity:e-1")
    assert adapter._graph.number_of_edges() == 1


@pytest.mark.asyncio
async def test_merge_relationship_updates_on_duplicate(adapter: NetworkXAdapter):
    """Second merge_relationship with same type updates properties."""
    await adapter.merge_node("Fact", {"fact_id": "f-1"}, "fact_id")
    await adapter.merge_node("Fact", {"fact_id": "f-2"}, "fact_id")

    await adapter.merge_relationship(
        "Fact:f-1", "Fact:f-2", EdgeType.CORROBORATES.value,
        {"weight": 0.5, "evidence_count": 1},
    )
    await adapter.merge_relationship(
        "Fact:f-1", "Fact:f-2", EdgeType.CORROBORATES.value,
        {"weight": 0.8, "evidence_count": 3},
    )

    # Should still have exactly one edge
    assert adapter._graph.number_of_edges() == 1
    edge_data = list(adapter._graph["Fact:f-1"]["Fact:f-2"].values())[0]
    assert edge_data["weight"] == 0.8
    assert edge_data["evidence_count"] == 3


@pytest.mark.asyncio
async def test_merge_relationship_different_types_create_separate_edges(
    adapter: NetworkXAdapter,
):
    """Different relationship types between same nodes create separate edges."""
    await adapter.merge_node("Fact", {"fact_id": "f-1"}, "fact_id")
    await adapter.merge_node("Fact", {"fact_id": "f-2"}, "fact_id")

    await adapter.merge_relationship(
        "Fact:f-1", "Fact:f-2", EdgeType.CORROBORATES.value, {"weight": 0.8},
    )
    await adapter.merge_relationship(
        "Fact:f-1", "Fact:f-2", EdgeType.PRECEDES.value, {"order": 1},
    )

    assert adapter._graph.number_of_edges() == 2


# ---------------------------------------------------------------------------
# 4. No full-pattern MERGE pitfall
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_relationship_merge_does_not_duplicate_nodes(adapter: NetworkXAdapter):
    """Merging a relationship between existing nodes must NOT create duplicate nodes.

    This validates that the adapter avoids the Neo4j full-pattern MERGE pitfall
    (Pitfall 1 from RESEARCH.md).
    """
    await adapter.merge_node("Fact", {"fact_id": "f-1", "text": "A"}, "fact_id")
    await adapter.merge_node("Entity", {"entity_id": "e-1", "name": "X"}, "entity_id")

    node_count_before = adapter._graph.number_of_nodes()

    await adapter.merge_relationship(
        "Fact:f-1", "Entity:e-1", EdgeType.MENTIONS.value, {},
    )

    assert adapter._graph.number_of_nodes() == node_count_before


@pytest.mark.asyncio
async def test_relationship_merge_creates_stub_nodes_if_missing(
    adapter: NetworkXAdapter,
):
    """If nodes don't exist, merge_relationship creates stubs (matching Neo4j MERGE behavior)."""
    await adapter.merge_relationship(
        "Fact:f-new", "Entity:e-new", EdgeType.MENTIONS.value, {},
    )

    assert "Fact:f-new" in adapter._node_index
    assert "Entity:e-new" in adapter._node_index
    assert adapter._graph.has_edge("Fact:f-new", "Entity:e-new")


# ---------------------------------------------------------------------------
# 5. Entity network query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_entity_network_returns_connected_nodes(adapter: NetworkXAdapter):
    """Entity network query returns nodes within N hops."""
    # Build: Entity:e-1 <-MENTIONS- Fact:f-1 -MENTIONS-> Entity:e-2
    await adapter.merge_node(
        "Entity",
        {"entity_id": "e-1", "name": "Entity A", "investigation_id": "inv-1"},
        "entity_id",
    )
    await adapter.merge_node(
        "Fact",
        {"fact_id": "f-1", "text": "Links A and B", "investigation_id": "inv-1"},
        "fact_id",
    )
    await adapter.merge_node(
        "Entity",
        {"entity_id": "e-2", "name": "Entity B", "investigation_id": "inv-1"},
        "entity_id",
    )
    await adapter.merge_relationship(
        "Fact:f-1", "Entity:e-1", EdgeType.MENTIONS.value, {},
    )
    await adapter.merge_relationship(
        "Fact:f-1", "Entity:e-2", EdgeType.MENTIONS.value, {},
    )

    result = await adapter.query_entity_network("e-1", max_hops=2)

    assert result.query_type == "entity_network"
    assert result.node_count >= 2  # At least Entity:e-1 and Fact:f-1
    node_ids = {n.id for n in result.nodes}
    assert "Entity:e-1" in node_ids
    assert "Fact:f-1" in node_ids


@pytest.mark.asyncio
async def test_query_entity_network_nonexistent_entity(adapter: NetworkXAdapter):
    """Query for a nonexistent entity returns empty result."""
    result = await adapter.query_entity_network("nonexistent")
    assert result.node_count == 0
    assert result.edge_count == 0


# ---------------------------------------------------------------------------
# 6. Corroboration clusters query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_corroboration_clusters(adapter: NetworkXAdapter):
    """Corroboration clusters returns CORROBORATES/CONTRADICTS edges."""
    await adapter.merge_node(
        "Fact",
        {"fact_id": "f-1", "text": "Claim A", "investigation_id": "inv-1"},
        "fact_id",
    )
    await adapter.merge_node(
        "Fact",
        {"fact_id": "f-2", "text": "Supports A", "investigation_id": "inv-1"},
        "fact_id",
    )
    await adapter.merge_node(
        "Fact",
        {"fact_id": "f-3", "text": "Contradicts A", "investigation_id": "inv-1"},
        "fact_id",
    )

    await adapter.merge_relationship(
        "Fact:f-1", "Fact:f-2", EdgeType.CORROBORATES.value, {"weight": 0.9},
    )
    await adapter.merge_relationship(
        "Fact:f-1", "Fact:f-3", EdgeType.CONTRADICTS.value, {"weight": 0.7},
    )

    result = await adapter.query_corroboration_clusters("inv-1")

    assert result.query_type == "corroboration_clusters"
    assert result.edge_count == 2
    assert result.node_count == 3

    # Verify sorted by weight descending
    assert result.edges[0].weight >= result.edges[1].weight


@pytest.mark.asyncio
async def test_query_corroboration_clusters_filters_investigation(
    adapter: NetworkXAdapter,
):
    """Corroboration clusters only returns edges from the specified investigation."""
    # inv-1 cluster
    await adapter.merge_node(
        "Fact", {"fact_id": "f-1", "investigation_id": "inv-1"}, "fact_id",
    )
    await adapter.merge_node(
        "Fact", {"fact_id": "f-2", "investigation_id": "inv-1"}, "fact_id",
    )
    await adapter.merge_relationship(
        "Fact:f-1", "Fact:f-2", EdgeType.CORROBORATES.value, {"weight": 0.8},
    )

    # inv-2 cluster (should not appear)
    await adapter.merge_node(
        "Fact", {"fact_id": "f-3", "investigation_id": "inv-2"}, "fact_id",
    )
    await adapter.merge_node(
        "Fact", {"fact_id": "f-4", "investigation_id": "inv-2"}, "fact_id",
    )
    await adapter.merge_relationship(
        "Fact:f-3", "Fact:f-4", EdgeType.CORROBORATES.value, {"weight": 0.9},
    )

    result = await adapter.query_corroboration_clusters("inv-1")
    assert result.edge_count == 1
    assert result.node_count == 2


# ---------------------------------------------------------------------------
# 7. Timeline query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_timeline_returns_chronological_facts(adapter: NetworkXAdapter):
    """Timeline query returns facts ordered by temporal_value ascending."""
    await adapter.merge_node(
        "Entity", {"entity_id": "e-1", "name": "Putin"}, "entity_id",
    )

    # Facts with temporal values (out of order intentionally)
    await adapter.merge_node(
        "Fact",
        {"fact_id": "f-2", "temporal_value": "2024-03-15", "investigation_id": "inv-1"},
        "fact_id",
    )
    await adapter.merge_node(
        "Fact",
        {"fact_id": "f-1", "temporal_value": "2024-01-10", "investigation_id": "inv-1"},
        "fact_id",
    )
    await adapter.merge_node(
        "Fact",
        {"fact_id": "f-3", "temporal_value": "2024-06-20", "investigation_id": "inv-1"},
        "fact_id",
    )
    # Fact without temporal_value (should be excluded)
    await adapter.merge_node(
        "Fact",
        {"fact_id": "f-4", "investigation_id": "inv-1"},
        "fact_id",
    )

    # Connect all facts to entity via MENTIONS
    for fid in ["f-1", "f-2", "f-3", "f-4"]:
        await adapter.merge_relationship(
            f"Fact:{fid}", "Entity:e-1", EdgeType.MENTIONS.value, {},
        )

    result = await adapter.query_timeline("e-1")

    assert result.query_type == "timeline"
    assert result.node_count == 3  # f-4 excluded (no temporal_value)

    temporal_values = [n.properties.get("temporal_value") for n in result.nodes]
    assert temporal_values == ["2024-01-10", "2024-03-15", "2024-06-20"]


@pytest.mark.asyncio
async def test_query_timeline_nonexistent_entity(adapter: NetworkXAdapter):
    """Timeline for nonexistent entity returns empty result."""
    result = await adapter.query_timeline("nonexistent")
    assert result.node_count == 0


# ---------------------------------------------------------------------------
# 8. Shortest path query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_shortest_path_finds_path(adapter: NetworkXAdapter):
    """Shortest path query finds A-B-C chain."""
    await adapter.merge_node("Entity", {"entity_id": "e-a", "name": "A"}, "entity_id")
    await adapter.merge_node("Fact", {"fact_id": "f-ab"}, "fact_id")
    await adapter.merge_node("Entity", {"entity_id": "e-b", "name": "B"}, "entity_id")
    await adapter.merge_node("Fact", {"fact_id": "f-bc"}, "fact_id")
    await adapter.merge_node("Entity", {"entity_id": "e-c", "name": "C"}, "entity_id")

    # A <- f-ab -> B <- f-bc -> C
    await adapter.merge_relationship(
        "Fact:f-ab", "Entity:e-a", EdgeType.MENTIONS.value, {},
    )
    await adapter.merge_relationship(
        "Fact:f-ab", "Entity:e-b", EdgeType.MENTIONS.value, {},
    )
    await adapter.merge_relationship(
        "Fact:f-bc", "Entity:e-b", EdgeType.MENTIONS.value, {},
    )
    await adapter.merge_relationship(
        "Fact:f-bc", "Entity:e-c", EdgeType.MENTIONS.value, {},
    )

    result = await adapter.query_shortest_path("e-a", "e-c")

    assert result.query_type == "shortest_path"
    assert result.node_count >= 3  # At least A, intermediate, C
    node_ids = {n.id for n in result.nodes}
    assert "Entity:e-a" in node_ids
    assert "Entity:e-c" in node_ids


@pytest.mark.asyncio
async def test_query_shortest_path_no_connection(adapter: NetworkXAdapter):
    """Shortest path between disconnected entities returns empty result."""
    await adapter.merge_node("Entity", {"entity_id": "e-a"}, "entity_id")
    await adapter.merge_node("Entity", {"entity_id": "e-z"}, "entity_id")

    result = await adapter.query_shortest_path("e-a", "e-z")
    assert result.node_count == 0


@pytest.mark.asyncio
async def test_query_shortest_path_nonexistent_entities(adapter: NetworkXAdapter):
    """Shortest path with nonexistent entities returns empty result."""
    result = await adapter.query_shortest_path("nonexistent-a", "nonexistent-b")
    assert result.node_count == 0


# ---------------------------------------------------------------------------
# 9. Delete node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_node_removes_node_and_edges(adapter: NetworkXAdapter):
    """delete_node removes the node and all connected edges."""
    await adapter.merge_node("Fact", {"fact_id": "f-1"}, "fact_id")
    await adapter.merge_node("Entity", {"entity_id": "e-1"}, "entity_id")
    await adapter.merge_relationship(
        "Fact:f-1", "Entity:e-1", EdgeType.MENTIONS.value, {},
    )

    assert adapter._graph.number_of_nodes() == 2
    assert adapter._graph.number_of_edges() == 1

    deleted = await adapter.delete_node("Fact:f-1")

    assert deleted is True
    assert adapter._graph.number_of_nodes() == 1
    assert adapter._graph.number_of_edges() == 0
    assert "Fact:f-1" not in adapter._node_index


@pytest.mark.asyncio
async def test_delete_node_returns_false_if_not_found(adapter: NetworkXAdapter):
    """delete_node returns False for nonexistent node."""
    deleted = await adapter.delete_node("Fact:nonexistent")
    assert deleted is False


# ---------------------------------------------------------------------------
# 10. execute_cypher raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_cypher_raises_not_implemented(adapter: NetworkXAdapter):
    """execute_cypher raises NotImplementedError on NetworkX adapter."""
    with pytest.raises(NotImplementedError, match="Raw Cypher is not supported"):
        await adapter.execute_cypher("MATCH (n) RETURN n")


# ---------------------------------------------------------------------------
# 11. Cross-investigation filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entity_network_filters_by_investigation(adapter: NetworkXAdapter):
    """Entity network query respects investigation_id filter."""
    await adapter.merge_node(
        "Entity",
        {"entity_id": "e-shared", "name": "Shared", "investigation_id": "inv-1"},
        "entity_id",
    )
    # Fact in inv-1
    await adapter.merge_node(
        "Fact",
        {"fact_id": "f-inv1", "investigation_id": "inv-1"},
        "fact_id",
    )
    # Fact in inv-2
    await adapter.merge_node(
        "Fact",
        {"fact_id": "f-inv2", "investigation_id": "inv-2"},
        "fact_id",
    )

    await adapter.merge_relationship(
        "Fact:f-inv1", "Entity:e-shared", EdgeType.MENTIONS.value, {},
    )
    await adapter.merge_relationship(
        "Fact:f-inv2", "Entity:e-shared", EdgeType.MENTIONS.value, {},
    )

    # Query filtered to inv-1
    result = await adapter.query_entity_network(
        "e-shared", max_hops=2, investigation_id="inv-1"
    )

    node_inv_ids = {
        n.properties.get("investigation_id")
        for n in result.nodes
        if n.properties.get("investigation_id") is not None
    }
    # All nodes with investigation_id should be inv-1
    assert "inv-2" not in node_inv_ids


@pytest.mark.asyncio
async def test_timeline_filters_by_investigation(adapter: NetworkXAdapter):
    """Timeline query respects investigation_id filter."""
    await adapter.merge_node(
        "Entity", {"entity_id": "e-1", "name": "Test"}, "entity_id",
    )
    await adapter.merge_node(
        "Fact",
        {"fact_id": "f-1", "temporal_value": "2024-01-01", "investigation_id": "inv-1"},
        "fact_id",
    )
    await adapter.merge_node(
        "Fact",
        {"fact_id": "f-2", "temporal_value": "2024-02-01", "investigation_id": "inv-2"},
        "fact_id",
    )

    await adapter.merge_relationship(
        "Fact:f-1", "Entity:e-1", EdgeType.MENTIONS.value, {},
    )
    await adapter.merge_relationship(
        "Fact:f-2", "Entity:e-1", EdgeType.MENTIONS.value, {},
    )

    result = await adapter.query_timeline("e-1", investigation_id="inv-1")
    assert result.node_count == 1
    assert result.nodes[0].properties["fact_id"] == "f-1"


# ---------------------------------------------------------------------------
# 12. Batch merge relationships
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_merge_relationships(adapter: NetworkXAdapter):
    """batch_merge_relationships processes multiple relationships."""
    await adapter.merge_node("Fact", {"fact_id": "f-1"}, "fact_id")
    await adapter.merge_node("Fact", {"fact_id": "f-2"}, "fact_id")
    await adapter.merge_node("Entity", {"entity_id": "e-1"}, "entity_id")

    rels = [
        {
            "from_id": "Fact:f-1",
            "to_id": "Entity:e-1",
            "rel_type": EdgeType.MENTIONS.value,
            "properties": {"marker": "E1"},
        },
        {
            "from_id": "Fact:f-2",
            "to_id": "Entity:e-1",
            "rel_type": EdgeType.MENTIONS.value,
            "properties": {"marker": "E1"},
        },
        {
            "from_id": "Fact:f-1",
            "to_id": "Fact:f-2",
            "rel_type": EdgeType.CORROBORATES.value,
            "properties": {"weight": 0.7},
        },
    ]

    count = await adapter.batch_merge_relationships(rels)
    assert count == 3
    assert adapter._graph.number_of_edges() == 3


# ---------------------------------------------------------------------------
# 13. Context manager
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_manager():
    """NetworkXAdapter supports async context manager."""
    async with NetworkXAdapter() as adapter:
        await adapter.merge_node("Fact", {"fact_id": "f-1"}, "fact_id")
        assert adapter._graph.number_of_nodes() == 1

    # After exit, graph should be cleared
    assert adapter._graph.number_of_nodes() == 0
