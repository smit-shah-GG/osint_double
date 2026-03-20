# Project Research Summary

**Project:** OSINT Intelligence System v2.0
**Domain:** LLM-powered OSINT pipeline with Next.js dashboard frontend
**Researched:** 2026-03-20
**Confidence:** HIGH

---

## Executive Summary

This milestone replaces the existing HTMX read-only dashboard with a full Next.js + shadcn/ui frontend and simultaneously hardens the production pipeline: persistent SQLite storage, Playwright browser pool, and LLM fallback chain robustness. The codebase is in excellent shape architecturally — all five data stores already expose clean async interfaces, the runner's six-phase structure maps directly to a progress stream, and Pydantic schemas are already in place as FastAPI response models. The work is additive and integration-focused rather than a redesign.

The recommended approach is to build the API layer first (FastAPI JSON endpoints + event bus + SSE stream), migrate storage second, then layer the frontend on top of stable infrastructure. This order is non-negotiable: the frontend cannot be built until API contracts are stable, and API contracts cannot be stable until the storage backend is decided. The critical architectural choice — SSE over WebSockets for pipeline progress, REST + OpenAPI codegen for type safety, SQLite over PostgreSQL for single-user simplicity — is consistent across all four research documents and has HIGH confidence backing from official sources.

The dominant risk is not architectural but operational: Playwright memory exhaustion from per-request browser launches will OOM-kill the container during batch crawls, and LLM model fallbacks silently produce malformed JSON that Pydantic swallows as partial data loss. Both must be addressed in Phase 1 before any production workload runs through the system.

---

## Key Findings

### Recommended Stack

The v2.0 stack adds six new technology decisions on top of the existing Python pipeline. The frontend stack (Next.js 16 App Router + shadcn/ui + Sigma.js) is well-characterized with high source confidence. The backend additions (SQLAlchemy 2.0 async + aiosqlite + SSE via `sse-starlette`) integrate cleanly with the existing FastAPI and asyncio architecture. No existing core dependencies change, only one version pin update (Playwright `>=1.58.0`).

**Core new technologies:**
- **Next.js 16 + shadcn/ui + TypeScript**: Frontend — App Router for SSR, shadcn component copies for zero runtime overhead, TypeScript to catch API schema drift at build time
- **@react-sigma/core v5 + graphology**: Knowledge graph — WebGL rendering handles 50K+ nodes; ForceAtlas2 layout in Web Worker offloads O(n^2) from main thread; data model mirrors NetworkX JSON export format directly
- **SSE (EventSourceResponse)**: Pipeline progress — unidirectional push fits the one-way server-to-client model; built-in reconnection via `Last-Event-ID`; WebSocket is rejected as overkill
- **SQLAlchemy 2.0 async + Alembic + aiosqlite**: Persistent storage — ORM preserves existing store interface contracts, Alembic handles schema evolution, aiosqlite bridges sqlite3 to asyncio; PostgreSQL explicitly rejected for single-user use
- **@hey-api/openapi-ts**: Type safety — generates TypeScript client from FastAPI's auto-generated OpenAPI spec; eliminates manual type duplication between Python and TypeScript
- **fake-useragent 2.2.0**: Crawler hardening — user-agent rotation for public sources; proxy rotation rejected as cost-disproportionate for personal-use volume
- **Docker Compose v2**: Deployment — two containers (Python backend on port 8000, Next.js frontend on port 3000); no Kubernetes, no Redis, no process managers beyond Docker's own restart policies

**Explicitly rejected:** PostgreSQL, WebSockets, tRPC, GraphQL, NextAuth, Kubernetes, Redis, D3.js, Cytoscape.js, Prisma, pm2, proxy rotation services.

### Expected Features

The feature set is driven directly by what the existing pipeline already produces — the frontend exposes, not augments, the backend's data. Five feature areas constitute the MVP. Two are post-MVP by explicit research recommendation.

**Must have (MVP):**
- Investigation launch UI: objective input, model selection, source tier toggles, launch with disable-during-execution — triggers `POST /api/v1/investigations`
- Live progress dashboard: 6-stage pipeline indicator, SSE-driven stats cards, elapsed time per phase, error display on mid-pipeline failures
- Report viewer: rendered Markdown with collapsible sections, confidence badges, version selector, fact drill-down from key judgments (the single highest-analytical-value feature)
- Investigation history: list, status badge, delete, report link, export trigger (exporter/archiver already exist)
- Knowledge graph visualization: force-directed layout, node/edge type color coding, edge filtering, entity-centric neighborhood exploration, node-count cap at 200-300

**Should have (differentiators, post-MVP):**
- Source management UI: authority score editing, feed health monitoring, add/remove custom feeds
- Configuration profiles: named save/load profiles mapping to `AnalysisConfig` fields, cost estimation per profile
- Alternative hypothesis comparison panel, contradiction highlights with resolution status
- Side-by-side investigation comparison, investigation tagging

**Defer (v2+):**
- Report diff between versions (high complexity text diffing, low frequency need)
- Cost estimation preview (requires maintaining model pricing that changes frequently)
- Full-text search across investigations (index overhead, marginal utility under 100 investigations)
- Investigation forking, multi-user sharing, plugin/extension system

**Critical backend gaps for MVP:** Seven API endpoints do not yet exist. The most blocking are `POST /api/v1/investigations` (pipeline launch), the SSE stream endpoint, and `GET /api/v1/investigations/{id}/report` returning JSON (currently only HTMX HTML). See FEATURES.md backend dependency table for the full list.

### Architecture Approach

The architecture is a clean frontend/backend split: Next.js is a pure presentation layer with no business logic, FastAPI owns all computation, SQLite is the persistence layer. The existing store interfaces are preserved verbatim — migration is an internal swap (dict + JSON -> aiosqlite) behind the same async method signatures, meaning all agent, pipeline, and analysis code is untouched. A new `PipelineEventBus` (in-memory, no persistence needed) bridges the runner's phase transitions to the SSE endpoint. Type safety flows `Pydantic models -> FastAPI OpenAPI spec -> @hey-api/openapi-ts -> TypeScript client`, with no manual type maintenance.

**Major components:**
1. **FastAPI API module** (`osint_system/api/`) — New; replaces `dashboard/` HTMX routes with JSON REST endpoints + SSE stream; OpenAPI spec is automatic from Pydantic response models
2. **PipelineEventBus** — New in-memory component; `InvestigationRunner` emits events at each phase boundary; SSE endpoint polls the bus and yields to `EventSourceResponse`
3. **SQLite store adapters** — Modified internals of five existing stores; interface contract unchanged; WAL mode for concurrent reads; Alembic for schema migrations
4. **Next.js frontend** — New `frontend/` directory; App Router; TanStack Query for server state; `EventSource` hook for SSE; `@react-sigma/core` for graph; generated API client from `packages/api-client/`
5. **Investigations registry table** — New SQLite table; first-class investigation entity with status enum; enables pipeline lifecycle tracking and frontend listing

**Data flow (new investigation):** `POST /investigations` -> creates DB record + spawns `asyncio.create_task(run_pipeline)` -> runner emits events -> SSE endpoint yields to frontend -> frontend transitions through states -> `GET /report/{id}` fetches final output.

**Unchanged:** All agents (extraction, classification, verification, analysis), all pipelines, synthesizer, report generator, config modules, CLI.

**Deprecated:** Entire `dashboard/` HTMX module — keep temporarily during transition, remove after frontend verification.

### Critical Pitfalls

1. **Playwright per-request browser launch (C1, CRITICAL)** — Each `_playwright_fetch()` call currently spawns a full Chromium instance (150-300 MB RAM). Batches of 20 articles trigger 20 concurrent processes, causing OOM kills. Implement `BrowserPool` with a single persistent browser and lightweight context pool (max 3 concurrent contexts, ~2 MB each). This is the highest-severity issue and must be the first code change in the crawler hardening phase.

2. **LLM fallback JSON schema breakage (C4, CRITICAL)** — DeepSeek R1 emits `<think>...</think>` tokens before JSON output; Hermes 405B has no native structured output enforcement; OpenRouter `response_format.type: "json_schema"` is silently ignored by some providers. The existing `claim_type: "statement"` bug is a known instance. Strip thinking tokens pre-parse with `re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL)`, normalize enum values post-extraction, log the actual model used per request, test each fallback model explicitly.

3. **Async lock semantics in store migration (C5, CRITICAL)** — Migrating stores from dicts to aiosqlite while keeping `asyncio.Lock()` serializes all DB access, eliminating concurrency. Removing the lock causes race conditions. Solution: replace application-level locks with SQLite WAL mode + database-level transactions. Enable `PRAGMA journal_mode=WAL` on connection init. Migrate one store at a time and run existing tests after each.

4. **Cloudflare AI Labyrinth serving honeypot content (C2, CRITICAL)** — Since March 2025, Cloudflare serves realistic fake content to detected bots instead of returning 403. The extraction pipeline has no mechanism to detect this. Add content validation: flag articles where URL depth exceeds 3 levels from seed, track fetch success rate changes per domain, and constrain crawling to specific provided URLs (no link following).

5. **Playwright sync/async API mixing causes deadlock (C3, CRITICAL)** — Any `from playwright.sync_api` import in an asyncio process causes non-deterministic deadlocks. The current codebase correctly uses `async_playwright`, but this is a latent risk for contributors. Add a pre-commit hook blocking `sync_playwright` imports and ban `nest_asyncio`.

**Moderate pitfalls worth immediate preventive action:**
- CORS: Use Next.js `rewrites` to proxy `/api/*` — eliminates the `localhost` vs `127.0.0.1` CORS origin mismatch
- API contract drift: Set up `@hey-api/openapi-ts` codegen before any UI components are built
- Next.js `NEXT_PUBLIC_*` variables: Never put secrets or environment-specific URLs in build-time variables; all LLM API keys stay backend-only
- Graph rendering: Commit to Sigma.js + Web Worker ForceAtlas2 before writing any graph UI; D3.js SVG rendering fails past 500 nodes
- `asyncio.Lock()` created in `__init__` before event loop starts (L3) — already exists in `FactStore.__init__`; will surface during store migration testing

---

## Implications for Roadmap

### Phase 1: API Layer + Crawler Hardening

**Rationale:** These are the two independent foundation tracks. The API layer must exist before anything frontend can be built. Crawler hardening must happen before any production batch runs (OOM risk). Neither depends on the other and they can proceed in parallel if desired, but the API layer is higher leverage for overall progress.

**Delivers:** `osint_system/api/` module with JSON REST endpoints (investigations, facts, classifications, verifications, reports), CORS middleware, OpenAPI spec auto-generated at `/openapi.json`. Plus: BrowserPool pattern replacing per-request browser launches, thinking token stripping, enum normalization in LLM response parsing, content validation layer for Cloudflare honeypot detection.

**Features addressed:** Investigation launch backend, investigation history backend, report viewer backend — all the API surface the frontend will consume.

**Pitfalls avoided:** C1 (OOM from browser launches), C2 (honeypot contamination), C3 (sync/async deadlock), C4 (LLM fallback JSON breakage), M1 (CORS), M2 (API contract drift setup via OpenAPI).

**Research flag:** STANDARD — REST API patterns with FastAPI are well-documented. The LLM fallback normalization may need a research spike if `instructor` library adoption is considered (MEDIUM confidence on that specific integration).

### Phase 2: Pipeline Event Bus + SSE

**Rationale:** Depends on Phase 1 (API module must exist to mount SSE endpoint). Can be built immediately after Phase 1's API module exists. The runner modification is low-risk (additive `event_bus.emit()` calls at existing phase boundaries).

**Delivers:** `PipelineEventBus` (in-memory), `InvestigationRunner` modified to emit structured events, `GET /api/v1/stream/{id}` SSE endpoint with `Last-Event-ID` reconnection support, `POST /api/v1/investigations` spawning pipeline as background task.

**Features addressed:** Live progress dashboard (pipeline stage indicator, stats cards, elapsed time, error display).

**Pitfalls avoided:** M3 (SSE proxy issues — add `X-Accel-Buffering: no` header from day one).

**Research flag:** STANDARD — FastAPI SSE patterns are well-documented and verified against official docs.

### Phase 3: SQLite Storage Migration

**Rationale:** Can run in parallel with Phase 2 (they touch different parts of the system). Storage migration must complete before Phase 4 (the frontend must not be built against stores that will change behavior). Recommended: sequential after Phase 2 to reduce context switching for a single developer.

**Delivers:** SQLAlchemy 2.0 async engine, aiosqlite adapter, six SQLite tables (investigations, articles, facts, classifications, verifications, reports), Alembic schema, WAL mode enabled, one-time JSON-to-SQLite migration script, `AbstractStore` protocol formalizing the interface, tests verifying interface parity.

**Features addressed:** Investigation history (status tracking, lifecycle), all data persistence moving from ephemeral JSON to durable SQLite.

**Pitfalls avoided:** C5 (lock semantics), L2 (Docker volume locking — use named Docker volumes for SQLite on macOS), L3 (asyncio.Lock created outside event loop — eliminated by replacing with DB transactions).

**Execution note:** Migrate one store at a time. FactStore first (most complex indexes). Run existing tests after each. Keep JSON persistence as backup with parallel-run validation before cutover.

**Research flag:** STANDARD — SQLAlchemy 2.0 async + aiosqlite patterns are well-documented. The incremental migration strategy is low-risk.

### Phase 4: Next.js Frontend Shell

**Rationale:** Depends on Phases 1, 2, 3 all being stable. The frontend should not be built against moving targets. Once the API is stable and storage is durable, frontend development is straightforward.

**Delivers:** Next.js 16 project in `frontend/`, shadcn/ui initialized, TanStack Query for server state, generated TypeScript API client via `@hey-api/openapi-ts`, Next.js rewrites proxy config (eliminates CORS), `usePipelineStream` hook for SSE, pages for investigation list and pipeline progress, root layout with sidebar navigation, Makefile for unified dev experience.

**Features addressed:** Investigation launch UI (table stakes), live progress dashboard (frontend), investigation history (list view).

**Pitfalls avoided:** M1 (CORS via Next.js rewrites), M2 (API contract drift via codegen), M6 (env var build-time bake-in — establish `NEXT_PUBLIC_*` convention before any env usage), L4 (Next.js fetch caching — establish `cache: 'no-store'` vs ISR patterns up front).

**Research flag:** STANDARD — Next.js App Router + shadcn/ui + TanStack Query patterns are well-documented.

### Phase 5: Report Viewer + Knowledge Graph

**Rationale:** High-value analytical features that are complex enough to deserve their own phase. Report viewer needs the full report data API to be stable (Phase 1). Graph needs the graph query endpoint and validated data (Phase 3). Both can be built concurrently within this phase.

**Delivers:** Report viewer with Markdown rendering, collapsible sections, IC confidence badges, version selector, fact drill-down from key judgments, alternative hypothesis panel, contradiction highlight view. Knowledge graph with Sigma.js + graphology, ForceAtlas2 layout in Web Worker, node/edge type color coding, edge filtering, entity-centric neighborhood exploration, node count cap at 200-300.

**Features addressed:** Report viewer (all table stakes + fact drill-down differentiator), knowledge graph (all table stakes + filtering differentiators).

**Pitfalls avoided:** M4 (graph rendering crash — commit to Sigma.js + Web Worker from the start, never D3 SVG).

**Research flag:** GRAPH NEEDS SPIKE — the NetworkX-to-graphology export pipeline (`QueryResult.to_dict()` -> node-link JSON -> `graphology.import()`) is architecturally sound but untested end-to-end. The ForceAtlas2 Web Worker integration with `@react-sigma/core` v5 may have rough edges in React component lifecycle. Plan for a 1-day spike before committing to this approach.

### Phase 6: Frontend Feature Completion + Deployment

**Rationale:** Remaining UI features (source management, configuration profiles, fact browser filters) and production deployment setup. These are lower priority than the core analytical views and can be delivered incrementally.

**Delivers:** Fact browser with filtering/sorting/pagination, source management UI with authority score display and feed health, configuration profile management, Docker Compose with multi-stage builds, Dockerfiles (backend + frontend), environment variable documentation, health check endpoints wired, deployment runbook.

**Features addressed:** Source management (table stakes), configuration profiles (table stakes), investigation delete, export UI.

**Pitfalls avoided:** M5 (Docker cache invalidation — copy deps before source), L6 (process supervision — Docker health checks + `restart: unless-stopped`).

**Research flag:** STANDARD for deployment. Source management requires a design decision: read-only config display vs user-editable authority scores (the latter needs a user-override store design).

### Phase Ordering Rationale

- **API before frontend**: The frontend has seven blocking backend dependencies that do not yet exist. Building UI before the API contracts are stable guarantees rework.
- **Crawler hardening in Phase 1**: C1 (Playwright OOM) is a production blocker that can corrupt any investigation run silently. It must be fixed before any batch processing is done in development.
- **Storage migration before frontend**: The stores change behavioral semantics (asyncio.Lock removal, WAL-mode concurrency). Frontend tests built against the old stores will produce misleading results.
- **Phases 2 and 3 decoupled**: The event bus touches the runner and API module; storage migration touches stores and data layer. They share no code. Either can go first.
- **Graph visualization last among features**: It has the longest unknown (NetworkX export pipeline) and the highest implementation complexity. It should not gate the rest of the frontend.

### Research Flags Summary

| Phase | Flag | Reason |
|-------|------|--------|
| Phase 1 | STANDARD | FastAPI REST patterns, LLM response normalization are documented |
| Phase 1 | SPIKE if using `instructor` | instructor + OpenRouter structured output integration — MEDIUM confidence |
| Phase 2 | STANDARD | FastAPI SSE official docs available |
| Phase 3 | STANDARD | SQLAlchemy 2.0 async + aiosqlite documented |
| Phase 4 | STANDARD | Next.js App Router + TanStack Query documented |
| Phase 5 | SPIKE on graph pipeline | NetworkX -> graphology export + ForceAtlas2 Web Worker in React needs 1-day validation spike |
| Phase 6 | STANDARD for deployment | Source management user-override store needs design decision |

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All technology choices verified on official package registries and docs. Version numbers confirmed. |
| Features | HIGH | Driven by direct codebase analysis of existing data schemas and pipeline structure. No speculation. |
| Architecture | HIGH | Based on direct codebase analysis of all store classes, runner, pipeline, and dashboard modules. Phase ordering validated by dependency analysis. |
| Pitfalls | HIGH | C1-C5 all cite specific GitHub issues, official documentation, or are direct observations of existing codebase bugs. |

**Overall confidence:** HIGH

### Gaps to Address

- **`instructor` library evaluation**: If adopted for structured output enforcement with automatic retries, its interaction with OpenRouter's provider variance needs a spike. Research is MEDIUM confidence on this specific integration. Decision: use it or stick with manual enum normalization + thinking-token stripping.
- **NetworkX -> graphology export pipeline**: The architecture is sound (both use node-link JSON format), but the actual `QueryResult.to_dict()` output format has not been validated against `graphology.import()` expectations. Validate in Phase 5 spike before committing to this approach.
- **SSE under nginx/Cloudflare**: Documented as M3. For a local personal tool this is not blocking, but if the tool is ever exposed remotely, `X-Accel-Buffering: no` and the polling fallback endpoint must be in place. Flag during Phase 6 deployment work.
- **SQLite WAL mode on macOS Docker volumes (L2)**: Linux host is unaffected. Document the named-volume requirement for macOS developers in the deployment runbook.
- **OpenRouter provider variance for structured output**: The exact behavior of `response_format.type: "json_schema"` per provider changes as OpenRouter adds/updates integrations. The normalization layer (enum mapping, thinking token stripping) must be maintained as new models are added to the fallback chain.

---

## Sources

### Primary (HIGH confidence)
- Official Playwright Python docs — async API, browser pool patterns, sync/async exclusivity
- FastAPI docs — SSE, CORS, background tasks, OpenAPI spec generation
- SQLAlchemy 2.0 docs — async engine, aiosqlite dialect, WAL mode
- Next.js 16 docs — App Router, rewrites proxy, environment variable build-time vs runtime behavior
- @hey-api/openapi-ts npm — OpenAPI -> TypeScript client generation
- @react-sigma/core npm (v5.0.6) — React wrapper for Sigma.js
- sigma.js official site — WebGL rendering performance characteristics
- DeepSeek R1 API docs — thinking token `<think>` output format
- OpenRouter official docs — provider variance, structured output support matrix
- Gemini API docs — `response_schema` token counting behavior
- Playwright GitHub issues #2511, #286, #462, #2705 — browser pool and async API footguns
- Direct codebase analysis — all store classes, runner.py, pipelines, dashboard module, schemas

### Secondary (MEDIUM confidence)
- ZenRows / ScrapFly — Cloudflare AI Labyrinth bypass documentation
- Vinta Software monorepo guide — Next.js + FastAPI monorepo patterns
- Type-safe fullstack guide (abhayramesh.com) — @hey-api/openapi-ts integration
- SSE production patterns (blog.greeden.me) — nginx buffering behavior
- Graph library benchmarks (PMC study, cylynx.io, memgraph.com) — Sigma.js vs alternatives
- SQLite vs PostgreSQL comparison (medium.com/pythonic-af) — single-user performance
- Docker Dockerfile best practices (devtoolbox.dedyn.io) — multi-stage build patterns

---

*Research completed: 2026-03-20*
*Ready for roadmap: yes*
