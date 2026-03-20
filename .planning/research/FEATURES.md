# Feature Landscape: OSINT Intelligence Dashboard v2.0

**Domain:** LLM-powered OSINT intelligence system with Next.js+shadcn/ui frontend
**Researched:** 2026-03-20
**Context:** Single-user personal research tool. Existing Python pipeline (crawl, extract, classify, verify, graph, analyze, report) with FastAPI backend. Replacing HTMX dashboard with full Next.js+shadcn/ui frontend.

---

## 1. Investigation Launch UI

### Table Stakes

| Feature | Why Expected | Complexity | Backend Dependency |
|---------|--------------|------------|-------------------|
| Objective text input with clear labeling | It is the primary input to the entire system; without it nothing happens | Low | `InvestigationRunner.__init__(objective)` already accepts string |
| Model selection dropdown | System already routes to different Gemini/OpenRouter models via `AnalysisConfig.synthesis_model`; user must pick before launch | Low | `AnalysisConfig` fields already exist |
| Launch button with disable-during-execution | Prevents double-submission; standard form pattern | Low | Need new endpoint: POST /api/investigations |
| Basic validation (non-empty objective, minimum length) | Garbage-in-garbage-out; analyst needs feedback before burning API tokens | Low | Client-side + server echo |
| Investigation ID display after launch | User needs to reference and return to results; ID is how the system tracks everything | Low | `InvestigationRunner` already generates `inv-{uuid[:8]}` |

### Differentiators

| Feature | Value Proposition | Complexity | Backend Dependency |
|---------|-------------------|------------|-------------------|
| Source tier selection (checkboxes for feed categories) | `feed_config.py` has 11 categories (wire, mainstream, government, etc.); letting user toggle them focuses crawling and reduces noise/cost | Medium | Need to thread category filters through `_phase_crawl()` |
| Keyword override / refinement | `_extract_keywords()` uses naive stopword removal; analyst may want to inject domain-specific terms or exclude irrelevant ones | Medium | Pass overrides to `_extract_keywords()` |
| Cost estimation preview | Before launch, show estimated API cost based on model choice and expected article count; critical for personal budget | Medium | Need token-cost lookup table per model, estimation heuristic |
| Investigation template / preset system | Save common configurations (model + sources + keyword strategy) for reuse; saves time on repeated research patterns | Medium | New: template storage (JSON file or DB) |
| Advanced parameter accordion (temperature, max articles, max_key_judgments) | Power user controls; `AnalysisConfig` already has these fields, just need UI exposure | Low | All fields exist in `AnalysisConfig` |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Multi-step wizard with 4+ pages | Single user, expert analyst. Wizard adds friction for someone who knows what they want. A wizard solves the "confused novice" problem this user does not have | Single-page form with collapsible "Advanced" section |
| Drag-and-drop source reordering | Source priority is determined by feed tier (TIER_1 vs TIER_2) and authority scores, not arbitrary user ordering. Exposing reorder implies user-defined priority that the pipeline ignores | Category-level toggles, not per-feed sorting |
| "Guided tour" or onboarding overlay | Single expert user. Wastes screen real estate | Rely on clear labels and tooltips |

---

## 2. Live Progress Dashboard

### Table Stakes

| Feature | Why Expected | Complexity | Backend Dependency |
|---------|--------------|------------|-------------------|
| Pipeline stage indicator (6 stages: Crawl, Extract, Classify, Verify, Graph, Analyze) | Runner already prints Rich console output per phase; web equivalent is mandatory. Without it, user stares at a spinner for 5-15 minutes | Medium | **NEW**: SSE endpoint streaming phase transitions from `InvestigationRunner` |
| Current stage highlighting with completed/active/pending states | Standard pipeline progress pattern. The runner has exactly 6 sequential phases | Low (frontend) | SSE events include stage name + status enum |
| Article/fact count updates during execution | Runner already tracks `_stats` dict with articles, facts, classified, verified, nodes; stream these | Medium | Emit SSE events from each `_phase_*` method |
| Error display if pipeline fails mid-execution | Pipeline can fail (API rate limits, network errors, empty results). Analyst needs to know what broke and at which stage | Medium | Catch exceptions in runner, emit error SSE event |
| Elapsed time per phase | Runner already has duration tracking in extraction phase; extend to all phases | Low | Timestamp each phase start/end in SSE events |

### Differentiators

| Feature | Value Proposition | Complexity | Backend Dependency |
|---------|-------------------|------------|-------------------|
| Log streaming panel (collapsible) | Structlog already produces structured JSON logs; streaming them gives full visibility into what the LLM is doing, which feeds failed, which articles were fetched | Medium | **NEW**: SSE log stream from structlog handler |
| Per-stage metric cards (articles fetched, facts extracted, dubious count, etc.) | Mirrors the Rich console table the runner prints at completion, but incrementally during execution | Low (frontend) | Stats already computed in `_stats` dict |
| Cancel investigation button | Long-running pipeline (5-15 min); analyst may realize they mis-specified the objective or want to abort after seeing early crawl results are off-topic | High | **NEW**: Cancellation token / asyncio.Event integration into runner |
| ETA estimation based on article count | After crawl phase completes, article count is known; can estimate remaining time from historical data or simple heuristic | Medium | Frontend heuristic based on prior runs |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| WebSocket bidirectional channel | SSE is sufficient for server-to-client push. WebSocket adds complexity (connection management, reconnection, protocol negotiation) for zero benefit -- client never sends mid-pipeline | Use SSE (text/event-stream) via FastAPI StreamingResponse or sse-starlette |
| Polling every 500ms for status updates | Wasteful; push via SSE is more efficient and lower latency | SSE push |
| Real-time log search/filter during execution | Over-engineering. Logs are temporary; after completion, the structured data (facts, reports) is what matters. Log search during a 10-minute run is not useful | Show last N log lines, full log downloadable after completion |

---

## 3. Report Viewer

### Table Stakes

| Feature | Why Expected | Complexity | Backend Dependency |
|---------|--------------|------------|-------------------|
| Rendered Markdown report with proper heading hierarchy | `ReportGenerator` already produces structured Markdown with H1/H2/H3 sections (Executive Summary, Key Findings, etc.) | Low | Report content stored in `ReportStore.markdown_content` |
| Collapsible sections for each report part | Intelligence reports are long (2000-5000 words). Analysts scan the executive summary then drill into specific sections | Low (frontend) | Parse Markdown headings into collapsible tree |
| Confidence level indicators (color-coded badges for low/moderate/high) | IC-standard confidence levels are core to the analysis. Visual encoding (red/yellow/green or similar) is how analysts parse at a glance | Low | `ConfidenceAssessment.level` already in `AnalysisSynthesis` |
| Version selector dropdown | `ReportStore` already supports versioned reports with content deduplication. Existing HTMX template has version select. Must preserve this | Low | `ReportStore.list_versions()` exists |
| Report regeneration trigger | Button to re-run synthesis with current facts. Already exists in HTMX dashboard | Low | Existing POST endpoint; may need new API route |
| Source attribution list with authority scores | `SourceInventoryEntry` has domain, type, authority_score, fact_count. Must be displayed | Low | Data in `AnalysisSynthesis.snapshot.source_inventory` |

### Differentiators

| Feature | Value Proposition | Complexity | Backend Dependency |
|---------|-------------------|------------|-------------------|
| Fact drill-down from key judgments | Each `KeyJudgment` has `supporting_fact_ids`. Click a judgment to see the specific facts that support it, with their verification status and source. This is the "show your work" capability intelligence analysts require | Medium | Need API endpoint: GET /api/facts/{fact_id} returning fact + classification + verification |
| Evidence chain visualization | Given a key judgment, show: Judgment -> supporting facts -> source articles -> source authority. Linear chain, not graph. Answers "why should I trust this conclusion?" | Medium | Traversal: KeyJudgment.supporting_fact_ids -> FactStore -> Provenance -> SourceInventory |
| Alternative hypothesis comparison panel | `AlternativeHypothesis` has likelihood, supporting_evidence, weaknesses. Side-by-side or tabbed display showing competing interpretations. This is core IC analysis tradecraft | Medium | Data already in `AnalysisSynthesis.alternative_hypotheses` |
| Contradiction highlight with resolution status | `ContradictionEntry` has fact_ids, resolution_status, resolution_notes. Visual indicator for unresolved contradictions; drill-down to conflicting facts | Medium | Data in `AnalysisSynthesis.contradictions` |
| Print/export to PDF | Single-user still wants to share reports occasionally. Markdown-to-PDF rendering | Medium | `report_store` already has `pdf_path` field; need renderer (e.g., Puppeteer or wkhtmltopdf) |
| Report diff between versions | When report is regenerated, highlight what changed. Content hash exists for deduplication; need actual text diff | High | Compute diff between `markdown_content` of two versions (server-side or client-side) |
| Timeline view extracted from report data | `TimelineEntry` objects in the snapshot have timestamp, event, confidence. Render as interactive chronological view | Medium | Data in `InvestigationSnapshot.timeline_entries` |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| WYSIWYG report editing in browser | The report is LLM-generated from structured data. Editing the rendered output creates a fork between the data and the display. If the user regenerates, edits are lost | Allow analyst annotations/notes as separate layer; regeneration preserves annotations |
| Inline fact editing from report view | Modifying facts from the report view conflates presentation with data management. Facts should be edited in the fact management view, then report regenerated | Link to fact detail view; provide regeneration button |
| Automatic report regeneration on fact changes | Expensive (LLM API call). User should explicitly choose when to regenerate. Some fact updates are trivial and don't warrant a new analysis pass | Manual regeneration button with "facts have changed since last report" indicator |

---

## 4. Knowledge Graph Visualization

### Table Stakes

| Feature | Why Expected | Complexity | Backend Dependency |
|---------|--------------|------------|-------------------|
| Force-directed graph layout with draggable nodes | Standard approach for entity-relationship visualization. NetworkX graph data maps directly to node-link format consumed by react-force-graph or D3 | Medium | **NEW**: API endpoint returning `QueryResult.to_dict()` in node-link JSON format |
| Node type color coding (Entity=blue, Fact=green, Source=orange, etc.) | 5 node labels (Fact, Entity, Source, Investigation, Classification). Color coding is the minimum visual encoding for graph readability | Low (frontend) | `GraphNode.label` field exists |
| Edge type labeling (CORROBORATES, CONTRADICTS, MENTIONS, etc.) | 13 EdgeType values. Without labels, the graph is meaningless -- relationships ARE the intelligence | Low (frontend) | `GraphEdge.edge_type` field exists |
| Node hover tooltip showing key properties | Name, type, confidence score, fact count. Critical for graph exploration -- analyst needs context without clicking | Low (frontend) | `GraphNode.properties` dict has all data |
| Zoom and pan | Standard graph interaction. Graphs with 50+ nodes require spatial navigation | Low | Built into react-force-graph |

### Differentiators

| Feature | Value Proposition | Complexity | Backend Dependency |
|---------|-------------------|------------|-------------------|
| Edge type filtering (toggle CORROBORATES, CONTRADICTS, etc. on/off) | 13 edge types is noisy. Analyst may want to see only contradictions, or only corroboration chains. This is the primary analytical interaction pattern | Medium | Client-side filter on edge data; no backend change |
| Node type filtering (show only Entities, hide Facts, etc.) | Same rationale as edge filtering. 5 node types; toggle visibility | Low (frontend) | Client-side filter |
| Entity-centric neighborhood exploration | Click an entity node to expand its 1-hop or 2-hop neighborhood. `GraphAdapter` already has `entity_network` query type | Medium | Existing `GraphPipeline.query("entity_network", entity_id=...)` |
| Edge weight visual encoding (thickness or opacity) | `GraphEdge.weight` (0.0-1.0) encodes relationship strength. Thicker/darker edges = stronger relationships. Provides at-a-glance strength assessment | Low (frontend) | `GraphEdge.weight` already computed |
| Corroboration cluster highlighting | `GraphAdapter` supports `corroboration_clusters` query type. Highlight groups of mutually corroborating facts -- this is the graph's analytical payoff | High | Existing query type, but need layout algorithm to visually group clusters |
| Cross-investigation edge markers | `GraphEdge.cross_investigation` flag already exists. Visually distinguish edges that connect facts from different investigations (dashed line, different color) | Low (frontend) | `cross_investigation` boolean on each edge |
| Click-to-navigate from graph node to fact/entity detail | Graph is exploration tool, not endpoint. Analyst clicks a Fact node and navigates to the fact detail view with full classification, verification, provenance | Low (frontend) | Router navigation; fact detail view needed |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| 3D or VR graph visualization | Cool demo, poor UX for actual analysis. 3D adds occlusion, disorientation, and performance overhead. 2D force-directed graphs are the standard for intelligence link analysis (Maltego, Palantir, i2 Analyst's Notebook) | 2D force-directed graph with good filtering |
| Graph editing (add/remove nodes/edges in browser) | The graph is computed from structured data (facts, entities, relationships). Manual graph editing creates data inconsistency -- the graph should reflect the evidence, not analyst wishes | Read-only visualization; data modifications go through fact/entity management |
| Full-graph rendering of 1000+ nodes | Performance disaster. Force-directed layout becomes unusable above ~500 nodes. Most investigation graphs will have 50-200 nodes | Entity-centric exploration with 1-2 hop limits; progressive loading; cluster summaries |
| Real-time graph animation during pipeline execution | Graph is built in Phase 5 (after verification). Animating node-by-node addition adds no analytical value and is expensive to render | Show graph after pipeline completion; provide refresh button |

---

## 5. Source Management

### Table Stakes

| Feature | Why Expected | Complexity | Backend Dependency |
|---------|--------------|------------|-------------------|
| Source list with domain, type, authority score | `source_credibility.py` has `SOURCE_BASELINES` (40+ sources), `SOURCE_TYPE_DEFAULTS`, `DOMAIN_PATTERN_DEFAULTS`. Must display this configuration | Low | Read from config; no store needed |
| Feed list with name, URL, tier, category | `feed_config.py` has `ALL_FEEDS` (45+ feeds) with `FeedSource` dataclass. Must display current feed configuration | Low | Read from `ALL_FEEDS` list |
| Propaganda risk indicators | `PROPAGANDA_RISK` dict already tags sources like Xinhua, TASS, Al Jazeera with risk levels and state affiliations | Low | Read from `PROPAGANDA_RISK` dict |
| Authority score display per source | Analysts need to understand why certain facts are weighted higher. Authority scores drive the entire classification and verification pipeline | Low | `SOURCE_BASELINES` values |

### Differentiators

| Feature | Value Proposition | Complexity | Backend Dependency |
|---------|-------------------|------------|-------------------|
| Authority score editing with save | Allow analyst to override default authority scores. A single user may have domain-specific knowledge about source credibility that differs from defaults (e.g., they know a particular regional source is unreliable for this topic) | Medium | **NEW**: User-override store that layers on top of `SOURCE_BASELINES`; persist to JSON/DB |
| Feed health monitoring (last fetch status, success rate, last article count) | Feeds go stale, URLs change, sites add paywalls. Currently invisible -- crawl phase silently gets 0 results from dead feeds | Medium | **NEW**: Track per-feed fetch stats in runner; persist to store |
| Add/remove custom feeds | Static `feed_config.py` is limiting. Analyst researching a niche topic may want temporary topic-specific RSS feeds | Medium | **NEW**: User feed store (JSON) that merges with `ALL_FEEDS` |
| Feed category grouping with bulk enable/disable | 11 feed categories. Toggle entire categories on/off for different investigation profiles | Low (frontend) | Categories already defined in `FeedCategory` type |
| Source contribution stats per investigation | "Reuters contributed 12 facts, 8 confirmed. RT contributed 3 facts, 2 refuted." Shows which sources are actually useful | Medium | Aggregation query across FactStore + VerificationStore by source domain |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Automatic feed discovery / crawler | Scope creep. Feed management is configuration, not a feature. Auto-discovery introduces unvetted sources into the credibility pipeline | Manual feed addition with authority score assignment |
| Source credibility "learning" from verification outcomes | Tempting but dangerous. Small sample sizes per source make ML-based credibility adjustment unreliable. A source could be right about geopolitics and wrong about economics -- topic-agnostic learning is invalid | Manual authority adjustment; display per-investigation source stats to inform analyst judgment |
| RSS feed content preview | Viewing raw RSS entries is not analytical work. The pipeline already handles fetching and filtering | Show feed metadata (name, category, tier, health) only |

---

## 6. Investigation History

### Table Stakes

| Feature | Why Expected | Complexity | Backend Dependency |
|---------|--------------|------------|-------------------|
| Investigation list with ID, objective, creation date, status | `ReportStore.list_investigations()` already returns this. Existing HTMX dashboard has investigation list | Low | Existing endpoint; may need pagination |
| Investigation detail view with stats summary | Fact count, classification breakdown, verification stats, report availability. Existing HTMX detail template has this | Low | Existing API endpoints aggregate this data |
| Delete investigation | Storage grows over time. Single user needs to clean up old investigations. Currently no deletion capability | Medium | **NEW**: Delete method on each store (FactStore, ClassificationStore, VerificationStore, ReportStore, ArticleStore) + filesystem cleanup |
| Report link from investigation list | Quick navigation to the most recent report version | Low | `ReportStore.get_latest()` exists |

### Differentiators

| Feature | Value Proposition | Complexity | Backend Dependency |
|---------|-------------------|------------|-------------------|
| Investigation status badge (running/completed/failed/partial) | Multiple investigations may exist in various states. Currently no explicit status tracking -- inferred from which stores have data | Low | **NEW**: Investigation metadata store with explicit status enum |
| Side-by-side investigation comparison | Compare findings from two investigations on the same or related topics. "What changed between my January and March analyses of X?" | High | **NEW**: Diff logic comparing `AnalysisSynthesis` objects (key judgments, confidence levels, fact counts) |
| Investigation tagging/categorization | Organize investigations by topic (e.g., "China-Taiwan", "Ukraine", "Semiconductors"). Personal taxonomy | Medium | **NEW**: Tags field on investigation metadata |
| Export investigation to archive (JSON/SQLite) | `InvestigationExporter` and `InvestigationArchiver` already exist in `database/` package. Need UI trigger | Low | Existing `exporter.export()` and `archive.create_archive()` methods |
| Timeline view across investigations | Chronological view of all investigations, showing when they were run and their primary findings. Useful for tracking how understanding of a topic evolves | Medium | Aggregate `created_at` + `executive_summary` across investigation metadata |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Investigation forking / branching | Implies version control semantics on intelligence analysis. Investigations are independent runs with independent data. "Fork investigation and re-run with different parameters" is just "launch new investigation" | Launch new investigation with similar parameters; provide "clone settings" button |
| Collaborative investigation sharing | Single-user system. Multi-user sharing requires auth, access control, conflict resolution -- massive scope expansion | Export to file for manual sharing |
| Full-text search across all investigations | Expensive to index, marginal utility for single user with <100 investigations. Investigation objectives are short and browsable | Filter by tag/category; search by objective substring |

---

## 7. Configuration Profiles

### Table Stakes

| Feature | Why Expected | Complexity | Backend Dependency |
|---------|--------------|------------|-------------------|
| Model selection with current model display | `AnalysisConfig.synthesis_model` currently set via env var. Must be viewable and changeable from UI | Low | Read/write `AnalysisConfig` fields |
| Temperature control | `AnalysisConfig.temperature` (0.0-1.0). Lower = more factual, higher = more creative/hallucination-prone. Analyst must understand the tradeoff | Low | Existing field; slider UI |
| API key status indicator (configured/missing, not the key itself) | Prevent confusing pipeline failures. "Gemini API: Configured" vs "OpenRouter API: Missing" | Low | Check env vars; display status only |
| Token budget display | `max_tokens_per_section` affects analysis quality. Show current value and what it means | Low | Existing field |

### Differentiators

| Feature | Value Proposition | Complexity | Backend Dependency |
|---------|-------------------|------------|-------------------|
| Named configuration profiles (save/load/switch) | "Quick & cheap" profile (Flash model, low temp, 10K tokens) vs "Deep analysis" profile (Pro model, higher token budget). Avoids re-configuring for different investigation types | Medium | **NEW**: Profile storage (JSON file) mapping name -> AnalysisConfig fields |
| Cost estimation per profile | "Quick profile: ~$0.05/investigation. Deep profile: ~$0.50/investigation." Based on model pricing and expected token volume | Medium | Token cost lookup table; estimation heuristic |
| Model tier explanation | Not all users know the difference between Gemini Flash and Pro. Brief explanation: "Flash: faster, cheaper, good for initial scans. Pro: slower, more expensive, better reasoning for complex analysis" | Low (frontend) | Static content |
| Per-model capability notes (context window, pricing, strengths) | Inform model selection decisions | Low (frontend) | Static content or fetched from model registry |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Per-agent model selection (different model for extraction vs classification vs synthesis) | The pipeline already has model tiering logic internally (Flash for high-volume, Pro for reasoning). Exposing per-agent model selection to the UI creates combinatorial complexity and makes cost estimation impossible | Single "quality tier" selector (quick/balanced/deep) that maps to internal model allocation |
| Runtime environment variable editing | Security risk. `.env` file should be edited directly, not through a web UI that could expose secrets | Display configured status only; link to documentation for env setup |
| Plugin/extension system for custom agents | Massive architectural scope. The agent system is Python code, not a plugin platform | Future concern; out of scope for v2.0 |

---

## Feature Dependencies

```
Investigation Launch UI
    |
    v
Live Progress Dashboard (requires SSE infrastructure)
    |
    v
[Pipeline execution completes]
    |
    +---> Report Viewer (requires report data)
    |
    +---> Knowledge Graph Visualization (requires graph data)
    |
    +---> Investigation History (requires investigation metadata)

Source Management (independent -- configuration, not execution)
Configuration Profiles (independent -- settings, not execution)

Cross-cutting:
  - Fact drill-down (used by Report Viewer AND Knowledge Graph)
  - Source stats (used by Source Management AND Report Viewer)
```

### Critical Path Dependencies on Backend

| Frontend Feature | Backend Prerequisite | Exists? |
|-----------------|---------------------|---------|
| Investigation launch | POST /api/investigations endpoint | NO -- must build |
| Live progress | SSE endpoint streaming runner events | NO -- must build |
| Report viewer | GET /api/reports/{id} returning structured data | Partial -- HTMX template exists, need JSON API |
| Knowledge graph | GET /api/graph/{investigation_id} returning node-link JSON | NO -- QueryResult.to_dict() exists but no API route |
| Source management | GET /api/sources, PUT /api/sources/{domain} | NO -- config is Python dicts, need API layer |
| Investigation history | GET /api/investigations | Partial -- HTMX route exists, need JSON API |
| Configuration profiles | GET/PUT /api/config/profiles | NO -- config is env vars, need profile storage |
| Fact detail/drill-down | GET /api/facts/{fact_id} with joins | Partial -- fact list exists, need single-fact detail |

---

## MVP Recommendation

For MVP, prioritize in this order:

1. **Investigation Launch UI** (table stakes only) -- Without this, the frontend cannot trigger the pipeline
2. **Live Progress Dashboard** (table stakes only) -- Without this, the user has no visibility during the 5-15 minute pipeline run
3. **Report Viewer** (table stakes + fact drill-down differentiator) -- This is the primary output; fact drill-down is the single most valuable analytical feature
4. **Investigation History** (table stakes only) -- Navigation and management of past work
5. **Knowledge Graph Visualization** (table stakes + filtering differentiators) -- High analytical value but depends on graph data existing

Defer to post-MVP:
- **Source Management**: Configuration works via Python files today; UI is convenience, not blocker
- **Configuration Profiles**: `.env` + CLI flags work for single user; nice-to-have, not launch-blocking
- **Report diff between versions**: Complex text diffing; low frequency need
- **Side-by-side investigation comparison**: High complexity, requires diff logic for analytical objects
- **Cost estimation**: Useful but requires maintaining pricing data that changes frequently

---

## Sources

- Existing codebase analysis: `runner.py`, `serve.py`, `analysis/schemas.py`, `data_management/schemas/fact_schema.py`, `data_management/graph/schema.py`, `config/analysis_config.py`, `config/source_credibility.py`, `config/feed_config.py`, `dashboard/` templates and routes
- [OSINT Dashboard Patterns](https://knowlesys.com/en/osint/osint-dashboard.html) -- Commercial OSINT dashboard features
- [Maltego vs SpiderFoot Comparison](https://osintteam.blog/spiderfoot-vs-maltego-for-osint-research-cases-a1e0c4d63aa2) -- OSINT tool interface patterns
- [SSE with FastAPI and React](https://www.softgrade.org/sse-with-fastapi-react-langgraph/) -- SSE implementation pattern for LLM agent pipelines
- [Streaming APIs with FastAPI and Next.js](https://dev.to/sahan/streaming-apis-with-fastapi-and-nextjs-part-1-3ndj) -- FastAPI-to-Next.js SSE integration
- [react-force-graph](https://github.com/vasturiano/react-force-graph) -- 2D/3D force-directed graph React component
- [NetworkX JSON Export](https://networkx.org/documentation/stable/reference/readwrite/json_graph.html) -- NetworkX to node-link JSON format
- [Knowledge Graph Visualization Guide](https://datavid.com/blog/knowledge-graph-visualization) -- KG visualization patterns
- [Cambridge Intelligence KG Visualization](https://cambridge-intelligence.com/use-cases/knowledge-graphs/) -- Enterprise KG visualization patterns
- [Wizard UI Pattern](https://www.eleken.co/blog-posts/wizard-ui-pattern-explained) -- When to use (and not use) wizards
- [NN/g Wizard Guidelines](https://www.nngroup.com/articles/wizards/) -- Form wizard design recommendations
- [IC Confidence Standards](https://www.cisecurity.org/ms-isac/services/words-of-estimative-probability-analytic-confidences-and-structured-analytic-techniques) -- Intelligence Community estimative language
- [College of Policing Intelligence Report Standards](https://www.college.police.uk/app/intelligence-management/intelligence-report) -- IC report structure
- [Next.js + shadcn/ui Dashboard Template](https://vercel.com/templates/next.js/next-js-and-shadcn-ui-admin-dashboard) -- Dashboard architecture patterns
- [Pipeline Monitoring KPIs](https://www.inetsoft.com/info/data-pipeline-monitoring-dashboard/) -- Pipeline health dashboard metrics
