# Phase 12: API Layer & Pipeline Events - Context

**Gathered:** 2026-03-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Expose the backend as a complete JSON REST API with real-time SSE event streaming. The frontend (Phase 14) consumes these endpoints to launch investigations, monitor pipeline progress, and review results. No frontend code in this phase — API only.

</domain>

<decisions>
## Implementation Decisions

### API shape & versioning
- **URL prefix:** `/api/v1/` — versioned prefix for all endpoints
- **Response envelope:** Wrapped with metadata for list endpoints: `{"data": [...], "total": N, "page": 1, "page_size": 100}`
- **Default page size:** 100 items. Client can override with `?page_size=N`.
- **Error format:** RFC 7807 Problem Details — `{"type": "...", "title": "...", "status": 404, "detail": "...", "instance": "..."}`

### SSE event design
- **Event granularity:** Phase-level + aggregate counts. Events: `phase_started`, `phase_progress` (with article/fact/verification counts + elapsed_ms), `phase_completed`, `pipeline_completed`, `pipeline_error`. ~20-30 events per run.
- **Heartbeat:** 15-second interval, SSE comment line (`: heartbeat`)
- **Reconnection:** Full replay — store events in memory per investigation. On reconnect with `Last-Event-ID`, replay all missed events. Frontend sees no gaps.
- **Post-completion:** Connecting to a completed investigation's stream replays full event history then sends `pipeline_completed`. Frontend can reconstruct timeline.

### Pipeline launch contract
- **POST body:** Full control. Required: `objective` (string). Optional: `extraction_model`, `synthesis_model`, `max_sources`, `enable_verification` (bool), `enable_graph` (bool), `rss_feeds` (list override). All optional params have server defaults.
- **Response:** 202 Accepted. Full investigation entity + `stream_url`. Body: `{"id": "inv-abc", "objective": "...", "status": "running", "params": {...}, "created_at": "...", "stream_url": "/api/v1/investigations/inv-abc/stream"}`
- **Cancel:** `POST /api/v1/investigations/{id}/cancel` — sets status to `cancelled`, signals pipeline to stop gracefully. Keeps partial results.
- **Regenerate:** `POST /api/v1/investigations/{id}/regenerate` — re-runs synthesis/report with optional model override. Creates new report version. Keeps existing facts/verification.

### OpenAPI & codegen
- **Codegen tool:** `@hey-api/openapi-ts` — generates typed fetch functions from OpenAPI spec. Tree-shakeable, no runtime dependency.
- **Spec source:** Live at runtime via FastAPI auto-generated `/openapi.json`. Frontend codegen runs against the live endpoint.
- **Response models:** Separate API models in `api/schemas.py`. Decouples API response shape from internal pipeline schemas. Internal models (ExtractedFact, VerificationResult) are NOT used directly as API responses.
- **SSE in spec:** Stream endpoint documented in OpenAPI spec with event type descriptions.

### Claude's Discretion
- FastAPI router organization (single file vs per-resource modules)
- Event ID format for SSE (incrementing int vs UUID)
- In-memory event store implementation details
- Background task runner choice (FastAPI BackgroundTasks vs asyncio.create_task)
- CORS configuration for local development

</decisions>

<specifics>
## Specific Ideas

- Investigation parameters in launch body match current `InvestigationRunner` constructor params — `extraction_model`, `synthesis_model` map to OpenRouter MODEL_MAP keys
- SSE stream URL returned in POST response so frontend can connect immediately without polling
- Cancel endpoint uses graceful shutdown — pipeline checks a cancellation flag between phases
- Regenerate endpoint reuses existing stores (FactStore, ClassificationStore, VerificationStore) and only re-runs AnalysisPipeline
- RFC 7807 errors are a FastAPI plugin away — `fastapi-problem` or custom exception handlers

</specifics>

<deferred>
## Deferred Ideas

- Per-article granularity in SSE events — decided against for Phase 12, could add later if frontend needs finer progress
- Committed OpenAPI spec file with CI drift detection — live endpoint sufficient for now
- Authentication/API keys — single-user for v2.0, no auth needed
- Rate limiting on API — single-user, no rate limiting needed
- WebSocket alternative to SSE — SSE is correct for unidirectional push (decided in v2.0 planning)

</deferred>

---

*Phase: 12-api-layer-pipeline-events*
*Context gathered: 2026-03-21*
