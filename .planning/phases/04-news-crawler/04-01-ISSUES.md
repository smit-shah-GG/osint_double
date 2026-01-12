# UAT Issues: Phase 4 Plan 1

**Tested:** 2026-01-12
**Source:** .planning/phases/04-news-crawler/04-01-SUMMARY.md
**Tester:** User via /gsd:verify-work

## Open Issues

### UAT-001: Deprecated google.generativeai package

**Discovered:** 2026-01-12
**Phase/Plan:** 04-01
**Severity:** Minor
**Feature:** Gemini LLM client initialization
**Description:** System uses deprecated `google.generativeai` package which shows FutureWarning on every run
**Expected:** Clean initialization without warnings
**Actual:** Warning message: "All support for the google.generativeai package has ended. Please switch to the google.genai package"
**Repro:** Run any command that imports osint_system modules
**File:** osint_system/llm/gemini_client.py lines 8-9

## Resolved Issues

[None yet]

---

*Phase: 04-news-crawler*
*Plan: 01*
*Tested: 2026-01-12*