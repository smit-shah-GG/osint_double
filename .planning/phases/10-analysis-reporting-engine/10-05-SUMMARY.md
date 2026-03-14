---
phase: 10-analysis-reporting-engine
plan: 05
subsystem: dashboard
tags: [fastapi, htmx, jinja2, dashboard, web-ui, monitoring, investigations]

requires:
  - phase: 10-analysis-reporting-engine
    plan: 01
    provides: FactStore, ClassificationStore, VerificationStore, AnalysisConfig
  - phase: 10-analysis-reporting-engine
    plan: 03
    provides: AnalysisPipeline for on-demand analysis
  - phase: 10-analysis-reporting-engine
    plan: 04
    provides: ReportStore, ReportGenerator for report viewing and generation

provides:
  - create_app: FastAPI application factory with store dependency injection
  - run_dashboard: CLI entry point for starting the dashboard server
  - 5 route modules: investigations, facts, reports, monitoring, API
  - Jinja2 HTML templates with HTMX partial page updates
  - Data-dense CSS stylesheet for analyst-oriented UI
  - JSON API endpoints for HTMX polling and partial swap

affects: []

tech-stack:
  added:
    - python-multipart (form data parsing for POST routes)
  patterns:
    - FastAPI application factory with app.state dependency injection
    - Jinja2Templates with modern TemplateResponse(request, name, context) API
    - HTMX for partial page updates (hx-get, hx-post, hx-trigger, hx-swap)
    - Per-investigation verification aggregation (no global stats method)
    - mistune for Markdown -> HTML conversion in report view

key-files:
  created:
    - osint_system/dashboard/__init__.py
    - osint_system/dashboard/app.py
    - osint_system/dashboard/routes/__init__.py
    - osint_system/dashboard/routes/investigations.py
    - osint_system/dashboard/routes/facts.py
    - osint_system/dashboard/routes/reports.py
    - osint_system/dashboard/routes/monitoring.py
    - osint_system/dashboard/routes/api.py
    - osint_system/dashboard/templates/base.html
    - osint_system/dashboard/templates/investigations/list.html
    - osint_system/dashboard/templates/investigations/detail.html
    - osint_system/dashboard/templates/facts/list.html
    - osint_system/dashboard/templates/reports/view.html
    - osint_system/dashboard/templates/monitoring/status.html
    - osint_system/dashboard/static/styles.css
    - tests/dashboard/__init__.py
    - tests/dashboard/test_app.py
    - tests/dashboard/test_routes.py
    - tests/dashboard/test_templates.py
  modified:
    - requirements.txt

key-decisions:
  - "Modern TemplateResponse(request, name, context) API to avoid deprecation warnings"
  - "Per-investigation verification aggregation: iterate fact_store.list_investigations() and call verification_store.get_stats() per investigation (VerificationStore has no global stats method)"
  - "mistune.html() for Markdown->HTML conversion in reports view route"
  - "HTMX hx-trigger='every 10s' for monitoring auto-refresh"
  - "POST /reports/{id}/generate delegates to AnalysisPipeline.run_analysis() which auto-generates reports"
  - "Graceful handling of nonexistent investigations (empty data, not 404)"

patterns-established:
  - "create_app() factory with store injection on app.state"
  - "HTMX auto-refresh via hx-trigger='every 10s' on monitoring table"
  - "Filter controls via hx-get with hx-include for query parameter forwarding"
  - "API endpoints return both JSON (/stats) and HTML partials (/facts) for HTMX"

duration: 8min
completed: 2026-03-14
---

# Phase 10 Plan 05: Web Dashboard Summary

**FastAPI + Jinja2 + HTMX local web dashboard with 5 route modules, data-dense CSS, HTMX partial updates, and 23 tests covering app factory, routes, and templates.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-14T12:55:38Z
- **Completed:** 2026-03-14T13:04:26Z
- **Tasks:** 2/2
- **Files created:** 19
- **Files modified:** 1

## Accomplishments

- FastAPI app factory (create_app) with dependency injection of FactStore, ClassificationStore, VerificationStore, ReportStore, ReportGenerator, and AnalysisPipeline on app.state
- 5 route modules covering all dashboard views:
  - **investigations**: list (/) with enriched stats, detail (/investigation/{id}) with facts and verification progress
  - **facts**: filterable fact table (/facts/{id}) with tier/status dropdowns, pagination (50 per page)
  - **reports**: report viewing (/reports/{id}) with mistune Markdown->HTML, on-demand generation via POST
  - **monitoring**: pipeline monitoring (/monitoring/status) with aggregated verification stats across all investigations
  - **api**: JSON stats endpoint and HTML partial for HTMX polling and swap
- Jinja2 templates extending base.html with HTMX script from CDN (v2.0.4)
- 523-line data-dense CSS: system fonts, dark nav, compact tables with alternating rows, status badges (confirmed=green, refuted=red, dubious=amber), impact tier indicators, responsive grid, print media query
- HTMX integration: filter dropdowns with hx-get, monitoring auto-refresh every 10s, fact detail inline expansion, report regeneration via hx-post
- Health check endpoint (GET /health) for connectivity monitoring
- 23 tests total: 4 app factory, 10 route response, 9 template rendering

## Task Commits

1. **Task 1: FastAPI app factory, route modules, and route tests** - `4895748` (feat)
2. **Task 2: HTML templates, CSS, and HTMX integration** - `8c539f0` (feat)

## Files Created/Modified

- `osint_system/dashboard/__init__.py` - Package init exporting create_app, run_dashboard
- `osint_system/dashboard/app.py` (122 lines) - Application factory with store injection
- `osint_system/dashboard/routes/__init__.py` - Route package init
- `osint_system/dashboard/routes/investigations.py` (118 lines) - Investigation list and detail
- `osint_system/dashboard/routes/facts.py` (137 lines) - Fact browsing with filtering
- `osint_system/dashboard/routes/reports.py` (89 lines) - Report viewing and generation
- `osint_system/dashboard/routes/monitoring.py` (91 lines) - Pipeline monitoring
- `osint_system/dashboard/routes/api.py` (143 lines) - JSON API and HTML partials
- `osint_system/dashboard/templates/base.html` (45 lines) - Base layout with HTMX + nav + health polling
- `osint_system/dashboard/templates/investigations/list.html` - Investigation card grid
- `osint_system/dashboard/templates/investigations/detail.html` - Detail view with HTMX tabs
- `osint_system/dashboard/templates/facts/list.html` - Filterable fact data table
- `osint_system/dashboard/templates/reports/view.html` - Report display with regenerate button
- `osint_system/dashboard/templates/monitoring/status.html` - Auto-refreshing status dashboard
- `osint_system/dashboard/static/styles.css` (523 lines) - Data-dense analyst CSS
- `tests/dashboard/__init__.py` - Test package init
- `tests/dashboard/test_app.py` (46 lines) - 4 app factory tests
- `tests/dashboard/test_routes.py` (247 lines) - 10 route response tests
- `tests/dashboard/test_templates.py` (227 lines) - 9 template rendering tests
- `requirements.txt` (modified) - Added python-multipart

## Decisions Made

1. **Modern TemplateResponse API** - Used `TemplateResponse(request, name, context)` parameter order instead of the deprecated `TemplateResponse(name, {"request": request, ...})` pattern. Eliminates DeprecationWarning from Starlette.

2. **Per-investigation verification aggregation** - VerificationStore has only `get_stats(investigation_id)`, no global stats method. The monitoring route iterates all investigations from `fact_store.list_investigations()` and aggregates totals manually. This is correct for the current in-memory store scale.

3. **mistune for Markdown->HTML in reports** - Uses `mistune.html()` in the reports route to convert stored Markdown to HTML before passing to the template. This reuses the existing mistune dependency from 10-04 (PDF rendering).

4. **Graceful nonexistent investigation handling** - Routes return 200 with empty data instead of 404 for nonexistent investigation IDs. This matches the store behavior (returning empty results rather than raising).

5. **POST /reports/{id}/generate delegates to AnalysisPipeline** - The generate endpoint calls `analysis_pipeline.run_analysis()` when available, which auto-generates and saves reports via its internal report_generator and report_store. Falls back gracefully when pipeline is not configured.

6. **HTMX auto-refresh** - Monitoring status table has `hx-trigger="every 10s"` for automatic polling. Individual investigation rows also poll `/api/investigation/{id}/stats` independently.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] FastAPI not installed in venv**

- **Found during:** Task 1 test execution
- **Issue:** FastAPI was pinned in requirements.txt by 10-01 but not installed in the virtual environment
- **Fix:** Ran `uv pip install fastapi uvicorn httpx mistune`
- **Committed in:** N/A (runtime environment fix)

**2. [Rule 1 - Bug] VerificationResult missing required fields in test fixture**

- **Found during:** Task 1 test execution
- **Issue:** Test fixture constructed VerificationResult without `original_confidence` and `reasoning` (required fields)
- **Fix:** Added all required fields matching the Pydantic model schema
- **Files modified:** tests/dashboard/test_routes.py
- **Committed in:** 4895748

**3. [Rule 1 - Bug] Starlette TemplateResponse deprecation warnings**

- **Found during:** Task 1 test execution
- **Issue:** `TemplateResponse(name, {"request": request, ...})` triggers DeprecationWarning in Starlette
- **Fix:** Updated all routes to use `TemplateResponse(request, name, context)` parameter order
- **Files modified:** All 5 route modules
- **Committed in:** 4895748

---

**Total deviations:** 3 auto-fixed (1 blocking, 2 bugs)
**Impact on plan:** Zero scope change.

## Issues Encountered

None beyond the auto-fixed deviations documented above.

## Phase 10 Complete

This plan completes Phase 10: Analysis & Reporting Engine. All 5 plans delivered:

| Plan | Subsystem | Key Deliverable |
|------|-----------|-----------------|
| 10-01 | Analysis Schemas | 8 Pydantic models, DataAggregator, AnalysisConfig |
| 10-02 | Database Export | InvestigationExporter (SQLite), InvestigationArchive (JSON) |
| 10-03 | LLM Synthesis | Synthesizer, PatternDetector, ContradictionAnalyzer, AnalysisPipeline |
| 10-04 | Report Generation | ReportGenerator (Jinja2), PDFRenderer (WeasyPrint), ReportStore |
| 10-05 | Web Dashboard | FastAPI + Jinja2 + HTMX dashboard with 5 route modules |

**Full pipeline chain:** classification -> verification -> graph -> analysis -> reporting -> dashboard

---
*Phase: 10-analysis-reporting-engine*
*Completed: 2026-03-14*
