---
phase: 06-fact-extraction-pipeline
plan: 01
subsystem: data_management
tags: [pydantic, schemas, fact-extraction, entity-resolution, provenance]

# Dependency graph
requires:
  - phase: 05-extended-crawler-cohort
    provides: Crawler output (articles, documents, social posts) with metadata
provides:
  - ExtractedFact Pydantic model for structured fact output
  - Entity schemas (PERSON, ORG, LOCATION, anonymous sources)
  - Provenance chain models with hop count and source classification
  - QualityMetrics with separate extraction_confidence and claim_clarity
  - TemporalMarker with explicit/inferred/unknown precision
  - 38 comprehensive schema validation tests
affects: [06-02, 06-03, 07-classification, 08-verification, 09-knowledge-graph]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Pydantic model_validator for auto-computed fields (content_hash)
    - Separate orthogonal dimensions for quality metrics
    - Entity markers in text linking to structured objects by ID

key-files:
  created:
    - osint_system/data_management/schemas/__init__.py
    - osint_system/data_management/schemas/entity_schema.py
    - osint_system/data_management/schemas/provenance_schema.py
    - osint_system/data_management/schemas/fact_schema.py
    - tests/data_management/schemas/test_fact_schema.py

key-decisions:
  - "Facts are single assertions, not maximally decomposed atoms"
  - "extraction_confidence and claim_clarity are separate orthogonal fields"
  - "UUID for storage, content hash for exact-match dedup"
  - "Entity clustering without forced resolution"
  - "Full provenance chains with hop count AND source type (separate dimensions)"
  - "Denials represented as underlying claim with assertion_type='denial'"

patterns-established:
  - "Entity markers in claim text: [E1:Putin] visited [E2:Beijing]"
  - "Temporal markers with precision: T1:March 2024, precision:month, temporal_precision:explicit"
  - "Schema version field for forward compatibility"
  - "model_validator for auto-computing content_hash from claim.text"

# Metrics
duration: 12min
completed: 2026-02-03
---

# Phase 6 Plan 1: Fact Extraction Schema Summary

**Pydantic schemas for ExtractedFact, Entity, Provenance with full CONTEXT.md decisions encoded: separate confidence dimensions, UUID+hash dedup, entity clustering without forced resolution**

## Performance

- **Duration:** 12 min
- **Started:** 2026-02-03T00:00:00Z
- **Completed:** 2026-02-03T00:12:00Z
- **Tasks:** 3
- **Files modified:** 7

## Accomplishments

- ExtractedFact schema with auto-computed content hash and UUID
- Entity schemas for PERSON, ORG, LOCATION, ANONYMOUS_SOURCE with clustering
- Provenance chains capturing full attribution depth with separate hop_count and source_type
- QualityMetrics with orthogonal extraction_confidence and claim_clarity dimensions
- 38 comprehensive tests validating all CONTEXT.md requirements

## Task Commits

Each task was committed atomically:

1. **Task 1+2: Create schemas** - `99ec206` (feat)
   - entity_schema.py, provenance_schema.py, fact_schema.py, __init__.py
2. **Task 3: Add schema tests** - `3bad414` (test)
   - tests/data_management/schemas/test_fact_schema.py

## Files Created/Modified

- `osint_system/data_management/schemas/__init__.py` - Package exports all schema types
- `osint_system/data_management/schemas/entity_schema.py` - Entity, EntityType, AnonymousSource, EntityCluster (161 lines)
- `osint_system/data_management/schemas/provenance_schema.py` - Provenance, AttributionHop, SourceType, SourceClassification (143 lines)
- `osint_system/data_management/schemas/fact_schema.py` - ExtractedFact, Claim, TemporalMarker, QualityMetrics, etc. (327 lines)
- `tests/data_management/__init__.py` - Test package marker
- `tests/data_management/schemas/__init__.py` - Test package marker
- `tests/data_management/schemas/test_fact_schema.py` - 38 comprehensive validation tests

## Decisions Made

All decisions followed CONTEXT.md specifications:

1. **Separate confidence dimensions** - extraction_confidence (LLM parsing accuracy) and claim_clarity (source text ambiguity) are separate fields, not combined into composite score
2. **UUID + content hash** - UUIDs for storage identity, SHA256 content hash for exact-match deduplication
3. **Entity clustering** - EntityCluster groups likely-same entities without forcing premature resolution
4. **Denial representation** - Denials are underlying claim with assertion_type="denial", not negation flags
5. **Full provenance chains** - AttributionHop list with hop count AND source type as separate orthogonal fields

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Schema package ready for FactExtractionAgent consumption:
- Import: `from osint_system.data_management.schemas import ExtractedFact, Claim`
- Minimal: `fact = ExtractedFact(claim=Claim(text="..."))`
- Full: All optional fields supported and validated

Ready for:
- 06-02: FactExtractionAgent implementation
- 06-03: Deduplication/consolidation logic
- 06-04: Prompt engineering for extraction

---
*Phase: 06-fact-extraction-pipeline*
*Completed: 2026-02-03*
