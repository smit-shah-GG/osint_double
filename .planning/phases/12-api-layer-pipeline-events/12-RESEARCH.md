# Phase 12: API Layer & Pipeline Events - Research

**Researched:** 2026-03-21
**Domain:** FastAPI REST API, Server-Sent Events, Pipeline Event Bus
**Confidence:** HIGH

## Summary

This phase exposes the existing OSINT investigation pipeline as a JSON REST API with real-time SSE streaming. The codebase already runs FastAPI 0.135.1 for an HTMX dashboard (`osint_system/dashboard/`), has mature in-memory stores with pagination support (`FactStore`, `ClassificationStore`, `VerificationStore`, `ReportStore`, `ArticleStore`), and a fully operational `InvestigationRunner` that orchestrates the six-phase pipeline sequentially.

The primary technical finding is that FastAPI 0.135.0+ ships built-in SSE support via `fastapi.sse.EventSourceResponse` and `fastapi.sse.ServerSentEvent`, eliminating the need for the `sse-starlette` third-party dependency. This module natively handles `Last-Event-ID` via header parameters, 15-second heartbeat pings, cache-control headers, and proxy buffering prevention. The existing stores already expose `retrieve_by_investigation()` with `limit`/`offset` pagination, `get_stats()`, `list_investigations()`, and `delete_investigation()` -- the API layer primarily wraps these with Pydantic response models and the decided response envelope.

The key architectural challenge is the PipelineEventBus and the integration with `InvestigationRunner`. The runner currently uses Rich console output and has no event emission mechanism. The API layer must introduce: (1) an investigation registry for lifecycle tracking, (2) a PipelineEventBus for structured event emission, (3) an event-emitting wrapper around `InvestigationRunner`, and (4) SSE endpoints that consume from the event bus.

**Primary recommendation:** Build the API as a parallel router module (`osint_system/api/`) alongside the existing dashboard, sharing the same FastAPI app and stores. Use FastAPI's built-in `fastapi.sse` module for SSE. Use `asyncio.create_task` for pipeline background execution since the pipeline is async-native and long-running (minutes). Implement RFC 7807 as custom exception handlers (the `fastapi-rfc7807` library is dead -- last release 2021, Python 3.6-3.9 only).

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | 0.135.1 | REST API framework + SSE | Already installed; built-in SSE added in 0.135.0 |
| fastapi.sse | (built-in) | EventSourceResponse, ServerSentEvent | Native SSE support, no third-party dependency needed |
| Pydantic | >=2.0 | API request/response schema validation | Already installed; tight FastAPI integration |
| uvicorn | >=0.30.0 | ASGI server | Already installed |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| starlette.middleware.cors | (built-in) | CORS for local dev | When frontend runs on different port |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| fastapi.sse (built-in) | sse-starlette 3.3.3 | sse-starlette has more config options (custom ping factory, send_timeout, shutdown grace period) but built-in is sufficient for our ~20-30 events per run use case |
| asyncio.create_task | FastAPI BackgroundTasks | BackgroundTasks runs after response is sent and ties up the event loop for the response duration; create_task starts immediately and is non-blocking -- correct for multi-minute pipeline runs |
| Custom RFC 7807 handlers | fastapi-rfc7807 0.5.0 | Library abandoned (last release 2021, Python 3.6-3.9); RFC 7807 is trivial to implement with 2 exception handlers |
| Celery/RQ | asyncio.create_task | Celery is massive overkill for single-user system; pipeline is already async-native; no need for external broker |

**Installation:**
```bash
# No new dependencies required -- all libraries already in requirements.txt
# FastAPI 0.135.1 is installed with built-in SSE support
```

## Architecture Patterns

### Recommended Project Structure
```
osint_system/
├── api/                          # NEW: JSON API layer
│   ├── __init__.py
│   ├── app.py                    # API app factory, mounts on existing FastAPI app
│   ├── schemas.py                # API-specific Pydantic response models
│   ├── errors.py                 # RFC 7807 exception classes + handlers
│   ├── dependencies.py           # FastAPI dependency injection (store access)
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── investigations.py     # CRUD + launch + cancel + regenerate
│   │   ├── facts.py              # Fact listing with classification/verification
│   │   ├── reports.py            # Report versions + regeneration
│   │   ├── sources.py            # Source inventory with authority scores
│   │   ├── graph.py              # Graph nodes/edges/queries
│   │   └── stream.py             # SSE event streaming endpoint
│   └── events/
│       ├── __init__.py
│       ├── event_bus.py           # PipelineEventBus (in-memory pub/sub)
│       ├── event_models.py        # Typed event dataclasses
│       └── investigation_registry.py  # Investigation lifecycle tracking
├── dashboard/                    # EXISTING: HTMX dashboard (untouched)
├── runner.py                     # EXISTING: InvestigationRunner (wrapped, not modified)
└── ...
```

### Pattern 1: Separate API Response Models
**What:** API schemas in `api/schemas.py` decouple the API contract from internal pipeline schemas (`ExtractedFact`, `VerificationResult`, etc.). API models are flat, JSON-friendly, and include only fields the frontend needs.
**When to use:** Always. Internal models have complex nested structures (provenance chains, entity markers) that the API should flatten and simplify.
**Why:** CONTEXT.md decision -- "Separate API models in api/schemas.py. Decouples API response shape from internal pipeline schemas."

```python
# api/schemas.py
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Any

class InvestigationResponse(BaseModel):
    """API response for a single investigation."""
    id: str
    objective: str
    status: str  # "pending" | "running" | "completed" | "failed" | "cancelled"
    params: dict[str, Any]
    created_at: datetime
    updated_at: datetime | None = None
    stream_url: str | None = None
    stats: dict[str, int] | None = None

class PaginatedResponse(BaseModel):
    """Wrapped list response with pagination metadata."""
    data: list[Any]
    total: int
    page: int
    page_size: int

class FactResponse(BaseModel):
    """Flat fact representation for API consumers."""
    fact_id: str
    claim_text: str
    claim_type: str
    source_id: str | None = None
    source_type: str | None = None
    extraction_confidence: float | None = None
    impact_tier: str | None = None  # from classification
    verification_status: str | None = None  # from verification
    created_at: str | None = None

class ProblemDetail(BaseModel):
    """RFC 7807 error response."""
    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: str | None = None
```

### Pattern 2: PipelineEventBus (In-Memory Pub/Sub)
**What:** Simple asyncio-based event bus that the pipeline emits to and SSE endpoints consume from. Events are stored per-investigation for replay support.
**When to use:** All pipeline event emission and SSE streaming.
**Why:** CONTEXT.md decisions specify full replay with Last-Event-ID, post-completion replay of full event history, and ~20-30 events per run.

```python
# api/events/event_bus.py
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

@dataclass
class PipelineEvent:
    """Structured pipeline event."""
    id: int                        # Auto-incrementing per investigation
    event_type: str                # phase_started, phase_progress, etc.
    data: dict                     # Event payload
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class PipelineEventBus:
    """In-memory event bus with per-investigation event storage and replay."""

    def __init__(self) -> None:
        self._events: dict[str, list[PipelineEvent]] = {}
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._counters: dict[str, int] = {}

    def emit(self, investigation_id: str, event_type: str, data: dict) -> PipelineEvent:
        """Emit an event. Stores for replay and pushes to active subscribers."""
        if investigation_id not in self._events:
            self._events[investigation_id] = []
            self._counters[investigation_id] = 0

        self._counters[investigation_id] += 1
        event = PipelineEvent(
            id=self._counters[investigation_id],
            event_type=event_type,
            data=data,
        )
        self._events[investigation_id].append(event)

        # Push to all active subscribers
        for queue in self._subscribers.get(investigation_id, []):
            queue.put_nowait(event)

        return event

    def subscribe(self, investigation_id: str) -> asyncio.Queue:
        """Create a new subscriber queue for an investigation."""
        if investigation_id not in self._subscribers:
            self._subscribers[investigation_id] = []
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers[investigation_id].append(queue)
        return queue

    def unsubscribe(self, investigation_id: str, queue: asyncio.Queue) -> None:
        """Remove a subscriber queue."""
        if investigation_id in self._subscribers:
            self._subscribers[investigation_id] = [
                q for q in self._subscribers[investigation_id] if q is not queue
            ]

    def get_events_since(self, investigation_id: str, last_event_id: int) -> list[PipelineEvent]:
        """Get all events after a given event ID (for replay)."""
        events = self._events.get(investigation_id, [])
        return [e for e in events if e.id > last_event_id]

    def get_all_events(self, investigation_id: str) -> list[PipelineEvent]:
        """Get full event history (for post-completion replay)."""
        return list(self._events.get(investigation_id, []))
```

### Pattern 3: Investigation Registry
**What:** First-class investigation entity tracking status, parameters, timestamps, and stream URL. Separate from store-level data -- this is the API-layer lifecycle tracker.
**When to use:** POST create, GET list/detail, status transitions, cancel/regenerate.
**Why:** Current stores track data per-investigation but have no unified "investigation" entity with status. The runner creates stores on the fly. The registry provides the investigation lifecycle the API needs.

```python
# api/events/investigation_registry.py
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

class InvestigationStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class Investigation:
    id: str
    objective: str
    status: InvestigationStatus = InvestigationStatus.PENDING
    params: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime | None = None
    error: str | None = None
    stats: dict[str, int] = field(default_factory=dict)
```

### Pattern 4: SSE Stream Endpoint with Replay
**What:** GET endpoint that yields ServerSentEvent objects from the event bus, supporting Last-Event-ID reconnection and post-completion replay.
**When to use:** Frontend connecting to `/api/v1/investigations/{id}/stream`.

```python
# api/routes/stream.py
from collections.abc import AsyncIterable
from typing import Annotated

from fastapi import APIRouter, Header, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent

import asyncio
import json

router = APIRouter()

@router.get("/investigations/{investigation_id}/stream", response_class=EventSourceResponse)
async def stream_events(
    request: Request,
    investigation_id: str,
    last_event_id: Annotated[int | None, Header()] = None,
) -> AsyncIterable[ServerSentEvent]:
    event_bus = request.app.state.event_bus
    registry = request.app.state.investigation_registry

    investigation = registry.get(investigation_id)
    if investigation is None:
        # Yield error event and close
        yield ServerSentEvent(
            data=json.dumps({"error": "Investigation not found"}),
            event="error",
        )
        return

    # Replay missed events (reconnection or post-completion)
    start_id = last_event_id or 0
    missed = event_bus.get_events_since(investigation_id, start_id)
    for event in missed:
        yield ServerSentEvent(
            data=json.dumps(event.data),
            event=event.event_type,
            id=str(event.id),
        )

    # If pipeline already completed, close stream after replay
    if investigation.status in ("completed", "failed", "cancelled"):
        return

    # Subscribe for live events
    queue = event_bus.subscribe(investigation_id)
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield ServerSentEvent(
                    data=json.dumps(event.data),
                    event=event.event_type,
                    id=str(event.id),
                )
                # Stop if terminal event
                if event.event_type in ("pipeline_completed", "pipeline_error"):
                    break
            except asyncio.TimeoutError:
                # Heartbeat is handled by FastAPI's built-in 15s ping
                continue
    finally:
        event_bus.unsubscribe(investigation_id, queue)
```

### Pattern 5: Response Envelope for List Endpoints
**What:** Wrap paginated list responses in `{"data": [...], "total": N, "page": 1, "page_size": 100}` per CONTEXT.md decision.
**When to use:** All list endpoints (GET facts, GET sources, GET investigations, GET report versions).

```python
# Helper for consistent pagination
def paginate(items: list, page: int, page_size: int) -> dict:
    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "data": items[start:end],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
```

### Pattern 6: asyncio.create_task for Pipeline Execution
**What:** Launch `InvestigationRunner.run()` as an asyncio task, not via FastAPI BackgroundTasks.
**When to use:** POST to create/launch investigation.
**Why:** BackgroundTasks waits for the response to be streamed before starting and blocks the event loop for the task duration. `asyncio.create_task` starts execution immediately and runs concurrently. The pipeline is already fully async.

```python
# In investigation launch endpoint
async def launch_investigation(request: Request, body: LaunchRequest):
    runner = InvestigationRunner(objective=body.objective, ...)
    # Store the task reference to prevent GC
    task = asyncio.create_task(run_pipeline_with_events(runner, event_bus, registry))
    request.app.state.active_tasks[investigation.id] = task
    return JSONResponse(status_code=202, content=investigation_response)
```

### Anti-Patterns to Avoid
- **Direct store mutation from API routes:** Always go through the store's async methods. Never access `_storage` directly.
- **Reusing internal schemas as API responses:** `ExtractedFact` has 15+ nested Pydantic models with entity markers, provenance chains, etc. The API should expose flat, simple JSON.
- **Blocking sync calls in async endpoints:** All store methods are async. The pipeline runner is async. Never use `run_in_executor` for store access.
- **Modifying InvestigationRunner directly:** Wrap it with an event-emitting adapter rather than adding SSE concerns to the runner itself. Keep the runner usable from CLI.
- **Using FastAPI BackgroundTasks for multi-minute jobs:** Use `asyncio.create_task` instead. BackgroundTasks is for quick fire-and-forget operations.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SSE streaming | Custom text/event-stream response | `fastapi.sse.EventSourceResponse` + `ServerSentEvent` | Built-in handles heartbeat, cache-control, proxy headers, Last-Event-ID automatically |
| OpenAPI spec generation | Manual spec writing | FastAPI auto-generates from type hints + Pydantic models | FastAPI generates `/openapi.json` at runtime; covers all routes automatically |
| Request validation | Manual parameter parsing | Pydantic BaseModel for bodies, FastAPI Query/Path for params | Built-in validation with automatic 422 error responses |
| JSON serialization | Custom serializers | Pydantic `.model_dump(mode="json")` | Handles datetime, enums, nested models correctly |
| CORS headers | Manual header injection | `starlette.middleware.cors.CORSMiddleware` | Handles preflight OPTIONS, allowed origins, credentials |
| Pagination math | Custom offset/limit logic | Reuse existing store `limit`/`offset` params | Stores already support `retrieve_by_investigation(limit=N, offset=M)` |

**Key insight:** FastAPI 0.135.1 provides everything needed for this phase without any new dependencies. The existing stores have pagination, listing, and stats APIs that map directly to the required REST endpoints.

## Common Pitfalls

### Pitfall 1: Task Reference Garbage Collection
**What goes wrong:** `asyncio.create_task` returns a Task object. If the reference is lost (not stored), the task can be garbage-collected before completion, silently killing the pipeline.
**Why it happens:** Python GC collects unreferenced objects. A fire-and-forget `create_task` without storing the reference is a common async footgun.
**How to avoid:** Store task references in `app.state.active_tasks` dict keyed by investigation_id. Remove on completion via task callback.
**Warning signs:** Pipeline starts but silently stops mid-execution with no error logged.

### Pitfall 2: SSE Connection Not Closing After Pipeline Completion
**What goes wrong:** The SSE generator keeps yielding heartbeats forever after the pipeline finishes because there is no terminal event check.
**Why it happens:** The subscriber queue never receives a "done" signal if the generator does not check for terminal events.
**How to avoid:** Emit `pipeline_completed` or `pipeline_error` as the final event. The SSE generator must break the loop when it receives a terminal event type.
**Warning signs:** Browser EventSource connections stay open indefinitely, client never sees stream end.

### Pitfall 3: Race Condition Between POST Response and First SSE Event
**What goes wrong:** Client receives 202 response with `stream_url`, connects to SSE endpoint, but the first events were already emitted before the client connected.
**Why it happens:** `asyncio.create_task` starts execution immediately, and the pipeline may emit `phase_started` before the client opens the SSE connection.
**How to avoid:** Event replay. The event bus stores all events. When the SSE endpoint connects, it replays all events from `last_event_id=0` before subscribing for live events.
**Warning signs:** Client misses the first few events (phase_started for crawling phase).

### Pitfall 4: Concurrent Investigation Mutation
**What goes wrong:** Two concurrent API calls (e.g., cancel + regenerate) race on updating investigation status.
**Why it happens:** Investigation registry is in-memory with no locking.
**How to avoid:** Use asyncio.Lock per investigation for status transitions. Or use a simple atomic compare-and-swap pattern: only transition if current status matches expected.
**Warning signs:** Investigation stuck in "running" after cancellation, or regeneration starts on a still-running investigation.

### Pitfall 5: OpenAPI Schema Bloat from Internal Models
**What goes wrong:** If internal models like `ExtractedFact` (with `Claim`, `Entity`, `Provenance`, `TemporalMarker`, etc.) leak into response types, the OpenAPI spec becomes massive and the TypeScript codegen produces unusable types.
**Why it happens:** Using `response_model=ExtractedFact` directly on an endpoint instead of a flattened API-specific model.
**How to avoid:** Always use dedicated API response models from `api/schemas.py`. Map internal models to API models in the route handler.
**Warning signs:** `/openapi.json` is > 100KB, TypeScript types have 10+ levels of nesting.

### Pitfall 6: Graph Adapter Not Available in API Context
**What goes wrong:** The graph pipeline creates a `NetworkXAdapter` per-run in `InvestigationRunner`, but the API layer needs to query it after the run completes. If the adapter is not retained, graph data is lost.
**Why it happens:** `GraphPipeline` creates and closes its adapter in `run_ingestion()`. After the method returns, the graph data is gone.
**How to avoid:** The event-emitting runner wrapper must retain the `GraphPipeline` (and its adapter) on `app.state` or in the investigation registry so the Graph API can query it post-completion.
**Warning signs:** Graph API returns empty results for completed investigations.

### Pitfall 7: Unserializable Event Data
**What goes wrong:** Event data dict contains non-JSON-serializable types (datetime, Pydantic models, enums) and `json.dumps` fails in the SSE generator.
**Why it happens:** Pipeline code uses Python-native types internally.
**How to avoid:** Serialize event data at emission time. Use `json.dumps(data, default=str)` or convert all values to primitives before emitting.
**Warning signs:** SSE stream errors with "TypeError: Object of type datetime is not JSON serializable".

## Code Examples

### RFC 7807 Error Handling (Custom Implementation)
```python
# api/errors.py
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

class ProblemDetailError(Exception):
    """Base exception for RFC 7807 problem detail responses."""
    def __init__(
        self,
        status: int,
        title: str,
        detail: str,
        type_uri: str = "about:blank",
        instance: str | None = None,
    ):
        self.status = status
        self.title = title
        self.detail = detail
        self.type_uri = type_uri
        self.instance = instance

def register_error_handlers(app: FastAPI) -> None:
    """Register RFC 7807 compliant error handlers."""

    @app.exception_handler(ProblemDetailError)
    async def problem_detail_handler(request: Request, exc: ProblemDetailError):
        return JSONResponse(
            status_code=exc.status,
            content={
                "type": exc.type_uri,
                "title": exc.title,
                "status": exc.status,
                "detail": exc.detail,
                "instance": exc.instance or str(request.url),
            },
            media_type="application/problem+json",
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "type": "about:blank",
                "title": exc.detail,
                "status": exc.status_code,
                "detail": exc.detail,
                "instance": str(request.url),
            },
            media_type="application/problem+json",
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "type": "about:blank",
                "title": "Validation Error",
                "status": 422,
                "detail": str(exc.errors()),
                "instance": str(request.url),
            },
            media_type="application/problem+json",
        )
```

### CORS Configuration for Local Development
```python
# In API app factory
from starlette.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",   # React dev server
        "http://localhost:5173",   # Vite dev server
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Investigation Launch Endpoint (202 Accepted Pattern)
```python
# api/routes/investigations.py
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/v1")

@router.post("/investigations", status_code=202)
async def create_investigation(request: Request, body: LaunchRequest):
    registry = request.app.state.investigation_registry
    event_bus = request.app.state.event_bus

    investigation = registry.create(
        objective=body.objective,
        params=body.model_dump(exclude={"objective"}, exclude_none=True),
    )

    # Launch pipeline as background async task
    task = asyncio.create_task(
        _run_pipeline(investigation.id, body, request.app.state)
    )
    request.app.state.active_tasks[investigation.id] = task
    task.add_done_callback(
        lambda t: request.app.state.active_tasks.pop(investigation.id, None)
    )

    return JSONResponse(
        status_code=202,
        content={
            "id": investigation.id,
            "objective": investigation.objective,
            "status": investigation.status.value,
            "params": investigation.params,
            "created_at": investigation.created_at.isoformat(),
            "stream_url": f"/api/v1/investigations/{investigation.id}/stream",
        },
    )
```

### Fact Enrichment (Joining Classification + Verification)
```python
# api/routes/facts.py - Joining fact data with classification and verification
async def _enrich_fact(
    fact: dict,
    classification_store,
    verification_store,
    investigation_id: str,
) -> dict:
    """Build flat FactResponse from internal fact + classification + verification."""
    fact_id = fact.get("fact_id", "")

    # Get classification
    classification = await classification_store.get_classification(
        investigation_id, fact_id
    )
    impact_tier = classification.impact_tier.value if classification else None

    # Get verification
    verification = await verification_store.get_result(
        investigation_id, fact_id
    )
    ver_status = None
    if verification:
        ver_status = (
            verification.status.value
            if hasattr(verification.status, "value")
            else str(verification.status)
        )

    claim = fact.get("claim", {})
    claim_text = claim.get("text", "") if isinstance(claim, dict) else str(claim)
    provenance = fact.get("provenance", {})

    return {
        "fact_id": fact_id,
        "claim_text": claim_text,
        "claim_type": claim.get("claim_type", "unknown") if isinstance(claim, dict) else "unknown",
        "source_id": provenance.get("source_id") if isinstance(provenance, dict) else None,
        "source_type": provenance.get("source_type") if isinstance(provenance, dict) else None,
        "extraction_confidence": fact.get("extraction_confidence"),
        "impact_tier": impact_tier,
        "verification_status": ver_status,
        "created_at": fact.get("stored_at"),
    }
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `sse-starlette` for SSE | `fastapi.sse` built-in | FastAPI 0.135.0 (Jan 2026) | No third-party dependency; native heartbeat, Last-Event-ID support |
| `fastapi-rfc7807` middleware | Custom exception handlers | Library abandoned 2021 | 3 exception handlers replace the entire library; more control |
| FastAPI BackgroundTasks | `asyncio.create_task` | Always for long-running | BackgroundTasks blocks event loop; create_task is non-blocking |
| Manual SSE format | `ServerSentEvent` dataclass | FastAPI 0.135.0 | Type-safe event construction with data/event/id/retry/comment fields |

**Deprecated/outdated:**
- `sse-starlette`: Still maintained (v3.3.3, March 2026) but redundant now that FastAPI has built-in SSE support
- `fastapi-rfc7807`: Dead library (v0.5.0, June 2021), Python 3.6-3.9 only, incompatible with current Pydantic/FastAPI versions

## Existing Codebase Integration Points

Critical existing interfaces the API layer must integrate with:

### Store Interfaces (API reads from these)
| Store | Key Methods for API | Notes |
|-------|-------------------|-------|
| `FactStore` | `retrieve_by_investigation(id, limit, offset)`, `get_fact(inv_id, fact_id)`, `list_investigations()`, `get_stats(inv_id)` | Already has pagination via limit/offset |
| `ClassificationStore` | `get_classification(inv_id, fact_id)`, `get_all_classifications(inv_id)`, `get_stats(inv_id)` | Returns `FactClassification` Pydantic models |
| `VerificationStore` | `get_result(inv_id, fact_id)`, `get_all_results(inv_id)`, `get_stats(inv_id)` | Returns `VerificationResultRecord` models |
| `ReportStore` | `get_latest(inv_id)`, `list_versions(inv_id)`, `get_version(inv_id, version)` | Returns `ReportRecord` Pydantic models |
| `ArticleStore` | `retrieve_by_investigation(id, limit, offset)`, `get_investigation_stats(inv_id)` | Source inventory derived from article sources |

### InvestigationRunner Interface
| Method | Signature | Notes |
|--------|-----------|-------|
| Constructor | `InvestigationRunner(objective, investigation_id=None, data_dir="data")` | Creates shared stores internally |
| Run | `async run() -> str` | Returns investigation_id; runs all 6 phases sequentially |
| Phases | `_phase_crawl`, `_phase_extract`, `_phase_classify`, `_phase_verify`, `_phase_graph`, `_phase_analyze` | Each is an async method |

### Graph Query Interface
| Method | Purpose | Returns |
|--------|---------|---------|
| `adapter.query_entity_network(entity_id, max_hops, inv_id)` | BFS from entity node | `QueryResult` with nodes + edges |
| `adapter.query_corroboration_clusters(inv_id)` | CORROBORATES/CONTRADICTS clusters | `QueryResult` |
| `adapter.query_timeline(entity_id, inv_id)` | Temporal fact ordering | `QueryResult` |
| `adapter.query_shortest_path(from_id, to_id, inv_id)` | Path between entities | `QueryResult` |

### Key Constraint: Phase 13 Migration
The API layer MUST work with current in-memory store interfaces. Phase 13 migrates to SQLite. The API schemas and route handlers must be store-agnostic -- they call store methods, not access internals.

## Open Questions

1. **Graph adapter lifecycle management**
   - What we know: `GraphPipeline` creates adapter per-run; `NetworkXAdapter` is in-memory. After run completes, data is in the adapter's `_graph` attribute.
   - What's unclear: Best strategy for retaining the adapter across requests. Options: (a) store on `app.state` per investigation, (b) serialize graph to JSON after run and reload on query, (c) keep `GraphPipeline` instances alive.
   - Recommendation: Store `GraphPipeline` instances in a dict on `app.state` keyed by investigation_id. Accept memory cost (graphs are small -- hundreds of nodes). Serialization adds complexity for no benefit pre-SQLite.

2. **Store sharing between runner and API**
   - What we know: `InvestigationRunner.__init__` creates its own store instances with `persistence_path`. The API layer also needs store access.
   - What's unclear: Whether to inject API-layer stores into the runner, or let the runner create its own and share them back.
   - Recommendation: The event-emitting wrapper creates stores with persistence paths, passes them to the runner constructor, AND mounts them on `app.state`. This gives both the runner and API access to the same store instances.

3. **Cancel mechanism implementation**
   - What we know: CONTEXT.md specifies "pipeline checks a cancellation flag between phases."
   - What's unclear: `InvestigationRunner` has no cancellation support. Adding it requires modifying the runner or wrapping each phase call.
   - Recommendation: Add an `asyncio.Event` as a cancellation flag. The event-emitting wrapper checks it between phases. If set, skip remaining phases and emit `pipeline_error` with reason "cancelled".

## Sources

### Primary (HIGH confidence)
- FastAPI 0.135.1 official SSE documentation: https://fastapi.tiangolo.com/tutorial/server-sent-events/ -- Built-in EventSourceResponse, ServerSentEvent, Last-Event-ID, heartbeat
- FastAPI 0.135.1 installed and verified locally via `uv run python -c "from fastapi.sse import EventSourceResponse, ServerSentEvent"`
- Codebase analysis: `osint_system/runner.py`, `osint_system/dashboard/app.py`, all store files, graph adapter
- PyPI fastapi 0.135.1: https://pypi.org/project/fastapi/ -- Released March 1, 2026

### Secondary (MEDIUM confidence)
- sse-starlette 3.3.3 PyPI: https://pypi.org/project/sse-starlette/ -- Released March 17, 2026 (still maintained but redundant)
- FastAPI BackgroundTasks vs asyncio.create_task discussion: https://github.com/fastapi/fastapi/discussions/10743
- FastAPI CORS documentation: https://fastapi.tiangolo.com/tutorial/cors/
- @hey-api/openapi-ts: https://heyapi.dev/openapi-ts/get-started -- v0.94.3, actively maintained

### Tertiary (LOW confidence)
- fastapi-rfc7807 GitHub: https://github.com/vapor-ware/fastapi-rfc7807 -- Last release 0.5.0 (June 2021), confirmed abandoned
- FastAPI RFC 7807 discussion: https://github.com/fastapi/fastapi/discussions/8059 -- No native support, custom handlers recommended

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - FastAPI 0.135.1 verified locally, built-in SSE tested, all dependencies already installed
- Architecture: HIGH - Based on deep codebase analysis of existing stores, runner, dashboard, and graph adapter interfaces
- Pitfalls: HIGH - Derived from well-known asyncio patterns and verified against actual codebase structure
- Event bus design: MEDIUM - Pattern is straightforward but specific implementation details (e.g., memory limits, cleanup) may need adjustment during implementation

**Research date:** 2026-03-21
**Valid until:** 2026-04-21 (30 days -- FastAPI stable, no expected breaking changes)
