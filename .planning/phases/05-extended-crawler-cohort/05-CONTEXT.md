# Phase 5: Extended Crawler Cohort - Context

**Gathered:** 2026-01-13
**Status:** Ready for research

<vision>
## How This Should Work

The extended crawler cohort operates as an intelligent, interconnected system that follows leads across different source types. Rather than blindly collecting everything, crawlers use smart targeting to track entities across platforms, expand from core topics to related discussions, and automatically cross-validate claims by searching for corroboration.

When a news article mentions a Reddit thread or references a document, the system follows those trails. Crawlers share discovered entities and topics with each other, creating a collaborative intelligence network where each crawler's findings help others locate related content. The focus is on following high-value trails deeper rather than shallow, broad collection.

The system starts with incremental collection — beginning narrow and expanding only when initial results prove insufficient. This prevents information overload while ensuring comprehensive coverage when needed.

</vision>

<essential>
## What Must Be Nailed

- **Quality filtering** - The critical differentiator. Only relevant, high-quality content worth processing should enter the system. This prevents downstream agents from drowning in noise.
- **Authority signals** - Crawlers must identify and prioritize credible sources, verified accounts, and official information
- **Novelty detection** - Avoid collecting redundant information already in the dataset

</essential>

<boundaries>
## What's Out of Scope

- Deep web access - No Tor, dark web, or authenticated/private sources
- Real-time streaming - Batch processing only, no live feeds or real-time monitoring
- Media analysis - Text only, no image/video/audio processing
- Historical archives - Focus on recent content, not deep historical data mining
- Top-level crawling only - Not trying to index entire platforms

</boundaries>

<specifics>
## Specific Ideas

- **Reddit thread prioritization**: Focus on discussion threads with high engagement, following comment chains for context. The valuable insights often come from the discussion, not just the original post.
- **Shared context between crawlers**: Crawlers should share discovered entities and topics to help each other find related content — creating a collaborative intelligence effect
- **Follow high-value trails**: Go deeper into threads/documents only when authority signals or relevance scores justify it
- **Incremental collection**: Start narrow with core sources, expand collection only if initial results are insufficient

</specifics>

<notes>
## Additional Context

User's vision emphasizes intelligence over volume. The crawler cohort should act like a team of investigators following leads, not vacuum cleaners sucking up everything. Quality filtering is the absolute priority — better to miss some content than to overwhelm the system with noise.

The interaction between crawlers is key: they should enhance each other's effectiveness through shared context, not just operate in parallel. This phase sets up the infrastructure for smart, targeted intelligence gathering that scales efficiently.

Entity tracking, topic expansion, and cross-validation are the core intelligent behaviors that distinguish this from simple web scraping.

</notes>

---

*Phase: 05-extended-crawler-cohort*
*Context gathered: 2026-01-13*