# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-10)

**Core value:** Automated, accurate extraction and verification of geopolitical facts from diverse open sources with intelligent multi-agent collaboration.
**Current focus:** Phase 7 - Fact Classification System

## Current Position

Phase: 7 of 10 (Fact Classification System)
Plan: 3 of 3 in current phase
Status: In progress
Last activity: 2026-02-03 - Completed 07-03-PLAN.md

Progress: ██████████████████████████████████████████████████████████████████████████████░░░░░░░░░░░░░░░░░░░░░░░ 72.5%

## Performance Metrics

**Velocity:**
- Total plans completed: 29
- Average duration: 22.7 min
- Total execution time: 659 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-foundation | 4/4 | 24 min | 6 min |
| 02-base-agent-architecture | 4/4 | 330 min | 82.5 min |
| 03-planning-orchestration | 3/3 | 146 min | 48.7 min |
| 04-news-crawler | 5/5 | 65 min | 13 min |
| 05-extended-crawler-cohort | 6/6 | 42 min | 7 min |
| 06-fact-extraction-pipeline | 4/4 | 28 min | 7 min |
| 07-fact-classification-system | 3/3 | 24 min | 8 min |

**Recent Trend:**
- Last 5 plans: 06-03 (7 min), 06-04 (4 min), 07-01 (8 min), 07-02 (11 min), 07-03 (5 min)
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

### Deferred Issues

None yet.

### Blockers/Concerns

None yet.

## Session Continuity

Last session: 2026-02-03
Stopped at: Completed 07-03-PLAN.md (Dubious Detection System)
Resume file: .planning/phases/07-fact-classification-system/07-04-PLAN.md

## Phase 7 Progress

Classification system complete (3/3 plans):
- **07-01:** Complete - FactClassification schema, ClassificationStore, FactClassificationAgent shell
- **07-02:** Complete - Credibility scoring formula implementation
- **07-03:** Complete - Dubious detection with Boolean logic gates

Key patterns established:
- Classifications separate from facts (linked by fact_id)
- ImpactTier (critical/less_critical) and DubiousFlag (phantom/fog/anomaly/noise)
- Orthogonal dimensions: impact tier and dubious status independent
- CredibilityBreakdown for full score decomposition
- ClassificationReasoning explains WHY each flag was triggered
- ClassificationHistory for full audit trail
- ClassificationStore with flag-type and tier indexes for Phase 8
- Priority calculation: Impact x Fixability
- NOISE-only excluded from verification queue (batch analysis only)

**Phase 7 Plan 03 adds dubious detection:**
- DubiousDetector with Boolean logic gates (not weighted formulas)
- PHANTOM: hop_count > 2 AND primary_source IS NULL
- FOG: claim_clarity < 0.5 OR vague attribution patterns
- ANOMALY: contradiction_count > 0 (external input)
- NOISE: source_credibility < 0.3 (batch only)
- Fixability scoring for Phase 8 queue prioritization
- 14 vague attribution regex patterns for FOG detection

**Phase 7 Plan 03 deliverable:**
```python
from osint_system.agents.sifters.classification import DubiousDetector, DubiousResult

detector = DubiousDetector()
result = detector.detect(fact_dict, credibility_score=0.5, contradictions=[])
# result.flags: List[DubiousFlag] - which species triggered
# result.reasoning: List[ClassificationReasoning] - why each triggered
# result.fixability_score: 0.0-1.0 - verification priority
```
