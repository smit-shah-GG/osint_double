---
phase: 07
plan: 01
subsystem: classification
tags: [classification, pydantic, schemas, agent, storage]

dependency-graph:
  requires: [06-01, 06-02]
  provides: [FactClassification schema, ClassificationStore, FactClassificationAgent]
  affects: [07-02, 07-03, 08-verification]

tech-stack:
  added: []
  patterns: [investigation-scoped storage, lazy initialization, orthogonal dimensions]

key-files:
  created:
    - osint_system/data_management/schemas/classification_schema.py
    - osint_system/data_management/classification_store.py
    - tests/data_management/schemas/test_classification_schema.py
    - tests/agents/sifters/test_fact_classification_agent.py
  modified:
    - osint_system/data_management/schemas/__init__.py
    - osint_system/data_management/__init__.py
    - osint_system/agents/sifters/__init__.py
    - osint_system/agents/sifters/fact_classification_agent.py

decisions:
  - id: classification-separate-from-facts
    choice: Classifications are separate records linked by fact_id
    why: Facts remain immutable, classifications are mutable
  - id: orthogonal-dimensions
    choice: Impact tier and dubious flags are orthogonal
    why: A fact can be critical AND dubious simultaneously
  - id: taxonomy-of-doubt
    choice: Four dubious flag species (phantom/fog/anomaly/noise)
    why: Each species triggers specific Phase 8 verification subroutine
  - id: noise-batch-only
    choice: NOISE-only facts excluded from individual verification queue
    why: Batch analysis for pattern detection, not individual verification

metrics:
  duration: 8 min
  completed: 2026-02-03
---

# Phase 7 Plan 01: Classification Schema and Agent Structure Summary

Classification schema with FactClassificationAgent shell for impact tier assessment and dubious flag detection.

## Commits

| Commit | Description | Key Changes |
|--------|-------------|-------------|
| 10547c2 | feat(07-01): add classification schema | FactClassification, ImpactTier, DubiousFlag, CredibilityBreakdown |
| bc33d00 | feat(07-01): implement ClassificationStore | Investigation-scoped storage with flag/tier indexes |
| 64074ad | feat(07-01): implement FactClassificationAgent shell | BaseSifter subclass with classification pipeline |
| 73b865f | test(07-01): add classification tests | 57 tests covering schemas and agent |

## Implementation Details

### FactClassification Schema (362 lines)

**Core models:**
- `FactClassification`: Complete classification record linked by `fact_id`
- `ImpactTier`: Enum with CRITICAL and LESS_CRITICAL values
- `DubiousFlag`: Taxonomy of doubt (PHANTOM, FOG, ANOMALY, NOISE)
- `CredibilityBreakdown`: Full score decomposition for debugging
- `ClassificationReasoning`: Explains WHY each flag was triggered
- `ClassificationHistory`: Audit trail for re-classifications

**Key properties:**
- `is_dubious`: True if any dubious flag set
- `is_critical_dubious`: True if critical AND dubious (priority verification)
- `is_noise`: True if NOISE is the only flag (batch analysis only)
- `requires_verification`: True if needs Phase 8 verification

**Per CONTEXT.md taxonomy:**
- PHANTOM: Structural failure (hop_count > 2 AND no primary)
- FOG: Attribution failure (claim_clarity < 0.5 OR vague attribution)
- ANOMALY: Coherence failure (contradictions detected)
- NOISE: Reputation failure (source_credibility < 0.3)

### ClassificationStore (682 lines)

**Features:**
- Investigation-scoped storage (`investigation_id` as primary key)
- O(1) lookup by `fact_id`
- Flag-type indexes for Phase 8 subroutine access
- Tier indexes for impact-based queries
- Priority queue with noise exclusion
- Optional JSON persistence

**Key methods:**
- `get_by_flag()`: Get all facts with a specific dubious flag
- `get_by_tier()`: Get all facts with specific impact tier
- `get_priority_queue()`: Priority-ordered queue for Phase 8
- `get_critical_dubious()`: Critical AND dubious facts (priority)
- `get_dubious_facts()`: All dubious facts (optional noise exclusion)

### FactClassificationAgent (473 lines)

**Classification flow:**
1. `_compute_credibility()`: Compute credibility score (shell for Plan 02)
2. `_assess_impact()`: Determine impact tier (shell for Plan 03)
3. `_detect_dubious()`: Detect dubious flags via Boolean gates
4. `_calculate_priority()`: Priority = Impact x Fixability

**Key methods:**
- `sift()`: Classify facts, return classifications
- `classify_fact()`: Classify single fact
- `reclassify_fact()`: Re-classify after new evidence
- `classify_investigation()`: Classify all facts in investigation

**Priority calculation:**
- Critical tier: 1.0 factor
- Less critical: 0.5 factor
- Fixability: 0.3 + (credibility * 0.7) for fixable dubious
- NOISE-only: 0.0 (batch analysis only)
- Non-dubious: 0.0 (no verification needed)

## Tests

**57 total tests:**

**test_classification_schema.py (26 tests):**
- Minimal/full FactClassification validation
- Property methods (is_dubious, is_critical_dubious, is_noise)
- History management and audit trail
- CredibilityBreakdown.compute_total() with logarithmic dampening
- Score bounds validation

**test_fact_classification_agent.py (31 tests):**
- Agent initialization and BaseSifter inheritance
- sift() with empty/single/multiple facts
- classify_fact() flow and dubious detection
- Priority calculation logic
- ClassificationStore integration
- Edge cases and error handling

## Deviations from Plan

None - plan executed exactly as written.

## Integration Points

**Uses:**
- `BaseSifter` from `osint_system.agents.sifters.base_sifter`
- `FactStore` from `osint_system.data_management.fact_store`
- Pydantic for schema validation

**Provides for Plans 02/03:**
- `_compute_credibility()`: Shell ready for full formula implementation
- `_assess_impact()`: Shell ready for context-aware impact assessment
- `_detect_dubious()`: Shell ready for Boolean logic gates

**Provides for Phase 8:**
- `get_priority_queue()`: Ordered queue for verification
- `get_by_flag()`: Flag-specific subroutine access
- `get_critical_dubious()`: Priority verification targets

## Next Phase Readiness

Plans 02 and 03 can now implement:
- Full credibility scoring formula (Plan 02)
- Context-aware impact assessment (Plan 03)
- Complete dubious flag detection logic (Plan 03)

The agent shell is ready with clear extension points.
