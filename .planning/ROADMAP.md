# Roadmap: OSINT Intelligence System

## Milestones

- ✅ **v1.0 Core Pipeline** - Phases 1-10 (shipped 2026-03-14)
- 🚧 **v2.0 Production Hardening & Frontend** - Phases 11-17 (in progress)

## Phases

<details>
<summary>✅ v1.0 Core Pipeline (Phases 1-10) - SHIPPED 2026-03-14</summary>

### Phase 1: Foundation & Environment Setup
**Goal**: Establish development environment with all base dependencies and API connectivity
**Plans**: 4/4 complete

Plans:
- [x] 01-01: Set up uv environment and core dependencies
- [x] 01-02: Configure Pydantic settings and logging infrastructure
- [x] 01-03: Integrate Gemini API with rate limiting
- [x] 01-04: Basic agent proof-of-concept

### Phase 2: Base Agent Architecture
**Goal**: Create foundational agent classes with MCP tool integration and A2A communication
**Plans**: 4/4 complete

Plans:
- [x] 02-01: Dependencies & Enhanced BaseAgent
- [x] 02-02: Message Bus & Registry
- [x] 02-03: LangGraph Orchestration
- [x] 02-04: MCP Tool Server & Integration

### Phase 3: Planning & Orchestration Agent
**Goal**: Build the central coordinator for objective decomposition and task distribution
**Plans**: 3/3 complete

Plans:
- [x] 03-01: Implement Planning Agent with LangGraph
- [x] 03-02: Create task queue and distribution system
- [x] 03-03: Build supervisor-worker coordination patterns

### Phase 4: News Crawler Implementation
**Goal**: Deploy first crawler for news sources with filtering and metadata preservation
**Plans**: 4/4 complete

Plans:
- [x] 04-01: Implement NewsFeedAgent base functionality
- [x] 04-02: Integrate RSS feeds and NewsAPI
- [x] 04-03: Add filtering and metadata extraction
- [x] 04-04: Data routing and integration

### Phase 5: Extended Crawler Cohort
**Goal**: Expand data acquisition with social media and document crawlers
**Plans**: 6/6 complete

Plans:
- [x] 05-01: Reddit crawler setup
- [x] 05-02: Reddit data collection and integration
- [x] 05-03: Document crawler setup
- [x] 05-04: Web scraper enhancement
- [x] 05-05: Crawler coordination system
- [x] 05-06: Integration testing

### Phase 6: Fact Extraction Pipeline
**Goal**: Extract discrete, verifiable facts from raw text with structured output per CONTEXT.md schema
**Plans**: 4/4 complete

Plans:
- [x] 06-01: Pydantic schemas for fact output (ExtractedFact, Entity, Provenance)
- [x] 06-02: FactExtractionAgent with Gemini prompts
- [x] 06-03: FactStore and FactConsolidator for dedup/storage
- [x] 06-04: ExtractionPipeline bridging crawler output to fact extraction

### Phase 7: Fact Classification System
**Goal**: Categorize facts into critical/less-critical/dubious tiers with credibility scoring
**Plans**: 4/4 complete

Plans:
- [x] 07-01: Classification schema and agent structure
- [x] 07-02: Credibility scoring system
- [x] 07-03: Dubious detection with Boolean logic gates
- [x] 07-04: Impact assessment and full integration

### Phase 8: Verification Loop
**Goal**: Investigate and resolve dubious facts through targeted searches
**Plans**: 4/4 complete

Plans:
- [x] 08-01: Verification schemas and status types
- [x] 08-02: Species-specialized query generation
- [x] 08-03: Evidence aggregation and re-classification
- [x] 08-04: VerificationAgent with batch processing and full integration

### Phase 9: Knowledge Graph Integration
**Goal**: Transform verified facts, entities, and relationships into a queryable graph
**Plans**: 5/5 complete

Plans:
- [x] 09-01: Graph Pydantic schemas, GraphAdapter Protocol, and Neo4j config
- [x] 09-02: Neo4j + NetworkX adapters, Cypher queries, docker-compose, adapter tests
- [x] 09-03: FactMapper and RelationshipExtractor (hybrid rule + LLM)
- [x] 09-04: Four query patterns validated with comprehensive test suite
- [x] 09-05: GraphIngestor, GraphPipeline, and end-to-end integration

### Phase 10: Analysis & Reporting Engine
**Goal**: Generate intelligence products with multiple output formats and dashboard
**Plans**: 5/5 complete

Plans:
- [x] 10-01: Analysis schemas, DataAggregator, AnalysisConfig, Phase 10 dependencies
- [x] 10-02: SQLite InvestigationExporter, JSON InvestigationArchive, ClassificationStore API
- [x] 10-03: Synthesizer, PatternDetector, ContradictionAnalyzer, AnalysisReportingAgent, AnalysisPipeline
- [x] 10-04: ReportGenerator (Jinja2), PDFRenderer (WeasyPrint), ReportStore (versioned)
- [x] 10-05: FastAPI dashboard with HTMX, 5 route modules, data-dense CSS

</details>

### 🚧 v2.0 Production Hardening & Frontend (In Progress)

**Milestone Goal:** Harden the pipeline for reliable unattended operation, build a production-quality Next.js frontend, and prepare for deployment.

- [x] **Phase 11: Crawler Hardening & Pipeline Quality** - Fix crawler fragility, extraction drops, verification coverage gaps
- [x] **Phase 12: API Layer & Pipeline Events** - REST API endpoints, event bus, SSE streaming for frontend consumption
- [x] **Phase 13: PostgreSQL + Memgraph Migration** - Replace in-memory+JSON stores with PostgreSQL+pgvector, replace NetworkX with Memgraph
- [ ] **Phase 14: Next.js Frontend Shell** - Monorepo setup, App Router, investigation launch and live progress
- [ ] **Phase 15: Report Viewer & Knowledge Graph** - Analytical report display, fact drill-down, interactive graph visualization
- [ ] **Phase 16: Feature Completion & Deployment** - Source management, configuration profiles, cost tracking, Docker deployment
- [ ] **Phase 17: Crawler Agent Integration** - Wire v1.0 crawler cohort into InvestigationRunner, replacing inline fetch with agent orchestration

## Phase Details

### Phase 11: Crawler Hardening & Pipeline Quality
**Goal**: Investigations run reliably against real-world sources without silent data loss from bot detection, malformed LLM output, or over-aggressive noise filtering
**Depends on**: Phase 10 (v1.0 complete)
**Requirements**: CRAWL-01, CRAWL-02, CRAWL-03, CRAWL-04, EXTRACT-01, EXTRACT-02, EXTRACT-03, VERIFY-01, VERIFY-02, VERIFY-03
**Success Criteria** (what must be TRUE):
  1. Crawler fetches content from JS-heavy and Cloudflare-protected sites via Playwright BrowserPool without OOM crashes during batch runs
  2. When article fetch fails, the pipeline falls back to RSS entry summary content and still extracts facts from it
  3. Extraction produces valid structured facts regardless of which LLM model in the fallback chain handles the request (no silent drops from thinking tokens, unrecognized enum values, or schema mismatches)
  4. Verification coverage improves: facts that were previously bulk-classified as NOISE are now correctly routed through verification with adversarial query variants, and unverifiable facts are ingested into the knowledge graph with status tagging
**Plans**: 4/4 complete

Plans:
- [x] 11-01-PLAN.md — BrowserPool, stealth, UA rotation, Cloudflare detection
- [x] 11-02-PLAN.md — RSS summary fallback, claim_type schema extension, enum normalization
- [x] 11-03-PLAN.md — Objective-aware extraction prompt, per-article metrics, warn-once fallback
- [x] 11-04-PLAN.md — Adversarial queries, LLM stance fallback, UNVERIFIABLE graph ingestion

### Phase 12: API Layer & Pipeline Events
**Goal**: The backend exposes a complete JSON REST API and real-time event stream that the frontend can consume to launch, monitor, and review investigations
**Depends on**: Phase 11
**Requirements**: API-01, API-02, API-03, API-04, API-05, API-06, API-07, EVENT-01, EVENT-02, EVENT-03
**Success Criteria** (what must be TRUE):
  1. A POST request to the investigations endpoint creates an investigation record, spawns the pipeline as a background task, and returns the investigation ID with a stream URL
  2. An SSE connection to the stream endpoint receives structured events (phase_started, phase_progress, phase_completed, pipeline_completed, pipeline_error) in real time as the pipeline executes, with Last-Event-ID reconnection support
  3. GET endpoints return JSON for investigation detail, paginated fact lists with classification and verification status, report content with version history, source inventory with authority scores, and graph node/edge data
  4. The OpenAPI spec auto-generated at /openapi.json accurately describes all endpoints and response models, ready for TypeScript client generation
**Plans**: 4/4 complete

Plans:
- [x] 12-01-PLAN.md — API schemas, RFC 7807 errors, event bus, investigation registry
- [x] 12-02-PLAN.md — Investigation lifecycle endpoints + SSE streaming
- [x] 12-03-PLAN.md — Facts, reports, sources, and graph data routes
- [x] 12-04-PLAN.md — App factory, serve.py wiring, OpenAPI verification

### Phase 13: PostgreSQL + Memgraph Migration
**Goal**: All investigation data persists durably in PostgreSQL with pgvector embeddings, knowledge graph persists in Memgraph with MAGE algorithms, surviving process restarts with no behavioral changes to pipeline or API code
**Depends on**: Phase 12
**Requirements**: STORE-01, STORE-02, STORE-03, STORE-04, STORE-05, STORE-06
**Success Criteria** (what must be TRUE):
  1. An investigation completed before server restart is fully available after restart with all articles, facts, classifications, verifications, and report data intact in PostgreSQL
  2. Concurrent API reads during an active pipeline run do not block or produce stale data
  3. Existing pipeline and agent code runs without modification against the new store implementations (interface contract preserved)
  4. A migration script converts existing JSON-persisted investigation data into PostgreSQL, Alembic manages schema versioning, and knowledge graph nodes/edges persist in Memgraph across restarts
  5. Facts, articles, entities, and reports have pgvector embedding columns populated by local gte-large-en-v1.5 model, enabling semantic similarity queries
  6. Full-text search via tsvector + GIN indexes works on fact claim text and article content
  7. Memgraph runs MAGE algorithms (PageRank, community detection, betweenness centrality) on ingested graph data post-pipeline
**Plans**: 7/7 complete

Plans:
- [x] 13-01-PLAN.md — Docker Compose + async SQLAlchemy engine + Alembic init
- [x] 13-02-PLAN.md — SQLAlchemy ORM models (6 tables) + initial Alembic migration
- [x] 13-03-PLAN.md — MemgraphAdapter + Memgraph Cypher queries + MAGE algorithms
- [x] 13-04-PLAN.md — ArticleStore + FactStore PostgreSQL migration
- [x] 13-05-PLAN.md — ClassificationStore + VerificationStore + ReportStore PostgreSQL migration
- [x] 13-06-PLAN.md — EmbeddingService (gte-large-en-v1.5 local embeddings)
- [x] 13-07-PLAN.md — Wiring (runner, API, pipeline), data migration script, Neo4j cleanup

### Phase 14: Next.js Frontend Shell
**Goal**: Users can launch investigations, watch live pipeline progress, and browse investigation history through a web interface
**Depends on**: Phase 13
**Requirements**: UI-INV-01, UI-INV-02, UI-INV-03, UI-INV-04, UI-INV-05, INFRA-04
**Success Criteria** (what must be TRUE):
  1. User fills out an investigation launch form (objective, model selection, parameters), submits it, and the pipeline starts executing on the backend
  2. While the pipeline runs, the user sees live stage indicators with article/fact/verification counts updating in real time, elapsed time per phase, and error display on failures
  3. User can view a history list of all investigations with summary stats (fact count, confirmed count, confidence), click into any investigation to see tabbed detail views, and see a streaming log panel during execution
  4. The frontend is a Next.js App Router project in `frontend/` with a generated TypeScript API client providing type-safe API access
**Plans**: TBD

### Phase 15: Report Viewer & Knowledge Graph
**Goal**: Users can read and navigate intelligence reports with fact provenance drill-down, and explore the knowledge graph visually to discover entity relationships
**Depends on**: Phase 14
**Requirements**: UI-RPT-01, UI-RPT-02, UI-RPT-03, UI-RPT-04, UI-RPT-05, UI-RPT-06, UI-RPT-07, UI-GRAPH-01, UI-GRAPH-02, UI-GRAPH-03, UI-GRAPH-04
**Success Criteria** (what must be TRUE):
  1. User reads the rendered intelligence report with collapsible sections, clicks a key judgment, and drills down to the supporting facts with full provenance chain (source URL, extraction date, verification status)
  2. Report displays confidence badges (color-coded low/moderate/high), an alternative hypothesis comparison panel, contradiction highlights with resolution status, source attribution with authority scores, and a version selector with regeneration trigger
  3. User opens the knowledge graph view and sees an interactive force-directed visualization (WebGL) with node type coloring, can filter nodes by type (Fact, Entity, Source, Investigation), click an entity to highlight its relationships and traverse the graph, and see verification status coloring on fact nodes
**Plans**: TBD

### Phase 16: Feature Completion & Deployment
**Goal**: Users can manage sources, configure investigation profiles, track costs, and deploy the entire system via Docker Compose
**Depends on**: Phase 15
**Requirements**: UI-SRC-01, UI-SRC-02, UI-SRC-03, UI-CFG-01, UI-CFG-02, UI-CFG-03, INFRA-01, INFRA-02, INFRA-03
**Success Criteria** (what must be TRUE):
  1. User views a source health dashboard showing crawl success rates per domain, can view and edit authority score baselines, and can review RSS feed configurations
  2. User selects models with a cost estimation preview, saves named configuration profiles (thorough/quick/budget), loads profiles to pre-fill investigation parameters, and saves/loads investigation templates
  3. After each investigation completes, the user can see token usage and cost breakdown (from OpenRouter response headers) for that run
  4. The system deploys as two Docker containers (Python backend + Next.js frontend) via `docker compose up`, with health checks, restart policies, and documented environment variables
**Plans**: TBD

### Phase 17: Crawler Agent Integration
**Goal**: InvestigationRunner uses the full v1.0 crawler agent cohort instead of inline RSS+trafilatura, enabling multi-source acquisition with proper coordination
**Depends on**: Phase 16
**Requirements**: TBD (define during planning)
**Success Criteria** (what must be TRUE):
  1. InvestigationRunner._phase_crawl delegates to NewsfeedAgent orchestrator instead of inline RSS polling + trafilatura fetch
  2. SocialMediaAgent (Reddit), APICrawler (NewsAPI), and DocumentScraperAgent are activated based on investigation parameters and contribute articles to the pipeline
  3. The deduplication engine and authority scorer from crawlers/coordination/ operate across all crawler outputs before extraction
  4. A2A message bus coordinates cross-crawler context (e.g., entities discovered by one crawler inform queries for others)
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 11 → 12 → 13 → 14 → 15 → 16 → 17

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Foundation & Environment Setup | v1.0 | 4/4 | Complete | 2026-01-10 |
| 2. Base Agent Architecture | v1.0 | 4/4 | Complete | 2026-01-12 |
| 3. Planning & Orchestration Agent | v1.0 | 3/3 | Complete | 2026-01-12 |
| 4. News Crawler Implementation | v1.0 | 4/4 | Complete | 2026-01-13 |
| 5. Extended Crawler Cohort | v1.0 | 6/6 | Complete | 2026-02-01 |
| 6. Fact Extraction Pipeline | v1.0 | 4/4 | Complete | 2026-02-03 |
| 7. Fact Classification System | v1.0 | 4/4 | Complete | 2026-02-03 |
| 8. Verification Loop | v1.0 | 4/4 | Complete | 2026-02-11 |
| 9. Knowledge Graph Integration | v1.0 | 5/5 | Complete | 2026-03-13 |
| 10. Analysis & Reporting Engine | v1.0 | 5/5 | Complete | 2026-03-14 |
| 11. Crawler Hardening & Pipeline Quality | v2.0 | 4/4 | Complete | 2026-03-21 |
| 12. API Layer & Pipeline Events | v2.0 | 4/4 | Complete | 2026-03-22 |
| 13. PostgreSQL + Memgraph Migration | v2.0 | 7/7 | Complete | 2026-03-22 |
| 14. Next.js Frontend Shell | v2.0 | 0/TBD | Not started | - |
| 15. Report Viewer & Knowledge Graph | v2.0 | 0/TBD | Not started | - |
| 16. Feature Completion & Deployment | v2.0 | 0/TBD | Not started | - |
| 17. Crawler Agent Integration | v2.0 | 0/TBD | Not started | - |
