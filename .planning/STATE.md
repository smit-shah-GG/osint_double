# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-20)

**Core value:** Automated, accurate extraction and verification of geopolitical facts from diverse open sources with intelligent multi-agent collaboration.
**Current focus:** Phase 11 — Crawler Hardening & Pipeline Quality

## Current Position

Phase: 11 of 16 (Crawler Hardening & Pipeline Quality)
Plan: —
Status: Ready to plan
Last activity: 2026-03-21 — v2.0 roadmap created (6 phases, 52 requirements mapped)

Progress: [██████████░░░░░░░░░░] 45/TBD plans (v1.0 complete, v2.0 starting)

## Performance Metrics

**v1.0 Velocity:**
- Total plans completed: 45
- Average duration: 17.9 min
- Total execution time: 804 min

**v2.0:**
- Total plans completed: 0
- No data yet

## Accumulated Context

### Decisions

See PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Next.js + shadcn/ui selected for frontend (over continuing HTMX)
- SSE over WebSocket for pipeline progress (unidirectional push)
- SQLite over PostgreSQL (single-user, zero-infrastructure)
- OpenAPI codegen for type safety (Pydantic -> @hey-api/openapi-ts -> TypeScript)

### Deferred Issues

None.

### Blockers/Concerns

- Playwright BrowserPool must replace per-request browser launches (OOM risk, CRITICAL)
- LLM fallback chain produces malformed JSON (thinking tokens, enum mismatches)
- Gemini 3.1 Flash Lite low fact yield (~4/article) — model selection still unresolved

## Session Continuity

Last session: 2026-03-21
Stopped at: v2.0 roadmap created, ready to plan Phase 11
Resume file: None
