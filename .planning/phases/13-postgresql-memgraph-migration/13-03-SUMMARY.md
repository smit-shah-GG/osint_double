# Phase 13 Plan 03: Memgraph Adapter + Queries + MAGE Summary

**One-liner:** MemgraphAdapter implementing GraphAdapter Protocol with Memgraph Cypher syntax (ASSERT constraints, localDateTime, BFS shortest path), 13 schema init queries, MAGE algorithm module (PageRank, Louvain, betweenness), and GraphConfig renamed from neo4j_* to memgraph_*.

---

## Metadata

| Field | Value |
|-------|-------|
| Phase | 13-postgresql-memgraph-migration |
| Plan | 03 |
| Duration | 7.5 min |
| Completed | 2026-03-22 |

---

## What Was Built

### memgraph_queries.py (160 lines)
- 13 schema init queries: 4 uniqueness constraints (ASSERT IS UNIQUE syntax), 9 label-property indexes (explicit, since Memgraph does NOT auto-create backing indexes for constraints)
- No `IF NOT EXISTS` (Memgraph doesn't support it) -- caller wraps in try/except
- No TEXT INDEX or relationship property indexes (Memgraph doesn't support them)
- MERGE_NODE, BATCH_MERGE_NODES, MERGE_RELATIONSHIP, BATCH_MERGE_RELATIONSHIPS: `localDateTime()` replaces `datetime()`
- DELETE_NODE: unchanged from Neo4j syntax
- QUERY_ENTITY_NETWORK, QUERY_CORROBORATION_CLUSTERS, QUERY_TIMELINE: unchanged (compatible Cypher)
- QUERY_SHORTEST_PATH: BFS traversal syntax (`-[*BFS ..10]-`) replaces `shortestPath()` function

### mage_algorithms.py (125 lines)
- PAGERANK_QUERY: `CALL pagerank.get()` with SET node.rank
- COMMUNITY_DETECTION_QUERY: `CALL community_detection.get()` with SET node.community
- BETWEENNESS_QUERY: `CALL betweenness_centrality.get(TRUE, TRUE)` with SET node.betweenness
- `run_mage_analysis()`: async function running all 3 sequentially, graceful degradation if MAGE modules unavailable
- Full-graph execution (investigation-scoped subgraph projection deferred per RESEARCH.md)

### memgraph_adapter.py (500 lines)
- `MemgraphAdapter` class implementing GraphAdapter Protocol
- Forked from Neo4jAdapter with Memgraph-specific changes:
  - Imports from `memgraph_queries` instead of `cypher_queries`
  - `initialize()`: wraps each schema init query in try/except for duplicate constraint/index handling
  - No `database_` parameter in any `execute_query` call (Memgraph CE single DB)
  - Conditional auth: passes `None` when user/password are empty (Memgraph CE default)
  - Helper functions renamed from `_neo4j_*` to `_bolt_*` for clarity (functionally identical)
- Consumer list documented in module docstring for wiring plan (13-07)

### graph_config.py (updated)
- Fields renamed: `neo4j_uri` -> `memgraph_uri`, `neo4j_user` -> `memgraph_user`, `neo4j_password` -> `memgraph_password`
- `neo4j_database` field REMOVED (Memgraph CE has single database)
- Defaults: `memgraph_user=""`, `memgraph_password=""` (Memgraph CE no auth)
- `from_env()` reads `MEMGRAPH_URI`, `MEMGRAPH_USER`, `MEMGRAPH_PASSWORD`
- Docstrings and examples updated to Memgraph

### graph/__init__.py (updated)
- `MemgraphAdapter` added to exports alongside existing `Neo4jAdapter`
- `Neo4jAdapter` preserved for backward compatibility until wiring plan

---

## Commits

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Memgraph Cypher queries + MAGE algorithms | e468fbe | memgraph_queries.py, mage_algorithms.py |
| 2 | MemgraphAdapter + GraphConfig rename | 6d96281 | memgraph_adapter.py, graph_config.py, __init__.py |

---

## Decisions Made

| ID | Decision | Rationale |
|----|----------|-----------|
| D13-03-01 | Helper functions renamed from `_neo4j_*` to `_bolt_*` | Bolt protocol objects are identical regardless of Neo4j/Memgraph backend; naming reflects the actual protocol layer |
| D13-03-02 | Conditional auth (None when empty) in MemgraphAdapter | Memgraph CE has no auth by default; passing empty strings to neo4j driver causes auth failures |

---

## Deviations from Plan

None -- plan executed exactly as written.

---

## Verification Results

- MemgraphAdapter imports cleanly from both direct and __init__ paths
- 13 schema init queries with ASSERT syntax, no IF NOT EXISTS, no REQUIRE
- localDateTime() in all 4 MERGE templates
- BFS syntax in QUERY_SHORTEST_PATH
- MAGE queries present with correct CALL syntax
- GraphConfig uses memgraph_* fields, no neo4j_* references
- Neo4jAdapter file preserved (not deleted)

---

## Next Phase Readiness

No blockers. MemgraphAdapter is ready for integration. The wiring plan (13-07) will:
1. Update `graph_pipeline.py` to import/instantiate MemgraphAdapter instead of Neo4jAdapter
2. Update `graph/__init__.py` to remove Neo4jAdapter export
3. Delete `neo4j_adapter.py` and `cypher_queries.py`
