---
phase: 12-api-layer-pipeline-events
plan: 03
subsystem: api-data-routes
tags: [fastapi, facts, reports, sources, graph, enrichment, pagination]
dependency-graph:
  requires:
    - 12-01 (schemas, errors, dependencies)
  provides:
    - api-facts-endpoint
    - api-reports-endpoint
    - api-sources-endpoint
    - api-graph-endpoint
  affects:
    - 12-04 (app factory wires route modules onto FastAPI app)
    - 14 (frontend consumes these endpoints for investigation results)
tech-stack:
  added: []
  patterns:
    - "Fact enrichment: join FactStore + ClassificationStore + VerificationStore into flat FactResponse"
    - "Source aggregation: group articles by domain, max authority_score, count per domain"
    - "Graph adapter resolution: direct dict or pipeline._adapter fallback"
    - "Query dispatch: pattern parameter routes to correct adapter query method"
    - "Store resolution: investigation_stores dict with app.state direct fallback"
key-files:
  created:
    - osint_system/api/routes/__init__.py
    - osint_system/api/routes/facts.py
    - osint_system/api/routes/reports.py
    - osint_system/api/routes/sources.py
    - osint_system/api/routes/graph.py
    - tests/api/test_facts_route.py
    - tests/api/test_reports_route.py
    - tests/api/test_sources_route.py
    - tests/api/test_graph_route.py
  modified: []
decisions:
  - id: D12-03-01
    summary: "Dual store resolution: investigation_stores dict (API runner) with app.state direct fallback (serve.py)"
    rationale: "Supports both per-investigation isolated stores and the single-store serve.py compatibility path"
  - id: D12-03-02
    summary: "Graph adapter resolved from graph_adapters dict or pipeline._adapter -- no pipeline modification needed"
    rationale: "Avoids modifying GraphPipeline; adapter access via composition, not inheritance"
metrics:
  duration: 5.8 min
  completed: 2026-03-21
---

# Phase 12 Plan 03: Data-Serving API Routes Summary

Facts with classification+verification enrichment, reports with version history, sources with domain aggregation, and graph nodes/edges/queries across four query patterns -- zero new dependencies, 40 tests.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Facts and Reports API routes with enrichment logic | `3265da5` | facts.py, reports.py, test_facts_route.py, test_reports_route.py |
| 2 | Sources inventory and Graph data API routes | `7c00a6f` | sources.py, graph.py, test_sources_route.py, test_graph_route.py |

## What Was Built

### Facts Route (facts.py) -- 2 endpoints
- **GET /investigations/{id}/facts** -- Paginated fact list with enrichment:
  - Calls `fact_store.retrieve_by_investigation()` for raw facts
  - `_enrich_fact()` helper joins classification (impact_tier) and verification (verification_status)
  - Flattens internal nested dicts (claim.text, provenance.source_id) into flat FactResponse
  - Handles None gracefully for unclassified/unverified facts
- **GET /investigations/{id}/facts/{fact_id}** -- Single enriched fact detail
  - 404 if fact not found in the investigation

### Reports Route (reports.py) -- 3 endpoints
- **GET /investigations/{id}/reports/latest** -- Most recent report version
  - Maps ReportRecord to ReportResponse (content, model_used, metadata)
- **GET /investigations/{id}/reports** -- Paginated version list
  - Maps ReportRecord to ReportVersionSummary (version, created_at, model_used)
- **GET /investigations/{id}/reports/{version}** -- Specific version by number

### Sources Route (sources.py) -- 1 endpoint
- **GET /investigations/{id}/sources** -- Source inventory
  - Aggregates articles from ArticleStore by source.name (domain)
  - Computes per-domain: article_count, max authority_score
  - Sorted by article_count descending (most-used sources first)
  - Skips articles with non-dict source values

### Graph Route (graph.py) -- 3 endpoints
- **GET /investigations/{id}/graph/nodes** -- All graph nodes, optional `?node_type=` filter
  - Reads directly from adapter._graph (networkx.MultiDiGraph)
  - Returns list (no pagination -- graphs are small per RESEARCH.md)
- **GET /investigations/{id}/graph/edges** -- All graph edges with relationship labels
- **GET /investigations/{id}/graph/query** -- Query dispatch:
  - `pattern=entity_network`: requires entity_id, calls adapter.query_entity_network()
  - `pattern=corroboration`: calls adapter.query_corroboration_clusters()
  - `pattern=timeline`: requires entity_id, calls adapter.query_timeline()
  - `pattern=shortest_path`: requires from_id and to_id, calls adapter.query_shortest_path()
  - Returns `{"nodes": [...], "edges": [...]}` mapped to API response types
  - 400 for invalid pattern or missing required parameters

### Store Resolution Pattern
All routes use a dual-resolution pattern:
1. Check `app.state.investigation_stores[investigation_id]` (per-investigation store dict)
2. Fall back to stores on `app.state` directly (serve.py compatibility)
3. Raise 404 if neither path resolves

## Test Coverage

- **test_facts_route.py:** 9 tests -- enrichment with classification+verification, pagination, empty investigation, 404 for unknown investigation, direct store fallback, single fact detail, fact not found 404, no enrichment data, non-dict claim graceful handling
- **test_reports_route.py:** 9 tests -- latest report success, latest not found, unknown investigation 404, version listing, empty versions, version pagination, specific version, version not found, direct store fallback
- **test_sources_route.py:** 7 tests -- domain aggregation (5+3 articles -> 2 sources), max authority score, empty, pagination, unknown investigation 404, direct store fallback, missing/non-dict source handling
- **test_graph_route.py:** 15 tests -- all nodes, type filter, unknown type empty, graph not available 404, all edges, entity_network query, missing entity_id 400, corroboration query, timeline query, missing timeline entity_id 400, shortest_path query, missing shortest_path params 400, invalid pattern 400, graph not available 404, pipeline-based adapter resolution

**Total: 40 tests, all passing.**

## Deviations from Plan

None -- plan executed exactly as written.

## Verification Results

1. `uv run python -m pytest tests/api/test_facts_route.py tests/api/test_reports_route.py tests/api/test_sources_route.py tests/api/test_graph_route.py -v` -- 40/40 tests pass
2. Facts are enriched with classification impact_tier and verification status -- not raw internal dicts
3. Reports serve content and version history
4. Sources aggregate by domain with correct counts and max authority scores
5. Graph query endpoint dispatches to correct adapter method based on pattern parameter
6. All responses use API-specific schemas from schemas.py, never internal pipeline models

## Next Phase Readiness

Plan 12-04 (app factory and wiring) can proceed. All route modules are ready to be included via `app.include_router(router)`:
- `osint_system.api.routes.facts.router`
- `osint_system.api.routes.reports.router`
- `osint_system.api.routes.sources.router`
- `osint_system.api.routes.graph.router`

Each route expects stores/adapters to be mounted on `app.state` (either via `investigation_stores` dict or directly).
