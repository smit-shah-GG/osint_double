# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-10)

**Core value:** Automated, accurate extraction and verification of geopolitical facts from diverse open sources with intelligent multi-agent collaboration.
**Current focus:** Phase 6 Complete - Ready for Phase 7

## Current Position

Phase: 6 of 10 (Fact Extraction Pipeline)
Plan: 4 of 4 in current phase
Status: Phase complete
Last activity: 2026-02-03 - Completed 06-04-PLAN.md

Progress: ██████████████████████████████████████████████████████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ 65%

## Performance Metrics

**Velocity:**
- Total plans completed: 26
- Average duration: 24.4 min
- Total execution time: 635 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-foundation | 4/4 | 24 min | 6 min |
| 02-base-agent-architecture | 4/4 | 330 min | 82.5 min |
| 03-planning-orchestration | 3/3 | 146 min | 48.7 min |
| 04-news-crawler | 5/5 | 65 min | 13 min |
| 05-extended-crawler-cohort | 6/6 | 42 min | 7 min |
| 06-fact-extraction-pipeline | 4/4 | 28 min | 7 min |

**Recent Trend:**
- Last 5 plans: 05-06 (8 min), 06-01 (12 min), 06-02 (5 min), 06-03 (7 min), 06-04 (4 min)
- Trend: Fast execution

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

### Deferred Issues

None yet.

### Blockers/Concerns

None yet.

## Session Continuity

Last session: 2026-02-03
Stopped at: Completed 06-04-PLAN.md (ExtractionPipeline)
Resume file: None (Phase 6 complete)

## Phase 6 Complete

Fact extraction pipeline completed:
- **06-01:** Complete - Pydantic schemas (ExtractedFact, Entity, Provenance)
- **06-02:** Complete - FactExtractionAgent with Gemini prompts
- **06-03:** Complete - FactStore and FactConsolidator for dedup/storage
- **06-04:** Complete - ExtractionPipeline bridging crawler output to fact extraction

Key patterns established:
- Entity markers in claim text: [E1:Putin] visited [E2:Beijing]
- Temporal markers with precision: T1:March 2024, precision:month, temporal_precision:explicit
- Schema version field for forward compatibility
- model_validator for auto-computing content_hash from claim.text
- BaseSifter.sift() abstract method for all analytical agents
- Lazy Gemini client initialization via property accessor
- Entity type normalization: ORG/LOC/PER/GPE -> standard EntityType enum
- FactStore follows ArticleStore patterns for investigation scoping
- Bidirectional variant linking for consistency
- ConsolidationStats dataclass for tracking dedup metrics
- ExtractionPipeline lazy component initialization

**Phase 6 deliverable:**
```python
from osint_system.pipelines import ExtractionPipeline

pipeline = ExtractionPipeline()
result = await pipeline.process_investigation('my-investigation')
# Articles from ArticleStore -> FactExtractionAgent -> FactConsolidator -> FactStore
```
