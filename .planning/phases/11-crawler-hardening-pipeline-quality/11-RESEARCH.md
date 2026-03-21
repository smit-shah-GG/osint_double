# Phase 11: Crawler Hardening & Pipeline Quality - Research

**Researched:** 2026-03-21
**Domain:** Web crawling stealth, LLM output resilience, verification coverage
**Confidence:** HIGH (codebase analysis) / MEDIUM (library specifics)

## Summary

Phase 11 hardens four distinct subsystems: (1) the web crawler for bot-detection evasion and JS-heavy sites, (2) the RSS fallback path when article fetch fails, (3) LLM output parsing resilience against malformed JSON from fallback chain models, and (4) verification coverage gaps where valid facts are dropped as NOISE or where unverifiable facts never reach the knowledge graph.

The existing codebase has clear insertion points for each requirement. The `HybridWebCrawler` already has a Playwright path but launches a new browser per request (OOM risk). The `FactExtractionAgent` already strips `<think>` tags and repairs JSON but has no per-model metrics and no `"statement"` in the `Claim.claim_type` Literal. The `QueryGenerator` generates only confirming queries. The `GraphIngestor._INGESTIBLE_STATUSES` excludes `UNVERIFIABLE`.

**Primary recommendation:** This is a hardening phase -- no new architectures, just targeted fixes across 4 files (web_crawler.py, fact_extraction_agent.py/fact_schema.py, query_generator.py, graph_ingestor.py) plus 2 new files (stealth fetcher, extraction metrics logger). Implementation order should follow the dependency chain: schema fixes first, then crawler, then extraction, then verification/graph.

## Standard Stack

### Core (New Dependencies)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `playwright-stealth` | 2.0.2 | Anti-bot evasion for Playwright | Industry-standard Python port of puppeteer-extra-plugin-stealth. Masks `navigator.webdriver`, removes "HeadlessChrome" from UA. MIT license. |
| `playwright` | >=1.40 | Browser automation | Already in requirements.txt. Used for JS-heavy site rendering. |

### Already Present (No Changes)
| Library | Version | Purpose | Status |
|---------|---------|---------|--------|
| `httpx` | >=0.25.0 | Fast async HTTP client | Already used in web_crawler.py |
| `feedparser` | latest | RSS/Atom parsing | Already used in rss_crawler.py |
| `trafilatura` | >=1.6.0 | Article text extraction | Used in runner.py for fetching |
| `openai` | >=1.0 | OpenRouter API client | Already used via openrouter_client.py |
| `ddgs` | >=9.0 | DuckDuckGo search | Already used in search_executor.py |
| `pydantic` | >=2.0 | Schema validation | Core schema layer |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `playwright-stealth` | `rebrowser-playwright` | Binary-level Chromium patches (deeper evasion) but requires custom Chromium build. Overkill for news sites. |
| `playwright-stealth` | `seleniumbase` UC mode | Different framework entirely, would require rewriting crawler. Not compatible. |
| Crawlee BrowserPool | Custom pool | Crawlee's BrowserPool has retirement policies and lifecycle hooks but adds a heavy dependency. Custom pool with asyncio.Semaphore + context reuse is simpler and matches existing patterns. |

**Installation:**
```bash
uv pip install playwright-stealth
```
No other new packages needed. All other dependencies already present.

## Architecture Patterns

### Current File Structure (Relevant Files)
```
osint_system/
├── agents/
│   ├── crawlers/
│   │   ├── web_crawler.py          # MODIFY: Add BrowserPool, stealth, Cloudflare detection
│   │   ├── sources/
│   │   │   └── rss_crawler.py      # READ-ONLY: RSS entry already has summary/description field
│   │   └── extractors/
│   │       └── article_extractor.py # MODIFY: RSS fallback behavior on fetch failure
│   └── sifters/
│       ├── fact_extraction_agent.py  # MODIFY: enum normalization, per-model metrics
│       ├── verification/
│       │   ├── query_generator.py    # MODIFY: adversarial query variants
│       │   ├── search_executor.py    # MODIFY: LLM stance fallback (optional)
│       │   └── evidence_aggregator.py # READ-ONLY: stance logic already correct
│       └── graph/
│           └── graph_ingestor.py     # MODIFY: add UNVERIFIABLE to _INGESTIBLE_STATUSES
├── config/
│   └── prompts/
│       └── fact_extraction_prompts.py # MODIFY: dynamic objective injection
├── data_management/
│   └── schemas/
│       └── fact_schema.py            # MODIFY: add "statement" to claim_type Literal
├── llm/
│   ├── openrouter_client.py          # MODIFY: warn-once fallback logging
│   └── gemini_client.py              # MODIFY: remove direct Gemini API path OR deprecate
├── pipelines/
│   └── extraction_pipeline.py        # MODIFY: per-article quality logging
└── runner.py                         # MODIFY: thread objective to extraction prompt
```

### Pattern 1: BrowserPool with Playwright Stealth
**What:** Replace per-request `async_playwright() -> launch() -> new_page()` with a persistent browser + context pool.
**When to use:** All Playwright-rendered fetches in `HybridWebCrawler._playwright_fetch()`.

**Current code (OOM-prone):**
```python
# web_crawler.py line 228-239: launches NEW browser per request
async with async_playwright() as p:
    browser = await p.chromium.launch(headless=True)
    page = await browser.new_page(user_agent=self._get_user_agent())
    await page.goto(url, timeout=self.playwright_timeout * 1000)
    await page.wait_for_load_state("networkidle")
    html = await page.content()
    await browser.close()
```

**Target pattern (context reuse):**
```python
# Source: playwright-stealth 2.0.2 docs + Playwright official docs
from playwright.async_api import async_playwright, Browser, BrowserContext
from playwright_stealth import stealth_async

class BrowserPool:
    """Persistent browser with rotated contexts. Max 5 concurrent."""

    def __init__(self, max_contexts: int = 5):
        self._max = max_contexts
        self._semaphore = asyncio.Semaphore(max_contexts)
        self._playwright = None
        self._browser: Browser | None = None

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )

    async def fetch(self, url: str, user_agent: str, timeout_ms: int) -> str:
        async with self._semaphore:
            context = await self._browser.new_context(
                user_agent=user_agent,
                viewport={"width": 1920, "height": 1080},
            )
            page = await context.new_page()
            await stealth_async(page)
            try:
                await page.goto(url, timeout=timeout_ms, wait_until="networkidle")
                return await page.content()
            finally:
                await context.close()  # Releases memory for this context

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
```

**Key design points:**
- Single browser process, multiple contexts (each context ~ 50-100MB vs 200-500MB per browser)
- `asyncio.Semaphore(5)` matches `MAX_CONCURRENT_EXTRACTIONS` in extraction_pipeline.py
- Context created per request and closed after -- inherently strips cookies (paywall visit counters)
- `stealth_async(page)` applied per page, not per context (library requirement)

### Pattern 2: RSS Summary Fallback
**What:** When article fetch returns None, extract facts from the RSS entry's `summary`/`description` field.
**Where:** `runner.py` `_phase_crawl()` and/or `newsfeed_agent.py` `_normalize_article()`.

**Current behavior:** `_fetch_article_sync()` returns `None` on failure. Article is silently dropped.
**Target behavior:** When trafilatura returns None, fall back to RSS entry text:

```python
# In runner.py _phase_crawl() after trafilatura fetch
article = await loop.run_in_executor(None, _fetch_article_sync, entry["url"])
if article is None:
    # RSS fallback: use entry summary as article content
    rss_summary = entry.get("summary", "") or entry.get("description", "")
    if rss_summary and len(rss_summary.strip()) > 50:
        article = {
            "url": entry["url"],
            "title": entry.get("title", ""),
            "content": rss_summary,  # 1-3 lead paragraphs from RSS
            "published_date": entry.get("published", ""),
            "source": {
                "name": entry.get("source", "unknown"),
                "type": "news_outlet",
            },
            "metadata": {
                "content_source": "rss_summary",  # Track provenance
                "content_length": len(rss_summary),
            },
        }
```

**Key design points:**
- No confidence penalty for RSS-sourced content (per CONTEXT.md decision)
- Tag `metadata.content_source = "rss_summary"` for debugging/analytics
- Minimum 50 chars to avoid extracting from empty summaries
- RSS `summary` field already populated by feedparser in `rss_crawler._normalize_entry()`

### Pattern 3: LLM Enum Normalization Pre-Validation
**What:** Normalize `claim_type` values before Pydantic validation to prevent silent drops.
**Where:** `fact_extraction_agent.py` `_raw_to_extracted_fact()`.

**Current problem:**
```python
# fact_schema.py line 48-50
claim_type: Literal["event", "state", "relationship", "prediction", "planned"] = "event"
# LLMs in fallback chain output "statement" -- Pydantic silently uses default "event"
# or raises ValidationError depending on strict mode
```

**Fix (two-part):**
1. Add `"statement"` to the `claim_type` Literal in `fact_schema.py`
2. Add normalization mapping in `_raw_to_extracted_fact()`:

```python
# In _raw_to_extracted_fact
_CLAIM_TYPE_NORMALIZE = {
    "statement": "statement",
    "action": "event",
    "fact": "statement",
    "opinion": "statement",
    "assertion": "statement",
    "observation": "state",
    "description": "state",
}
raw_type = claim_data.get("claim_type", "event")
claim_type = _CLAIM_TYPE_NORMALIZE.get(raw_type.lower(), raw_type.lower())
if claim_type not in {"event", "state", "relationship", "prediction", "planned", "statement"}:
    claim_type = "event"  # Final fallback
```

### Pattern 4: Adversarial Query Variants
**What:** Add refutation/adversarial queries alongside confirming queries.
**Where:** `query_generator.py`, new method `_generate_adversarial_queries()`.

**Current state:** All queries are confirming (entity_focused, exact_phrase, broader_context).
**Target:** 5 queries max: 2 confirming + 2 adversarial + 1 original.

```python
def _generate_adversarial_queries(
    self,
    fact: dict[str, Any],
    claim_text: str,
    entity_str: str,
) -> list[VerificationQuery]:
    """Generate adversarial/refutation queries to seek disconfirming evidence."""
    queries = []
    if entity_str:
        queries.append(VerificationQuery(
            query=f"{entity_str} denied false disproven",
            variant_type="broader_context",  # Reuse existing variant type
            target_sources=["news_outlet", "wire_service"],
            purpose="Seek refuting evidence for claim",
            dubious_flag=None,
        ))
    if claim_text:
        phrase = claim_text[:60].strip()
        queries.append(VerificationQuery(
            query=f'"{phrase}" false OR denied OR disproven',
            variant_type="exact_phrase",
            target_sources=["news_outlet"],
            purpose="Seek contradiction via negation keywords",
            dubious_flag=None,
        ))
    return queries
```

### Anti-Patterns to Avoid
- **Launching browser per request:** Current `_playwright_fetch()` does `async_playwright() -> launch() -> close()` per URL. Each Chromium process is 200-500MB. With 100 articles, that is guaranteed OOM.
- **Silent enum drops:** Pydantic `Literal` with strict validation drops facts when LLM returns unexpected enum values. Always normalize before validation.
- **Hardcoded NOISE threshold:** The current NOISE classification at `source_credibility < 0.3` catches too many valid facts from lesser-known sources. The fix is in extraction prompt, not threshold tuning.
- **Regex-only stance detection:** 33 negation patterns work for clear cases but miss nuanced refutation. LLM fallback is needed for ambiguous snippets.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Browser fingerprint evasion | Custom `navigator.webdriver` patches | `playwright-stealth` 2.0.2 | 15+ evasion modules maintained by community, covers WebGL, canvas, plugins, permissions, etc. |
| Browser pool lifecycle | Custom process management | `asyncio.Semaphore` + Playwright context reuse | Crawlee's BrowserPool is overkill -- we need 5 contexts, not 100. Semaphore + context.close() is sufficient. |
| RSS feed parsing | Custom XML parsing | `feedparser` (already used) | 20+ years of edge cases handled. Summary/description field already normalized. |
| JSON repair | Complex parser | Existing `_repair_json()` + `_extract_json_from_response()` | Current implementation handles truncation, missing commas, markdown fences, think-tags. Extend, don't replace. |
| Cloudflare challenge detection | Cloudflare API integration | Simple HTML heuristic check | Check for `cf-turnstile`, `challenge-form`, `__cf_chl_f_tk` in HTML. Cloudflare intentionally obscures AI Labyrinth specifics, so heuristic detection of challenge pages is the pragmatic approach. |

**Key insight:** This phase is hardening, not greenfield. Every component being modified already exists. The task is to add resilience layers, not rebuild.

## Common Pitfalls

### Pitfall 1: Playwright Context Leak
**What goes wrong:** Contexts not closed on exception, accumulating memory until process crashes.
**Why it happens:** `await context.close()` skipped when `page.goto()` or `page.content()` throws.
**How to avoid:** Always use `try/finally` for context cleanup. The BrowserPool pattern above uses `finally: await context.close()`.
**Warning signs:** Memory usage climbing monotonically across a batch run. Check with `psutil.Process().memory_info().rss`.

### Pitfall 2: User-Agent / Header Inconsistency
**What goes wrong:** Bot detection triggered despite UA rotation because other headers (Accept-Language, Sec-CH-UA) don't match the claimed browser.
**Why it happens:** Setting only `User-Agent` header while leaving Playwright's default Sec-CH-UA values.
**How to avoid:** When setting custom UA via `browser.new_context(user_agent=...)`, also set `locale`, `timezone_id`, and use `stealth_async()` which patches Client Hints.
**Warning signs:** 403s from sites that were previously accessible.

### Pitfall 3: stealth_async Must Be Per-Page
**What goes wrong:** Stealth applied to context but not individual pages, leaving pages detectable.
**Why it happens:** playwright-stealth 2.0.2 API changed -- `stealth_async(page)` is the correct call, not `stealth_async(context)`.
**How to avoid:** Apply `await stealth_async(page)` after `context.new_page()`, before `page.goto()`.
**Warning signs:** `navigator.webdriver` returns `true` in browser console.

### Pitfall 4: RSS Summary Content May Contain HTML
**What goes wrong:** Facts extracted from RSS summary contain embedded HTML tags (`<p>`, `<a>`, `<b>`), corrupting claim text.
**Why it happens:** RSS `description` field often contains HTML fragments, not plain text.
**How to avoid:** Strip HTML from RSS summary before passing to extraction. Use `BeautifulSoup(text, "html.parser").get_text()` or simple regex `re.sub(r'<[^>]+>', '', text)`.
**Warning signs:** Entity markers like `[E1:<a href=...]` in extracted facts.

### Pitfall 5: Claim Schema Migration Risk
**What goes wrong:** Adding `"statement"` to `Claim.claim_type` Literal breaks existing serialized facts if loaded with strict validation.
**Why it happens:** Pydantic v2 Literal validation rejects values not in the type.
**How to avoid:** This is an additive change (new enum value), not destructive. Existing facts with `claim_type="event"` remain valid. Only new extractions will produce `"statement"`. No migration needed.
**Warning signs:** None -- this is safe.

### Pitfall 6: NOISE Threshold vs Extraction Prompt
**What goes wrong:** Tuning the NOISE credibility threshold from 0.3 to lower value lets in actual noise, while raising it drops valid facts from less-known sources.
**Why it happens:** Threshold-based classification can't distinguish "irrelevant to investigation" from "low-credibility source."
**How to avoid:** Per CONTEXT.md decision: filter at extraction prompt, not at classification. Pass investigation objective into extraction prompt so the LLM only extracts relevant facts. Don't change NOISE threshold.
**Warning signs:** A/B test results showing swimming results and beer releases in geopolitical intelligence reports.

### Pitfall 7: OpenRouter Response Healing vs Manual JSON Repair
**What goes wrong:** Double-processing JSON -- OpenRouter's Response Healing fixes some issues, then our `_repair_json()` tries to fix already-valid JSON and corrupts it.
**Why it happens:** OpenRouter's Response Healing (announced 2025) automatically fixes malformed JSON before delivery. Our repair pipeline doesn't know if response was already healed.
**How to avoid:** Keep repair pipeline as-is. Response Healing is transparent and only fixes genuinely broken JSON. Our pipeline's first step is `json.loads()` which succeeds on already-valid JSON. Repair only triggers on parse failure. No conflict.
**Warning signs:** None -- the two layers are complementary.

## Code Examples

### Cloudflare Challenge Page Detection
```python
# Source: Cloudflare documentation + community patterns
import re

_CF_CHALLENGE_INDICATORS = [
    re.compile(r'cf-turnstile', re.IGNORECASE),
    re.compile(r'challenge-form', re.IGNORECASE),
    re.compile(r'__cf_chl_f_tk', re.IGNORECASE),
    re.compile(r'cf-browser-verification', re.IGNORECASE),
    re.compile(r'cf_clearance', re.IGNORECASE),
    re.compile(r'Checking your browser', re.IGNORECASE),
    re.compile(r'Enable JavaScript and cookies to continue', re.IGNORECASE),
    re.compile(r'ray\s+id', re.IGNORECASE),  # Cloudflare Ray ID in challenge pages
]

# AI Labyrinth detection (best-effort -- Cloudflare intentionally obscures)
_CF_LABYRINTH_INDICATORS = [
    # AI-generated content with nofollow links to more AI content
    # Content is topically unrelated to the source domain
    # Multiple nofollow links to same-domain paths that return AI content
]

def is_cloudflare_challenge(html: str) -> bool:
    """Detect Cloudflare challenge/interstitial pages.

    Returns True if HTML appears to be a Cloudflare challenge page
    rather than actual article content.
    """
    if len(html) > 50000:
        return False  # Challenge pages are small

    hits = sum(1 for p in _CF_CHALLENGE_INDICATORS if p.search(html[:5000]))
    return hits >= 2  # Require 2+ indicators to avoid false positives
```

### Updated User-Agent Pool (March 2026)
```python
# Source: useragents.me, geekflare.com/guides/latest-browser-user-agents
USER_AGENTS: list[str] = [
    # Chrome (Windows) -- ~65% market share
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    # Chrome (macOS)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    # Chrome (Linux)
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    # Firefox (Windows) -- ~8% market share
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:136.0) "
    "Gecko/20100101 Firefox/136.0",
    # Firefox (macOS)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:136.0) "
    "Gecko/20100101 Firefox/136.0",
    # Firefox (Linux)
    "Mozilla/5.0 (X11; Linux x86_64; rv:136.0) "
    "Gecko/20100101 Firefox/136.0",
    # Edge (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 Edg/134.0.0.0",
    # Safari (macOS)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.3 Safari/605.1.15",
]

# Googlebot UA for soft paywall bypass (Tier 1 of paywall strategy)
GOOGLEBOT_UA = (
    "Mozilla/5.0 (compatible; Googlebot/2.1; "
    "+http://www.google.com/bot.html)"
)
GOOGLE_REFERER = "https://www.google.com/"
```

### Per-Model Extraction Metrics Logging
```python
# Structured log events for extraction metrics
import structlog
from dataclasses import dataclass, field
from typing import Dict

@dataclass
class ExtractionMetrics:
    """Per-model extraction success/failure tracking."""
    model_id: str
    success_count: int = 0
    failure_count: int = 0
    repair_count: int = 0
    total_facts: int = 0
    total_duration_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0

    def emit(self, logger: structlog.BoundLogger) -> None:
        logger.info(
            "extraction_metrics",
            model=self.model_id,
            success=self.success_count,
            failures=self.failure_count,
            repairs=self.repair_count,
            facts=self.total_facts,
            success_rate=f"{self.success_rate:.1%}",
            avg_ms=self.total_duration_ms / max(1, self.success_count + self.failure_count),
        )

# Usage in ExtractionPipeline or FactExtractionAgent
_metrics: Dict[str, ExtractionMetrics] = {}
```

### Dynamic Extraction Prompt with Objective
```python
# Modified user prompt template with investigation objective
FACT_EXTRACTION_USER_PROMPT_V2 = """Extract all discrete, verifiable facts from the following source text.

INVESTIGATION OBJECTIVE: {objective}
Only extract facts relevant to this investigation objective. Skip facts unrelated to the objective.

SOURCE_ID: {source_id}
SOURCE_TYPE: {source_type}
PUBLICATION_DATE: {publication_date}

---TEXT START---
{text}
---TEXT END---

Return ONLY a valid JSON array of fact objects. No other text, no markdown formatting, just the JSON array."""
```

### UNVERIFIABLE Status in GraphIngestor
```python
# graph_ingestor.py -- add UNVERIFIABLE to ingestible statuses
_INGESTIBLE_STATUSES = {
    VerificationStatus.CONFIRMED,
    VerificationStatus.SUPERSEDED,
    VerificationStatus.UNVERIFIABLE,  # NEW: ingest with status tag
}
```

### LLM Stance Fallback for Ambiguous Snippets
```python
# In search_executor.py or new module
async def _llm_stance_assessment(
    self,
    snippet: str,
    claim_text: str,
) -> bool:
    """LLM fallback for stance detection when regex is inconclusive.

    Uses Gemini 3.1 Flash Lite via OpenRouter ($0.06/500 calls).
    Returns True if snippet supports claim, False if refutes.
    """
    prompt = (
        f"Does the following snippet SUPPORT or REFUTE the claim?\n\n"
        f"CLAIM: {claim_text}\n\n"
        f"SNIPPET: {snippet}\n\n"
        f"Respond with JSON: {{\"stance\": \"supports\" | \"refutes\" | \"neutral\"}}"
    )
    try:
        response = await self._llm_client.aio.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=[prompt],
            config={
                "temperature": 0.0,
                "max_output_tokens": 50,
                "response_format": "json",
            },
        )
        import json
        result = json.loads(response.text)
        return result.get("stance", "neutral") != "refutes"
    except Exception:
        return True  # Default to supporting on failure
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Per-request browser launch | BrowserPool with context reuse | Playwright best practice, 2024+ | 5-10x memory reduction for batch crawling |
| Static User-Agent pool (Chrome 120) | Rotated current UAs (Chrome 134, Firefox 136) | Ongoing -- UAs must be updated quarterly | Reduces 403s from UA-based blocking |
| `navigator.webdriver` only | `playwright-stealth` 2.0.2 (15+ evasion modules) | Feb 2026 release | Covers WebGL, canvas, permissions, plugins |
| Hardcoded extraction prompt | Dynamic objective-aware prompt | Phase 11 requirement | Filters noise at source instead of post-hoc |
| Confirming-only queries | Confirming + adversarial query pairs | Phase 11 requirement | Enables genuine refutation detection |

**Deprecated/outdated:**
- Chrome 120/121 User-Agent strings in current `web_crawler.py` line 26-30 -- these are 2+ years stale and flagged by modern bot detection.
- `GeminiClient` singleton in `gemini_client.py` -- per CONTEXT.md decision, all LLM calls route through OpenRouter. The direct Gemini path should be deprecated (not deleted -- leave for backwards compat but emit deprecation warning).

## Open Questions

1. **Cloudflare AI Labyrinth Detection**
   - What we know: AI Labyrinth embeds hidden `nofollow` links to AI-generated content pages. Content is topically unrelated to the site.
   - What's unclear: Cloudflare intentionally obscures all technical indicators (URL patterns, HTML attributes, content signatures). No public documentation on detectable signatures.
   - Recommendation: Implement Cloudflare challenge page detection (Turnstile, cf_clearance indicators) as CRAWL-04. Skip AI Labyrinth-specific detection for now -- it targets AI training crawlers, not OSINT tools fetching individual articles. Our usage pattern (fetch ~100 specific article URLs) doesn't trigger the labyrinth flow (which activates on deep crawling behavior).

2. **Extraction Model Selection**
   - What we know: Gemini 3.1 Flash Lite yields ~4 facts/article. Qwen 3.5 Flash is current primary extraction model per MODEL_MAP. DeepSeek R1 produces `<think>` blocks.
   - What's unclear: Which model in the fallback chain produces the best fact yield. Per-model metrics (EXTRACT requirement) will answer this.
   - Recommendation: Implement per-model metrics first. Model selection is a data-driven decision, not a planning decision.

3. **Googlebot UA Legality/ToS**
   - What we know: Googlebot UA + Google referer bypasses many soft paywalls. News sites serve full content to Googlebot for SEO.
   - What's unclear: ToS compliance varies by site. Some sites (NYT, WSJ) have hard paywalls that check IP ranges, not just UA.
   - Recommendation: Implement as Tier 1 of 3-tier paywall strategy per CONTEXT.md. Log when Googlebot UA is used. Fall back to RSS summary (Tier 2) when Googlebot also fails.

4. **Warn-Once Fallback Logging**
   - What we know: OpenRouter fallback chain can log per-request, creating log spam.
   - What's unclear: How to implement "warn once per model" in async context without race conditions.
   - Recommendation: Use a `set()` of seen model transitions, protected by asyncio lock. Log once per unique `(primary, fallback)` pair per investigation run.

## Sources

### Primary (HIGH confidence)
- **Codebase analysis**: All files listed in Architecture Patterns section -- read and analyzed in full
- **playwright-stealth PyPI**: v2.0.2, Feb 2026 release, Python 3.9+ -- [pypi.org/project/playwright-stealth](https://pypi.org/project/playwright-stealth/)
- **Playwright official docs**: BrowserContext isolation -- [playwright.dev/python/docs/browser-contexts](https://playwright.dev/python/docs/browser-contexts)
- **Cloudflare AI Labyrinth announcement**: Technical details (intentionally vague) -- [blog.cloudflare.com/ai-labyrinth](https://blog.cloudflare.com/ai-labyrinth/)
- **Cloudflare AI Labyrinth docs**: [developers.cloudflare.com/bots/additional-configurations/ai-labyrinth](https://developers.cloudflare.com/bots/additional-configurations/ai-labyrinth/)

### Secondary (MEDIUM confidence)
- **User-Agent data**: Current browser market share and UA strings -- [useragents.me](https://www.useragents.me/), [geekflare.com/guides/latest-browser-user-agents](https://geekflare.com/guides/latest-browser-user-agents/)
- **OpenRouter structured outputs**: JSON mode support, response healing -- [openrouter.ai/docs/guides/features/structured-outputs](https://openrouter.ai/docs/guides/features/structured-outputs)
- **Crawlee BrowserPool API**: Reference for pool patterns -- [crawlee.dev/python/api/class/BrowserPool](https://crawlee.dev/python/api/class/BrowserPool)

### Tertiary (LOW confidence)
- **Googlebot paywall bypass**: Community-reported effectiveness, varies by site -- [HN discussion](https://news.ycombinator.com/item?id=26593619)
- **Cloudflare challenge indicators**: Community-observed patterns (cf-turnstile class, data-sitekey, challenge-form) -- multiple scraping blogs, not official Cloudflare documentation

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- `playwright-stealth` is the only new dependency, verified on PyPI with current release
- Architecture: HIGH -- All patterns derived from direct codebase analysis of existing files
- Pitfalls: MEDIUM -- BrowserPool memory behavior based on Playwright docs + community reports, not direct measurement
- Cloudflare detection: LOW -- AI Labyrinth indicators intentionally undocumented by Cloudflare
- Googlebot bypass: MEDIUM -- well-documented technique but effectiveness varies by target site

**Research date:** 2026-03-21
**Valid until:** 2026-04-21 (30 days -- stable domain, no rapidly-changing APIs)
