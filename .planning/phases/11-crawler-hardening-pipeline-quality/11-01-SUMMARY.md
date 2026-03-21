---
phase: 11-crawler-hardening-pipeline-quality
plan: 01
subsystem: crawling
tags: [playwright, stealth, cloudflare, browser-pool, user-agent, web-crawler]

# Dependency graph
requires:
  - phase: 04-news-crawler
    provides: HybridWebCrawler with httpx-first Playwright fallback
  - phase: 10-analysis-reporting-engine
    provides: runner.py InvestigationRunner with _phase_crawl
provides:
  - BrowserPool class for persistent browser + context reuse (OOM prevention)
  - Updated User-Agent pool (Chrome 134, Firefox 136, Edge 134, Safari 18.3)
  - Cloudflare challenge page detection (is_cloudflare_challenge)
  - playwright-stealth integration for automation evasion
  - GOOGLEBOT_UA and GOOGLE_REFERER constants for paywall bypass
  - BrowserPool fallback in runner._phase_crawl for failed trafilatura fetches
affects:
  - 11-02 (RSS fallback uses same failed_entries tracking)
  - 11-03 (extraction pipeline receives playwright_fallback articles)
  - 17-crawler-agent-integration (BrowserPool pattern for agent crawlers)

# Tech tracking
tech-stack:
  added: [playwright-stealth>=2.0.2]
  patterns:
    - "BrowserPool: persistent browser + semaphore-bounded context reuse"
    - "Cloudflare detection: 2+ indicator threshold on first 5KB of HTML"
    - "Fallback fetch: trafilatura-first, BrowserPool on failure"

key-files:
  created: []
  modified:
    - osint_system/agents/crawlers/web_crawler.py
    - osint_system/runner.py
    - requirements.txt

key-decisions:
  - "playwright-stealth 2.0.2 API uses Stealth().apply_stealth_async(page), not stealth_async(page)"
  - "BrowserPool.fetch returns empty string on Cloudflare challenge (not exception)"
  - "Runner fallback creates its own BrowserPool instance with try/finally lifecycle"

patterns-established:
  - "BrowserPool: single browser, context-per-request, semaphore(5), finally cleanup"
  - "Fallback provenance tagging: metadata.content_source='playwright_fallback'"

# Metrics
duration: 4min
completed: 2026-03-21
---

# Phase 11 Plan 01: Crawler Stealth & BrowserPool Summary

**BrowserPool with persistent Chromium, playwright-stealth evasion, Cloudflare detection, 8 current User-Agents, and Playwright fallback wired into runner._phase_crawl**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-21T16:19:14Z
- **Completed:** 2026-03-21T16:23:39Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Replaced per-request browser launch (200-500MB each, OOM at 100 articles) with BrowserPool (single browser, 5 concurrent contexts, ~500MB total)
- Updated stale User-Agent strings from Chrome 120/Firefox 121 (2+ years old) to Chrome 134/Firefox 136/Edge 134/Safari 18.3 (March 2026 current)
- Added Cloudflare challenge page detection with 2+ indicator threshold to prevent treating interstitial pages as article content
- Integrated playwright-stealth for WebGL, canvas, navigator.webdriver, and 15+ other fingerprint evasion modules
- Wired BrowserPool into runner._phase_crawl as fallback for failed trafilatura fetches, recovering JS-heavy/Cloudflare-blocked articles

## Task Commits

Each task was committed atomically:

1. **Task 1: BrowserPool, stealth, Cloudflare detection, updated UAs** - `7b122d7` (feat)
2. **Task 2: Wire BrowserPool into runner._phase_crawl** - `85f9424` (feat)

## Files Created/Modified
- `osint_system/agents/crawlers/web_crawler.py` - BrowserPool class, 8 current UAs, GOOGLEBOT_UA/GOOGLE_REFERER, is_cloudflare_challenge(), stealth integration, HybridWebCrawler uses BrowserPool
- `osint_system/runner.py` - BrowserPool fallback in _phase_crawl for failed trafilatura fetches, articles tagged with content_source="playwright_fallback"
- `requirements.txt` - Added playwright-stealth>=2.0.2

## Decisions Made
- **playwright-stealth API:** RESEARCH.md assumed `stealth_async(page)` function, but playwright-stealth 2.0.2 actually uses `Stealth().apply_stealth_async(page)` class-based API. Corrected during execution.
- **BrowserPool.fetch error handling:** Returns empty string on both Cloudflare challenge detection and navigation failure (consistent interface, caller checks for empty string).
- **Runner BrowserPool lifecycle:** Runner creates its own BrowserPool instance per _phase_crawl invocation with try/finally cleanup, rather than sharing with HybridWebCrawler (which isn't used in the production path).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] playwright-stealth API mismatch**
- **Found during:** Task 1 (stealth integration)
- **Issue:** RESEARCH.md specified `from playwright_stealth import stealth_async` but v2.0.2 exports `Stealth` class, not `stealth_async` function
- **Fix:** Changed to `from playwright_stealth import Stealth` and `await Stealth().apply_stealth_async(page)`
- **Files modified:** osint_system/agents/crawlers/web_crawler.py
- **Verification:** `uv run python -c "from playwright_stealth import Stealth; Stealth().apply_stealth_async"` succeeds
- **Committed in:** 7b122d7

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** API mismatch in research doc, corrected at implementation. No scope creep.

## Issues Encountered
None beyond the stealth API mismatch documented above.

## User Setup Required
None - no external service configuration required. playwright-stealth installs via `uv pip install -r requirements.txt`.

## Next Phase Readiness
- BrowserPool and stealth infrastructure ready for use by RSS fallback (11-02)
- `failed_entries` tracking in runner._phase_crawl ready for RSS summary fallback to hook into
- Cloudflare detection ready for extraction pipeline to use (11-03)
- Remaining Phase 11 concerns: LLM output resilience (11-03), verification coverage (11-04)

---
*Phase: 11-crawler-hardening-pipeline-quality*
*Completed: 2026-03-21*
