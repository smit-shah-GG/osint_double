---
phase: 12-api-layer-pipeline-events
plan: 02
subsystem: api-routes
tags: [fastapi, rest-api, sse, asyncio, event-streaming, investigation-lifecycle]
dependency-graph:
  requires:
    - 12-01 (schemas, errors, event bus, registry, dependencies)
  provides:
    - investigation-crud-endpoints
    - investigation-launch-with-event-emission
    - investigation-cancel-mechanism
    - investigation-regenerate-endpoint
    - sse-event-streaming-with-replay
  affects:
    - 12-04 (app factory wires these routers onto the FastAPI app)
    - 14 (frontend consumes these endpoints)
tech-stack:
  added: []
  patterns:
    - "asyncio.create_task for multi-minute pipeline execution with GC-safe task reference storage"
    - "Phase-by-phase runner wrapper with event emission and cancellation check between phases"
    - "SSE raw_data field for pre-serialized JSON (prevents double-encoding by FastAPI)"
    - "Last-Event-ID SSE reconnection with full replay from event bus"
    - "Post-completion SSE replay: connect after pipeline done, get full history, stream closes"
key-files:
  created:
    - osint_system/api/routes/investigations.py
    - osint_system/api/routes/stream.py
    - tests/api/test_investigations_route.py
    - tests/api/test_stream_route.py
  modified:
    - osint_system/api/routes/__init__.py
decisions:
  - id: D12-02-01
    summary: "Pipeline wrapper calls runner phases individually (_phase_crawl, _phase_extract, etc.) rather than runner.run()"
    rationale: "Required for event emission between phases and cancellation check between phases; runner.run() provides no hooks"
  - id: D12-02-02
    summary: "SSE uses raw_data field instead of data field in ServerSentEvent"
    rationale: "FastAPI auto-serializes data field; pre-serializing with json.dumps(default=str) and using raw_data prevents double JSON encoding"
  - id: D12-02-03
    summary: "Regenerate endpoint directly mutates investigation status under registry lock (bypasses transition graph)"
    rationale: "COMPLETED->RUNNING is not a valid transition in the registry graph; regeneration is a special case that needs temporary RUNNING state"
metrics:
  duration: 7.3 min
  completed: 2026-03-21
---

# Phase 12 Plan 02: Investigation Routes & SSE Streaming Summary

Investigation CRUD + launch/cancel/regenerate endpoints with phase-by-phase event-emitting pipeline wrapper, and SSE streaming with Last-Event-ID replay and post-completion access.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Investigation CRUD, launch, cancel, and regenerate endpoints | `f7f476e` | investigations.py, test_investigations_route.py |
| 2 | SSE event streaming endpoint with replay and reconnection | `b1a2eb3` | stream.py, test_stream_route.py |

## What Was Built

### Investigation Endpoints (investigations.py -- 6 routes)

1. **POST /api/v1/investigations** (202) -- Creates investigation in registry, transitions to PENDING, launches `_run_pipeline_with_events` via `asyncio.create_task`, stores task reference in `app.state.active_tasks` to prevent GC, returns `InvestigationResponse` with `stream_url`.

2. **GET /api/v1/investigations** -- Returns `PaginatedResponse[InvestigationResponse]` with all investigations sorted by created_at descending. Supports `page` and `page_size` query parameters.

3. **GET /api/v1/investigations/{id}** -- Returns single `InvestigationResponse`. 404 if not found (RFC 7807).

4. **DELETE /api/v1/investigations/{id}** (204) -- Cancels running task if needed, deletes from registry, cleans up event bus, investigation stores, and graph pipelines.

5. **POST /api/v1/investigations/{id}/cancel** -- Sets `asyncio.Event` cancellation flag, transitions RUNNING->CANCELLED, emits `pipeline_error` event with `{"reason": "cancelled"}`. Returns 409 if not RUNNING.

6. **POST /api/v1/investigations/{id}/regenerate** (202) -- Re-runs only AnalysisPipeline with existing stores for COMPLETED investigations. Returns 409 if not COMPLETED.

### Pipeline Wrapper (_run_pipeline_with_events)

The wrapper orchestrates runner phases individually (not `runner.run()`) to:
- Emit `phase_started` before each phase
- Emit `phase_completed` with `elapsed_ms` and cumulative stats after each phase
- Emit `phase_progress` with cumulative counts between phases
- Check `cancel_event.is_set()` between phases
- Transition to COMPLETED/FAILED on success/error
- Emit `pipeline_completed`/`pipeline_error` terminal events
- Retain runner stores on `app.state.investigation_stores` for API read access
- Retain `GraphPipeline` on `app.state.graph_pipelines` for Graph API (Pitfall 6)

### SSE Streaming Endpoint (stream.py -- 1 route)

**GET /api/v1/investigations/{id}/stream** (EventSourceResponse):
- **Replay**: Get missed events via `event_bus.get_events_since(id, last_event_id)`, yield as `ServerSentEvent` with `raw_data`/`event`/`id` fields.
- **Post-completion**: If investigation is terminal (COMPLETED/FAILED/CANCELLED), close stream after replay.
- **Live streaming**: Subscribe via `event_bus.subscribe(id)`, yield events until terminal event type (`pipeline_completed` or `pipeline_error`), then break.
- **Disconnect detection**: Checks `request.is_disconnected()` on 30s timeout.
- **Cleanup**: `event_bus.unsubscribe()` in finally block.
- **Serialization**: Uses `raw_data=json.dumps(data, default=str)` to prevent double JSON encoding (Pitfall 7).

## Test Coverage

- **test_investigations_route.py**: 19 tests -- create (202 + validation), list (empty, data, pagination), detail (found, 404 RFC 7807), delete (success, 404, event bus cleanup), cancel (success, 409 non-running, 404, event emission), regenerate (202 completed, 409 non-completed), route count, pipeline execution.
- **test_stream_route.py**: 8 tests -- nonexistent investigation error event, completed replay (all events), event order preservation, Last-Event-ID partial replay, SSE field format (data/event/id), JSON serialization, failed investigation replay, route count.

**Total: 27 tests, all passing. Full API suite: 123 tests, all passing.**

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed double JSON serialization in SSE events**
- **Found during:** Task 2 test execution
- **Issue:** `ServerSentEvent(data=json.dumps(event.data))` causes FastAPI to double-serialize: the data string gets JSON-encoded again (quoted and escaped), producing `data: "{\"phase\": \"crawl\"}"` instead of `data: {"phase": "crawl"}`.
- **Fix:** Switched from `data=` to `raw_data=` field in `ServerSentEvent`, which FastAPI uses as-is without further serialization. Pre-serializing with `json.dumps(default=str)` handles non-JSON-serializable types (Pitfall 7) while `raw_data` prevents double encoding.
- **Files modified:** osint_system/api/routes/stream.py
- **Commit:** b1a2eb3

## Verification Results

1. `uv run python -m pytest tests/api/test_investigations_route.py tests/api/test_stream_route.py -v` -- 27/27 tests pass
2. POST /api/v1/investigations returns 202 with InvestigationResponse including stream_url
3. GET /api/v1/investigations returns PaginatedResponse with investigation list
4. SSE endpoint yields ServerSentEvent objects with correct data/event/id fields
5. Last-Event-ID reconnection replays only missed events (verified: IDs > 3 when Last-Event-ID=3)
6. Pipeline wrapper emits events at each phase boundary (verified via mock runner test)
7. Cancel flag is checked between phases (cancel endpoint sets asyncio.Event)
8. Task references stored in app.state.active_tasks (verified via done_callback cleanup)

## Next Phase Readiness

Plan 12-04 (app factory) can wire these routers. All route modules are self-contained:
- `investigations.router` provides 6 endpoints on `/api/v1`
- `stream.router` provides 1 SSE endpoint on `/api/v1`
- Both access dependencies via `request.app.state` (event_bus, investigation_registry, etc.)
- App factory needs to: mount routers, initialize app.state attributes, register error handlers
