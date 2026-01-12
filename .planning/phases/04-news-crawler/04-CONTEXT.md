# Phase 4: News Crawler Implementation - Context

**Gathered:** 2026-01-12
**Status:** Ready for research

<vision>
## How This Should Work

The news crawler operates as an on-demand service, triggered by specific investigations rather than continuously monitoring. When activated for an investigation, it takes a depth-over-breadth approach - thoroughly mining selected high-quality sources rather than casting a wide net.

The crawler should be exhaustive in what it returns - gathering everything relevant and letting downstream agents handle filtering and prioritization. Age doesn't matter if the content is relevant; historical articles that provide important context should be included alongside breaking news.

Smart deduplication is essential - the crawler needs to detect when multiple sources are reporting the same story to avoid redundant processing downstream.

</vision>

<essential>
## What Must Be Nailed

- **On-demand operation** - Crawler activates in response to investigation needs, not continuous monitoring
- **Depth over breadth** - Thorough extraction from quality sources rather than surface-level scanning
- **Complete metadata preservation** - Source credibility, temporal context, and geographic context are all equally important
- **Smart deduplication** - Detect and handle duplicate stories across sources
- **Mixed authority sources** - Blend mainstream, specialist, and alternative sources for comprehensive perspective

</essential>

<boundaries>
## What's Out of Scope

- **Social media sources** - Twitter, Reddit, forums are for Phase 5
- **Non-English content** - English-language news only in this phase
- **Paywalled content** - Skip subscription-required sources initially
- **Continuous monitoring** - This phase focuses on on-demand fetching only
- **Content filtering** - Return everything relevant; downstream agents handle prioritization

</boundaries>

<specifics>
## Specific Ideas

- Smart deduplication to identify when multiple outlets report the same story
- Exhaustive retrieval - return all relevant content, not filtered subsets
- No time limits on article age - include older content if it provides context
- Mixed authority levels for sources - mainstream, specialist, and alternative
- Investigation-triggered rather than always-running

</specifics>

<notes>
## Additional Context

The user envisions this as a targeted, thorough crawler that responds to specific investigation needs rather than a broad monitoring system. The emphasis is on depth and completeness of extraction from selected sources, with all filtering and prioritization decisions deferred to downstream processing.

The crawler should be source-agnostic regarding age of content - a weeks-old article providing crucial context is as valuable as breaking news. Deduplication is the only "smart" filtering the crawler should do.

</notes>

---

*Phase: 04-news-crawler*
*Context gathered: 2026-01-12*