# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-20)

**Core value:** Automated, accurate extraction and verification of geopolitical facts from diverse open sources with intelligent multi-agent collaboration.
**Current focus:** Phase 12 — API Layer & Pipeline Events

## Current Position

Phase: 12 of 17 (API Layer & Pipeline Events)
Plan: 1 of 4
Status: In progress
Last activity: 2026-03-21 — Completed 12-01-PLAN.md (API infrastructure: schemas, errors, event bus, registry)

Progress: [██████████░░░░░░░░░░] 50/TBD plans (v1.0 complete, v2.0: 5/8+ Phase 12 plan 1 done)

## Performance Metrics

**v1.0 Velocity:**
- Total plans completed: 45
- Average duration: 17.9 min
- Total execution time: 804 min

**v2.0:**
- Total plans completed: 5
- Average duration: 4.2 min
- Total execution time: 21.0 min

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

Last session: 2026-03-21
Stopped at: Completed 12-01-PLAN.md, ready to execute 12-02-PLAN.md
Resume file: None
