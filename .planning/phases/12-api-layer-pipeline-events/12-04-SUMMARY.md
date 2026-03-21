---
phase: 12-api-layer-pipeline-events
plan: 04
subsystem: api-integration
tags: [fastapi, cors, openapi, uvicorn, app-factory, serve, lifespan]
dependency-graph:
  requires:
    - 12-01 (schemas, errors, event bus, registry, dependencies)
    - 12-02 (investigation + stream route modules)
    - 12-03 (facts, reports, sources, graph route modules)
  provides:
    - api-app-factory
    - api-openapi-spec
    - dual-mode-serve-entrypoint
    - cors-middleware
    - lifespan-shutdown-handler
  affects:
    - 14 (frontend consumes OpenAPI spec for type codegen)
    - 17 (crawler integration adds routes or modifies pipeline wrapper)
tech-stack:
  added: []
  patterns:
    - "App factory pattern: create_api_app() returns fully wired FastAPI instance"
    - "Lifespan context manager for graceful shutdown of active pipeline tasks"
    - "Dual-mode serve.py: API mode (no args, port 8000) vs dashboard mode (with investigation_id)"
key-files:
  created:
    - osint_system/api/app.py
    - tests/api/test_app.py
    - tests/api/test_openapi.py
  modified:
    - osint_system/serve.py
    - osint_system/api/routes/__init__.py
decisions:
  - id: D12-04-01
    summary: "Lifespan context manager used instead of deprecated on_event('shutdown') for active task cancellation"
    rationale: "FastAPI recommends lifespan over on_event; cancels all pending asyncio.Tasks on shutdown with gather+return_exceptions"
metrics:
  duration: 3min
  completed: 2026-03-22
---

# Phase 12 Plan 04: API App Factory & Integration Summary

**FastAPI app factory wiring 6 route modules (17 endpoints), CORS, RFC 7807 errors, lifespan shutdown handler, and dual-mode serve.py with OpenAPI spec validation -- 169 total API tests passing.**

## Performance

- **Duration:** ~3 min (checkpoint wait excluded)
- **Started:** 2026-03-21T18:20:00Z
- **Completed:** 2026-03-22T00:00:00Z (checkpoint approved)
- **Tasks:** 2 (1 auto + 1 human-verify checkpoint)
- **Files created/modified:** 5

## Accomplishments

- `create_api_app()` factory produces fully configured FastAPI app with all 6 route modules, CORS middleware (localhost:3000/5173), RFC 7807 error handlers, and app.state initialized with event bus, registry, stores, tasks, and cancel flags
- OpenAPI spec at `/openapi.json` describes 15 endpoint paths, 15 component schemas, all `$ref` pointers resolve
- Lifespan handler cancels all active pipeline asyncio.Tasks on server shutdown
- `serve.py` supports dual mode: no args boots API on port 8000, with investigation_id boots HTMX dashboard on port 8050
- Full API test suite: 169 tests across 10 test files, all passing in 2.3s

## Task Commits

Each task was committed atomically:

1. **Task 1: API app factory, serve.py update, and integration tests** - `aa2c23a` (feat)
2. **Task 2: Human verification checkpoint** - approved by user, no code changes

**Plan metadata:** (this commit)

## Files Created/Modified

- `osint_system/api/app.py` -- App factory: create_api_app() with CORS, error handlers, app.state, router wiring, health endpoint, lifespan shutdown
- `osint_system/serve.py` -- Dual-mode entrypoint: API mode (create_api_app + uvicorn on 8000) and dashboard mode (existing HTMX on 8050)
- `osint_system/api/routes/__init__.py` -- Updated imports for all 6 route modules
- `tests/api/test_app.py` -- 16 tests: factory, state initialization, health endpoint, CORS headers, RFC 7807 format, route module mounting, lifespan shutdown
- `tests/api/test_openapi.py` -- 30 tests: all 15 endpoint paths with correct HTTP methods, 15 component schemas, $ref resolution, schema structure validation

## Decisions Made

- **[D12-04-01]** Used lifespan context manager (not deprecated `on_event('shutdown')`) for graceful task cancellation. Lifespan gathers all pending tasks with `return_exceptions=True` to avoid unhandled exceptions during shutdown.

## Deviations from Plan

None -- plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None -- no external service configuration required.

## Next Phase Readiness

Phase 12 (API Layer & Pipeline Events) is now complete. All 4 plans delivered:

1. **12-01**: API schemas, RFC 7807 errors, event bus, investigation registry (56 tests)
2. **12-02**: Investigation CRUD + launch/cancel/regenerate routes, SSE streaming (27 tests)
3. **12-03**: Facts, reports, sources, graph data-serving routes (40 tests)
4. **12-04**: App factory, serve.py integration, OpenAPI spec validation (46 tests)

**Total: 169 API tests, all passing.**

The API is ready for:
- **Phase 13** (SQLite persistence): Replace in-memory stores with persistent storage
- **Phase 14** (Next.js frontend): Consume OpenAPI spec via `@hey-api/openapi-ts` for type-safe client generation
- **Phase 17** (Crawler integration): Wire crawler agents into the pipeline runner

---
*Phase: 12-api-layer-pipeline-events*
*Completed: 2026-03-22*
