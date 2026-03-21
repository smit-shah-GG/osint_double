# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-20)

**Core value:** Automated, accurate extraction and verification of geopolitical facts from diverse open sources with intelligent multi-agent collaboration.
**Current focus:** Phase 11 — Crawler Hardening & Pipeline Quality

## Current Position

Phase: 11 of 17 (Crawler Hardening & Pipeline Quality)
Plan: 1 of 4
Status: In progress
Last activity: 2026-03-21 — Completed 11-01-PLAN.md (BrowserPool + stealth + Cloudflare detection)

Progress: [██████████░░░░░░░░░░] 46/TBD plans (v1.0 complete, v2.0: 1/4 Phase 11 plans done)

## Performance Metrics

**v1.0 Velocity:**
- Total plans completed: 45
- Average duration: 17.9 min
- Total execution time: 804 min

**v2.0:**
- Total plans completed: 1
- Average duration: 4 min
- Total execution time: 4 min

## Accumulated Context

### Decisions

See PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Next.js + shadcn/ui selected for frontend (over continuing HTMX)
- SSE over WebSocket for pipeline progress (unidirectional push)
- SQLite over PostgreSQL (single-user, zero-infrastructure)
- OpenAPI codegen for type safety (Pydantic -> @hey-api/openapi-ts -> TypeScript)

### Roadmap Evolution

- Phase 17 added: Crawler Agent Integration — wire v1.0 crawler cohort (NewsfeedAgent, SocialMediaAgent, APICrawler, DocumentScraperAgent) into InvestigationRunner

### Deferred Issues

None.

### Blockers/Concerns

- ~~Playwright BrowserPool must replace per-request browser launches (OOM risk, CRITICAL)~~ RESOLVED in 11-01
- LLM fallback chain produces malformed JSON (thinking tokens, enum mismatches)
- Gemini 3.1 Flash Lite low fact yield (~4/article) — model selection still unresolved

## Session Continuity

Last session: 2026-03-21
Stopped at: Completed 11-01-PLAN.md
Resume file: None
