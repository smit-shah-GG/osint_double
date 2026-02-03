---
phase: 07
plan: 03
subsystem: classification
tags: [dubious-detection, boolean-logic-gates, taxonomy-of-doubt, verification-routing]

dependency-graph:
  requires: [07-01, 07-02]
  provides: [DubiousDetector, DubiousResult, classification_prompts]
  affects: [07-04, 08-verification]

tech-stack:
  added: []
  patterns: [boolean-logic-gates, regex-pattern-matching, fixability-prioritization]

key-files:
  created:
    - osint_system/agents/sifters/classification/__init__.py
    - osint_system/agents/sifters/classification/dubious_detector.py
    - osint_system/config/prompts/classification_prompts.py
    - tests/agents/sifters/classification/__init__.py
    - tests/agents/sifters/classification/test_dubious_detector.py
  modified:
    - osint_system/config/prompts/__init__.py

decisions:
  - id: boolean-not-weighted
    choice: Boolean logic gates for dubious detection
    why: Each species triggers specific Phase 8 subroutine, not weighted magnitude
  - id: fixability-priority
    choice: FOG (0.9) > ANOMALY (0.8) > PHANTOM (0.6) > NOISE (0.1)
    why: Prioritize easily verifiable claims for Phase 8 queue efficiency
  - id: pure-noise-exclusion
    choice: Pure NOISE facts get 0.0 fixability (batch only)
    why: Per CONTEXT.md, NOISE excluded from individual verification queue
  - id: vague-patterns-regex
    choice: 14 compiled regex patterns for FOG detection
    why: Efficient pattern matching for common hedging/vague attribution phrases

metrics:
  duration: 5 min
  completed: 2026-02-03
---

# Phase 7 Plan 03: Dubious Detection System Summary

Boolean logic gates for Taxonomy of Doubt (PHANTOM/FOG/ANOMALY/NOISE) with fixability-based verification routing.

## Commits

| Commit | Description | Key Changes |
|--------|-------------|-------------|
| 572175e | feat(07-03): add classification prompts | 14 vague patterns, entity/event keywords |
| 8213c5a | feat(07-03): implement DubiousDetector | 467 lines, Boolean logic gates, fixability scoring |
| b5a4f1c | test(07-03): add DubiousDetector tests | 41 tests covering all four species |

## Implementation Details

### Classification Prompts (121 lines)

**ENTITY_SIGNIFICANCE_PROMPT:**
- LLM-assisted entity significance assessment
- Tiers: world_leader (1.0), senior_official (0.8), government_official (0.6), etc.
- Returns JSON with per-entity scores and overall significance

**EVENT_TYPE_PROMPT:**
- LLM-assisted event categorization
- Types: military_action (1.0), treaty_agreement (0.9), sanctions (0.9), etc.
- Returns JSON with event type, score, and reasoning

**VAGUE_ATTRIBUTION_PATTERNS (14 patterns):**
- English vague patterns: "sources say", "according to officials", "reportedly"
- Hedging language: "may have", "appears to", "likely"
- Case-insensitive compiled regex for efficient matching

**CRITICAL_ENTITY_PATTERNS (6 patterns):**
- World leaders: president, prime minister, named leaders
- Organizations: NATO, UN, EU, G7, Kremlin, Pentagon
- Military: army, navy, nuclear, missile

**CRITICAL_EVENT_KEYWORDS (25 keywords):**
- Military: attack, strike, invasion, nuclear
- Diplomatic: summit, treaty, sanction
- Major events: election, coup, assassination

### DubiousDetector (467 lines)

**Taxonomy of Doubt - Boolean Logic Gates:**

| Species | Trigger | Signal | Phase 8 Action |
|---------|---------|--------|----------------|
| PHANTOM | hop_count > 2 AND primary_source IS NULL | Echo without root | Trace back |
| FOG | claim_clarity < 0.5 OR vague attribution | Speaker mumbling | Find clearer source |
| ANOMALY | contradiction_count > 0 | Sources disagree | Arbitrate |
| NOISE | source_credibility < 0.3 | Known unreliable | Batch only |

**CRITICAL: Boolean logic gates, NOT weighted formulas.**

**Key Methods:**
- `detect(fact, credibility_score, contradictions)`: Main entry point
- `_check_phantom(fact)`: Gate 1 - Structural failure
- `_check_fog(fact)`: Gate 2 - Attribution failure
- `_check_anomaly(fact, contradictions)`: Gate 3 - Coherence failure
- `_check_noise(credibility_score)`: Gate 4 - Reputation failure
- `_calculate_fixability(flags, credibility_score)`: Verification priority

**Fixability Scores:**
- FOG: 0.9 (highly fixable - find clearer source)
- ANOMALY: 0.8 (highly fixable - arbitrate with context)
- PHANTOM: 0.6 (moderately fixable - trace root)
- NOISE: 0.1 (not individually fixable)
- Pure NOISE: 0.0 (excluded from verification queue)

**DubiousResult dataclass:**
```python
@dataclass
class DubiousResult:
    flags: List[DubiousFlag]
    reasoning: List[ClassificationReasoning]
    fixability_score: float
```

### Tests (676 lines, 41 tests)

**Test Classes:**
- TestDubiousDetectorInitialization: 3 tests
- TestPhantomDetection: 5 tests
- TestFogDetection: 8 tests
- TestAnomalyDetection: 3 tests
- TestNoiseDetection: 4 tests
- TestMultipleFlags: 3 tests
- TestCleanFact: 2 tests
- TestFixabilityCalculation: 5 tests
- TestDubiousResult: 2 tests
- TestEdgeCases: 6 tests

## Deviations from Plan

None - plan executed exactly as written.

## Integration Points

**Uses:**
- `ClassificationReasoning` and `DubiousFlag` from classification_schema.py (Phase 7 Plan 01)
- `VAGUE_ATTRIBUTION_PATTERNS` from classification_prompts.py
- `loguru` for structured logging

**Provides for Plan 04:**
- `DubiousDetector.detect()`: Core dubious detection
- `DubiousResult`: Container with flags, reasoning, fixability

**Provides for Phase 8:**
- Dubious species routing for verification subroutines
- Fixability scores for queue prioritization
- ClassificationReasoning for understanding WHY verification needed

## Next Phase Readiness

Plan 04 can now implement:
- ImpactAssessor using CRITICAL_ENTITY_PATTERNS and CRITICAL_EVENT_KEYWORDS
- AnomalyDetector for contradiction detection (provides input to ANOMALY gate)
- Full FactClassificationAgent integration with DubiousDetector

The dubious detection foundation is complete and tested.
