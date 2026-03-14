# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-10)

**Core value:** Automated, accurate extraction and verification of geopolitical facts from diverse open sources with intelligent multi-agent collaboration.
**Current focus:** Phase 10 Analysis & Reporting Engine - Plan 04 complete

## Current Position

Phase: 10 of 10 (Analysis & Reporting Engine)
Plan: 4 of 5 in current phase
Status: In progress
Last activity: 2026-03-14 - Completed 10-04-PLAN.md

Progress: █████████████████████████████████████████████████████████████████████████████████████████████████████████░ 98%

## Performance Metrics

**Velocity:**
- Total plans completed: 43
- Average duration: 18.3 min
- Total execution time: 786 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-foundation | 4/4 | 24 min | 6 min |
| 02-base-agent-architecture | 4/4 | 330 min | 82.5 min |
| 03-planning-orchestration | 3/3 | 146 min | 48.7 min |
| 04-news-crawler | 5/5 | 65 min | 13 min |
| 05-extended-crawler-cohort | 6/6 | 42 min | 7 min |
| 06-fact-extraction-pipeline | 4/4 | 28 min | 7 min |
| 07-fact-classification-system | 4/4 | 34 min | 8.5 min |
| 08-verification-loop | 4/4 | 60 min | 15 min |
| 09-knowledge-graph-integration | 5/5 | 33 min | 6.6 min |
| 10-analysis-reporting-engine | 4/5 | 24 min | 6 min |

**Recent Trend:**
- Last 5 plans: 09-05 (10 min), 10-01 (7 min), 10-02 (5 min), 10-04 (6 min)
- Trend: Consistent sub-10min pace; reporting pipeline built efficiently

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- LangChain/LangGraph framework selected for agent orchestration
- News sources prioritized for initial crawlers
- Fully automated verification loop planned
- Knowledge graph included in beta scope
- Gemini model tiering strategy defined
- Use structlog for structured logging instead of loguru alone
- Make MCP integration optional to maintain flexibility
- Use async context manager pattern for clean resource management
- Use singleton pattern for MessageBus to ensure single hub instance
- Implement capability indexing for O(1) agent lookup
- Use Pydantic for message validation and type safety
- Use keyword matching for routing logic instead of LLM-based routing initially
- Implement fallback to SimpleAgent when primary workflow fails
- Build graph dynamically based on available agents in registry
- Use @server.list_tools() pattern for MCP 1.25.0 compatibility
- Use add_async_listener() for aiopubsub 3.0.0 API
- Create simplified integration tests for actual API validation
- Async-first architecture with sync wrappers for LangGraph integration
- Implement fallback decomposition strategy when Gemini unavailable
- Enforce hard refinement limits to prevent infinite loops
- Use 40% finding count + 60% confidence weighting for signal strength
- Use heap-based priority queue for efficient task ordering (O(log n))
- Multi-factor priority scoring: keyword 40%, recency 20%, retry penalty 20%, diversity 20%
- Four-component signal strength: keyword 30%, entity 20%, credibility 30%, density 20%
- Track four coverage dimensions: source diversity, geographic, temporal, topical
- Novelty-based diminishing returns: source 30%, entity 40%, content 30%
- Use RefinementEngine for iterative investigation improvements
- Limit hierarchy to 2 levels to prevent complexity explosion
- Track conflicts without attempting premature resolution
- Hard limit of 7 refinement iterations to prevent infinite loops
- Three-layer deduplication: URL, content hash, semantic similarity
- 0.85 similarity threshold for semantic deduplication
- Exhaustive mode returns all relevant content regardless of age
- Complete metadata extraction including credibility and geographic context
- Investigation-scoped storage with investigation_id as primary key
- In-memory storage with optional JSON persistence for beta
- Message bus topics: investigation.start, crawler.fetch, crawler.complete, crawler.failed
- Automatic crawler triggering when Planning Agent detects news-related subtasks
- URL-based indexing for O(1) duplicate detection across investigations
- yarl for URL normalization (immutable URLs, RFC compliance)
- Domain-based authority: wire services 0.9, .gov/.edu 0.85, .org 0.7, social 0.3
- Investigation-scoped deduplication allows same URL in different investigations
- Entity-based context sharing with message bus broadcast on 'context.update' topic
- Reddit authority score: 0.3 for user-generated content
- Reddit quality thresholds: score > 10, comments > 5 for inclusion
- Follow comment threads for high-value posts (score > 100)
- Reddit message bus topics: reddit.crawl, reddit.complete, reddit.failed
- pypdfium2 as primary PDF extractor (best quality), pdfplumber for table fallback
- trafilatura for web content extraction (F1 0.958)
- Three-stage extraction fallback: trafilatura (precision) -> trafilatura (recall) -> BeautifulSoup
- Minimum content length 500 chars for quality filtering
- Domain-based authority scoring: .gov/.edu 0.9, .org 0.7, default 0.5
- Keyword-based crawler selection in Planning Agent (not LLM-based)
- Parallel crawler execution with asyncio.gather for efficiency
- Source type detection from task description and objective keywords
- Default to news + web crawlers when no specific sources detected
- Facts are single assertions, not maximally decomposed atoms
- extraction_confidence and claim_clarity are separate orthogonal fields
- UUID for storage, content hash for exact-match dedup
- Entity clustering without forced resolution
- Full provenance chains with hop count AND source type (separate dimensions)
- Denials represented as underlying claim with assertion_type='denial'
- Entity markers [E1:name] in claim text linking to structured entity objects
- Default min_confidence=0.0 (include all facts, downstream filters)
- Lazy Gemini client initialization via property accessor
- Chunk size 12000 chars for long document processing
- Entity type normalization (ORG/LOC/PER/GPE -> EntityType enum)
- O(1) indexes for fact_id, content_hash, and source_id in FactStore
- Bidirectional variant linking for consistency
- 0.3 semantic threshold for consolidation (when embeddings enabled)
- Provenance merging tracks additional_sources for corroboration
- Lazy pipeline component initialization via property accessors
- Concurrent batch extraction using asyncio.gather
- Failed extractions don't stop pipeline (partial recovery)
- Article title prepended to content for extraction context
- Classifications separate from facts (facts immutable, classifications mutable)
- Impact tier and dubious flags are orthogonal dimensions
- Taxonomy of doubt: phantom/fog/anomaly/noise species
- NOISE-only facts excluded from individual verification queue (batch analysis)
- Proximity decay factor: 0.7^hop for exponential decay
- Echo dampening alpha: 0.2 for logarithmic dampening (botnet-proof)
- Precision weights: entity 30%, temporal 30%, quote 20%, document 20%
- Single-source scoring in Phase 7 (full multi-source in Phase 8)
- Boolean logic gates for dubious detection (not weighted formulas)
- Fixability priority: FOG (0.9) > ANOMALY (0.8) > PHANTOM (0.6) > NOISE (0.1)
- Pure NOISE facts get 0.0 fixability (batch analysis only)
- 14 compiled regex patterns for vague attribution detection
- Impact threshold 0.6 combined score for CRITICAL tier
- Entity (50%) + Event (50%) weights for impact calculation
- Context boost capped at 0.2 maximum
- Four contradiction types: negation, numeric, temporal, attribution
- Two-pass classification for anomaly detection (detect contradictions first)
- 3-query limit per fact: entity_focused -> exact_phrase -> broader_context
- Short-circuit on CONFIRMED/REFUTED (don't waste remaining queries)
- Authority thresholds: HIGH_AUTHORITY >= 0.85, REFUTATION >= 0.7
- Confidence boosts: wire_service +0.3, official +0.25, news +0.2, social +0.1
- 2+ independent sources required for lower-authority confirmation
- Origin dubious flags saved to history before clearing on reclassification
- ANOMALY resolution: temporal contradictions -> SUPERSEDED, factual -> REFUTED
- CRITICAL tier facts skip reclassification until human review completed
- Serper API for verification searches with graceful mock mode (empty when no key)
- VerificationStore: investigation-scoped with human review tracking
- Automatic verification via VerificationPipeline event handler
- asyncio.Semaphore for batch concurrency control (configurable batch_size)
- 13 edge types: structural (MENTIONS/SOURCED_FROM/PART_OF/HAS_CLASSIFICATION), semantic (CORROBORATES/CONTRADICTS/RELATED_TO/ATTRIBUTED_TO/CAUSES), temporal (PRECEDES/SUPERSEDES), spatial (LOCATED_AT), verification (VERIFIED_BY)
- Node ID format: {label}:{natural_key} for global uniqueness
- Edge weight formula: base + authority*0.3 + min(0.2, 0.05*log1p(count)) - min(0.2, days/365*0.2), clamped [0,1]
- GraphConfig uses from_env() classmethod (not BaseSettings) to avoid requiring GEMINI_API_KEY
- LLM relationship extraction gated behind GRAPH_LLM_EXTRACTION env var (default off)
- Label allowlist (Fact/Entity/Source/Investigation/Classification) for safe Cypher f-string injection
- Relationship type allowlist (EdgeType enum values) for Cypher injection prevention
- NetworkX stub node creation on merge_relationship (matches Neo4j MERGE behavior)
- Undirected graph view for shortest path finding (bidirectional entity traversal)
- Batch relationship grouping by (from_label, to_label, rel_type) for efficient UNWIND
- Entity resolution uses exact canonical name match (resolution_confidence=1.0)
- Cross-investigation detection via dict interface (decoupled from adapter)
- LLM-inferred edges use lower base weight (0.4) vs rule-based (0.5+)
- Source nodes deduplicated by source_id within mapper session
- Union-find for corroboration cluster counting (no subgraph construction needed)
- Same-entity shortest path returns single-node result with path_length=0
- Edge exclusion on investigation-filtered entity network results (no dangling refs)
- Timeline fact deduplication via seen_facts set
- Default ingestion filters to CONFIRMED + SUPERSEDED only (separate method for all statuses)
- Bulk ingestion uses single FactMapper for cross-fact entity resolution
- GraphPipeline lazy-inits all components from config (matches VerificationPipeline pattern)
- GraphEdge weight and cross_investigation stored as edge properties through batch merge
- Entity IDs in SQLite use canonical:type composite key for global uniqueness (not per-fact E1/E2 markers)
- Schema v1.0 uses TEXT columns for JSON-serialized complex fields for maximum SQLite tool portability
- Sources table derived from fact provenance at export time (not separately stored)
- Archive dubious_count aggregates unverifiable + pending + in_progress verification statuses
- TYPE_CHECKING import for GraphPipeline in analysis layer to avoid cascading Settings singleton
- InvestigationSnapshot as single typed container for all investigation data
- DataAggregator parallel async fetching from all stores with asyncio.gather
- AnalysisConfig.from_env() with ANALYSIS_ prefix env vars
- Timeline confidence derived from classification credibility_score thresholds
- Source inventory enriched from verification evidence authority scores
- token_estimate() heuristic: len(json) / 4
- Jinja2 Environment with trim_blocks and lstrip_blocks for clean Markdown template output
- Embedded CSS via <style> tag in PDFRenderer (avoids WeasyPrint file path issues)
- WeasyPrint graceful fallback: render_pdf() returns None when unavailable
- ReportStore persistence excludes markdown_content for file size efficiency
- SHA256 content hashing for report version deduplication

### Deferred Issues

None yet.

### Blockers/Concerns

None yet.

## Session Continuity

Last session: 2026-03-14
Stopped at: Completed 10-04-PLAN.md (Report Generation)
Resume file: None

## Phase 10 In Progress

Analysis & Reporting Engine (4/5 plans complete):
- **10-01:** Complete - Analysis schemas (8 Pydantic models), DataAggregator, AnalysisConfig, Phase 10 deps
- **10-02:** Complete - InvestigationExporter (SQLite) + InvestigationArchive (JSON), 19 tests
- **10-03:** Pending - LLM synthesis engine
- **10-04:** Complete - ReportGenerator (Jinja2), PDFRenderer (mistune + WeasyPrint), ReportStore (versioned), 32 tests
- **10-05:** Pending - Web dashboard (FastAPI + HTMX)

Key patterns established in 10-01:
- InvestigationSnapshot: single typed container for all investigation data
- DataAggregator: parallel async fetch from all stores into InvestigationSnapshot
- AnalysisConfig: from_env() with ANALYSIS_ prefix (matches GraphConfig pattern)
- 8 analysis output models: ConfidenceAssessment, KeyJudgment, AlternativeHypothesis, ContradictionEntry, TimelineEntry, SourceInventoryEntry, InvestigationSnapshot, AnalysisSynthesis

**Phase 10-01 Entry Points:**
```python
from osint_system.analysis import (
    DataAggregator,
    AnalysisSynthesis,
    InvestigationSnapshot,
    KeyJudgment,
    AlternativeHypothesis,
    ConfidenceAssessment,
)
from osint_system.config.analysis_config import AnalysisConfig

# Aggregate all investigation data
aggregator = DataAggregator(fact_store, classification_store, verification_store, graph_pipeline)
snapshot = await aggregator.aggregate("inv-123")
print(snapshot.fact_count, snapshot.confirmed_count, snapshot.token_estimate())

# Load config
config = AnalysisConfig.from_env()
print(config.synthesis_model, config.temperature)
```

Key patterns established in 10-02:
- Store aggregation: export layer reads from multiple stores to create unified output
- Schema versioning: archive files include schema_version for forward compatibility
- Static load/validate: InvestigationArchive.load_archive() as static method for standalone validation

**Phase 10-02 Entry Points:**
```python
from osint_system.database import InvestigationExporter, InvestigationArchive

# SQLite export
exporter = InvestigationExporter(fact_store, classification_store, verification_store)
db_path = await exporter.export("inv-123")
# -> queryable .db file with 6 normalized tables

# JSON archive
archive = InvestigationArchive(fact_store, classification_store, verification_store)
archive_path = await archive.create_archive("inv-123")
# -> self-contained JSON with schema versioning and statistics

# Load and validate archive
data = await InvestigationArchive.load_archive(archive_path)
```

Key patterns established in 10-04:
- Jinja2 FileSystemLoader with built-in templates/ directory
- _build_template_context() flattens Pydantic models to dicts for Jinja2
- PDFRenderer embeds CSS via <style> tag (self-contained HTML)
- SHA256 content hashing for version deduplication in ReportStore
- asyncio.to_thread() for all blocking I/O (file writes, PDF rendering)

**Phase 10-04 Entry Points:**
```python
from osint_system.reporting import ReportGenerator, PDFRenderer, ReportStore

# Generate Markdown report from AnalysisSynthesis
generator = ReportGenerator()
markdown = generator.generate_markdown(synthesis)
await generator.save_markdown(markdown, "reports/inv-123-v1.md")

# Generate executive brief only
brief = generator.generate_executive_brief(synthesis)

# Render PDF (returns None if WeasyPrint unavailable)
renderer = PDFRenderer()
pdf_path = await renderer.render_pdf(markdown, "reports/inv-123-v1.pdf")

# Track report versions
store = ReportStore(output_dir="reports/")
record = await store.save_report("inv-123", markdown, synthesis=synthesis)
print(record.version, record.content_hash)
changed = await store.has_changed("inv-123", new_markdown)
```
