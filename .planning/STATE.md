# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-20)

**Core value:** Automated, accurate extraction and verification of geopolitical facts from diverse open sources with intelligent multi-agent collaboration.
**Current focus:** Phase 13 — PostgreSQL + Memgraph Migration

## Current Position

Phase: 13 of 17 (PostgreSQL + Memgraph Migration)
Plan: 6 of 7
Status: In progress
Last activity: 2026-03-22 — Completed 13-06-PLAN.md (Embedding Service)

Progress: [████████████░░░░░░░░] 59/TBD plans (v1.0 complete, v2.0: 14 plans done)

## Performance Metrics

**v1.0 Velocity:**
- Total plans completed: 45
- Average duration: 17.9 min
- Total execution time: 804 min

**v2.0:**
- Total plans completed: 14
- Average duration: 4.4 min
- Total execution time: 61.2 min

## Accumulated Context

### Decisions

See PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Next.js + shadcn/ui selected for frontend (over continuing HTMX)
- SSE over WebSocket for pipeline progress (unidirectional push)
- SQLite over PostgreSQL (single-user, zero-infrastructure)
- OpenAPI codegen for type safety (Pydantic -> @hey-api/openapi-ts -> TypeScript)
- [D12-01-01] API schemas fully decoupled from internal pipeline models (zero imports)
- [D12-01-02] Event bus uses synchronous emit (GIL-protected, no asyncio.Lock needed for single event loop)
- [D12-01-03] Valid transition graph enforced in registry with ConflictError for violations
- [D12-02-01] Pipeline wrapper calls runner phases individually for event emission and cancellation
- [D12-02-02] SSE uses raw_data field to prevent double JSON serialization by FastAPI
- [D12-02-03] Regenerate bypasses transition graph under lock (COMPLETED->RUNNING is special case)
- [D12-03-01] Dual store resolution: investigation_stores dict with app.state direct fallback
- [D12-03-02] Graph adapter resolved from graph_adapters dict or pipeline._adapter
- [D12-04-01] Lifespan context manager for graceful shutdown (not deprecated on_event)
- [D13-01-01] expire_on_commit=False mandatory for async sessions (prevents MissingGreenlet)
- [D13-01-02] Dual driver pattern: asyncpg for queries, psycopg for pgvector type registration
- [D13-01-03] Models Base stub created in Plan 01 so migrations/env.py import resolves immediately
- [D13-06-01] Empty/whitespace input returns zero vector -- stores call embed() unconditionally

### Roadmap Evolution

- Phase 17 added: Crawler Agent Integration -- wire v1.0 crawler cohort (NewsfeedAgent, SocialMediaAgent, APICrawler, DocumentScraperAgent) into InvestigationRunner

### Deferred Issues

None.

### Blockers/Concerns

- ~~Playwright BrowserPool must replace per-request browser launches (OOM risk, CRITICAL)~~ RESOLVED in 11-01
- ~~LLM fallback chain produces malformed JSON (thinking tokens, enum mismatches)~~ RESOLVED in 11-02 (enum normalization added; JSON repair already existed)
- ~~Irrelevant facts (swimming results, beer releases) polluting reports~~ RESOLVED in 11-03 (objective-aware extraction prompt)
- Gemini 3.1 Flash Lite low fact yield (~4/article) -- per-model ExtractionMetrics now available for data-driven model selection (11-03)

## Session Continuity

Last session: 2026-03-22
Stopped at: Completed 13-06-PLAN.md (Embedding Service). Wave 2 complete.
Resume file: None
