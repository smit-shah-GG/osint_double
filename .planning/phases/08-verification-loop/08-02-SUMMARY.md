---
phase: 08-verification-loop
plan: 02
subsystem: verification
tags: [query-generation, species-specialized, phantom, fog, anomaly]

requires:
  - phase: 08-01
    provides: "VerificationQuery schema, DubiousFlag enum"
provides:
  - "QueryGenerator class with species-specialized query generation"
  - "PHANTOM source-chain queries (entity_focused, exact_phrase, broader_context)"
  - "FOG clarity-seeking queries (vague quantity/temporal detection, wire service fallback)"
  - "ANOMALY compound queries (temporal_context, authority_arbitration, clarity_enhancement)"
affects: [08-verification-loop, 08-04]

tech-stack:
  added: []
  patterns:
    - "Compiled regex patterns for vague language detection"
    - "Async generate_queries dispatching to sync species-specific generators"
    - "Flag-based dispatch with NOISE exclusion"

key-files:
  created:
    - "osint_system/agents/sifters/verification/query_generator.py"
    - "tests/agents/sifters/verification/test_query_generator.py"
  modified:
    - "osint_system/agents/sifters/verification/__init__.py"

key-decisions:
  - "Combined Tasks 1+2 into single file since all strategies share helpers"
  - "NOISE flag skipped in iteration loop, not just at top-level (supports mixed PHANTOM+NOISE)"
  - "Compiled regex patterns at module level for vague quantity and temporal detection"

duration: 10min
completed: 2026-02-11
---

# Phase 8 Plan 02: Species-Specialized Query Generation Summary

**QueryGenerator with PHANTOM/FOG/ANOMALY strategies, 3-query limit per fact, 36 passing tests**

## Performance

- **Duration:** 10 min
- **Started:** 2026-02-11T04:02:02Z
- **Completed:** 2026-02-11T04:36:00Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- QueryGenerator class with species-specialized query generation per CONTEXT.md
- PHANTOM: source-chain queries (entity_focused, exact_phrase, broader_context)
- FOG: clarity-seeking queries with vague quantity/temporal detection and wire service fallback
- ANOMALY: compound queries (temporal_context, authority_arbitration, clarity_enhancement)
- NOISE-only facts excluded; NOISE flags skipped in multi-flag iteration
- 3-query limit per fact enforced via max_queries parameter
- 36 comprehensive tests covering all strategies, edge cases, and variant validation

## Task Commits

1. **Tasks 1+2: Implement QueryGenerator with all strategies** - `edeacbf` (feat)
2. **Task 3: Add comprehensive tests and export** - `4a68215` (test)

## Files Created/Modified
- `osint_system/agents/sifters/verification/query_generator.py` - QueryGenerator (379 lines)
- `tests/agents/sifters/verification/test_query_generator.py` - 36 tests
- `osint_system/agents/sifters/verification/__init__.py` - Added QueryGenerator export
- `tests/agents/sifters/verification/__init__.py` - Test package init

## Decisions Made
- Combined PHANTOM + FOG + ANOMALY into single implementation commit (strategies share entity/claim extraction helpers)
- Used compiled regex at module level for `_VAGUE_QUANTITY_PATTERNS` and `_VAGUE_TEMPORAL_PATTERNS`
- NOISE flag skipped per-flag in loop (not just via `is_noise` check) to handle mixed flags like PHANTOM+NOISE

## Deviations from Plan

Minor: Tasks 1 and 2 combined into a single commit since all three strategies share helpers and were naturally implemented together. No functional deviation.

## Issues Encountered
None

## User Setup Required
None

## Next Phase Readiness
- QueryGenerator ready for VerificationAgent (08-04) to call during verification loop
- All 6 variant types (entity_focused, exact_phrase, broader_context, temporal_context, authority_arbitration, clarity_enhancement) exercised and tested

---
*Phase: 08-verification-loop*
*Completed: 2026-02-11*
