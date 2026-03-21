---
phase: 11-crawler-hardening-pipeline-quality
plan: 04
subsystem: verification-pipeline
tags: [adversarial-queries, llm-stance, graph-ingestion, verification]
depends_on:
  requires: [phase-8-verification-loop, phase-9-graph-layer]
  provides: [adversarial-query-generation, llm-stance-fallback, unverifiable-ingestion]
  affects: [phase-12-api-layer, phase-17-crawler-integration]
tech_stack:
  added: []
  patterns: [two-tier-stance-detection, adversarial-query-pairs, constructor-injection-with-lazy-init]
key_files:
  created: []
  modified:
    - osint_system/agents/sifters/verification/query_generator.py
    - osint_system/agents/sifters/verification/search_executor.py
    - osint_system/agents/sifters/graph/graph_ingestor.py
    - osint_system/data_management/schemas/verification_schema.py
    - tests/agents/sifters/verification/test_query_generator.py
decisions:
  - key: adversarial-variant-type
    choice: Added "adversarial" to VerificationQuery.variant_type Literal rather than reusing existing types
    reason: Clean separation between confirming and refuting queries in logging, filtering, and analytics
  - key: llm-client-injection-pattern
    choice: Constructor injection with lazy-init fallback via _get_llm_client()
    reason: Testable (inject mock), production-ready (auto-init from env), zero-config for existing callers
  - key: adversarial-dubious-flag-none
    choice: Adversarial queries have dubious_flag=None (not species-specific)
    reason: Adversarial queries are appended to ALL non-NOISE facts regardless of species, so binding to a species flag is semantically incorrect
metrics:
  duration: 6m 37s
  completed: 2026-03-21
---

# Phase 11 Plan 04: Verification Coverage Gaps Summary

Adversarial query generation, LLM stance fallback for ambiguous snippets, and UNVERIFIABLE fact ingestion into the knowledge graph.

## What Was Done

### Task 1: Adversarial Query Generation (max_queries 3 -> 5)

- Changed `QueryGenerator` default `max_queries` from 3 to 5 (2 confirming + 2 adversarial + 1 original).
- Added `_generate_adversarial_queries()` method producing up to 2 refutation-seeking queries per fact:
  1. Entity + negation keywords (`{entities} denied false disproven`)
  2. Claim phrase + contradiction keywords (`"{claim}" false OR denied OR disproven OR debunked`)
- Added `"adversarial"` to `VerificationQuery.variant_type` Literal in verification_schema.py.
- Adversarial queries appended after species-specific queries in `generate_queries()`, respecting NOISE skip logic.
- Updated 36 existing tests and added 7 new adversarial-specific tests (43 total, all passing).

### Task 2: LLM Stance Fallback and UNVERIFIABLE Ingestion

- Added `llm_client` parameter to `SearchExecutor.__init__` (constructor injection).
- Added `_get_llm_client()` lazy-initialization from `OPENROUTER_API_KEY` environment variable.
- Added `_llm_stance_assessment()` async method using Gemini 3.1 Flash Lite via OpenRouter:
  - Triggers only when regex finds no negation AND snippet > 100 chars AND claim_text provided AND LLM client available.
  - Returns stance as supports/refutes/neutral via JSON mode.
  - Defaults to supporting on LLM failure (graceful degradation).
- Added `claim_text` parameter to `execute_query()` and `execute_queries()` (backward-compatible default `""`).
- Added `VerificationStatus.UNVERIFIABLE` to `_INGESTIBLE_STATUSES` in `graph_ingestor.py`.

## Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Adversarial variant type | New `"adversarial"` Literal value | Clean separation from confirming variants for analytics/filtering |
| LLM client pattern | Constructor injection + lazy-init | Testable with mocks, zero-config for existing callers, auto-discovers OPENROUTER_API_KEY |
| Adversarial dubious_flag | None (not species-specific) | Adversarial queries apply to all non-NOISE facts, not bound to a specific species |
| LLM fallback threshold | Snippet > 100 chars | Shorter snippets lack enough context for meaningful semantic analysis |
| Fallback on LLM error | Default to supports=True | Conservative: don't flip stance on infrastructure failures |

## Deviations from Plan

None -- plan executed exactly as written.

## Commits

| Hash | Message |
|------|---------|
| fd306f4 | feat(11-04): add adversarial query generation and increase max_queries to 5 |
| 6c30ce1 | feat(11-04): add LLM stance fallback to SearchExecutor and UNVERIFIABLE graph ingestion |

## Test Results

- 43 query generator tests: all passing (36 updated + 7 new)
- 451/452 sifter tests passing (1 pre-existing failure in test_fact_extraction_agent.py unrelated to this plan)
- Pre-existing failure: `test_initialization_defaults` asserts model_name == `"gemini-3.1-flash-lite-preview"` but model was changed to `"gemini-3-flash"` in a prior session

## Next Phase Readiness

- `verification_agent.py` calls `execute_query(query)` without `claim_text` -- backward-compatible via default parameter. Future enhancement: thread claim_text from the verification agent's fact context into the search call for LLM stance to activate.
- No blockers for subsequent plans.
