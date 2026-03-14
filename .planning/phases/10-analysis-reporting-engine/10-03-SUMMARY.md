---
phase: 10-analysis-reporting-engine
plan: 03
subsystem: analysis, pipeline
tags: [synthesizer, pattern-detection, contradiction-analysis, gemini, llm-synthesis, ic-confidence, event-driven-pipeline]

requires:
  - phase: 10-analysis-reporting-engine
    provides: AnalysisSynthesis schema, InvestigationSnapshot, DataAggregator, AnalysisConfig
  - phase: 09-knowledge-graph-integration
    provides: GraphPipeline with query convenience, GraphIngestor
  - phase: 08-verification-loop
    provides: VerificationPipeline, VerificationStore, VerificationStatus

provides:
  - Synthesizer: LLM synthesis orchestrator (sectioned Gemini calls)
  - PatternDetector: rule-based cross-fact pattern detection
  - ContradictionAnalyzer: contradiction identification (no LLM)
  - AnalysisReportingAgent: BaseSifter subclass orchestrating full analysis
  - AnalysisPipeline: event-driven (graph.ingested) and standalone analysis
  - GraphPipeline graph.ingested event emission via MessageBus
  - 5 Gemini prompt templates for IC-style synthesis

affects:
  - 10-04 (report generation consumes AnalysisSynthesis from pipeline)
  - 10-05 (dashboard wires AnalysisPipeline into create_app())

tech-stack:
  added: []
  patterns:
    - Sectioned LLM synthesis (5 focused prompts instead of monolithic)
    - Graceful fallback on LLM failure (degraded output, never crash)
    - TYPE_CHECKING import for AnalysisReportingAgent to avoid Settings cascade
    - graph.ingested event extending pipeline chain (graph -> analysis)
    - Optional report auto-generation via typed Any dependencies

key-files:
  created:
    - osint_system/analysis/synthesizer.py
    - osint_system/analysis/pattern_detector.py
    - osint_system/analysis/contradiction_analyzer.py
    - osint_system/config/prompts/analysis_prompts.py
    - osint_system/pipeline/analysis_pipeline.py
    - tests/analysis/test_synthesizer.py
    - tests/analysis/test_pattern_detector.py
    - tests/pipelines/test_analysis_pipeline.py
  modified:
    - osint_system/analysis/__init__.py
    - osint_system/pipeline/__init__.py
    - osint_system/pipeline/graph_pipeline.py
    - osint_system/agents/sifters/analysis_reporting_agent.py

key-decisions:
  - "TYPE_CHECKING import for AnalysisReportingAgent in AnalysisPipeline to avoid cascading Settings singleton through agents.__init__"
  - "GraphPipeline.set_message_bus() with optional _message_bus attribute for graph.ingested event emission"
  - "ReportGenerator and ReportStore typed as Any in AnalysisPipeline to avoid hard import dependency on reporting package"
  - "Sectioned LLM synthesis: 5 focused prompts instead of single monolithic call per RESEARCH.md Pattern 3"
  - "Contradiction detection from 3 sources: explicit relationships, refuted verifications, conflicting assertion_types"
  - "Overall confidence computed as weighted average of key judgment confidences"

patterns-established:
  - "Sectioned LLM synthesis with independent error handling per section"
  - "Optional downstream dependencies via Any typing (AnalysisPipeline accepts optional report_generator/report_store)"
  - "Pipeline chain extension via MessageBus: graph.ingested event bridges GraphPipeline to AnalysisPipeline"

duration: 10min
completed: 2026-03-14
---

# Phase 10 Plan 03: LLM Synthesis Engine & Analysis Pipeline Summary

**Sectioned Gemini synthesis (5 IC-style prompts), rule-based PatternDetector and ContradictionAnalyzer, AnalysisReportingAgent (BaseSifter), AnalysisPipeline extending event chain from graph.ingested, and GraphPipeline event emission -- 38 tests with mocked LLM.**

## Performance

- **Duration:** 10 min
- **Started:** 2026-03-14T12:40:04Z
- **Completed:** 2026-03-14T12:50:34Z
- **Tasks:** 2/2
- **Files created:** 8
- **Files modified:** 4

## Accomplishments

- Synthesizer with sectioned LLM calls: executive summary, key judgments, alternative hypotheses, implications, source assessment -- each with independent error handling and graceful fallback
- PatternDetector: recurring entities (3+ facts), temporal clusters (same day), source clusters, escalation indicators (less_critical -> critical) -- all rule-based, no LLM
- ContradictionAnalyzer: explicit contradicts relationships, REFUTED verifications, conflicting assertion_types (statement vs denial) -- with resolution tracking
- AnalysisReportingAgent inheriting BaseSifter, orchestrating synthesis + patterns + contradictions
- AnalysisPipeline: graph.ingested event handler and standalone mode, auto-generates Markdown report when ReportGenerator/ReportStore available
- GraphPipeline patched to emit graph.ingested via MessageBus after successful ingestion
- 5 Gemini prompt templates with IC-style grounding instructions and structured JSON output
- 38 tests total with mocked LLM (zero API cost)

## Task Commits

1. **Task 1: Synthesizer, PatternDetector, ContradictionAnalyzer, and prompt templates** - `2db8cda` (feat)
2. **Task 2: AnalysisReportingAgent and AnalysisPipeline** - `303b5af` (feat)

## Files Created/Modified

- `osint_system/analysis/synthesizer.py` (540 lines) - LLM synthesis orchestrator with 5 sectioned calls
- `osint_system/analysis/pattern_detector.py` (298 lines) - Rule-based cross-fact pattern detection
- `osint_system/analysis/contradiction_analyzer.py` (341 lines) - Contradiction identification from 3 sources
- `osint_system/config/prompts/analysis_prompts.py` (158 lines) - 5 Gemini prompt templates
- `osint_system/agents/sifters/analysis_reporting_agent.py` (205 lines) - BaseSifter subclass
- `osint_system/pipeline/analysis_pipeline.py` (296 lines) - Event-driven + standalone analysis pipeline
- `osint_system/analysis/__init__.py` - Updated exports for Synthesizer, PatternDetector, ContradictionAnalyzer
- `osint_system/pipeline/__init__.py` - Added AnalysisPipeline export
- `osint_system/pipeline/graph_pipeline.py` - Added _message_bus, set_message_bus(), graph.ingested emission
- `tests/analysis/test_synthesizer.py` (460 lines) - 16 tests with mocked LLM
- `tests/analysis/test_pattern_detector.py` (386 lines) - 12 tests for patterns + contradictions
- `tests/pipelines/test_analysis_pipeline.py` (414 lines) - 10 pipeline integration tests

## Decisions Made

1. **TYPE_CHECKING import for AnalysisReportingAgent** - Same cascading Settings singleton issue as DataAggregator (10-01). Importing AnalysisReportingAgent at module level triggers agents.__init__ -> SimpleAgent -> gemini_client -> Settings requiring GEMINI_API_KEY. Runtime import in _get_agent() method avoids this.

2. **Sectioned LLM synthesis** - 5 separate focused prompts instead of one monolithic call. Per RESEARCH.md Pattern 3 and Pitfall 1: quality degrades beyond ~100K tokens, and independent error handling means partial LLM failures produce degraded output rather than total failure.

3. **Optional report generation via Any typing** - ReportGenerator and ReportStore typed as Any in AnalysisPipeline constructor. The reporting package is built in 10-04 (same wave); using Any avoids hard import dependency while providing type-safe usage at runtime.

4. **GraphPipeline event emission** - Added _message_bus attribute and set_message_bus() to GraphPipeline. on_verification_complete now publishes graph.ingested after successful ingestion. register_with_pipeline also captures message_bus from investigation_pipeline if available.

5. **Contradiction detection from 3 sources** - Not just explicit relationships: also REFUTED verifications (resolved contradictions) and same-entity conflicting claims (statement vs denial). Each source produces ContradictionEntry with appropriate resolution_status.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] TYPE_CHECKING import for AnalysisReportingAgent in AnalysisPipeline**

- **Found during:** Task 2 (AnalysisPipeline import verification)
- **Issue:** Direct import of AnalysisReportingAgent triggers agents.__init__.py -> SimpleAgent -> gemini_client -> Settings singleton requiring GEMINI_API_KEY at import time
- **Fix:** Moved import to TYPE_CHECKING guard with runtime import in _get_agent() method body
- **Files modified:** osint_system/pipeline/analysis_pipeline.py
- **Verification:** `uv run python -c "from osint_system.pipeline.analysis_pipeline import AnalysisPipeline"` succeeds without GEMINI_API_KEY (with caveat that GraphPipeline import in pipeline/__init__.py still requires it due to existing architecture)
- **Committed in:** 303b5af (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Essential fix for import chain isolation. Same pattern as 10-01 DataAggregator fix. No scope creep.

## Issues Encountered

None beyond the import chain issue documented above.

## User Setup Required

None - no external service configuration required. All tests run with mocked LLM.

## Next Phase Readiness

- AnalysisPipeline ready for wiring in 10-05's create_app() with report_generator and report_store
- ReportGenerator from 10-04 can call Synthesizer directly or through AnalysisPipeline.run_analysis()
- Full pipeline chain established: classification -> verification -> graph -> analysis
- Entry points:
  ```python
  from osint_system.pipeline import AnalysisPipeline
  from osint_system.analysis import Synthesizer, PatternDetector, ContradictionAnalyzer
  from osint_system.agents.sifters.analysis_reporting_agent import AnalysisReportingAgent

  # Standalone analysis
  pipeline = AnalysisPipeline(fact_store=fs, classification_store=cs, verification_store=vs)
  synthesis = await pipeline.run_analysis("inv-123")

  # Event-driven (auto-triggered by GraphPipeline)
  pipeline.register_with_pipeline(investigation_pipeline)
  ```

---
*Phase: 10-analysis-reporting-engine*
*Completed: 2026-03-14*
