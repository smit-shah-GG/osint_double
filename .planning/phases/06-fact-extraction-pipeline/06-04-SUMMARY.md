---
phase: 06-fact-extraction-pipeline
plan: 04
subsystem: pipelines
tags: [pipeline, orchestration, extraction, integration, batch-processing]

# Dependency graph
requires:
  - phase: 06-01
    provides: ExtractedFact, Entity, Provenance schemas
  - phase: 06-02
    provides: FactExtractionAgent for LLM extraction
  - phase: 06-03
    provides: FactStore and FactConsolidator for dedup/storage
provides:
  - ExtractionPipeline orchestrating article-to-fact flow
  - PipelineStats dataclass for tracking progress
  - Batch processing with configurable batch size
  - Article-to-content format transformation
  - Single article and investigation processing modes
  - 33 comprehensive pipeline tests
affects: [07-classification, 08-verification, 09-knowledge-graph]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Lazy component initialization via property accessors
    - Concurrent batch processing with asyncio.gather
    - Error handling with partial recovery
    - Investigation-scoped processing

key-files:
  created:
    - osint_system/pipelines/__init__.py
    - osint_system/pipelines/extraction_pipeline.py
    - tests/pipelines/__init__.py
    - tests/pipelines/test_extraction_pipeline.py

key-decisions:
  - "Lazy initialization avoids API key requirement at import time"
  - "Concurrent extraction within batches via asyncio.gather"
  - "Failed extractions don't stop pipeline (partial recovery)"
  - "Consolidation failure returns original facts (graceful degradation)"
  - "Article title prepended to content for context in extraction"

patterns-established:
  - "Pipeline property accessors for lazy component initialization"
  - "PipelineStats dataclass for tracking metrics"
  - "Article-to-content transformation mapping store formats"
  - "Error tracking in stats.errors list"

# Metrics
duration: 4min
completed: 2026-02-03
---

# Phase 6 Plan 4: ExtractionPipeline Summary

**ExtractionPipeline wiring ArticleStore to FactExtractionAgent to FactConsolidator with batch processing, concurrent extraction, and error recovery**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-02T19:12:20Z
- **Completed:** 2026-02-02T19:16:17Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- ExtractionPipeline class orchestrating complete article-to-fact flow
- Lazy component initialization via property accessors (avoids import-time failures)
- Configurable batch processing (default batch_size=10)
- Concurrent extraction within batches using asyncio.gather
- Article-to-content transformation mapping ArticleStore to FactExtractionAgent format
- Single article and full investigation processing modes
- Error handling with partial recovery (failed articles don't stop pipeline)
- PipelineStats dataclass tracking progress and errors
- 33 comprehensive tests covering all functionality

## Task Commits

Each task was committed atomically:

1. **Task 1: Create ExtractionPipeline** - `fa90e9a` (feat)
   - osint_system/pipelines/__init__.py, extraction_pipeline.py (479 lines)
2. **Task 2: Add pipeline tests** - `74238c7` (test)
   - tests/pipelines/__init__.py, test_extraction_pipeline.py (33 tests)

## Files Created/Modified

- `osint_system/pipelines/__init__.py` - Package exports ExtractionPipeline
- `osint_system/pipelines/extraction_pipeline.py` - Complete pipeline implementation (479 lines)
- `tests/pipelines/__init__.py` - Test package marker
- `tests/pipelines/test_extraction_pipeline.py` - 33 comprehensive tests

## Key Implementation Details

### Pipeline Flow
```
ArticleStore -> FactExtractionAgent -> FactConsolidator -> FactStore
      |                |                      |                |
  read articles   extract facts      deduplicate/link     persist
```

### Article-to-Content Transformation
```python
# ArticleStore format:
{
    'url': 'https://...',
    'title': 'Article Title',
    'content': 'Full text...',
    'source': {'name': 'Reuters', 'type': 'wire_service'},
    'published_date': '2024-03-15T...'
}

# Transformed to extraction format:
{
    'text': 'Article Title\n\nFull text...',
    'source_id': 'https://...',
    'source_type': 'wire_service',
    'publication_date': '2024-03-15',
    'metadata': {...}
}
```

### Usage
```python
from osint_system.pipelines import ExtractionPipeline

# With defaults (auto-creates components)
pipeline = ExtractionPipeline()
result = await pipeline.process_investigation('inv-001')

# With custom batch size
pipeline = ExtractionPipeline(batch_size=25)

# With injected mocks for testing
pipeline = ExtractionPipeline(
    article_store=mock_store,
    extraction_agent=mock_agent,
)
```

## Decisions Made

1. **Lazy initialization** - Components created on first access via property, not at init. Avoids Gemini API key requirement at import time.
2. **Concurrent batch processing** - Uses asyncio.gather for concurrent extraction within batches. Significantly faster than sequential.
3. **Partial recovery** - Failed article extraction doesn't stop pipeline. Errors tracked in stats.errors list.
4. **Graceful consolidation degradation** - If consolidation fails, original facts returned unchanged.
5. **Title prepending** - Article title prepended to content with newlines for better extraction context.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - pipeline uses components already configured from previous phases.

## Phase 6 Complete

This completes Phase 6: Fact Extraction Pipeline. All four plans executed:

1. **06-01:** Pydantic schemas (ExtractedFact, Entity, Provenance)
2. **06-02:** FactExtractionAgent with Gemini prompts
3. **06-03:** FactStore and FactConsolidator for dedup/storage
4. **06-04:** ExtractionPipeline bridging crawler output to fact extraction

**Full pipeline usage:**
```python
from osint_system.pipelines import ExtractionPipeline

pipeline = ExtractionPipeline()
result = await pipeline.process_investigation('my-investigation')

print(f"Articles processed: {result['articles_processed']}")
print(f"Facts extracted: {result['facts_extracted']}")
print(f"Facts consolidated: {result['facts_consolidated']}")
```

Ready for:
- Phase 7: Fact Classification (critical/less-than-critical/dubious)
- Phase 8: Verification loop for dubious facts
- Phase 9: Knowledge graph storage

---
*Phase: 06-fact-extraction-pipeline*
*Completed: 2026-02-03*
