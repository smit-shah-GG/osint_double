---
phase: 07
plan: 04
subsystem: classification
tags: [impact-assessment, anomaly-detection, contradiction, integration, full-pipeline]

dependency-graph:
  requires: [07-01, 07-02, 07-03]
  provides: [ImpactAssessor, AnomalyDetector, full-classification-pipeline]
  affects: [08-verification]

tech-stack:
  added: []
  patterns: [entity-significance-scoring, event-type-categorization, contradiction-detection, two-pass-classification]

key-files:
  created:
    - osint_system/agents/sifters/classification/impact_assessor.py
    - osint_system/agents/sifters/classification/anomaly_detector.py
    - tests/agents/sifters/classification/test_impact_assessor.py
    - tests/agents/sifters/classification/test_anomaly_detector.py
  modified:
    - osint_system/agents/sifters/classification/__init__.py
    - osint_system/agents/sifters/fact_classification_agent.py

decisions:
  - id: impact-threshold
    choice: 0.6 combined score for CRITICAL tier
    why: Significant entity OR event should trigger critical classification
  - id: entity-event-weights
    choice: 50% entity significance + 50% event type
    why: Both dimensions equally important for geopolitical impact
  - id: context-boost-cap
    choice: Maximum 0.2 boost from investigation context
    why: Prevent context from overwhelming intrinsic significance
  - id: contradiction-types
    choice: Four types (negation, numeric, temporal, attribution)
    why: Cover main contradiction categories from CONTEXT.md
  - id: two-pass-classification
    choice: Detect contradictions first, then classify with ANOMALY input
    why: ANOMALY flag requires cross-fact comparison

metrics:
  duration: 10 min
  completed: 2026-02-03
---

# Phase 7 Plan 04: Impact Assessment and Full Integration Summary

ImpactAssessor for critical/less-critical determination, AnomalyDetector for contradiction detection, and full integration of all classification components into FactClassificationAgent.

## Commits

| Commit | Description | Key Changes |
|--------|-------------|-------------|
| eb1a355 | feat(07-04): implement ImpactAssessor | Entity significance, event type categorization, context boost |
| 52ec110 | feat(07-04): implement AnomalyDetector | Negation, numeric, temporal, attribution contradiction detection |
| 046fe35 | feat(07-04): integrate all components | DubiousDetector, ImpactAssessor, AnomalyDetector in agent |
| d7fdcdb | test(07-04): add tests | 58 tests for ImpactAssessor and AnomalyDetector |

## Implementation Details

### ImpactAssessor (340 lines)

**Purpose:** Determine CRITICAL vs LESS_CRITICAL impact tier based on geopolitical significance.

**Entity Significance Scoring:**
- World leaders (Putin, Biden, Xi, Zelensky): 1.0
- Senior officials (ministers, generals): 0.8
- Major organizations (NATO, UN, Pentagon): 0.6
- Generic entities: 0.3-0.4

**Event Type Categorization:**
- Military action (attack, strike, nuclear): 1.0
- Treaties/sanctions: 0.9
- Major events (election, coup, crisis): 0.8
- Diplomatic meetings: 0.7
- Routine activities: 0.2

**Formula:** `combined_score = entity_weight * entity_score + event_weight * event_score`

**Investigation Context Boost (0.0-0.2):**
- +0.1 for objective keyword match in claim
- +0.1 for entity focus match

**Key Methods:**
- `assess(fact, investigation_context)`: Returns ImpactResult with tier, score, reasoning
- `bulk_assess(facts, investigation_context)`: Batch processing

### AnomalyDetector (420 lines)

**Purpose:** Detect contradictions between facts for ANOMALY dubious flag input.

**Contradiction Types:**

| Type | Detection Logic | Confidence |
|------|-----------------|------------|
| Negation | One claim has negation words, other doesn't + shared content | 0.5-0.9 (by overlap) |
| Attribution | statement vs denial assertion types + shared entities | 0.8 |
| Numeric | Disjoint value ranges + shared entities | 0.6-0.8 |
| Temporal | Different explicit dates at same precision + shared entities | 0.7 |

**Shared Content Requirement:**
- Negation: >= 2 shared non-stop words
- Numeric/Temporal/Attribution: >= 1 shared entity

**Key Methods:**
- `find_contradictions(target_fact, comparison_facts)`: Async, returns List[Contradiction]
- Internal: `_check_negation`, `_check_assertion_contradiction`, `_check_numeric_contradiction`, `_check_temporal_contradiction`

### FactClassificationAgent Integration

**Added Lazy Properties:**
- `dubious_detector`: DubiousDetector instance
- `impact_assessor`: ImpactAssessor instance
- `anomaly_detector`: AnomalyDetector instance

**Updated Methods:**
- `_assess_impact()`: Now uses ImpactAssessor for full entity/event significance
- `_detect_dubious()`: Now uses DubiousDetector with optional contradictions input
- `classify_investigation()`: Two-pass classification with anomaly detection

**Two-Pass Classification Flow:**
1. Pass 1: Detect contradictions across all facts
2. Pass 2: Classify each fact with contradiction info for ANOMALY flag

### Tests

**58 tests total:**

**test_impact_assessor.py (32 tests):**
- Initialization (default/custom thresholds)
- World leader detection (Putin, Biden, Xi, Zelensky)
- Military action keywords (strike, invasion, nuclear, missile)
- Diplomatic events (treaty, sanctions, summit)
- Organization significance (NATO, UN, Pentagon)
- Less-critical routine facts
- Investigation context boost
- Bulk assessment
- Edge cases (missing fields, None values)

**test_anomaly_detector.py (26 tests):**
- Initialization (default/custom confidence)
- Negation contradiction (did, never, denied)
- Statement vs denial assertion
- Numeric range disagreement
- Temporal conflict detection
- Entity overlap requirement
- Confidence thresholds
- Self-comparison handling
- Edge cases (empty claims, missing fields)

## Deviations from Plan

None - plan executed exactly as written.

## Integration Points

**Uses:**
- `DubiousDetector`, `DubiousResult` from classification/dubious_detector.py (Plan 03)
- `SourceCredibilityScorer`, `EchoDetector` from credibility/ (Plan 02)
- `FactClassification`, `ImpactTier`, `DubiousFlag` from classification_schema.py (Plan 01)
- `CRITICAL_ENTITY_PATTERNS`, `CRITICAL_EVENT_KEYWORDS` from classification_prompts.py (Plan 03)
- `ENTITY_SIGNIFICANCE`, `EVENT_TYPE_SIGNIFICANCE` from source_credibility.py (Plan 02)

**Provides for Phase 8:**
- `ImpactAssessor.assess()`: Impact tier for priority calculation
- `AnomalyDetector.find_contradictions()`: Contradiction input for ANOMALY flag
- `FactClassificationAgent.classify_investigation()`: Full classification with anomaly detection

## Phase 7 Complete

Phase 7 fact classification system is now complete:

1. **Plan 01:** Schema (FactClassification, ImpactTier, DubiousFlag) + ClassificationStore
2. **Plan 02:** Credibility scoring (SourceCredibilityScorer, EchoDetector)
3. **Plan 03:** Dubious detection (DubiousDetector with Boolean logic gates)
4. **Plan 04:** Impact assessment + anomaly detection + full integration

**Full Pipeline Flow:**
```
ExtractedFact
    -> SourceCredibilityScorer.compute_credibility()
    -> ImpactAssessor.assess()
    -> AnomalyDetector.find_contradictions() [batch mode]
    -> DubiousDetector.detect()
    -> FactClassification
```

**Key Architectural Properties:**
- Impact and dubious are orthogonal dimensions
- Boolean logic gates, not weighted formulas
- Taxonomy of doubt: PHANTOM/FOG/ANOMALY/NOISE
- Fixability-based priority for Phase 8 queue
- Full audit trail in FactClassification

## Phase 8 Readiness

The classification system provides everything Phase 8 verification needs:

1. **Priority Queue:** `ClassificationStore.get_priority_queue()` returns dubious facts ordered by priority_score
2. **Flag-Type Indexes:** `ClassificationStore.get_by_flag()` returns all facts with specific dubious flag
3. **Contradiction Details:** `DubiousResult.reasoning` includes contradicting_fact_ids for ANOMALY
4. **Fixability Scores:** Route verification effort to fixable claims first

Phase 8 can implement specialized subroutines per dubious species:
- PHANTOM: Trace back to find root source
- FOG: Find harder/clearer version of claim
- ANOMALY: Arbitrate with temporal/location context
- NOISE: Batch analysis for pattern detection
