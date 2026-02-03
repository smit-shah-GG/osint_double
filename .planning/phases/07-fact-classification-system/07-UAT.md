---
status: testing
phase: 07-fact-classification-system
source: [07-01-SUMMARY.md, 07-02-SUMMARY.md, 07-03-SUMMARY.md, 07-04-SUMMARY.md]
started: 2026-02-04T12:00:00Z
updated: 2026-02-04T12:00:00Z
---

## Current Test

number: 1
name: Classification Schema Imports
expected: |
  All classification schema classes import successfully:
  - FactClassification, ImpactTier, DubiousFlag
  - CredibilityBreakdown, ClassificationReasoning
  - ClassificationStore
awaiting: user response

## Tests

### 1. Classification Schema Imports
expected: All classification schema classes import successfully (FactClassification, ImpactTier, DubiousFlag, CredibilityBreakdown, ClassificationReasoning, ClassificationStore)
result: [pending]

### 2. FactClassificationAgent Instantiation
expected: FactClassificationAgent instantiates without error and has all required components (credibility_scorer, dubious_detector, impact_assessor, anomaly_detector)
result: [pending]

### 3. Source Credibility Scoring
expected: SourceCredibilityScorer returns correct baseline scores - Reuters/AP ~0.9, Twitter/Reddit ~0.3, RT/Sputnik ~0.4
result: [pending]

### 4. Proximity Decay Calculation
expected: Proximity decay follows 0.7^hop formula - hop=0: 1.0, hop=1: 0.7, hop=2: 0.49
result: [pending]

### 5. Dubious Flag Detection - PHANTOM
expected: Fact with hop_count > 2 AND no primary source triggers PHANTOM flag
result: [pending]

### 6. Dubious Flag Detection - FOG
expected: Fact with vague attribution ("sources say", "reportedly") triggers FOG flag
result: [pending]

### 7. Dubious Flag Detection - NOISE
expected: Fact from low-credibility source (score < 0.3) triggers NOISE flag
result: [pending]

### 8. Impact Assessment - Critical
expected: Fact mentioning world leaders (Putin, Biden) or military action triggers CRITICAL tier
result: [pending]

### 9. Impact Assessment - Less Critical
expected: Routine fact without significant entities/events receives LESS_CRITICAL tier
result: [pending]

### 10. Anomaly Detection - Contradictions
expected: Two contradicting facts (e.g., "X attacked Y" vs "X never attacked Y") detected as contradiction
result: [pending]

### 11. Priority Queue Ordering
expected: ClassificationStore.get_priority_queue() returns facts ordered by priority_score descending, excludes NOISE-only
result: [pending]

### 12. Full Classification Pipeline
expected: classify_investigation() processes multiple facts, applies all scoring, stores classifications with full audit trail
result: [pending]

### 13. Unit Tests Pass
expected: All Phase 7 unit tests pass (pytest tests/agents/sifters/classification/ tests/agents/sifters/credibility/ tests/data_management/schemas/test_classification_schema.py)
result: [pending]

## Summary

total: 13
passed: 0
issues: 0
pending: 13
skipped: 0

## Gaps

[none yet]
