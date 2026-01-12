---
phase: 04-news-crawler
plan: 04-FIX
type: fix
---

<objective>
Fix 5 UAT issues from Phase 4 testing.

Source: 04-ISSUES.md
Priority: 1 blocker, 1 major, 3 minor
Purpose: Restore full functionality to news crawler pipeline
Output: Working storage retrieval, complete metadata extraction, clean RSS parsing
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-phase.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/ROADMAP.md
@.planning/phases/04-news-crawler/04-ISSUES.md
@.planning/phases/04-news-crawler/04-04-PLAN.md
@.planning/phases/04-news-crawler/04-03-PLAN.md
@.planning/phases/04-news-crawler/04-02-PLAN.md
@.planning/phases/04-news-crawler/04-01-PLAN.md
@osint_system/data_management/article_store.py
@osint_system/agents/crawlers/sources/rss_crawler.py
@osint_system/agents/crawlers/newsfeed_agent.py
</context>

<tasks>

<task type="auto">
  <name>Fix UAT-002: ArticleStore retrieval returns dictionary instead of list</name>
  <files>osint_system/agents/crawlers/newsfeed_agent.py, tests/integration/test_crawler_integration.py</files>
  <action>The ArticleStore.retrieve_by_investigation() method returns a dictionary with 'articles' key, not a list. Update NewsFeedAgent and any calling code to correctly access the returned dictionary structure {"articles": [...], "total_articles": N}. In NewsFeedAgent.handle_message(), when retrieving articles from storage, access result['articles'] not just result. Update integration tests to match this pattern. This is the blocker issue preventing proper article retrieval.</action>
  <verify>python -c "import asyncio; from osint_system.data_management.article_store import ArticleStore; async def test(): store = ArticleStore(); await store.save_articles('test_fix', [{'url': 'http://test1', 'title': 'Test 1'}, {'url': 'http://test2', 'title': 'Test 2'}]); result = await store.retrieve_by_investigation('test_fix'); print(f'Articles: {len(result[\"articles\"])}'); return len(result['articles']) == 2; print('PASS' if asyncio.run(test()) else 'FAIL')"</verify>
  <done>ArticleStore retrieval returns correct article count via dictionary['articles'] access</done>
</task>

<task type="auto">
  <name>Fix UAT-003: Parse and extract published dates from RSS feeds</name>
  <files>osint_system/agents/crawlers/sources/rss_crawler.py</files>
  <action>In RSSCrawler._parse_date() method, expand date parsing to handle more RSS date formats. Currently missing many common RSS date fields. Check for: entry.get('published'), entry.get('pubDate'), entry.get('updated'), entry.get('dc:date'), entry.get('created'). Use dateutil.parser.parse() for flexible parsing. If no date found, check for 'published_parsed' or 'updated_parsed' time tuples and convert. Add fallback to current date only if truly no date available. Log which field provided the date for debugging.</action>
  <verify>python -c "import asyncio; from osint_system.agents.crawlers.sources.rss_crawler import RSSCrawler; async def test(): crawler = RSSCrawler(); result = await crawler.parse_feed('https://feeds.bbci.co.uk/news/rss.xml'); entries = result.get('entries', []); dates_found = sum(1 for e in entries[:10] if e.get('published') and 'Unknown' not in str(e.get('published'))); print(f'Dates found: {dates_found}/10'); return dates_found > 5; print('PASS' if asyncio.run(test()) else 'FAIL')"</verify>
  <done>RSS articles have published dates extracted correctly (>50% success rate)</done>
</task>

<task type="auto">
  <name>Fix UAT-004: Handle Reuters RSS feed encoding error</name>
  <files>osint_system/agents/crawlers/sources/rss_crawler.py</files>
  <action>In RSSCrawler.parse_feed(), add specific handling for the Reuters encoding error. Wrap the feedparser.parse() call in a try/except for AttributeError. When catching "object has no attribute 'encoding'" error, retry parsing with explicit encoding by first fetching raw content as bytes, then decode with 'utf-8' or 'latin-1' fallback, then parse the string. Add Reuters-specific handling if URL contains 'reuters'. This prevents one feed failure from logging errors while still continuing with other sources.</action>
  <verify>python -c "import asyncio; from osint_system.agents.crawlers.newsfeed_agent import NewsFeedAgent; async def test(): agent = NewsFeedAgent(); result = await agent.fetch_investigation_data('test', exhaustive=False); stats = result.get('stats', {}); print(f'Fetched from sources: {stats.get(\"source_count\", 0)}'); return True; asyncio.run(test())"</verify>
  <done>Reuters feed error handled gracefully without breaking other feeds</done>
</task>

<task type="auto">
  <name>Fix UAT-001 & UAT-005: Add documentation for optional dependencies</name>
  <files>README.md, osint_system/agents/crawlers/deduplication/dedup_engine.py, osint_system/agents/crawlers/sources/api_crawler.py</files>
  <action>Add "Optional Dependencies" section to README.md explaining: (1) SemHash library is optional - system uses fallback for semantic deduplication if not installed. To enable: 'pip install semhash'. (2) NewsAPI is optional - RSS feeds work without it. To enable NewsAPI: set NEWS_API_KEY environment variable with key from newsapi.org. In dedup_engine.py, change warning to info level. In api_crawler.py, change warning to debug level and add comment that it's optional.</action>
  <verify>cat README.md | grep -A 5 "Optional Dependencies"</verify>
  <done>Documentation clearly explains optional dependencies and warnings are reduced</done>
</task>

</tasks>

<verification>
Before declaring plan complete:
- [ ] ArticleStore retrieval returns correct article counts
- [ ] RSS articles have published dates (>50% success rate)
- [ ] Reuters feed errors handled without breaking pipeline
- [ ] Optional dependencies documented in README
- [ ] All integration tests still pass
</verification>

<success_criteria>
- Blocker issue (UAT-002) fixed - storage retrieval works correctly
- Major issue (UAT-003) fixed - dates extracted from RSS feeds
- Minor issues addressed or documented
- System functions end-to-end without critical errors
- Ready for re-verification with /gsd:verify-work
</success_criteria>

<output>
After completion, create `.planning/phases/04-news-crawler/04-FIX-SUMMARY.md`:

# Phase 4 Fix Summary

**Fixed storage retrieval bug and improved RSS metadata extraction**

## Issues Fixed
- UAT-002 (Blocker): ArticleStore retrieval dictionary access
- UAT-003 (Major): RSS date parsing expanded
- UAT-004 (Minor): Reuters encoding error handled
- UAT-001 & UAT-005 (Minor): Optional dependencies documented

## Files Modified
- Article retrieval logic
- RSS date parsing
- Error handling
- Documentation

## Verification Results
- Storage retrieval works correctly
- Dates extracted from RSS feeds
- All feeds parse without breaking
- Documentation updated

## Ready for Re-verification
Run `/gsd:verify-work 04` to confirm all fixes work correctly
</output>