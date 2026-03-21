# Phase 11: Crawler Hardening & Pipeline Quality - Context

**Gathered:** 2026-03-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Make investigations run reliably against real-world sources without silent data loss. Fix crawler fragility (bot detection, paywalls, JS-heavy sites), extraction drops (malformed LLM output), and verification coverage gaps (over-aggressive noise filtering, unverifiable facts dropped). This phase hardens existing pipeline components — no new capabilities, no new UI, no new storage layer.

</domain>

<decisions>
## Implementation Decisions

### Fetch failure behavior
- **Stealth-first Playwright approach**: Rotate User-Agent, add random delays, use stealth plugins (playwright-extra). Try hard to look human before falling back.
- **BrowserPool with 5 concurrent contexts**: Matches existing extraction semaphore (MAX_CONCURRENT_EXTRACTIONS=5). ~500MB memory budget.
- **Paywall strategy (3-tier):**
  1. Googlebot UA + Google referer spoofing (bypass soft paywalls)
  2. RSS summary fallback — when full fetch fails, extract facts from RSS entry's `description`/`summary` field (1-3 lead paragraphs). Treat equally to full articles (no confidence penalty).
  3. Skip and log coverage gap — if both above fail, log which sources were paywalled so analysis can note coverage limitations.
- **No archive.org fallback** — excluded from scope.
- **No unpaywalled extension** — same bypass techniques implemented natively in the fetcher instead.

### LLM output resilience
- **Existing recovery pipeline preserved**: Think-tag stripping, markdown fence extraction, array regex, dict-to-list wrapping, `_repair_json()`, 2-retry loop. No changes to recovery layers.
- **After all retries fail: skip and log** — article yields zero facts, raw response logged for debugging. No fallback to different model on parse failure.
- **Per-model extraction metrics**: Track success/fail/repair counts per model. Emit structured log events for future model selection decisions.
- **Fallback chain logging**: Warn once per model when OpenRouter fallback chain activates (429/5xx). One line per switch, not per request.
- **OpenRouter only**: All LLM calls route through OpenRouter. Remove direct Gemini API path. Single billing point, simpler client code.

### Noise filtering calibration
- **Filter at extraction prompt**: Tell extraction LLM to only extract facts relevant to the investigation objective. Noise never enters the pipeline.
- **Dynamic relevance filter**: Pass investigation objective into extraction prompt — "Extract facts relevant to: [objective]". Not hardcoded to geopolitical.
- **Borderline facts: err toward inclusion** — better to have noise in the report than miss a real signal. Intelligence analysis principle: don't discard prematurely.
- **Per-article quality logging**: Log stats per article as they process (facts extracted, extraction time, failures) plus end-of-run summary table.

### Verification coverage
- **Unverifiable facts: ingest with status tag** — add to knowledge graph with `status='unverified'`. Visible in reports with explicit 'unverified' badge. Don't drop them.
- **Query strategy: confirming + adversarial** — generate both confirming AND refuting query variants per fact. 5 queries max per fact (2 confirming + 2 adversarial + 1 original).
- **LLM stance fallback**: When regex (33 negation patterns) is inconclusive, send snippet + claim to Gemini 3.1 Flash Lite ($0.06/500 calls) for semantic stance assessment.
- **Stance model**: `google/gemini-3.1-flash-lite-preview` via OpenRouter. Supports JSON mode. ~$0.06 total per investigation run.

### Claude's Discretion
- Playwright stealth plugin selection and configuration
- Exact User-Agent rotation pool and delay timing
- JSON repair heuristics beyond current implementation
- Structured log event schema for extraction metrics
- Adversarial query generation prompt design
- LLM stance assessment prompt design

</decisions>

<specifics>
## Specific Ideas

- RSS fallback identified as "highest-ROI fix" in prior session — cheapest to implement, zero ToS concerns, recovers most high-authority sources (Reuters, Bloomberg, NYT)
- Googlebot spoofing: set `User-Agent: Googlebot` + `Referer: https://www.google.com/` — many paywalls show full content to search engine crawlers
- Fresh Playwright context per request inherently handles cookie stripping (paywall visit count tracking)
- Investigation objective already flows through PlanningAgent — needs to be threaded through to extraction prompt
- A/B test revealed swimming results and beer releases in geopolitical intelligence reports — extraction prompt is the right filter point

</specifics>

<deferred>
## Deferred Ideas

- Archive.org / Wayback Machine fallback for paywalled content — reconsidered, excluded from this phase
- Model switching on extraction parse failure (try next model in chain) — decided against, skip-and-log sufficient
- Dual API path (direct Gemini + OpenRouter) — decided OpenRouter-only
- Source type classification fix (carnegieendowment.org as "think_tank" not "news_outlet") — related but likely Phase 12/API layer concern
- Confidence calibration in synthesis prompts (anchor to verification rate) — synthesis is not in Phase 11 scope

</deferred>

---

*Phase: 11-crawler-hardening-pipeline-quality*
*Context gathered: 2026-03-21*
