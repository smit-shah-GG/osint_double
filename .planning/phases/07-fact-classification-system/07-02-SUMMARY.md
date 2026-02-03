---
phase: 07
plan: 02
subsystem: classification
tags: [credibility, scoring, echo-detection, anti-gaming, source-baselines]

dependency-graph:
  requires: [07-01]
  provides: [SourceCredibilityScorer, EchoDetector, source_credibility config]
  affects: [07-03, 08-verification]

tech-stack:
  added: []
  patterns: [logarithmic-dampening, exponential-decay, baseline-lookup, lazy-initialization]

key-files:
  created:
    - osint_system/agents/sifters/credibility/__init__.py
    - osint_system/agents/sifters/credibility/source_scorer.py
    - osint_system/agents/sifters/credibility/echo_detector.py
    - osint_system/config/source_credibility.py
    - tests/agents/sifters/credibility/__init__.py
    - tests/agents/sifters/credibility/test_source_scorer.py
    - tests/agents/sifters/credibility/test_echo_detector.py
  modified:
    - osint_system/agents/sifters/fact_classification_agent.py

decisions:
  - id: proximity-decay-factor
    choice: 0.7^hop exponential decay
    why: Moderate decay, secondary sources still meaningful (hop=2 -> 0.49)
  - id: echo-dampening-alpha
    choice: alpha=0.2 for logarithmic dampening
    why: First echo adds value, 100th adds near-zero, botnet-proof
  - id: precision-weights
    choice: entity 30%, temporal 30%, quote 20%, document 20%
    why: Balance verifiability signals for precision scoring
  - id: single-source-limitation
    choice: Phase 7 scores primary source only
    why: Full multi-source echo dampening requires Phase 8 variant provenance

metrics:
  duration: 11 min
  completed: 2026-02-03
---

# Phase 7 Plan 02: Credibility Scoring System Summary

Multi-factor credibility scoring with logarithmic echo dampening per CONTEXT.md formula: Claim Score = Sum(SourceCred x Proximity x Precision) + alpha * log10(1 + sum(echoes)).

## Commits

| Commit | Description | Key Changes |
|--------|-------------|-------------|
| 89811f9 | feat(07-02): add source credibility configuration | 25 source baselines, type defaults, proximity/echo constants |
| 7cdcc45 | feat(07-02): implement SourceCredibilityScorer | 443 lines, baseline lookups, domain extraction, precision scoring |
| 2799539 | feat(07-02): implement EchoDetector | 406 lines, logarithmic dampening, circular reporting detection |
| 1b0c916 | feat(07-02): integrate into FactClassificationAgent | Lazy initialization, scorer integration, Phase 8 path documented |
| 205da22 | test(07-02): add credibility tests | 65 tests covering all scoring components |

## Implementation Details

### Source Credibility Configuration (128 lines)

**SOURCE_BASELINES (25 sources):**
- Wire services: Reuters/AP/AFP (0.9), TASS (0.75), Xinhua (0.7)
- Major news: BBC/NYT/WaPo/Economist (0.85), CNN (0.75), Fox (0.7)
- State propaganda: RT/Sputnik (0.4)
- Social media: Twitter/Reddit/Facebook (0.3)

**SOURCE_TYPE_DEFAULTS:**
- wire_service: 0.85, official_statement: 0.8
- news_outlet: 0.6, academic: 0.85
- social_media: 0.3, unknown: 0.3

**DOMAIN_PATTERN_DEFAULTS:**
- .gov/.mil/.edu/.int: 0.85
- .org: 0.7

**Constants:**
- PROXIMITY_DECAY_FACTOR: 0.7
- ECHO_DAMPENING_ALPHA: 0.2
- PRECISION_WEIGHTS: entity 0.3, temporal 0.3, quote 0.2, document 0.2

### SourceCredibilityScorer (443 lines)

**Core formula:** SourceCred x Proximity x Precision

**Credibility lookup priority:**
1. Exact match in baselines
2. Domain extraction from URL
3. Domain pattern match (.gov, .edu)
4. Type-based default
5. Fallback 0.3

**Proximity calculation:**
- 0.7^hop_count
- hop=0: 1.0, hop=1: 0.7, hop=2: 0.49, hop=3: 0.343

**Precision factors:**
- Entity count: More entities = more precise (diminishing returns)
- Temporal precision: explicit > inferred > unknown
- Quote presence: Direct quotes increase precision
- Document citation: Official documents in chain increase precision

**Key methods:**
- `compute_credibility(fact)`: Score single fact, return (score, breakdown)
- `score_multiple_sources(fact, additional_provenances)`: Score with echoes

### EchoDetector (406 lines)

**Core formula:** Total = S_root + (alpha * log10(1 + sum(S_echoes)))

**Logarithmic dampening properties:**
- echo_sum=1: bonus ~ 0.06
- echo_sum=10: bonus ~ 0.21
- echo_sum=100: bonus ~ 0.40
- echo_sum=1000: bonus ~ 0.60
- echo_sum=10000: bonus ~ 0.80

**Botnet crushing:** 1M low-quality sources contribute same as ~10 quality echoes.

**Circular reporting detection:**
- All sources trace to same non-primary root: WARNING
- No primary sources among 4+ sources: WARNING

**Key methods:**
- `analyze_sources(provenances, scores)`: Full echo analysis
- `_cluster_by_root(provenances, scores)`: Group by attribution chain root
- `_detect_circular_reporting(clusters, provenances)`: Warning detection
- `compute_corroboration_strength(unique_roots, root_score)`: Phase 8 use

### FactClassificationAgent Integration

**Added lazy properties:**
- `credibility_scorer`: SourceCredibilityScorer instance
- `echo_detector`: EchoDetector instance (ready for Phase 8)

**Updated _compute_credibility():**
- Uses SourceCredibilityScorer.compute_credibility()
- Documents Phase 8 integration path for multi-source echo dampening
- Returns full CredibilityBreakdown for debugging

## Tests

**65 tests total:**

**test_source_scorer.py (34 tests):**
- Initialization (default/custom baselines)
- Known source baselines (Reuters, AP, BBC, RT, Twitter)
- Unknown source type defaults
- Domain extraction from URLs
- Domain pattern matching (.gov, .edu, .org)
- Proximity decay calculation
- Precision scoring (entities, temporal, quotes, documents)
- Combined scoring and score ordering
- Multiple source scoring

**test_echo_detector.py (31 tests):**
- Initialization (default/custom alpha)
- Single source analysis
- Multiple independent sources
- Logarithmic dampening values
- Botnet crushing (100x sources = 50% more credit)
- Diminishing returns per source
- Circular reporting detection
- Root clustering by attribution chain
- Corroboration strength calculation
- Breakdown update

## Deviations from Plan

None - plan executed exactly as written.

## Integration Points

**Uses:**
- `CredibilityBreakdown` from classification_schema.py (Phase 7 Plan 01)
- `loguru` for structured logging

**Provides for Phase 8:**
- `EchoDetector.analyze_sources()`: Multi-source echo analysis
- `EchoDetector.compute_corroboration_strength()`: Impact assessment
- `SourceCredibilityScorer.score_multiple_sources()`: Variant scoring

**Phase 7 Limitation:**
Single-source scoring only. Full multi-source echo dampening requires Phase 8
variant provenance enrichment. The EchoDetector infrastructure is ready;
variant provenances just need to be fetched and wired.

## Next Phase Readiness

Plan 03 can now implement:
- Dubious flag detection using credibility scores (NOISE: credibility < 0.3)
- Impact assessment using entity/event significance configs
- Full Boolean logic gates for PHANTOM, FOG, ANOMALY detection

The credibility scoring foundation is complete and tested.
