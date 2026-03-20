# Architecture: Next.js Frontend Integration with Python OSINT Backend

**Project:** OSINT Intelligence System v2.0
**Dimension:** Frontend integration, API design, storage migration, monorepo structure
**Researched:** 2026-03-20
**Overall confidence:** HIGH (based on direct codebase analysis + verified patterns)

---

## 1. Current Architecture (As-Is)

### Component Map

```
CLI (typer)
  |
  v
InvestigationRunner          <-- Orchestrates entire pipeline
  |
  |-- ArticleStore           <-- In-memory dict + JSON persistence
  |-- FactStore              <-- In-memory dict + JSON persistence + O(1) indexes
  |-- ClassificationStore    <-- In-memory dict + JSON persistence + flag/tier indexes
  |-- VerificationStore      <-- In-memory dict + JSON persistence
  |-- ReportStore            <-- In-memory dict + JSON persistence (slimmed)
  |
  |-- ExtractionPipeline     <-- asyncio.gather, semaphore-controlled
  |-- VerificationPipeline
  |-- GraphPipeline          <-- NetworkX fallback (no Neo4j)
  |-- AnalysisPipeline
  |
  v
Dashboard (FastAPI + HTMX)   <-- Read-only viewer, post-hoc
  |-- /                      <-- Investigation list (HTML)
  |-- /investigation/{id}    <-- Detail view (HTML)
  |-- /facts/{id}            <-- Fact browser (HTML)
  |-- /reports/{id}          <-- Report viewer (HTML, Markdown->HTML via mistune)
  |-- /api/investigation/{id}/stats  <-- JSON stats (HTMX polling)
  |-- /api/investigation/{id}/facts  <-- HTML partial (HTMX swap)
```

### Critical Observations

1. **Stores are pure Python objects** -- they expose async methods but have no network boundary. Every store is instantiated in-process and passed by reference. The `InvestigationRunner.__init__` creates all stores with file paths, and the `serve.py` entry point re-creates stores pointing at the same JSON files.

2. **Pipeline is synchronous in orchestration, async in execution** -- `InvestigationRunner.run()` calls phases sequentially (`await self._phase_crawl()`, then `_phase_extract()`, etc.), but each phase internally uses `asyncio.gather` for concurrent LLM calls.

3. **No investigation lifecycle management** -- Investigations are fire-and-forget. There is no "investigation" entity tracked across pipeline stages. The investigation_id is a UUID generated at runner instantiation. There is no way to list running investigations, cancel one, or check progress from outside the process.

4. **Dashboard is a read-only post-hoc viewer** -- The current FastAPI dashboard assumes the pipeline has already completed. It loads stores from persisted JSON and renders HTML templates. It cannot start investigations or track progress.

5. **Data directory structure is implicit** -- `data/<inv_id>/*.json` is the convention, but there is no registry of investigations. The `serve.py` entry point scans `data/` for `inv-*` directories.

---

## 2. Target Architecture (To-Be)

### High-Level Integration

```
+---------------------------+        +---------------------------+
|   Next.js Frontend        |        |   FastAPI Backend (API)   |
|   (shadcn/ui + TS)        |        |                           |
|                           |  HTTP  |                           |
|  Investigation Dashboard  | <----> |  /api/v1/investigations   |
|  Pipeline Progress (SSE)  | <-SSE- |  /api/v1/stream/{id}      |
|  Report Viewer            | <----> |  /api/v1/reports          |
|  Fact Browser             | <----> |  /api/v1/facts            |
|                           |        |                           |
+---------------------------+        +---------------------------+
                                              |
                                              v
                                     +------------------+
                                     |  SQLite (WAL)    |
                                     |  via aiosqlite   |
                                     +------------------+
                                              |
                                     +------------------+
                                     |  Store Adapters  |
                                     |  (same interface)|
                                     +------------------+
```

### Design Principles

1. **Backend owns all computation.** The Next.js frontend is a pure presentation layer. No business logic, no LLM calls, no data transformation on the frontend.

2. **SSE for pipeline progress, REST for everything else.** Pipeline runs are long (2-10 minutes). SSE is the correct primitive: unidirectional server-to-client, auto-reconnect via `Last-Event-ID`, no WebSocket complexity. FastAPI has first-class SSE support via `EventSourceResponse` + `ServerSentEvent`.

3. **Store interface preserved.** The existing store classes (ArticleStore, FactStore, etc.) have well-designed async interfaces with `asyncio.Lock` thread safety. The migration path is: replace the `_storage` dict and `_save_to_file/_load_from_file` with SQLite-backed implementations behind the same async method signatures. Pipeline code does not change.

4. **OpenAPI as contract.** FastAPI auto-generates OpenAPI spec. Use `@hey-api/openapi-ts` to generate TypeScript client from the spec. Zero manual type duplication.

---

## 3. API Design

### Endpoint Taxonomy

The API serves three distinct access patterns:

| Pattern | Transport | Use Case |
|---------|-----------|----------|
| CRUD | REST (JSON) | List/get/create investigations, facts, reports |
| Progress | SSE | Pipeline execution progress, phase transitions |
| Stats | REST (JSON) | Aggregated counts, summaries for dashboard cards |

### Endpoint Specification

#### Investigations

```
POST   /api/v1/investigations              -- Start new investigation
GET    /api/v1/investigations              -- List all investigations
GET    /api/v1/investigations/{id}         -- Get investigation detail
DELETE /api/v1/investigations/{id}         -- Delete investigation and all data
GET    /api/v1/investigations/{id}/status  -- Pipeline status (phase, progress %)
```

**POST /api/v1/investigations** is the critical endpoint. It must:
1. Create the investigation record immediately (synchronous).
2. Return the `investigation_id` and initial status.
3. Spawn the pipeline as a background task (`asyncio.create_task`).
4. NOT block on pipeline completion.

```python
@router.post("/investigations", status_code=201)
async def create_investigation(
    request: InvestigationRequest,
    background_tasks: BackgroundTasks,
) -> InvestigationCreatedResponse:
    inv_id = f"inv-{uuid.uuid4().hex[:8]}"
    # Register investigation in DB immediately
    await investigation_registry.create(inv_id, request.objective)
    # Spawn pipeline as background task
    background_tasks.add_task(run_pipeline, inv_id, request.objective)
    return InvestigationCreatedResponse(
        investigation_id=inv_id,
        status="crawling",
        stream_url=f"/api/v1/stream/{inv_id}",
    )
```

#### Pipeline Progress (SSE)

```
GET    /api/v1/stream/{id}                 -- SSE stream of pipeline events
```

This is the architectural linchpin. The pipeline runner emits events as it progresses through phases. The SSE endpoint yields those events to the client.

**Event types:**

```
event: phase_started
data: {"phase": "crawling", "timestamp": "..."}

event: phase_progress
data: {"phase": "extraction", "current": 15, "total": 42, "message": "Processing article 15/42"}

event: phase_completed
data: {"phase": "extraction", "duration_seconds": 45.2, "stats": {"facts_extracted": 127}}

event: pipeline_completed
data: {"investigation_id": "inv-abc123", "total_duration": 312.5}

event: pipeline_error
data: {"phase": "verification", "error": "Rate limit exceeded", "recoverable": true}
```

**Implementation pattern:**

```python
from fastapi.sse import EventSourceResponse, ServerSentEvent

@router.get("/stream/{investigation_id}", response_class=EventSourceResponse)
async def stream_progress(
    investigation_id: str,
    last_event_id: Annotated[int | None, Header()] = None,
) -> AsyncIterable[ServerSentEvent]:
    """Stream pipeline progress events via SSE."""
    event_id = last_event_id or 0
    while True:
        events = await event_bus.get_events_since(investigation_id, event_id)
        for event in events:
            event_id = event.id
            yield ServerSentEvent(
                data=event.payload,
                event=event.type,
                id=str(event.id),
            )
        if await event_bus.is_complete(investigation_id):
            break
        await asyncio.sleep(0.5)  # Poll interval
```

**Why SSE over WebSocket:** The data flow is unidirectional (server -> client). SSE runs over standard HTTP, supports `Last-Event-ID` for connection recovery, and FastAPI has native support since 0.115+. WebSocket adds bidirectional complexity we do not need. The pipeline does not accept commands mid-execution.

**Why SSE over polling:** A pipeline run touches 6 phases, each with sub-progress (e.g., "extracting article 15/42"). Polling at 1-second intervals would generate 300+ unnecessary requests per investigation. SSE pushes only when there is new data.

#### Facts

```
GET    /api/v1/investigations/{id}/facts                -- Paginated fact list
GET    /api/v1/investigations/{id}/facts/{fact_id}      -- Single fact detail
GET    /api/v1/investigations/{id}/facts/stats           -- Fact statistics
```

#### Classifications

```
GET    /api/v1/investigations/{id}/classifications       -- All classifications
GET    /api/v1/investigations/{id}/classifications/stats -- Classification stats
GET    /api/v1/investigations/{id}/classifications/dubious -- Dubious facts only
```

#### Verifications

```
GET    /api/v1/investigations/{id}/verifications          -- All verification results
GET    /api/v1/investigations/{id}/verifications/pending  -- Pending human review
POST   /api/v1/investigations/{id}/verifications/{fact_id}/review -- Mark reviewed
```

#### Reports

```
GET    /api/v1/investigations/{id}/report                -- Latest report (JSON with markdown)
GET    /api/v1/investigations/{id}/report/html            -- Rendered HTML report
POST   /api/v1/investigations/{id}/report/regenerate      -- Trigger re-analysis
GET    /api/v1/investigations/{id}/report/versions        -- Version history
```

### Pydantic Response Models

The existing Pydantic schemas in `osint_system/analysis/schemas.py` and `osint_system/data_management/schemas/` are directly usable as FastAPI response models. This is a significant architectural advantage -- the backend already speaks Pydantic.

Key models to expose:
- `AnalysisSynthesis` -> report response
- `FactClassification` (from `data_management/schemas/`) -> classification response
- `VerificationResultRecord` (from `verification_schema.py`) -> verification response
- New: `InvestigationSummary`, `PipelineStatus`, `InvestigationRequest`

---

## 4. Event Bus for Pipeline Progress

### New Component: PipelineEventBus

The `InvestigationRunner` currently prints progress to Rich console. It needs to emit structured events that the SSE endpoint can consume.

```python
class PipelineEvent:
    id: int                    # Auto-incrementing, used for Last-Event-ID
    investigation_id: str
    event_type: str            # phase_started, phase_progress, phase_completed, etc.
    payload: dict[str, Any]
    timestamp: datetime

class PipelineEventBus:
    """In-memory event buffer for pipeline progress streaming.

    Events are stored per-investigation with an auto-incrementing ID.
    The SSE endpoint reads events by ID for resumable streaming.
    Events are pruned after pipeline completion + TTL.
    """

    async def emit(self, investigation_id: str, event_type: str, payload: dict) -> int:
        """Emit an event. Returns the event ID."""

    async def get_events_since(self, investigation_id: str, after_id: int) -> list[PipelineEvent]:
        """Get all events after a given ID. Non-blocking."""

    async def is_complete(self, investigation_id: str) -> bool:
        """Check if pipeline has emitted a terminal event."""
```

**Integration with InvestigationRunner:** The runner receives an `event_bus` reference and calls `await self.event_bus.emit(...)` at each phase boundary and at progress intervals within phases.

The event bus is in-memory only. Pipeline progress is ephemeral -- no value in persisting it to disk. If the server restarts mid-pipeline, the pipeline itself is lost (process-bound), so the events are moot.

---

## 5. Storage Migration: JSON -> SQLite

### Why SQLite (Not Postgres)

This is a single-user personal research tool. SQLite is the correct choice:
- Zero infrastructure (no server process)
- Single-file database (portable, backupable)
- WAL mode handles concurrent reads + single writer (the pipeline)
- `aiosqlite` provides async interface for FastAPI compatibility
- Performance ceiling far exceeds this use case (hundreds of investigations, thousands of facts)

PostgreSQL is overkill and would require a running server process -- unacceptable for a personal tool.

### Migration Strategy: Adapter Pattern

The stores already have clean async interfaces. The migration preserves these interfaces while swapping the storage backend.

```
BEFORE:                          AFTER:
FactStore                        FactStore
  ._storage: dict               ._db: aiosqlite.Connection
  ._fact_index: dict             (indexes are SQL indexes)
  ._hash_index: dict             (indexes are SQL indexes)
  ._lock: asyncio.Lock           (SQLite WAL handles concurrency)
  ._save_to_file()               (implicit -- writes go to DB)
  ._load_from_file()             (implicit -- reads come from DB)
```

**Schema design for facts table:**

```sql
CREATE TABLE facts (
    fact_id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL,
    content_hash TEXT,
    claim_text TEXT,
    data JSON NOT NULL,          -- Full fact dict as JSON blob
    stored_at TEXT NOT NULL,
    FOREIGN KEY (investigation_id) REFERENCES investigations(id)
);

CREATE INDEX idx_facts_investigation ON facts(investigation_id);
CREATE INDEX idx_facts_hash ON facts(content_hash);
```

**Why JSON column for data:** The fact structure is complex and varies (provenance, claim sub-objects, variants). Decomposing it into fully normalized columns provides no query benefit for this use case. Store the full dict as a JSON blob, index the fields we actually query on (`investigation_id`, `content_hash`, `fact_id`).

**Migration script:** Read existing `data/<inv_id>/*.json` files, insert into SQLite tables. This is a one-time batch operation.

### Store Interface Contract (Preserved)

```python
# These signatures DO NOT CHANGE:
async def save_facts(self, investigation_id: str, facts: list[dict], ...) -> dict
async def get_fact(self, investigation_id: str, fact_id: str) -> dict | None
async def retrieve_by_investigation(self, investigation_id: str, ...) -> dict
async def get_facts_by_hash(self, content_hash: str, ...) -> list[dict]
async def get_stats(self, investigation_id: str) -> dict
async def list_investigations(self) -> list[dict]
```

Pipeline code, analysis code, and agent code continue to call the same methods. Only the store internals change.

### New Table: Investigations Registry

Currently there is no first-class "investigation" entity -- the investigation_id is just a key in each store's dict. Add:

```sql
CREATE TABLE investigations (
    id TEXT PRIMARY KEY,
    objective TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, crawling, extracting, ..., completed, failed
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    stats JSON                               -- Summary stats updated at each phase
);
```

This enables:
- Listing investigations with their current status
- Tracking pipeline progress per-investigation
- Frontend showing investigation lifecycle

---

## 6. Frontend Architecture

### Next.js Configuration

- **App Router** (not Pages Router) -- current standard, supports React Server Components
- **TypeScript** -- mandatory for type-safe API integration
- **shadcn/ui** -- not a dependency, copies components into your tree. Zero runtime overhead.
- **TanStack Query** (React Query) -- server state management for API data

### State Management Split

| Data | Where It Lives | Why |
|------|---------------|-----|
| Investigation list | Server (TanStack Query cache) | Changes rarely, needs fresh data |
| Pipeline progress | SSE subscription (EventSource) | Real-time, server-pushed |
| Report content | Server (TanStack Query cache) | Large, immutable once generated |
| Fact list + filters | Server (TanStack Query cache) | Paginated, server-filtered |
| UI state (tabs, filters, modals) | React state (useState) | Ephemeral, client-only |
| Theme preference | localStorage | Persists across sessions |

**No Redux. No Zustand.** TanStack Query handles all server state. React state handles UI state. For a single-user read-heavy dashboard, this is sufficient. Adding a client-side state management library is premature complexity.

### Key Frontend Components

```
app/
  layout.tsx                   -- Root layout with sidebar nav
  page.tsx                     -- Investigation list (dashboard home)
  investigations/
    [id]/
      page.tsx                 -- Investigation detail (pipeline status, stats)
      facts/
        page.tsx               -- Fact browser with filters
      report/
        page.tsx               -- Report viewer (rendered markdown)
      progress/
        page.tsx               -- Pipeline progress (SSE-driven)
```

### SSE Integration on Frontend

```typescript
// hooks/use-pipeline-stream.ts
export function usePipelineStream(investigationId: string) {
  const [events, setEvents] = useState<PipelineEvent[]>([]);
  const [phase, setPhase] = useState<string>("pending");

  useEffect(() => {
    const source = new EventSource(`/api/v1/stream/${investigationId}`);

    source.addEventListener("phase_started", (e) => {
      const data = JSON.parse(e.data);
      setPhase(data.phase);
      setEvents(prev => [...prev, { type: "phase_started", ...data }]);
    });

    source.addEventListener("phase_progress", (e) => {
      const data = JSON.parse(e.data);
      setEvents(prev => [...prev, { type: "phase_progress", ...data }]);
    });

    source.addEventListener("pipeline_completed", () => {
      source.close();
    });

    return () => source.close();
  }, [investigationId]);

  return { events, phase };
}
```

### Type Safety: OpenAPI -> TypeScript

```
FastAPI Pydantic models
        |
        v
  /openapi.json  (auto-generated by FastAPI)
        |
        v
  @hey-api/openapi-ts  (generates TypeScript client)
        |
        v
  packages/api-client/  (generated TS types + fetch functions)
        |
        v
  Next.js imports typed client
```

**Build step:** `npx @hey-api/openapi-ts --input http://localhost:8000/openapi.json --output packages/api-client/`

This eliminates all manual type duplication. When a Pydantic model changes, regenerate the client. Type errors surface at build time.

---

## 7. Monorepo Structure

```
osint_double/
  |
  |-- backend/                        <-- Renamed from osint_system/
  |   |-- osint_system/               <-- Python package (unchanged internally)
  |   |   |-- agents/
  |   |   |-- analysis/
  |   |   |-- api/                    <-- NEW: FastAPI REST + SSE endpoints
  |   |   |   |-- __init__.py
  |   |   |   |-- app.py              <-- FastAPI app factory (replaces dashboard/app.py)
  |   |   |   |-- routes/
  |   |   |   |   |-- investigations.py
  |   |   |   |   |-- facts.py
  |   |   |   |   |-- classifications.py
  |   |   |   |   |-- verifications.py
  |   |   |   |   |-- reports.py
  |   |   |   |   |-- stream.py       <-- SSE endpoint
  |   |   |   |-- schemas.py          <-- API-specific request/response models
  |   |   |   |-- dependencies.py     <-- FastAPI dependency injection
  |   |   |   |-- event_bus.py        <-- Pipeline event bus
  |   |   |-- cli/
  |   |   |-- config/
  |   |   |-- dashboard/              <-- DEPRECATED: Remove after frontend is live
  |   |   |-- data_management/
  |   |   |-- pipeline/
  |   |   |-- pipelines/
  |   |   |-- reporting/
  |   |   |-- runner.py               <-- MODIFIED: Emits events to event bus
  |   |   |-- serve.py                <-- MODIFIED: Serves API instead of dashboard
  |   |-- tests/
  |   |-- pyproject.toml              <-- Python project config (replaces requirements.txt)
  |   |-- data/                       <-- SQLite DB + migration scripts
  |
  |-- frontend/                       <-- NEW: Next.js app
  |   |-- src/
  |   |   |-- app/                    <-- App Router pages
  |   |   |-- components/             <-- shadcn/ui components
  |   |   |-- hooks/                  <-- Custom hooks (usePipelineStream, etc.)
  |   |   |-- lib/                    <-- API client, utilities
  |   |-- package.json
  |   |-- tsconfig.json
  |   |-- next.config.ts
  |
  |-- packages/                       <-- Shared packages (monorepo)
  |   |-- api-client/                 <-- Generated TypeScript API client
  |   |   |-- src/
  |   |   |-- package.json
  |
  |-- .env                            <-- Shared env vars
  |-- package.json                    <-- Root workspace config (pnpm)
  |-- pnpm-workspace.yaml
  |-- Makefile                        <-- Unified dev commands
```

### Why NOT Move osint_system to backend/osint_system

**Correction:** Actually, moving the Python package under `backend/` is cleaner but requires updating all import paths and the `pyproject.toml` package discovery. The simpler approach: keep `osint_system/` at the repo root, add `frontend/` alongside it.

```
osint_double/
  |-- osint_system/                   <-- UNCHANGED location
  |-- frontend/                       <-- NEW
  |-- packages/api-client/            <-- NEW (generated)
  |-- tests/                          <-- UNCHANGED
  |-- data/                           <-- UNCHANGED (SQLite replaces JSON)
  |-- pyproject.toml
  |-- package.json                    <-- Root workspace
  |-- pnpm-workspace.yaml
  |-- Makefile
```

This avoids the import path upheaval. The tradeoff is a slightly flatter root, which is acceptable for a single-person project.

### Development Commands

```makefile
# Makefile
.PHONY: dev api frontend client

dev: api frontend          ## Start both backend and frontend

api:                       ## Start FastAPI dev server
	cd osint_system && uv run uvicorn api.app:create_app --factory --reload --port 8000

frontend:                  ## Start Next.js dev server
	cd frontend && pnpm dev

client:                    ## Regenerate TypeScript API client from OpenAPI spec
	cd packages/api-client && npx @hey-api/openapi-ts \
		--input http://localhost:8000/openapi.json \
		--output src/

migrate:                   ## Run JSON -> SQLite migration
	uv run python -m osint_system.data_management.migrate
```

### Next.js Proxy Configuration

During development, Next.js dev server proxies API calls to FastAPI:

```typescript
// frontend/next.config.ts
const nextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://localhost:8000/api/:path*',
      },
    ];
  },
};
```

In production (if ever deployed), this would be handled by a reverse proxy (nginx/caddy). For a personal tool, the dev proxy is likely permanent.

---

## 8. Data Flow: Investigation Lifecycle

### Sequence: New Investigation

```
Frontend                    FastAPI                     InvestigationRunner
   |                           |                              |
   |-- POST /investigations -->|                              |
   |                           |-- Create DB record           |
   |                           |-- Spawn background task ---->|
   |<- 201 {id, stream_url} --|                              |
   |                           |                              |
   |-- GET /stream/{id} ----->|                              |
   |                           |                              |-- Phase 1: Crawling
   |<-- SSE: phase_started ---|<-- event_bus.emit() ---------|
   |<-- SSE: phase_progress --|<-- event_bus.emit() ---------|
   |<-- SSE: phase_completed -|<-- event_bus.emit() ---------|
   |                           |                              |-- Phase 2: Extraction
   |<-- SSE: phase_started ---|<-- event_bus.emit() ---------|
   |   ...                     |   ...                        |   ...
   |<-- SSE: pipeline_done ---|<-- event_bus.emit() ---------|
   |                           |                              |
   |-- GET /investigations/{id} ->|                           |
   |<- {status: completed, stats} |                           |
   |                           |                              |
   |-- GET /report/{id} ----->|                              |
   |<- {markdown, synthesis}  |                              |
```

### Frontend State Transitions

```
[No Investigation] -> [Creating...] -> [Pipeline Running] -> [Completed]
                                            |
                                            |-- SSE connected
                                            |-- Progress bar per phase
                                            |-- Live stats update
                                            |
                                        [Failed]
                                            |-- Error message
                                            |-- Retry button
```

---

## 9. CORS Configuration

The FastAPI backend must allow requests from the Next.js dev server:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Next.js dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

With the Next.js rewrite proxy, CORS is not strictly needed in development (requests appear same-origin). But configure it anyway for direct API access during debugging.

---

## 10. Build Order (Phase Structure Recommendation)

This is the critical output for roadmap creation. Dependencies dictate ordering.

### Phase 1: API Layer + Investigation Registry

**What:** Create FastAPI REST API with JSON responses. Add investigations table/registry. Wire POST /investigations to spawn `InvestigationRunner` as background task.

**Why first:** Everything else depends on having an API to call. The frontend cannot exist without endpoints. The SSE stream cannot exist without a running pipeline to observe.

**Deliverables:**
- `osint_system/api/` module with app factory, routes, schemas
- Investigation registry (SQLite table or in-memory for now)
- POST /investigations -> background task pipeline
- GET /investigations, GET /investigations/{id}
- GET endpoints for facts, classifications, verifications, reports
- CORS middleware
- OpenAPI spec auto-generated

**Does NOT require:** Frontend, SQLite migration, SSE

**Testable via:** curl, httpie, FastAPI's /docs Swagger UI

### Phase 2: Pipeline Event Bus + SSE

**What:** Add PipelineEventBus. Modify InvestigationRunner to emit events. Create SSE endpoint.

**Why second:** The API must exist to mount the SSE endpoint on. The runner must be callable from the API (Phase 1) before we can add event emission.

**Deliverables:**
- PipelineEventBus class (in-memory)
- InvestigationRunner modifications to emit events at each phase
- GET /stream/{id} SSE endpoint
- Event types: phase_started, phase_progress, phase_completed, pipeline_completed, pipeline_error

**Testable via:** curl with SSE (`curl -N`), EventSource in browser console

### Phase 3: SQLite Storage Migration

**What:** Replace in-memory dict + JSON persistence with SQLite via aiosqlite. Migrate existing data.

**Why third:** The API and SSE work with the existing stores. Storage migration is an internal refactor that does not change any external interface. Doing it now (rather than first) means Phases 1-2 can be built and tested against the existing working stores.

**Deliverables:**
- SQLite schema (investigations, articles, facts, classifications, verifications, reports)
- aiosqlite-backed store implementations (same async interface)
- Migration script: read `data/<inv_id>/*.json` -> insert into SQLite
- Tests verifying interface parity between old and new stores

**Risk:** This is the most mechanically tedious phase. Five stores to migrate. Recommend migrating one at a time (FactStore first as it has the most complex indexes) and running existing tests after each.

### Phase 4: Next.js Frontend Shell

**What:** Create Next.js project with App Router, shadcn/ui, TanStack Query. Build pages for investigation list, detail, and pipeline progress. Generate TypeScript API client.

**Why fourth:** All backend infrastructure must exist before the frontend can consume it. The API (Phase 1), SSE (Phase 2), and stable storage (Phase 3) must all be working.

**Deliverables:**
- Next.js project in `frontend/`
- Generated API client in `packages/api-client/`
- Pages: investigation list, investigation detail, pipeline progress (SSE)
- Components: investigation card, pipeline progress bar, phase indicator
- Proxy configuration in next.config.ts
- Makefile for unified dev experience

### Phase 5: Frontend Feature Completion

**What:** Build remaining frontend features: fact browser, report viewer, classification/verification views.

**Why last:** These are presentation-layer features that depend on all backend APIs being stable. They can be built incrementally.

**Deliverables:**
- Fact browser with filtering, sorting, pagination
- Report viewer (markdown rendering)
- Classification view with dubious flag breakdown
- Verification view with human review UI
- Dashboard summary cards with aggregated stats

### Phase Dependency Graph

```
Phase 1 (API Layer)
    |
    v
Phase 2 (Event Bus + SSE)     Phase 3 (SQLite Migration)
    |                               |
    +-------------------------------+
    |
    v
Phase 4 (Frontend Shell)
    |
    v
Phase 5 (Frontend Features)
```

Note: Phases 2 and 3 are independent of each other and could theoretically be parallelized, but sequential execution is recommended for a single developer to avoid context switching.

---

## 11. Components: New vs Modified vs Unchanged

### New Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `api/app.py` | `osint_system/api/` | FastAPI app factory for JSON API |
| `api/routes/*.py` | `osint_system/api/routes/` | REST + SSE endpoints |
| `api/schemas.py` | `osint_system/api/` | Request/response Pydantic models |
| `api/dependencies.py` | `osint_system/api/` | FastAPI dependency injection |
| `api/event_bus.py` | `osint_system/api/` | Pipeline progress event bus |
| `frontend/` | repo root | Entire Next.js application |
| `packages/api-client/` | repo root | Generated TypeScript API client |
| `data/osint.db` | `data/` | SQLite database file |
| Migration script | `osint_system/data_management/` | JSON -> SQLite migrator |

### Modified Components

| Component | Change |
|-----------|--------|
| `InvestigationRunner` | Accept event_bus, emit events at phase boundaries |
| `FactStore` | Replace dict storage with aiosqlite |
| `ArticleStore` | Replace dict storage with aiosqlite |
| `ClassificationStore` | Replace dict storage with aiosqlite |
| `VerificationStore` | Replace dict storage with aiosqlite |
| `ReportStore` | Replace dict storage with aiosqlite |
| `serve.py` | Serve API app instead of dashboard app |

### Unchanged Components

| Component | Why Unchanged |
|-----------|---------------|
| All agents (extraction, classification, verification, analysis) | Store interface preserved |
| All pipelines (extraction, verification, graph, analysis) | Store interface preserved |
| Synthesizer | Consumes InvestigationSnapshot, unchanged |
| ReportGenerator | Generates markdown from AnalysisSynthesis, unchanged |
| Config modules | No changes needed |
| CLI (`cli/main.py`) | Still works for direct pipeline invocation |

### Deprecated Components

| Component | Replaced By |
|-----------|-------------|
| `dashboard/` (HTMX templates) | Next.js frontend |
| `dashboard/routes/` | `api/routes/` |
| `dashboard/templates/` | Next.js pages |
| `dashboard/static/` | Next.js static assets |

The `dashboard/` module should be kept temporarily during transition and removed once the Next.js frontend is verified complete.

---

## 12. Anti-Patterns to Avoid

### Anti-Pattern 1: GraphQL

Do not introduce GraphQL. The data access patterns are straightforward CRUD with some filtering. GraphQL adds schema definition overhead, resolver complexity, and N+1 query risks for zero benefit. REST + OpenAPI type generation provides the same type safety with less tooling.

### Anti-Pattern 2: WebSocket for Pipeline Progress

WebSocket is bidirectional. Pipeline progress is unidirectional (server -> client). WebSocket requires connection upgrade, heartbeat management, and reconnection logic that SSE handles natively. SSE also works through most proxies without configuration.

### Anti-Pattern 3: Frontend Data Transformation

Do not fetch raw data and transform it on the frontend. The backend has all the data and should compute summaries, aggregations, and filtered views. The frontend renders what the API returns.

### Anti-Pattern 4: Premature Database Abstraction

Do not introduce SQLAlchemy ORM with models, migrations, alembic, etc. The stores already have a clean interface. Use `aiosqlite` directly with raw SQL. The schema is simple (6 tables). An ORM layer would add configuration complexity with no benefit at this scale.

### Anti-Pattern 5: Microservice Split

Do not separate the API and the pipeline runner into different processes/services. They share in-memory stores (during transition) and the event bus. A single process with background tasks is the correct architecture for a single-user tool.

---

## Sources

- FastAPI SSE documentation: [fastapi.tiangolo.com/tutorial/server-sent-events](https://fastapi.tiangolo.com/tutorial/server-sent-events/)
- Full-stack type safety with hey-api: [abhayramesh.com/blog/type-safe-fullstack](https://abhayramesh.com/blog/type-safe-fullstack)
- FastAPI + Next.js monorepo patterns: [vintasoftware.com/blog/nextjs-fastapi-monorepo](https://www.vintasoftware.com/blog/nextjs-fastapi-monorepo)
- aiosqlite: [github.com/omnilib/aiosqlite](https://github.com/omnilib/aiosqlite)
- SSE for long-running tasks: [blog.nigelsim.org/2026-03-17-long-running-http-calls-using-sse](https://blog.nigelsim.org/2026-03-17-long-running-http-calls-using-sse/)
- Direct codebase analysis of all store classes, runner, pipeline, and dashboard modules
