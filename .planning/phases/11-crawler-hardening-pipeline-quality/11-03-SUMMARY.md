---
phase: 11-crawler-hardening-pipeline-quality
plan: 03
subsystem: extraction, classification, llm
tags: [objective-aware-prompt, extraction-metrics, warn-once-fallback, noise-threshold, pipeline-quality]

# Dependency graph
requires:
  - phase: 11-02
    provides: RSS fallback, "statement" claim_type, enum normalization in fact_extraction_agent
  - phase: 06-fact-schema
    provides: ExtractedFact and Claim schema with Pydantic validation
  - phase: 07-fact-classification
    provides: FactClassificationAgent, DubiousDetector with NOISE threshold
provides:
  - FACT_EXTRACTION_USER_PROMPT_V2 with investigation objective injection
  - Objective threading from runner -> ExtractionPipeline -> FactExtractionAgent -> prompt
  - ExtractionMetrics dataclass for per-model extraction performance tracking
  - Per-article extraction logging (url, facts, duration, progress)
  - End-of-run extraction summary with per-model success rate and avg latency
  - Warn-once fallback logging in OpenRouter client (eliminates log spam)
  - Configurable NOISE credibility threshold in FactClassificationAgent
affects:
  - 11-04 (verification coverage improvements receive objective-filtered facts)
  - 17-crawler-agent-integration (objective threading pattern for agent crawlers)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Objective-aware extraction: investigation objective injected into user prompt, not system prompt"
    - "Warn-once pattern: module-level set with .clear() reset per investigation run"
    - "ExtractionMetrics: per-model success/failure/fact tracking with end-of-run summary"

key-files:
  created: []
  modified:
    - osint_system/config/prompts/fact_extraction_prompts.py
    - osint_system/agents/sifters/fact_extraction_agent.py
    - osint_system/pipelines/extraction_pipeline.py
    - osint_system/runner.py
    - osint_system/llm/openrouter_client.py
    - osint_system/agents/sifters/fact_classification_agent.py

key-decisions:
  - "V2 prompt uses 'When in doubt, include the fact' guidance per CONTEXT.md (err toward inclusion)"
  - "Original FACT_EXTRACTION_USER_PROMPT preserved for backward compat; V2 selected dynamically when objective is non-empty"
  - "warn-once uses set.clear() instead of global rebinding for correct behavior with from-imports"
  - "ExtractionMetrics tracked at pipeline level (not agent level) for centralized summary logging"
  - "NOISE threshold wired from FactClassificationAgent to DubiousDetector constructor, not changed from 0.3"

patterns-established:
  - "Objective threading: runner.objective -> pipeline.process_investigation(objective=) -> _article_to_content -> content['objective'] -> agent.sift() -> _extract_single(objective=) -> prompt"
  - "Per-model metrics: ExtractionMetrics dataclass accumulated in _extract_one closure, summary logged after asyncio.gather"

# Metrics
duration: 5min
completed: 2026-03-21
---

# Phase 11 Plan 03: Extraction Quality & Metrics Summary

**Objective-aware extraction prompt filtering noise at source, per-model ExtractionMetrics with end-of-run summary, warn-once fallback logging, and configurable NOISE threshold in FactClassificationAgent**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-21T16:32:58Z
- **Completed:** 2026-03-21T16:38:26Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- Added FACT_EXTRACTION_USER_PROMPT_V2 with INVESTIGATION OBJECTIVE field and relevance filtering guidance ("When in doubt, include the fact" per CONTEXT.md)
- Threaded investigation objective from InvestigationRunner through ExtractionPipeline._article_to_content into FactExtractionAgent.sift -> _extract_single/_extract_chunked
- Original FACT_EXTRACTION_USER_PROMPT preserved for backward compat; V2 selected dynamically when objective is non-empty
- Added ExtractionMetrics dataclass tracking per-model success/failure counts, total facts, and total duration
- Per-article extraction logging with URL, fact count, duration, and progress counter
- End-of-run extraction summary with per-model success rate and average latency
- Implemented warn-once fallback logging in OpenRouter client using module-level set of (primary, fallback) transition tuples
- reset_fallback_warnings() called at start of each _phase_extract to reset per-investigation-run state
- Added noise_credibility_threshold parameter to FactClassificationAgent.__init__, passed through to DubiousDetector constructor (VERIFY-01 classification-level fix)

## Task Commits

Each task was committed atomically:

1. **Task 1: Objective-aware prompt, objective threading, NOISE threshold** - `4cae99d` (feat)
2. **Task 2: Per-article metrics, summary logging, warn-once fallback** - `3a13b0d` (feat)

## Files Created/Modified
- `osint_system/config/prompts/fact_extraction_prompts.py` - Added FACT_EXTRACTION_USER_PROMPT_V2 with {objective} placeholder and relevance filtering
- `osint_system/agents/sifters/fact_extraction_agent.py` - Added objective param to __init__, sift, _extract_single, _extract_chunked; V2 prompt selection
- `osint_system/pipelines/extraction_pipeline.py` - Added ExtractionMetrics dataclass, _model_metrics tracking, per-article logging, end-of-run summary, objective param to __init__/process_investigation/_article_to_content
- `osint_system/runner.py` - Thread objective to ExtractionPipeline, reset_fallback_warnings() in _phase_extract, noise_credibility_threshold in _phase_classify
- `osint_system/llm/openrouter_client.py` - _warned_transitions set, reset_fallback_warnings(), warn-once checks in _SyncModels and _AsyncModels
- `osint_system/agents/sifters/fact_classification_agent.py` - noise_credibility_threshold param, passed to DubiousDetector in lazy init

## Decisions Made
- **Prompt placement:** Investigation objective goes in user prompt (V2), not system prompt, per plan specification. System prompt remains focused on extraction rules and schema.
- **Backward compat:** V2 prompt selected conditionally (`if objective:`) so existing callers without objective get the original prompt.
- **set.clear() vs rebinding:** Used `_warned_transitions.clear()` instead of `global _warned_transitions; _warned_transitions = set()` so `from ... import _warned_transitions` references remain valid. This is the correct Python pattern for module-level mutable state that gets reset.
- **Metrics scope:** ExtractionMetrics tracked at pipeline level (in `_extract_one` closure) rather than agent level, since the pipeline owns the batch processing loop and end-of-run summary.
- **NOISE threshold unchanged:** Wired the threshold as configurable (from runner -> classifier -> detector) but kept default at 0.3 per CONTEXT.md. Noise filtering is addressed at the extraction prompt level (objective-aware), not by tuning the threshold.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Warn-once reset uses set.clear() instead of global rebinding**
- **Found during:** Task 2 verification
- **Issue:** Plan specified `global _warned_transitions; _warned_transitions = set()` which breaks `from ... import _warned_transitions` references (Python binding semantics: the from-import creates a separate name binding to the original set object; rebinding the module-level name doesn't update the from-import reference)
- **Fix:** Changed to `_warned_transitions.clear()` which mutates the existing set in-place, keeping all references valid
- **Files modified:** osint_system/llm/openrouter_client.py
- **Committed in:** 3a13b0d

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Minor implementation correction. No scope change.

## Issues Encountered
- **Pre-existing test failures:** 18 tests fail (same as 11-02 baseline): async test infrastructure issues, pre-existing assertion mismatches in test_fact_extraction_agent.py (model default), test_07_pipeline.py (batch_size), reddit integration tests. 918 tests pass. No regressions.

## User Setup Required
None - no new dependencies, no external service configuration.

## Next Phase Readiness
- Extraction prompt now filters irrelevant facts (swimming results, beer releases) at source
- Per-model metrics enable data-driven model selection decisions (Gemini Flash Lite vs Qwen 3.5 Flash)
- Fallback chain log spam eliminated
- NOISE threshold configurable for future tuning
- Ready for 11-04 (verification coverage improvements)

---
*Phase: 11-crawler-hardening-pipeline-quality*
*Completed: 2026-03-21*
