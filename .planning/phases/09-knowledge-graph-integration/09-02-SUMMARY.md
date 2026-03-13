# Phase 9 Plan 02: Graph Adapter Implementations Summary

**One-liner:** Neo4jAdapter with UNWIND batch MERGE and label allowlist injection, NetworkXAdapter with manual uniqueness enforcement, 10 centralized Cypher query constants, docker-compose for one-command Neo4j dev, 28 passing behavioral tests.

---

phase: 09-knowledge-graph-integration
plan: 02
subsystem: data-management-graph
tags: [neo4j, networkx, graph-adapter, cypher, docker-compose, batch-merge]

requires:
  - 09-01 (GraphAdapter Protocol, GraphNode/GraphEdge/QueryResult, EdgeType, GraphConfig)

provides:
  - Neo4jAdapter implementing GraphAdapter Protocol
  - NetworkXAdapter implementing GraphAdapter Protocol
  - Centralized Cypher query constants (SCHEMA_INIT_QUERIES, MERGE_NODE, BATCH_MERGE_NODES, etc.)
  - docker-compose.yml for Neo4j dev (2025-community + APOC)
  - 28 behavioral tests validating adapter semantics

affects:
  - 09-03 (FactMapper uses adapters for graph ingestion)
  - 09-04 (GraphIngestor uses adapters for event-driven ingestion)
  - Phase 10 (Analysis queries via adapters)

tech-stack:
  added:
    - neo4j>=6.1.0 (official async Python driver)
    - networkx>=3.0 (in-memory graph for tests/CI)
  patterns:
    - UNWIND batch MERGE for high-performance ingestion
    - Label allowlist validation for safe f-string Cypher injection
    - Manual uniqueness enforcement via dict-based node index
    - Async context manager for adapter lifecycle
    - BFS-based entity network traversal (NetworkX)

key-files:
  created:
    - osint_system/data_management/graph/cypher_queries.py
    - osint_system/data_management/graph/neo4j_adapter.py
    - osint_system/data_management/graph/networkx_adapter.py
    - docker-compose.yml
    - tests/data_management/graph/__init__.py
    - tests/data_management/graph/test_networkx_adapter.py
  modified:
    - osint_system/data_management/graph/__init__.py
    - requirements.txt

decisions:
  - id: label-allowlist
    decision: "Only Fact/Entity/Source/Investigation/Classification labels allowed in Cypher f-string injection"
    rationale: "Prevents Cypher injection via label parameter while allowing necessary label substitution"
  - id: rel-type-allowlist
    decision: "Only EdgeType enum values allowed as relationship types"
    rationale: "Prevents injection via relationship type parameter"
  - id: node-id-parsing
    decision: "Node IDs parsed as {label}:{key_value} with label-to-key-property inference"
    rationale: "Consistent with 09-01 node ID format, enables label and key extraction for Cypher"
  - id: stub-nodes
    decision: "NetworkX merge_relationship creates stub nodes if from_id/to_id don't exist"
    rationale: "Matches Neo4j MERGE behavior where MERGE_RELATIONSHIP template MERGEs nodes first"
  - id: undirected-path-finding
    decision: "Shortest path uses undirected graph view"
    rationale: "Entity networks are traversed bidirectionally; directed-only paths would miss connections"
  - id: batch-grouping
    decision: "Neo4j batch_merge_relationships groups by (from_label, to_label, rel_type) for efficient UNWIND"
    rationale: "Single UNWIND query per group reduces transaction count"

metrics:
  duration: 6 min
  completed: 2026-03-13

---

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Cypher query templates and Neo4jAdapter implementation | 4abca37 | cypher_queries.py, neo4j_adapter.py, docker-compose.yml, requirements.txt |
| 2 | NetworkXAdapter implementation and adapter behavioral tests | 8d59d47 | networkx_adapter.py, __init__.py, test_networkx_adapter.py |

## What Was Built

### cypher_queries.py (143 lines)
- **SCHEMA_INIT_QUERIES**: 10 idempotent schema statements (4 uniqueness constraints, 4 range indexes, 1 text index, 1 relationship index)
- **MERGE_NODE**: Single node MERGE with ON CREATE/ON MATCH SET, label/key_property injected via validated f-string
- **BATCH_MERGE_NODES**: UNWIND-based batch MERGE for high-performance ingestion
- **MERGE_RELATIONSHIP**: Separate node MERGEs then relationship MERGE (Pitfall 1 avoidance)
- **BATCH_MERGE_RELATIONSHIPS**: UNWIND-based batch relationship MERGE
- **DELETE_NODE**: DETACH DELETE by label and key
- **QUERY_ENTITY_NETWORK**: N-hop traversal with .format(max_hops=N) for path bounds, $params for values
- **QUERY_CORROBORATION_CLUSTERS**: CORROBORATES|CONTRADICTS edges within investigation, sorted by weight
- **QUERY_TIMELINE**: Temporal facts for entity, sorted ascending
- **QUERY_SHORTEST_PATH**: shortestPath bounded to 10 hops

### neo4j_adapter.py (593 lines)
- **Neo4jAdapter**: Full GraphAdapter Protocol implementation
- Constructor takes GraphConfig, creates AsyncGraphDatabase.driver with auth
- `initialize()`: verify_connectivity() then run all SCHEMA_INIT_QUERIES
- `merge_node()`: Single MERGE via execute_query with database_ param
- `batch_merge_nodes()`: UNWIND with config.batch_size chunking, label allowlist validation
- `merge_relationship()`: Parses node IDs, validates rel_type against EdgeType allowlist
- `batch_merge_relationships()`: Groups by (from_label, to_label, rel_type) for efficient UNWIND
- `delete_node()`: DETACH DELETE with label/key parsing
- Query methods: Convert Neo4j path/node/relationship objects to GraphNode/GraphEdge/QueryResult
- `execute_cypher()`: Raw Cypher passthrough
- `_extract_paths()`: Deduplicated path extraction from multi-path results
- Async context manager (__aenter__/__aexit__)

### networkx_adapter.py (519 lines)
- **NetworkXAdapter**: Full GraphAdapter Protocol implementation using nx.MultiDiGraph
- `_node_index: dict[str, dict]` for O(1) key-property uniqueness enforcement
- `merge_node()`: Check index, update existing or add new (emulates ON CREATE/ON MATCH)
- `merge_relationship()`: Iterates edge keys to find matching rel_type, updates or creates
- Stub node creation on relationship merge if nodes don't exist (matches Neo4j MERGE behavior)
- `query_entity_network()`: BFS traversal with bidirectional edge following
- `query_corroboration_clusters()`: Edge iteration filtered by CORROBORATES/CONTRADICTS
- `query_timeline()`: Predecessor traversal for MENTIONS edges, temporal_value sort
- `query_shortest_path()`: nx.shortest_path on undirected view
- `execute_cypher()`: Raises NotImplementedError

### docker-compose.yml
- neo4j:2025-community image
- Ports 7474/7687 with env var overrides
- NEO4J_AUTH from env vars
- APOC plugin enabled
- Memory: 256m initial, 512m max heap
- Named volumes for data/logs
- Healthcheck with neo4j status
- restart: unless-stopped

### test_networkx_adapter.py (632 lines, 28 tests)
- Merge semantics: create, update, property preservation, missing key error
- Batch operations: count, deduplication, empty list
- Relationship merge: create, update, separate types
- No-duplicate-nodes pitfall: relationship merge does not create extra nodes
- Stub node creation: relationship merge creates stubs for missing nodes
- Entity network query: connected nodes, nonexistent entity
- Corroboration clusters: detection, investigation filtering
- Timeline: chronological ordering, temporal_value filtering, nonexistent entity
- Shortest path: A-B-C chain, no connection, nonexistent entities
- Delete node: removal with edges, not found
- execute_cypher: NotImplementedError
- Cross-investigation filtering: entity network, timeline
- Batch merge relationships: multi-type batch
- Context manager: async with lifecycle

## Deviations from Plan

None -- plan executed exactly as written.

## Decisions Made

1. **Label allowlist** (5 labels): Prevents Cypher injection via label f-string substitution
2. **Relationship type allowlist** (13 EdgeType values): Prevents injection via rel_type parameter
3. **Stub node creation**: NetworkX merge_relationship creates stub nodes for missing IDs, matching Neo4j MERGE template behavior
4. **Undirected path finding**: Shortest path uses undirected graph view for bidirectional entity traversal
5. **Batch relationship grouping**: Neo4j groups relationships by (from_label, to_label, rel_type) for single UNWIND per group

## Verification Results

```
28/28 tests PASSED (0.18s)
Neo4jAdapter: importable, 593 lines (min 200)
NetworkXAdapter: importable, 519 lines (min 150)
test_networkx_adapter.py: 632 lines (min 100)
docker-compose.yml: neo4j:2025-community present
requirements.txt: neo4j>=6.1.0, networkx>=3.0 present
Cypher queries: all use $param syntax
```

## Next Plan Readiness

09-03 (Fact-to-Graph Mapping) can now:
- Import both adapters: `from osint_system.data_management.graph import Neo4jAdapter, NetworkXAdapter`
- Use NetworkXAdapter for tests without Docker
- Merge facts/entities/sources via `adapter.merge_node()` and `adapter.batch_merge_nodes()`
- Create relationships via `adapter.merge_relationship()` and `adapter.batch_merge_relationships()`
- Query graph via four high-level query methods
- Run against Neo4j dev via `docker compose up -d`
