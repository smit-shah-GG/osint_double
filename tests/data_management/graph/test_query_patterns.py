"""Comprehensive query pattern tests for the four essential graph queries.

Validates entity network, corroboration clusters, timeline, and shortest path
query patterns against NetworkXAdapter with a realistic OSINT investigation
graph. These tests lock the query interface contract that Phase 10's Analysis
& Reporting Engine will consume.

Test fixture builds a graph modeling two investigations:
- inv-1: 5 facts, 4 entities (Putin, Russia, Ukraine, NATO), 2 sources,
  CORROBORATES/CONTRADICTS edges, MENTIONS edges, temporal ordering
- inv-2: 1 fact, 1 entity (Putin duplicate in separate investigation scope)

Coverage:
- Happy path for all four query patterns
- Edge cases: nonexistent nodes, empty results, cross-investigation isolation
- Metadata validation: cluster_count, fact_count, path_length
- Type correctness: all results contain GraphNode/GraphEdge objects
- Serialization: QueryResult.model_dump() produces JSON-compatible dicts
"""

import pytest
import pytest_asyncio

from osint_system.data_management.graph.networkx_adapter import NetworkXAdapter
from osint_system.data_management.graph.schema import (
    EdgeType,
    GraphEdge,
    GraphNode,
    QueryResult,
)


@pytest_asyncio.fixture
async def rich_adapter() -> NetworkXAdapter:
    """Build a realistic graph for query pattern testing.

    Graph structure:

    Investigation inv-1:
      Facts: f1 (2024-01-10), f2 (2024-03-15), f3 (2024-06-20),
             f4 (2024-09-01), f5 (no temporal_value)
      Entities: Putin (PERSON), Russia (ORGANIZATION),
                Ukraine (LOCATION), NATO (ORGANIZATION)
      Sources: src-reuters, src-bbc

    MENTIONS edges:
      f1 -> Putin, f1 -> Russia
      f2 -> Putin, f2 -> Ukraine
      f3 -> Russia, f3 -> NATO
      f4 -> Ukraine, f4 -> NATO
      f5 -> Putin  (no temporal_value)

    Semantic edges:
      f1 -CORROBORATES-> f2  (weight 0.8)
      f3 -CONTRADICTS-> f4   (weight 0.7)

    SOURCED_FROM edges:
      f1 -> src-reuters, f2 -> src-reuters
      f3 -> src-bbc, f4 -> src-bbc

    PART_OF edges:
      f1..f5 -> inv-1

    Investigation inv-2:
      Facts: f6 (2024-02-01)
      Entities: Putin (PERSON) -- same name, different investigation scope
      f6 -> Entity:inv-2:Vladimir Putin
      f6 PART_OF inv-2
    """
    a = NetworkXAdapter()
    await a.initialize()

    # -- Investigation nodes --
    await a.merge_node(
        "Investigation",
        {"investigation_id": "inv-1", "name": "Ukraine Conflict"},
        "investigation_id",
    )
    await a.merge_node(
        "Investigation",
        {"investigation_id": "inv-2", "name": "Separate Probe"},
        "investigation_id",
    )

    # -- Fact nodes (inv-1) --
    facts_inv1 = [
        {
            "fact_id": "f1",
            "claim_text": "[E1:Putin] met with [E2:Russia] officials",
            "temporal_value": "2024-01-10",
            "investigation_id": "inv-1",
            "extraction_confidence": 0.92,
        },
        {
            "fact_id": "f2",
            "claim_text": "[E1:Putin] visited [E2:Ukraine] border",
            "temporal_value": "2024-03-15",
            "investigation_id": "inv-1",
            "extraction_confidence": 0.88,
        },
        {
            "fact_id": "f3",
            "claim_text": "[E1:Russia] expanded [E2:NATO] tensions",
            "temporal_value": "2024-06-20",
            "investigation_id": "inv-1",
            "extraction_confidence": 0.75,
        },
        {
            "fact_id": "f4",
            "claim_text": "[E1:Ukraine] joined [E2:NATO] talks",
            "temporal_value": "2024-09-01",
            "investigation_id": "inv-1",
            "extraction_confidence": 0.80,
        },
        {
            "fact_id": "f5",
            "claim_text": "[E1:Putin] made statement",
            "investigation_id": "inv-1",
            "extraction_confidence": 0.60,
            # No temporal_value -- should be excluded from timeline
        },
    ]
    for f in facts_inv1:
        await a.merge_node("Fact", f, "fact_id")

    # -- Fact node (inv-2) --
    await a.merge_node(
        "Fact",
        {
            "fact_id": "f6",
            "claim_text": "[E1:Putin] separate investigation fact",
            "temporal_value": "2024-02-01",
            "investigation_id": "inv-2",
            "extraction_confidence": 0.70,
        },
        "fact_id",
    )

    # -- Entity nodes (inv-1) --
    entities_inv1 = [
        {
            "entity_id": "inv-1:Vladimir Putin",
            "name": "Putin",
            "canonical": "Vladimir Putin",
            "entity_type": "PERSON",
            "investigation_id": "inv-1",
        },
        {
            "entity_id": "inv-1:Russia",
            "name": "Russia",
            "canonical": "Russia",
            "entity_type": "ORGANIZATION",
            "investigation_id": "inv-1",
        },
        {
            "entity_id": "inv-1:Ukraine",
            "name": "Ukraine",
            "canonical": "Ukraine",
            "entity_type": "LOCATION",
            "investigation_id": "inv-1",
        },
        {
            "entity_id": "inv-1:NATO",
            "name": "NATO",
            "canonical": "NATO",
            "entity_type": "ORGANIZATION",
            "investigation_id": "inv-1",
        },
    ]
    for e in entities_inv1:
        await a.merge_node("Entity", e, "entity_id")

    # -- Entity node (inv-2) --
    await a.merge_node(
        "Entity",
        {
            "entity_id": "inv-2:Vladimir Putin",
            "name": "Putin",
            "canonical": "Vladimir Putin",
            "entity_type": "PERSON",
            "investigation_id": "inv-2",
        },
        "entity_id",
    )

    # -- Source nodes --
    await a.merge_node(
        "Source",
        {"source_id": "src-reuters", "name": "Reuters", "authority": 0.9},
        "source_id",
    )
    await a.merge_node(
        "Source",
        {"source_id": "src-bbc", "name": "BBC", "authority": 0.85},
        "source_id",
    )

    # -- MENTIONS edges --
    mentions = [
        ("Fact:f1", "Entity:inv-1:Vladimir Putin"),
        ("Fact:f1", "Entity:inv-1:Russia"),
        ("Fact:f2", "Entity:inv-1:Vladimir Putin"),
        ("Fact:f2", "Entity:inv-1:Ukraine"),
        ("Fact:f3", "Entity:inv-1:Russia"),
        ("Fact:f3", "Entity:inv-1:NATO"),
        ("Fact:f4", "Entity:inv-1:Ukraine"),
        ("Fact:f4", "Entity:inv-1:NATO"),
        ("Fact:f5", "Entity:inv-1:Vladimir Putin"),
        ("Fact:f6", "Entity:inv-2:Vladimir Putin"),
    ]
    for from_id, to_id in mentions:
        await a.merge_relationship(
            from_id, to_id, EdgeType.MENTIONS.value, {}
        )

    # -- CORROBORATES / CONTRADICTS edges --
    await a.merge_relationship(
        "Fact:f1", "Fact:f2", EdgeType.CORROBORATES.value, {"weight": 0.8}
    )
    await a.merge_relationship(
        "Fact:f3", "Fact:f4", EdgeType.CONTRADICTS.value, {"weight": 0.7}
    )

    # -- SOURCED_FROM edges --
    await a.merge_relationship(
        "Fact:f1", "Source:src-reuters", EdgeType.SOURCED_FROM.value, {}
    )
    await a.merge_relationship(
        "Fact:f2", "Source:src-reuters", EdgeType.SOURCED_FROM.value, {}
    )
    await a.merge_relationship(
        "Fact:f3", "Source:src-bbc", EdgeType.SOURCED_FROM.value, {}
    )
    await a.merge_relationship(
        "Fact:f4", "Source:src-bbc", EdgeType.SOURCED_FROM.value, {}
    )

    # -- PART_OF edges --
    for fid in ["f1", "f2", "f3", "f4", "f5"]:
        await a.merge_relationship(
            f"Fact:{fid}",
            "Investigation:inv-1",
            EdgeType.PART_OF.value,
            {},
        )
    await a.merge_relationship(
        "Fact:f6", "Investigation:inv-2", EdgeType.PART_OF.value, {}
    )

    yield a
    await a.close()


# ===========================================================================
# Entity Network Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_entity_network_1hop(rich_adapter: NetworkXAdapter) -> None:
    """Putin entity, max_hops=1: returns directly connected facts and entities."""
    result = await rich_adapter.query_entity_network(
        "inv-1:Vladimir Putin", max_hops=1
    )

    assert result.query_type == "entity_network"
    node_ids = {n.id for n in result.nodes}

    # Putin itself
    assert "Entity:inv-1:Vladimir Putin" in node_ids
    # Directly connected facts (via incoming MENTIONS: f1, f2, f5 -> Putin)
    assert "Fact:f1" in node_ids
    assert "Fact:f2" in node_ids
    assert "Fact:f5" in node_ids
    # Within 1 hop we should NOT reach NATO or the sources (those are 2+ hops away)
    assert "Entity:inv-1:NATO" not in node_ids


@pytest.mark.asyncio
async def test_entity_network_2hop(rich_adapter: NetworkXAdapter) -> None:
    """Putin entity, max_hops=2: reaches wider network via shared facts."""
    result = await rich_adapter.query_entity_network(
        "inv-1:Vladimir Putin", max_hops=2
    )

    node_ids = {n.id for n in result.nodes}

    # Putin itself + facts
    assert "Entity:inv-1:Vladimir Putin" in node_ids
    assert "Fact:f1" in node_ids
    assert "Fact:f2" in node_ids

    # 2 hops away: entities mentioned by same facts as Putin
    # f1 also mentions Russia, f2 also mentions Ukraine
    assert "Entity:inv-1:Russia" in node_ids
    assert "Entity:inv-1:Ukraine" in node_ids

    # Also 2 hops: f1 CORROBORATES f2, f1 SOURCED_FROM reuters, etc.
    assert "Source:src-reuters" in node_ids


@pytest.mark.asyncio
async def test_entity_network_with_investigation_filter(
    rich_adapter: NetworkXAdapter,
) -> None:
    """Putin entity, investigation_id='inv-1': only inv-1 nodes returned."""
    result = await rich_adapter.query_entity_network(
        "inv-1:Vladimir Putin", max_hops=3, investigation_id="inv-1"
    )

    for node in result.nodes:
        inv_id = node.properties.get("investigation_id")
        # Nodes with an investigation_id set must be inv-1
        if inv_id is not None:
            assert inv_id == "inv-1", (
                f"Node {node.id} has investigation_id={inv_id}, expected inv-1"
            )


@pytest.mark.asyncio
async def test_entity_network_nonexistent_entity(
    rich_adapter: NetworkXAdapter,
) -> None:
    """Query for a nonexistent entity returns empty QueryResult, not exception."""
    result = await rich_adapter.query_entity_network("nonexistent-entity")

    assert isinstance(result, QueryResult)
    assert result.node_count == 0
    assert result.edge_count == 0
    assert result.query_type == "entity_network"


@pytest.mark.asyncio
async def test_entity_network_returns_correct_types(
    rich_adapter: NetworkXAdapter,
) -> None:
    """All items in the result are correctly typed GraphNode/GraphEdge."""
    result = await rich_adapter.query_entity_network(
        "inv-1:Vladimir Putin", max_hops=2
    )

    for node in result.nodes:
        assert isinstance(node, GraphNode)
        assert isinstance(node.id, str)
        assert isinstance(node.label, str)
        assert isinstance(node.properties, dict)

    for edge in result.edges:
        assert isinstance(edge, GraphEdge)
        assert isinstance(edge.source_id, str)
        assert isinstance(edge.target_id, str)
        assert isinstance(edge.edge_type, EdgeType)
        assert isinstance(edge.weight, float)
        assert 0.0 <= edge.weight <= 1.0


# ===========================================================================
# Corroboration Cluster Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_corroboration_clusters_finds_corroborating(
    rich_adapter: NetworkXAdapter,
) -> None:
    """inv-1 clusters include the f1-f2 CORROBORATES pair."""
    result = await rich_adapter.query_corroboration_clusters("inv-1")

    assert result.query_type == "corroboration_clusters"

    corroborate_edges = [
        e for e in result.edges if e.edge_type == EdgeType.CORROBORATES
    ]
    assert len(corroborate_edges) >= 1

    # Verify the f1-f2 corroboration is present
    c_edge = corroborate_edges[0]
    pair = {c_edge.source_id, c_edge.target_id}
    assert "Fact:f1" in pair
    assert "Fact:f2" in pair


@pytest.mark.asyncio
async def test_corroboration_clusters_finds_contradicting(
    rich_adapter: NetworkXAdapter,
) -> None:
    """inv-1 clusters include the f3-f4 CONTRADICTS pair."""
    result = await rich_adapter.query_corroboration_clusters("inv-1")

    contradict_edges = [
        e for e in result.edges if e.edge_type == EdgeType.CONTRADICTS
    ]
    assert len(contradict_edges) >= 1

    c_edge = contradict_edges[0]
    pair = {c_edge.source_id, c_edge.target_id}
    assert "Fact:f3" in pair
    assert "Fact:f4" in pair


@pytest.mark.asyncio
async def test_corroboration_clusters_empty_investigation(
    rich_adapter: NetworkXAdapter,
) -> None:
    """Nonexistent investigation returns empty QueryResult."""
    result = await rich_adapter.query_corroboration_clusters("inv-999")

    assert isinstance(result, QueryResult)
    assert result.node_count == 0
    assert result.edge_count == 0
    assert result.metadata["cluster_count"] == 0


@pytest.mark.asyncio
async def test_corroboration_clusters_metadata(
    rich_adapter: NetworkXAdapter,
) -> None:
    """Metadata includes cluster_count reflecting distinct agreement groups."""
    result = await rich_adapter.query_corroboration_clusters("inv-1")

    assert "cluster_count" in result.metadata
    # f1-f2 is one cluster, f3-f4 is another: 2 clusters
    assert result.metadata["cluster_count"] == 2
    assert result.metadata["investigation_id"] == "inv-1"


# ===========================================================================
# Timeline Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_timeline_chronological_order(
    rich_adapter: NetworkXAdapter,
) -> None:
    """Putin timeline returns facts in ascending temporal_value order."""
    result = await rich_adapter.query_timeline("inv-1:Vladimir Putin")

    assert result.query_type == "timeline"
    temporal_values = [
        n.properties["temporal_value"] for n in result.nodes
    ]
    # f1: 2024-01-10, f2: 2024-03-15 -- f5 has no temporal_value (excluded)
    assert temporal_values == sorted(temporal_values)
    assert len(temporal_values) >= 2


@pytest.mark.asyncio
async def test_timeline_excludes_no_temporal(
    rich_adapter: NetworkXAdapter,
) -> None:
    """Facts without temporal_value are excluded from the timeline."""
    result = await rich_adapter.query_timeline("inv-1:Vladimir Putin")

    fact_ids = {n.properties.get("fact_id") for n in result.nodes}
    # f5 has no temporal_value
    assert "f5" not in fact_ids
    # f1 and f2 have temporal_value and mention Putin
    assert "f1" in fact_ids
    assert "f2" in fact_ids


@pytest.mark.asyncio
async def test_timeline_with_investigation_filter(
    rich_adapter: NetworkXAdapter,
) -> None:
    """Timeline with investigation_id='inv-1' only returns inv-1 facts."""
    result = await rich_adapter.query_timeline(
        "inv-1:Vladimir Putin", investigation_id="inv-1"
    )

    for node in result.nodes:
        assert node.properties.get("investigation_id") == "inv-1"


@pytest.mark.asyncio
async def test_timeline_nonexistent_entity(
    rich_adapter: NetworkXAdapter,
) -> None:
    """Timeline for nonexistent entity returns empty QueryResult."""
    result = await rich_adapter.query_timeline("nonexistent-entity")

    assert isinstance(result, QueryResult)
    assert result.node_count == 0
    assert result.metadata["fact_count"] == 0


@pytest.mark.asyncio
async def test_timeline_returns_query_result_type(
    rich_adapter: NetworkXAdapter,
) -> None:
    """Timeline query returns QueryResult with query_type='timeline'."""
    result = await rich_adapter.query_timeline("inv-1:Vladimir Putin")

    assert isinstance(result, QueryResult)
    assert result.query_type == "timeline"
    assert "entity_id" in result.metadata
    assert result.metadata["entity_id"] == "inv-1:Vladimir Putin"
    assert "fact_count" in result.metadata
    assert result.metadata["fact_count"] == result.node_count


# ===========================================================================
# Shortest Path Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_shortest_path_direct(
    rich_adapter: NetworkXAdapter,
) -> None:
    """Putin to Russia: connected via f1 (Entity<-MENTIONS-Fact-MENTIONS->Entity).

    Path: Entity:Putin <- Fact:f1 -> Entity:Russia (length 2 edges).
    """
    result = await rich_adapter.query_shortest_path(
        "inv-1:Vladimir Putin", "inv-1:Russia"
    )

    assert result.query_type == "shortest_path"
    assert result.node_count >= 2

    node_ids = {n.id for n in result.nodes}
    assert "Entity:inv-1:Vladimir Putin" in node_ids
    assert "Entity:inv-1:Russia" in node_ids
    # Intermediate fact f1 connects them
    assert "Fact:f1" in node_ids

    assert result.metadata["path_length"] == 2


@pytest.mark.asyncio
async def test_shortest_path_indirect(
    rich_adapter: NetworkXAdapter,
) -> None:
    """Putin to NATO: no direct shared fact, must route through intermediates."""
    result = await rich_adapter.query_shortest_path(
        "inv-1:Vladimir Putin", "inv-1:NATO"
    )

    assert result.node_count >= 3  # At least: Putin, intermediate(s), NATO
    node_ids = {n.id for n in result.nodes}
    assert "Entity:inv-1:Vladimir Putin" in node_ids
    assert "Entity:inv-1:NATO" in node_ids
    # Path length should be >= 4 (Putin <- f1/f2 -> Russia/Ukraine <- f3/f4 -> NATO)
    assert result.metadata["path_length"] >= 4


@pytest.mark.asyncio
async def test_shortest_path_no_path(rich_adapter: NetworkXAdapter) -> None:
    """Isolated entity has no path to any other entity."""
    # Create an isolated entity with no edges
    await rich_adapter.merge_node(
        "Entity",
        {"entity_id": "inv-1:Isolated", "investigation_id": "inv-1"},
        "entity_id",
    )

    result = await rich_adapter.query_shortest_path(
        "inv-1:Isolated", "inv-1:Vladimir Putin"
    )

    assert isinstance(result, QueryResult)
    assert result.node_count == 0
    assert result.edge_count == 0
    assert result.metadata["path_length"] == 0


@pytest.mark.asyncio
async def test_shortest_path_same_entity(
    rich_adapter: NetworkXAdapter,
) -> None:
    """Same entity for from and to returns single-node path with length 0."""
    result = await rich_adapter.query_shortest_path(
        "inv-1:Vladimir Putin", "inv-1:Vladimir Putin"
    )

    assert result.node_count == 1
    assert result.nodes[0].id == "Entity:inv-1:Vladimir Putin"
    assert result.edge_count == 0
    assert result.metadata["path_length"] == 0


@pytest.mark.asyncio
async def test_shortest_path_nonexistent(
    rich_adapter: NetworkXAdapter,
) -> None:
    """Nonexistent entity returns empty QueryResult."""
    result = await rich_adapter.query_shortest_path(
        "nonexistent-a", "nonexistent-b"
    )

    assert isinstance(result, QueryResult)
    assert result.node_count == 0
    assert result.metadata["path_length"] == 0


@pytest.mark.asyncio
async def test_shortest_path_metadata(
    rich_adapter: NetworkXAdapter,
) -> None:
    """Shortest path metadata includes from_id, to_id, path_length."""
    result = await rich_adapter.query_shortest_path(
        "inv-1:Vladimir Putin", "inv-1:Russia"
    )

    assert "from_entity_id" in result.metadata
    assert "to_entity_id" in result.metadata
    assert "path_length" in result.metadata
    assert result.metadata["from_entity_id"] == "inv-1:Vladimir Putin"
    assert result.metadata["to_entity_id"] == "inv-1:Russia"
    assert isinstance(result.metadata["path_length"], int)
    assert result.metadata["path_length"] > 0


# ===========================================================================
# Cross-Cutting Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_query_result_is_serializable(
    rich_adapter: NetworkXAdapter,
) -> None:
    """All QueryResult objects can be model_dump()-ed to JSON-compatible dict."""
    # Exercise all four query patterns
    results = [
        await rich_adapter.query_entity_network("inv-1:Vladimir Putin"),
        await rich_adapter.query_corroboration_clusters("inv-1"),
        await rich_adapter.query_timeline("inv-1:Vladimir Putin"),
        await rich_adapter.query_shortest_path(
            "inv-1:Vladimir Putin", "inv-1:Russia"
        ),
    ]

    for result in results:
        dumped = result.model_dump()
        assert isinstance(dumped, dict)
        assert "nodes" in dumped
        assert "edges" in dumped
        assert "query_type" in dumped
        assert "metadata" in dumped
        # Nodes and edges should be lists of dicts
        for node_dict in dumped["nodes"]:
            assert isinstance(node_dict, dict)
            assert "id" in node_dict
            assert "label" in node_dict
            assert "properties" in node_dict
        for edge_dict in dumped["edges"]:
            assert isinstance(edge_dict, dict)
            assert "source_id" in edge_dict
            assert "target_id" in edge_dict
            assert "edge_type" in edge_dict


@pytest.mark.asyncio
async def test_investigation_id_none_returns_all(
    rich_adapter: NetworkXAdapter,
) -> None:
    """No investigation filter (None) returns cross-investigation results.

    Entity network for inv-1:Putin with no investigation filter should include
    nodes from inv-1 without filtering out any.
    """
    # No filter -- should get all reachable nodes regardless of investigation
    result_unfiltered = await rich_adapter.query_entity_network(
        "inv-1:Vladimir Putin", max_hops=2, investigation_id=None
    )
    # With filter -- should only get inv-1 nodes
    result_filtered = await rich_adapter.query_entity_network(
        "inv-1:Vladimir Putin", max_hops=2, investigation_id="inv-1"
    )

    # Unfiltered should have >= filtered count (nodes without investigation_id
    # or with different investigation_id are included in unfiltered)
    assert result_unfiltered.node_count >= result_filtered.node_count


@pytest.mark.asyncio
async def test_timeline_investigation_none_returns_all(
    rich_adapter: NetworkXAdapter,
) -> None:
    """Timeline with no investigation filter returns all temporal facts."""
    result = await rich_adapter.query_timeline(
        "inv-1:Vladimir Putin", investigation_id=None
    )

    # Should include f1 (2024-01-10) and f2 (2024-03-15) at minimum
    fact_ids = {n.properties.get("fact_id") for n in result.nodes}
    assert "f1" in fact_ids
    assert "f2" in fact_ids
    assert result.metadata["fact_count"] == result.node_count
