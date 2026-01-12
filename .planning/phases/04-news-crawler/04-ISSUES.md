# UAT Issues: Phase 4

**Tested:** 2026-01-13
**Source:** .planning/phases/04-news-crawler/ (all 4 SUMMARY.md files tested)
**Tester:** User via /gsd:verify-work

## Open Issues

### UAT-001: SemHash library not available causing fallback

**Discovered:** 2026-01-13
**Phase/Plan:** 04-03
**Severity:** Minor
**Feature:** Semantic deduplication engine
**Description:** System shows "SemHash library not available - using fallback implementation" warning
**Expected:** Semantic similarity detection using SemHash library
**Actual:** Falls back to basic implementation, potentially reducing deduplication accuracy
**Repro:**
1. Import DeduplicationEngine
2. Observe warning in logs

### UAT-002: ArticleStore retrieval returns incorrect number of articles

**Discovered:** 2026-01-13
**Phase/Plan:** 04-04
**Severity:** Blocker
**Feature:** Article storage and retrieval
**Description:** ArticleStore saves 279 articles but only retrieves 7 when fetching by investigation ID
**Expected:** All 279 saved articles should be retrievable
**Actual:** Only 7 articles returned despite logs showing 279 saved successfully
**Repro:**
1. Fetch articles using NewsFeedAgent.fetch_investigation_data()
2. Save articles to ArticleStore with investigation ID
3. Retrieve articles by same investigation ID
4. Count mismatch: saved 279, retrieved 7

### UAT-003: Missing published dates in RSS feed parsing

**Discovered:** 2026-01-13
**Phase/Plan:** 04-02
**Severity:** Major
**Feature:** RSS feed metadata extraction
**Description:** Published dates showing as "Unknown date" for many RSS articles
**Expected:** Published date extracted from RSS feed metadata
**Actual:** Published field missing or not parsed correctly
**Repro:**
1. Fetch articles from RSS feeds
2. Check published field in article metadata
3. Many show "Unknown date"

### UAT-004: Reuters RSS feed parsing error

**Discovered:** 2026-01-13
**Phase/Plan:** 04-01
**Severity:** Minor
**Feature:** RSS feed parsing
**Description:** Reuters feed consistently fails with "object has no attribute 'encoding'" error
**Expected:** All configured RSS feeds should parse successfully
**Actual:** Reuters feed fails but system continues with other sources
**Repro:**
1. Include Reuters in RSS feed sources
2. Fetch articles
3. Observe error in logs for Reuters feed

### UAT-005: NewsAPI requires API key but not documented

**Discovered:** 2026-01-13
**Phase/Plan:** 04-02
**Severity:** Minor
**Feature:** NewsAPI integration
**Description:** System warns about missing NEWS_API_KEY but continues without it
**Expected:** Either API key requirement documented or system works without it
**Actual:** Warning appears but RSS feeds still work, unclear if NewsAPI is required
**Repro:**
1. Run without NEWS_API_KEY environment variable
2. See warning in logs

## Resolved Issues

[None yet]

---

*Phase: 04-news-crawler*
*Tested: 2026-01-13*