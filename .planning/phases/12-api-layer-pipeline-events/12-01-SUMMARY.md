---
phase: 12-api-layer-pipeline-events
plan: 01
subsystem: api-infrastructure
tags: [fastapi, pydantic, rfc7807, event-bus, investigation-registry, sse]
dependency-graph:
  requires: []
  provides:
    - api-response-schemas
    - rfc7807-error-handling
    - pipeline-event-bus
    - investigation-registry
    - fastapi-dependency-injection
  affects:
    - 12-02 (route modules consume schemas, errors, dependencies, registry)
    - 12-03 (SSE endpoint consumes event bus, registry)
    - 12-04 (app factory wires event bus, registry, stores onto app.state)
    - 13 (SQLite migration: stores change, API schemas stay stable)
tech-stack:
  added: []
  patterns:
    - "Decoupled API schemas (api/schemas.py) -- flat Pydantic models, zero internal imports"
    - "RFC 7807 custom exception handlers (ProblemDetailError, register_error_handlers)"
    - "In-memory pub/sub event bus with per-investigation storage and replay"
    - "Compare-and-swap status transitions with asyncio.Lock"
    - "FastAPI Depends() via request.app.state attribute extraction"
key-files:
  created:
    - osint_system/api/__init__.py
    - osint_system/api/schemas.py
    - osint_system/api/errors.py
    - osint_system/api/dependencies.py
    - osint_system/api/events/__init__.py
    - osint_system/api/events/event_models.py
    - osint_system/api/events/event_bus.py
    - osint_system/api/events/investigation_registry.py
    - tests/api/__init__.py
    - tests/api/test_schemas.py
    - tests/api/test_event_bus.py
    - tests/api/test_investigation_registry.py
  modified: []
decisions:
  - id: D12-01-01
    summary: "API schemas fully decoupled -- zero imports from internal pipeline modules"
    rationale: "Prevents OpenAPI spec bloat and enables frontend codegen with clean types"
  - id: D12-01-02
    summary: "Event bus uses synchronous emit (no asyncio.Lock) -- GIL-protected dict ops from single event loop"
    rationale: "Events are ~20-30 per run; lock overhead unjustified for single-loop in-memory operations"
  - id: D12-01-03
    summary: "Valid transition graph enforced in registry -- terminal states (COMPLETED, FAILED, CANCELLED) have no outgoing edges"
    rationale: "Prevents invalid state mutations; ConflictError raised for violations"
metrics:
  duration: 5.9 min
  completed: 2026-03-21
---

# Phase 12 Plan 01: API Infrastructure Summary

API response schemas, RFC 7807 error handling, PipelineEventBus with replay, and InvestigationRegistry with atomic status transitions -- zero new dependencies.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | API response schemas, request models, and RFC 7807 error handling | `0096c4c` | schemas.py, errors.py, dependencies.py, test_schemas.py |
| 2 | PipelineEventBus, event models, and InvestigationRegistry with tests | `78b5fbb` | event_models.py, event_bus.py, investigation_registry.py, test_event_bus.py, test_investigation_registry.py |

## What Was Built

### API Schemas (schemas.py)
- **Request models:** `LaunchRequest` (objective required, min_length=3, optional model/source/feed overrides), `RegenerateRequest`
- **Response models:** `InvestigationResponse`, `FactResponse`, `ReportResponse`, `ReportVersionSummary`, `SourceResponse`, `GraphNodeResponse`, `GraphEdgeResponse`
- **Pagination:** `PaginatedResponse[T]` generic with `from_items()` class method for server-side slicing
- **Error schema:** `ProblemDetail` for OpenAPI documentation
- **Decoupling:** Zero imports from internal pipeline schemas -- API models are flat, JSON-friendly, mapped in route handlers

### RFC 7807 Error Handling (errors.py)
- `ProblemDetailError` base exception with status/title/detail/type_uri/instance
- `NotFoundError` (404) and `ConflictError` (409) convenience subclasses
- `register_error_handlers(app)` installs three handlers:
  - `ProblemDetailError` -> `application/problem+json` with all RFC 7807 fields
  - `HTTPException` -> wrapped in RFC 7807 format
  - `RequestValidationError` -> 422 with RFC 7807 format
- All handlers include `instance: str(request.url)` per CONTEXT.md

### FastAPI Dependencies (dependencies.py)
- 7 dependency injection functions: `get_event_bus`, `get_registry`, `get_fact_store`, `get_classification_store`, `get_verification_store`, `get_report_store`, `get_article_store`
- Each extracts from `request.app.state`, raises `AttributeError` with clear message if not mounted

### PipelineEventBus (events/event_bus.py)
- `emit(investigation_id, event_type, data)` -> stores event, pushes to subscriber queues
- `subscribe(investigation_id)` -> returns `asyncio.Queue[PipelineEvent]`
- `unsubscribe(investigation_id, queue)` -> removes queue from subscriber list
- `get_events_since(investigation_id, last_event_id)` -> replay for SSE reconnection
- `get_all_events(investigation_id)` -> post-completion replay (returns copy)
- `clear(investigation_id)` -> cleanup (removes events, subscribers, counter)

### Event Models (events/event_models.py)
- `EventType(str, Enum)`: PHASE_STARTED, PHASE_PROGRESS, PHASE_COMPLETED, PIPELINE_COMPLETED, PIPELINE_ERROR
- `PipelineEvent` dataclass: id (auto-increment), event_type, data (JSON-serializable dict), timestamp

### InvestigationRegistry (events/investigation_registry.py)
- `InvestigationStatus(str, Enum)`: PENDING, RUNNING, COMPLETED, FAILED, CANCELLED
- `Investigation` dataclass: id, objective, status, params, created_at, updated_at, error, stats
- `create()` -> generates `inv-{uuid_hex[:8]}` ID, status=PENDING
- `get()` -> returns None if not found
- `list_all()` -> sorted by created_at descending
- `transition()` -> atomic compare-and-swap with asyncio.Lock; validates transition graph; raises ConflictError
- `delete()` -> returns bool
- Valid transitions: PENDING->{RUNNING,CANCELLED}, RUNNING->{COMPLETED,FAILED,CANCELLED}, terminal states have no outgoing edges

## Test Coverage

- **test_schemas.py:** 18 tests -- LaunchRequest validation (required, empty, min_length, full), PaginatedResponse slicing (page 1/2/3, beyond range, empty, single), InvestigationResponse datetime serialization, FactResponse optional fields
- **test_event_bus.py:** 17 tests -- emit storage/counter, subscribe delivery, multi-subscriber, unsubscribe stops delivery, replay (since ID, from 0, all events, copy safety), clear, edge cases
- **test_investigation_registry.py:** 21 tests -- create (unique IDs, explicit ID, params, timestamp), get (found, not found), list_all (sorted desc, empty), transition (success, wrong status, updated_at, error, stats, invalid COMPLETED->RUNNING, nonexistent, cancel paths), delete (success, not found, isolation)

**Total: 56 tests, all passing.**

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test_list_all_returns_sorted_by_created_at_descending flakiness**
- **Found during:** Task 2 test execution
- **Issue:** Three investigations created within the same microsecond produced identical `created_at` timestamps, making sort order non-deterministic.
- **Fix:** Explicitly assigned distinct `created_at` timestamps in the test to guarantee deterministic ordering.
- **Files modified:** tests/api/test_investigation_registry.py
- **Commit:** 78b5fbb

## Verification Results

1. All imports from `osint_system.api.schemas`, `osint_system.api.errors`, `osint_system.api.events` succeed
2. `uv run python -m pytest tests/api/ -v` -- 56/56 tests pass
3. No internal pipeline schemas imported in api/schemas.py (grep confirms zero matches)
4. PipelineEventBus replay returns correct events after a given ID (tested)
5. InvestigationRegistry rejects invalid status transitions with ConflictError (tested)

## Next Phase Readiness

Plan 12-02 (route modules) can proceed immediately. All infrastructure it depends on is in place:
- Response schemas for all entity types
- RFC 7807 error handlers ready for `register_error_handlers(app)`
- Event bus ready for SSE streaming in 12-03
- Investigation registry ready for lifecycle management
- Dependency injection helpers ready for `Depends()` parameters
