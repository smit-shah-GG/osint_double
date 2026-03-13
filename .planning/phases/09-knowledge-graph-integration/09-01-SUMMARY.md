# Phase 9 Plan 01: Graph Layer Type Foundation Summary

**One-liner:** GraphAdapter Protocol, Pydantic graph schemas (GraphNode/GraphEdge/QueryResult), 13-type EdgeType enum, weight formula, and Neo4j env-based config -- zero driver dependency.

---

phase: 09-knowledge-graph-integration
plan: 01
subsystem: data-management-graph
tags: [pydantic, protocol, neo4j, graph-schema, configuration]

requires:
  - Phase 6 (fact_schema.py pattern)
  - Phase 7 (classification_schema.py pattern)
  - Phase 8 (verification_schema.py pattern)

provides:
  - GraphAdapter Protocol (runtime_checkable interface for Neo4j/NetworkX)
  - GraphNode, GraphEdge, QueryResult Pydantic models
  - EdgeType enum (13 semantic relationship types)
  - compute_edge_weight() formula
  - GraphConfig env-based configuration

affects:
  - 09-02 (Neo4jAdapter implements GraphAdapter)
  - 09-03 (NetworkXAdapter implements GraphAdapter)
  - 09-04 (FactMapper uses GraphNode/GraphEdge/EdgeType)
  - 09-05 (GraphIngestor uses GraphAdapter)
  - Phase 10 (Analysis consumes QueryResult)

tech-stack:
  added: [] (no new dependencies -- pure Python + Pydantic)
  patterns:
    - Protocol with @runtime_checkable for adapter abstraction
    - Pydantic BaseModel for typed graph results
    - str Enum for edge type categorization
    - Classmethod from_env() for config loading

key-files:
  created:
    - osint_system/data_management/graph/__init__.py
    - osint_system/data_management/graph/schema.py
    - osint_system/data_management/graph/adapter.py
    - osint_system/config/graph_config.py
  modified:
    - .env.example

decisions:
  - id: edge-type-count
    decision: "13 edge types across 5 categories (structural, semantic, temporal, spatial, verification)"
    rationale: "Covers all relationships from CONTEXT.md plus VERIFIED_BY for Phase 8 integration"
  - id: node-id-format
    decision: "Node IDs use {label}:{natural_key} format"
    rationale: "Global uniqueness across node types without a central ID generator"
  - id: weight-formula
    decision: "base + authority*0.3 + min(0.2, 0.05*log1p(count)) - min(0.2, days/365*0.2)"
    rationale: "Per RESEARCH.md: authority dominates, evidence has diminishing returns, recency decays linearly"
  - id: config-from-env
    decision: "GraphConfig uses from_env() classmethod, not BaseSettings"
    rationale: "Avoids requiring GEMINI_API_KEY at import time; explicit env reads are clearer"
  - id: no-driver-dependency
    decision: "graph_config.py has zero dependency on neo4j driver package"
    rationale: "Config is loaded everywhere; driver is only needed in adapter implementations"

metrics:
  duration: 4 min
  completed: 2026-03-13

---

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Graph Pydantic schemas, EdgeType enum, and GraphAdapter Protocol | 1ce05a0 | schema.py, adapter.py, __init__.py |
| 2 | Graph configuration with Neo4j connection settings | 6badcaa | graph_config.py, .env.example |

## What Was Built

### schema.py
- **EdgeType**: 13 semantic relationship types grouped into 5 categories (structural: MENTIONS/SOURCED_FROM/PART_OF/HAS_CLASSIFICATION, semantic: CORROBORATES/CONTRADICTS/RELATED_TO/ATTRIBUTED_TO/CAUSES, temporal: PRECEDES/SUPERSEDES, spatial: LOCATED_AT, verification: VERIFIED_BY)
- **GraphNode**: Pydantic model with `id` (format `{label}:{key}`), `label`, `properties` dict, and helper properties (`investigation_id`, `name_or_id`)
- **GraphEdge**: Pydantic model with `source_id`, `target_id`, `edge_type` (EdgeType enum), `weight` (0.0-1.0), `properties` dict, and `cross_investigation` flag
- **QueryResult**: Container with `nodes`, `edges`, `query_type`, `metadata`, plus `node_count`/`edge_count` properties and `to_dict()` method
- **compute_edge_weight()**: Formula clamped to [0.0, 1.0] -- authority boost (0-0.3), evidence boost (diminishing via log1p, capped 0.2), recency decay (linear over 365 days, capped 0.2)

### adapter.py
- **GraphAdapter**: `typing.Protocol` with `@runtime_checkable` decorator
- 12 async methods with full docstrings: `initialize`, `close`, `merge_node`, `merge_relationship`, `batch_merge_nodes`, `batch_merge_relationships`, `delete_node`, `query_entity_network`, `query_corroboration_clusters`, `query_timeline`, `query_shortest_path`, `execute_cypher`
- Each method documents its Neo4j vs NetworkX behavior, error conditions, and parameter semantics

### graph_config.py
- **GraphConfig**: 9 fields with validation constraints (batch_size ge=100/le=50000, max_hops ge=1/le=10)
- `from_env()` classmethod reads NEO4J_URI/USER/PASSWORD/DATABASE and GRAPH_USE_NETWORKX/GRAPH_LLM_EXTRACTION
- Best-effort dotenv loading (no hard dependency on python-dotenv)
- Boolean parsing handles "true"/"1"/"yes" variants

## Deviations from Plan

None -- plan executed exactly as written.

## Decisions Made

1. **13 edge types** (plan specified ~12-15): settled on 13 covering all CONTEXT.md relationships plus VERIFIED_BY
2. **from_env() over BaseSettings**: Plan specified this explicitly. Avoids the global Settings singleton pattern which requires GEMINI_API_KEY at import time
3. **Extra env vars** (GRAPH_BATCH_SIZE, GRAPH_MAX_HOPS, GRAPH_CROSS_INVESTIGATION): Added to from_env() for completeness even though not in .env.example -- they're optional overrides

## Verification Results

```
GraphAdapter is runtime_checkable Protocol: OK
EdgeType: 13 types (>= 12)
compute_edge_weight: all values in [0.0, 1.0]
GraphConfig.from_env(): OK, no neo4j driver dependency
No circular imports detected
ALL VERIFICATIONS PASSED
```

## Next Plan Readiness

09-02 (Neo4jAdapter) can now:
- Import `GraphAdapter` Protocol to implement
- Import `QueryResult`, `GraphNode`, `GraphEdge`, `EdgeType` for return types
- Import `GraphConfig` for connection parameters
- Use `compute_edge_weight()` when computing relationship weights
