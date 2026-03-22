# Requirements: OSINT Intelligence System v2.0

**Defined:** 2026-03-21
**Core Value:** Automated, accurate extraction and verification of geopolitical facts from diverse open sources with intelligent multi-agent collaboration.

## v2.0 Requirements

Requirements for production hardening and full frontend. Each maps to roadmap phases.

### Crawler Hardening

- [x] **CRAWL-01**: Rotate realistic browser User-Agent strings per request to reduce bot detection
- [x] **CRAWL-02**: Fall back to RSS entry description/summary content when article fetch returns None
- [x] **CRAWL-03**: Use Playwright BrowserPool with context reuse for JS-heavy and Cloudflare-protected sites
- [x] **CRAWL-04**: Validate fetched content against Cloudflare AI Labyrinth honeypot indicators before extraction

### Extraction Quality

- [x] **EXTRACT-01**: Accept "statement" as valid claim_type in Pydantic Claim schema (currently silently dropped)
- [x] **EXTRACT-02**: Optimize extraction prompt for higher fact yield without sacrificing structure
- [x] **EXTRACT-03**: Strip LLM thinking tokens (<think> blocks) and normalize enum values pre-validation

### Verification Coverage

- [x] **VERIFY-01**: Tune NOISE classification threshold to reduce false-positive NOISE flags on valid facts
- [x] **VERIFY-02**: Add adversarial/refutation query variants to QueryGenerator (denied, disproven, false)
- [x] **VERIFY-03**: Add UNVERIFIABLE to GraphIngestor _INGESTIBLE_STATUSES with status tagging

### API Layer

- [x] **API-01**: Investigation registry with first-class investigation entity (create, list, get, delete)
- [x] **API-02**: Facts API (list by investigation, get by ID with classification + verification)
- [x] **API-03**: Report API (get latest, list versions, trigger regeneration)
- [x] **API-04**: Source inventory API (list sources with authority scores per investigation)
- [x] **API-05**: Pipeline launch API (POST to start investigation, returns investigation ID)
- [x] **API-06**: SSE endpoint streaming pipeline progress events during execution
- [x] **API-07**: Graph data API (nodes, edges, query patterns for visualization)

### Storage

- [x] **STORE-01**: Migrate ArticleStore from in-memory+JSON to SQLAlchemy+PostgreSQL with pgvector embeddings
- [x] **STORE-02**: Migrate FactStore from in-memory+JSON to SQLAlchemy+PostgreSQL with pgvector embeddings and full-text search
- [x] **STORE-03**: Migrate ClassificationStore from in-memory+JSON to SQLAlchemy+PostgreSQL
- [x] **STORE-04**: Migrate VerificationStore from in-memory+JSON to SQLAlchemy+PostgreSQL
- [x] **STORE-05**: Migrate ReportStore from in-memory+JSON to SQLAlchemy+PostgreSQL with pgvector embeddings
- [x] **STORE-06**: Alembic migration infrastructure, Docker Compose (Postgres + Memgraph), and JSON data migration script

### Pipeline Events

- [x] **EVENT-01**: PipelineEventBus emitting structured events at phase boundaries
- [x] **EVENT-02**: InvestigationRunner emits progress events (articles fetched, facts extracted, etc.)
- [x] **EVENT-03**: SSE streaming of pipeline events to frontend via FastAPI EventSourceResponse

### Frontend — Investigation Management

- [ ] **UI-INV-01**: Investigation launch form (objective input, model selection, advanced parameters)
- [ ] **UI-INV-02**: Investigation history list with summary stats (facts, confirmed, confidence)
- [ ] **UI-INV-03**: Investigation detail page with tabbed views (facts, report, graph, sources)
- [ ] **UI-INV-04**: Live pipeline progress with stage indicators, counts, elapsed time
- [ ] **UI-INV-05**: Log streaming panel during pipeline execution

### Frontend — Report Viewer

- [ ] **UI-RPT-01**: Rendered Markdown report with collapsible sections
- [ ] **UI-RPT-02**: Confidence level badges (color-coded low/moderate/high)
- [ ] **UI-RPT-03**: Fact drill-down from key judgments to supporting facts with provenance chain
- [ ] **UI-RPT-04**: Alternative hypothesis comparison panel
- [ ] **UI-RPT-05**: Contradiction display with resolution status
- [ ] **UI-RPT-06**: Version selector and report regeneration trigger
- [ ] **UI-RPT-07**: Source attribution table with authority scores

### Frontend — Knowledge Graph

- [ ] **UI-GRAPH-01**: Interactive graph visualization using Sigma.js/react-sigma (WebGL)
- [ ] **UI-GRAPH-02**: Node filtering by type (Fact, Entity, Source, Investigation)
- [ ] **UI-GRAPH-03**: Entity highlighting and relationship traversal on click
- [ ] **UI-GRAPH-04**: Verification status coloring on fact nodes

### Frontend — Source Management

- [ ] **UI-SRC-01**: Source health dashboard (crawl success rates per domain)
- [ ] **UI-SRC-02**: Authority score viewer/editor for SOURCE_BASELINES
- [ ] **UI-SRC-03**: RSS feed configuration viewer

### Frontend — Configuration

- [ ] **UI-CFG-01**: Model selection UI with cost estimation preview
- [ ] **UI-CFG-02**: YAML configuration profile save/load
- [ ] **UI-CFG-03**: Investigation template/preset system

### Infrastructure

- [ ] **INFRA-01**: Token usage and cost tracking per investigation (from OpenRouter response headers)
- [ ] **INFRA-02**: YAML-based configuration profiles (thorough vs quick vs budget)
- [ ] **INFRA-03**: Docker Compose for Python backend + Next.js frontend
- [ ] **INFRA-04**: Monorepo structure with frontend/ directory alongside osint_system/

## Future Requirements

Deferred beyond v2.0.

### Multi-User

- **MULTI-01**: User authentication and session management
- **MULTI-02**: Per-user investigation isolation
- **MULTI-03**: Shared investigation collaboration

### Advanced Analysis

- **ANAL-01**: Cross-investigation comparison and trend detection
- **ANAL-02**: Automated monitoring with scheduled re-runs
- **ANAL-03**: Report diff between versions (text-level diff)

### Content Types

- **CONTENT-01**: Visual/image content analysis
- **CONTENT-02**: Multi-language source support
- **CONTENT-03**: Dark web source integration

## Out of Scope

| Feature | Reason |
|---------|--------|
| Multi-user authentication | Personal use only for v2.0 |
| Mobile app | Web-first, responsive design sufficient |
| Real-time streaming | Batch processing sufficient for intelligence analysis |
| 3D graph visualization | Over-engineering; 2D WebGL is sufficient |
| WYSIWYG report editing | Reports are LLM-generated analytical products, not editable documents |
| Per-agent model selection UI | Over-complexity; profile-based selection is cleaner |
| Automatic credibility learning | ML feedback loops are premature; manual baselines sufficient |
| WebSocket for progress | SSE is correct for unidirectional server push |
| PostgreSQL | SQLite sufficient for single-user; SQLAlchemy dialect abstraction allows future migration |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| CRAWL-01 | Phase 11 | Complete |
| CRAWL-02 | Phase 11 | Complete |
| CRAWL-03 | Phase 11 | Complete |
| CRAWL-04 | Phase 11 | Complete |
| EXTRACT-01 | Phase 11 | Complete |
| EXTRACT-02 | Phase 11 | Complete |
| EXTRACT-03 | Phase 11 | Complete |
| VERIFY-01 | Phase 11 | Complete |
| VERIFY-02 | Phase 11 | Complete |
| VERIFY-03 | Phase 11 | Complete |
| API-01 | Phase 12 | Complete |
| API-02 | Phase 12 | Complete |
| API-03 | Phase 12 | Complete |
| API-04 | Phase 12 | Complete |
| API-05 | Phase 12 | Complete |
| API-06 | Phase 12 | Complete |
| API-07 | Phase 12 | Complete |
| EVENT-01 | Phase 12 | Complete |
| EVENT-02 | Phase 12 | Complete |
| EVENT-03 | Phase 12 | Complete |
| STORE-01 | Phase 13 | Complete |
| STORE-02 | Phase 13 | Complete |
| STORE-03 | Phase 13 | Complete |
| STORE-04 | Phase 13 | Complete |
| STORE-05 | Phase 13 | Complete |
| STORE-06 | Phase 13 | Complete |
| UI-INV-01 | Phase 14 | Pending |
| UI-INV-02 | Phase 14 | Pending |
| UI-INV-03 | Phase 14 | Pending |
| UI-INV-04 | Phase 14 | Pending |
| UI-INV-05 | Phase 14 | Pending |
| INFRA-04 | Phase 14 | Pending |
| UI-RPT-01 | Phase 15 | Pending |
| UI-RPT-02 | Phase 15 | Pending |
| UI-RPT-03 | Phase 15 | Pending |
| UI-RPT-04 | Phase 15 | Pending |
| UI-RPT-05 | Phase 15 | Pending |
| UI-RPT-06 | Phase 15 | Pending |
| UI-RPT-07 | Phase 15 | Pending |
| UI-GRAPH-01 | Phase 15 | Pending |
| UI-GRAPH-02 | Phase 15 | Pending |
| UI-GRAPH-03 | Phase 15 | Pending |
| UI-GRAPH-04 | Phase 15 | Pending |
| UI-SRC-01 | Phase 16 | Pending |
| UI-SRC-02 | Phase 16 | Pending |
| UI-SRC-03 | Phase 16 | Pending |
| UI-CFG-01 | Phase 16 | Pending |
| UI-CFG-02 | Phase 16 | Pending |
| UI-CFG-03 | Phase 16 | Pending |
| INFRA-01 | Phase 16 | Pending |
| INFRA-02 | Phase 16 | Pending |
| INFRA-03 | Phase 16 | Pending |

**Coverage:**
- v2.0 requirements: 52 total
- Mapped to phases: 52/52
- Unmapped: 0

---
*Requirements defined: 2026-03-21*
*Last updated: 2026-03-21 after roadmap creation (all requirements mapped)*
