---
phase: 10-analysis-reporting-engine
plan: 01
subsystem: analysis, config
tags: [pydantic, schemas, data-aggregation, investigation-snapshot, analysis-config, ic-confidence]

requires:
  - phase: 06-fact-extraction-pipeline
    provides: ExtractedFact schema, FactStore
  - phase: 07-fact-classification-system
    provides: FactClassification schema, ClassificationStore, DubiousFlag taxonomy
  - phase: 08-verification-loop
    provides: VerificationResult schema, VerificationStore, VerificationStatus
  - phase: 09-knowledge-graph-integration
    provides: GraphPipeline with query convenience, QueryResult

provides:
  - Analysis output Pydantic models (AnalysisSynthesis, KeyJudgment, AlternativeHypothesis, etc.)
  - InvestigationSnapshot container for all investigation data
  - DataAggregator for collecting from all stores into single snapshot
  - AnalysisConfig with from_env() for synthesis model, token budgets, dashboard settings
  - Phase 10 dependencies pinned (mistune, WeasyPrint, Jinja2, FastAPI, uvicorn)

affects:
  - 10-02 (synthesis engine consumes InvestigationSnapshot, produces AnalysisSynthesis)
  - 10-03 (report generator renders AnalysisSynthesis to Markdown/PDF)
  - 10-04 (database exporter uses InvestigationSnapshot for SQLite export)
  - 10-05 (dashboard displays InvestigationSnapshot and AnalysisSynthesis)

tech-stack:
  added: [mistune, WeasyPrint, Jinja2, fastapi, uvicorn]
  patterns:
    - IC-style confidence language (low/moderate/high) with numeric backing
    - InvestigationSnapshot as single typed container for all investigation data
    - DataAggregator parallel store fetching with asyncio.gather
    - TYPE_CHECKING import to avoid cascading import chains from pipeline layer
    - from_env() classmethod pattern matching GraphConfig

key-files:
  created:
    - osint_system/analysis/__init__.py
    - osint_system/analysis/schemas.py
    - osint_system/analysis/data_aggregator.py
    - osint_system/config/analysis_config.py
    - tests/analysis/__init__.py
    - tests/analysis/test_schemas.py
    - tests/analysis/test_data_aggregator.py
  modified:
    - requirements.txt

key-decisions:
  - "TYPE_CHECKING import for GraphPipeline to avoid cascading Settings singleton validation"
  - "get_priority_queue(exclude_noise=False) as the method to fetch ALL classifications from ClassificationStore"
  - "Timeline confidence derived from classification credibility_score (high >= 0.7, moderate >= 0.4, low < 0.4)"
  - "Source inventory groups facts by source_id from provenance, enriches authority from verification evidence"
  - "token_estimate() uses len(json) / 4 heuristic for prompt budget planning"

patterns-established:
  - "InvestigationSnapshot: single typed container for all investigation data ready for synthesis"
  - "DataAggregator: parallel async fetch from all stores, then compute derived fields"
  - "AnalysisConfig.from_env(): ANALYSIS_ prefix env vars matching GraphConfig pattern"

duration: 7min
completed: 2026-03-14
---

# Phase 10 Plan 01: Analysis Schemas & Data Aggregation Summary

**IC-style analysis output Pydantic models (8 schema types) plus DataAggregator that collects all investigation data from FactStore, ClassificationStore, VerificationStore, and optional GraphPipeline into a single typed InvestigationSnapshot with source inventory, chronological timeline, and verification counts.**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-14T12:26:10Z
- **Completed:** 2026-03-14T12:33:15Z
- **Tasks:** 2/2
- **Files created:** 7
- **Files modified:** 1

## Accomplishments

- 8 typed Pydantic models for analysis output: ConfidenceAssessment, KeyJudgment, AlternativeHypothesis, ContradictionEntry, TimelineEntry, SourceInventoryEntry, InvestigationSnapshot, AnalysisSynthesis
- DataAggregator with parallel async fetching from all 3 stores + optional graph, producing self-contained InvestigationSnapshot
- AnalysisConfig with from_env() for synthesis model, token budgets, dashboard host/port, auto-generation toggle
- All Phase 10 dependencies (mistune, WeasyPrint, Jinja2, FastAPI, uvicorn) pinned in requirements.txt
- 33 tests total (19 schema validation + 14 data aggregator integration)

## Task Commits

1. **Task 1: Analysis Pydantic schemas and AnalysisConfig** - `c326380` (feat)
2. **Task 2: DataAggregator** - `e5198fd` (feat)

## Files Created/Modified

- `osint_system/analysis/__init__.py` - Package init exporting all schema classes and DataAggregator
- `osint_system/analysis/schemas.py` (553 lines) - 8 Pydantic models for analysis output
- `osint_system/analysis/data_aggregator.py` (410 lines) - DataAggregator collecting from all stores into InvestigationSnapshot
- `osint_system/config/analysis_config.py` (221 lines) - AnalysisConfig with from_env()
- `tests/analysis/__init__.py` - Test package init
- `tests/analysis/test_schemas.py` (301 lines) - 19 schema validation tests
- `tests/analysis/test_data_aggregator.py` (395 lines) - 14 integration tests with populated stores
- `requirements.txt` - Added mistune, WeasyPrint, Jinja2, fastapi, uvicorn

## Decisions Made

1. **TYPE_CHECKING import for GraphPipeline** - Importing GraphPipeline at runtime triggers the agent -> llm -> Settings chain which requires GEMINI_API_KEY. Using `TYPE_CHECKING` avoids this cascade while preserving type hints.

2. **Classification fetching via get_priority_queue** - ClassificationStore has no "get all classifications" method. `get_priority_queue(exclude_noise=False)` returns all classifications sorted by priority_score, which is the correct API.

3. **Timeline confidence from classification credibility** - Timeline entries derive ConfidenceAssessment from the fact's classification credibility_score: >= 0.7 is "high", >= 0.4 is "moderate", < 0.4 is "low".

4. **Source inventory enrichment from verification evidence** - Authority scores and source types are enriched from verification evidence items, not just from provenance metadata. This provides more accurate source assessment.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] GraphPipeline import triggers Settings singleton validation**

- **Found during:** Task 2 (DataAggregator import verification)
- **Issue:** `from osint_system.pipeline.graph_pipeline import GraphPipeline` cascades through agent -> llm -> Settings, which requires GEMINI_API_KEY env var
- **Fix:** Changed from try/except import to `TYPE_CHECKING` guard; DataAggregator already uses `from __future__ import annotations` so string-based type hints work
- **Files modified:** osint_system/analysis/data_aggregator.py
- **Verification:** `uv run python -c "from osint_system.analysis.data_aggregator import DataAggregator"` succeeds without GEMINI_API_KEY
- **Committed in:** e5198fd (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Essential fix for import chain isolation. No scope creep.

## Issues Encountered

None beyond the import chain issue documented above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All downstream plans can import schemas: `from osint_system.analysis import AnalysisSynthesis, InvestigationSnapshot, DataAggregator`
- DataAggregator ready for use by synthesis engine (10-02)
- AnalysisConfig ready for LLM model selection and token budget configuration
- Phase 10 dependencies pinned for remaining plans (10-02 through 10-05)

---
*Phase: 10-analysis-reporting-engine*
*Completed: 2026-03-14*
