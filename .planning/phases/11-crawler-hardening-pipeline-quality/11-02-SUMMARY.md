---
phase: 11-crawler-hardening-pipeline-quality
plan: 02
subsystem: crawling, extraction
tags: [rss-fallback, claim-schema, enum-normalization, fact-extraction, pipeline-resilience]

# Dependency graph
requires:
  - phase: 11-01
    provides: BrowserPool fallback in runner._phase_crawl with failed_entries tracking
  - phase: 06-fact-schema
    provides: ExtractedFact and Claim schema with Pydantic validation
provides:
  - RSS summary fallback in runner._phase_crawl for entries that fail both trafilatura and BrowserPool
  - Summary field capture in _poll_rss_feeds from feedparser entries
  - "statement" as valid claim_type in Claim schema
  - Enum normalization for both claim_type and assertion_type in fact_extraction_agent.py
affects:
  - 11-03 (extraction pipeline receives rss_summary articles alongside playwright_fallback articles)
  - 17-crawler-agent-integration (RSS fallback pattern available for agent crawlers)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "3-tier fetch fallback: trafilatura -> BrowserPool -> RSS summary"
    - "Enum normalization: pre-validation mapping before Pydantic Literal construction"
    - "Provenance tagging: metadata.content_source differentiates article origin"

key-files:
  created: []
  modified:
    - osint_system/runner.py
    - osint_system/data_management/schemas/fact_schema.py
    - osint_system/agents/sifters/fact_extraction_agent.py

key-decisions:
  - "RSS fallback runs AFTER BrowserPool, operating on entries that failed BOTH trafilatura AND BrowserPool"
  - "failed_entries list updated after BrowserPool to remove recovered entries before RSS fallback"
  - "12 claim_type normalization entries + 12 assertion_type normalization entries cover observed LLM output patterns"
  - "Unknown claim_type falls back to 'event', unknown assertion_type falls back to 'statement'"

patterns-established:
  - "3-tier fallback chain: trafilatura -> BrowserPool -> RSS summary (each operating on previous tier's failures)"
  - "Pre-validation enum normalization at module level (_CLAIM_TYPE_NORMALIZE, _ASSERTION_TYPE_NORMALIZE)"

# Metrics
duration: 2min
completed: 2026-03-21
---

# Phase 11 Plan 02: RSS Fallback & Enum Normalization Summary

**RSS summary fallback for paywalled/blocked articles, "statement" claim_type, and dual enum normalization for claim_type + assertion_type to prevent silent fact drops**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-21T16:28:08Z
- **Completed:** 2026-03-21T16:30:36Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Added RSS entry summary capture in `_poll_rss_feeds` (feedparser normalizes `entry.summary` and `entry.description` into `entry.summary`)
- After BrowserPool fallback, `failed_entries` now updated to only contain entries that failed BOTH trafilatura AND BrowserPool (previously retained all originally failed entries)
- RSS summary fallback strips HTML, applies 50-char minimum, tags articles with `metadata.content_source='rss_summary'`, and assigns domain-based authority scores
- Extended Claim schema with `"statement"` claim_type (additive, no migration needed)
- Added 12-entry `_CLAIM_TYPE_NORMALIZE` mapping (action->event, opinion->statement, fact->statement, etc.)
- Added 12-entry `_ASSERTION_TYPE_NORMALIZE` mapping (fact->statement, allegation->claim, assertion->claim, etc.)
- Both normalizations applied in `_raw_to_extracted_fact` before Claim construction with fallbacks for completely unknown values

## Task Commits

Each task was committed atomically:

1. **Task 1: RSS summary capture + fallback in runner._phase_crawl** - `52e996c` (feat)
2. **Task 2: "statement" claim_type + dual enum normalization** - `df0a5e2` (feat)

## Files Created/Modified
- `osint_system/runner.py` - summary field in _poll_rss_feeds, failed_entries update after BrowserPool, RSS summary fallback after BrowserPool
- `osint_system/data_management/schemas/fact_schema.py` - "statement" added to Claim.claim_type Literal
- `osint_system/agents/sifters/fact_extraction_agent.py` - _CLAIM_TYPE_NORMALIZE, _ASSERTION_TYPE_NORMALIZE mappings, normalization in _raw_to_extracted_fact

## Decisions Made
- **failed_entries update:** BrowserPool fallback now updates `failed_entries` to only contain entries that failed BOTH tiers, so RSS fallback doesn't re-process entries already recovered by Playwright. This required modifying the 11-01 BrowserPool result loop to track `still_failed` separately.
- **HTML stripping:** Used `re.sub(r'<[^>]+>', '', text)` for RSS summary HTML removal rather than BeautifulSoup (avoids adding dependency for simple tag stripping on short RSS summaries).
- **Normalization scope:** 12 entries per mapping covers all observed LLM output patterns from DeepSeek, Hermes, Nemotron, and Gemini Flash Lite. Unknown values hit final fallback rather than causing Pydantic ValidationError.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- **Pre-existing test failure:** `test_initialization_defaults` expects `gemini-3.1-flash-lite-preview` but agent defaults to `gemini-3-flash`. Pre-existing, unrelated to this plan. 39/40 tests pass.

## User Setup Required
None - no new dependencies, no external service configuration.

## Next Phase Readiness
- 3-tier fetch fallback chain complete (trafilatura -> BrowserPool -> RSS summary)
- Enum normalization prevents silent fact drops from all models in the fallback chain
- Ready for 11-03 (extraction pipeline quality improvements)

---
*Phase: 11-crawler-hardening-pipeline-quality*
*Completed: 2026-03-21*
