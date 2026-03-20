# Session Log: 2026-03-15 UAT Bugfixes & Verification Analysis

## Context

Continuation of full manual UAT session. Previous session ran "Iran nuclear program developments and diplomatic negotiations 2024-2025". This session picked up mid-investigation of classification errors, then moved to a new investigation: "Russian military deployments and Wagner Group activities in Africa 2024-2025".

User is on **Gemini Tier 1 paid subscription** (20 RPM, 1.5M TPM). Settings were updated in the previous session.

---

## Bugs Fixed

### 1. `'NoneType' object has no attribute 'lower'` in classification (~100+ facts failing)

**Root cause:** Python's `dict.get(key, default)` only uses the default when the key is *absent*. When the key exists with value `None`, it returns `None`. This bit in three places:

- `extraction_pipeline.py:444` — `article.get("url", f"article-{investigation_id}")` returns `None` when article has `url: None`
- `fact_extraction_agent.py:136` — `content.get("source_id", "unknown")` propagates the `None`
- `source_scorer.py:155` — `provenance.get("source_id", "unknown")` passes `None` to `_get_source_credibility()`
- `source_scorer.py:210` — `source_id.lower()` crashes on `None`

**Fix:** Changed all `.get(key, default)` to `.get(key) or default` pattern:
- `extraction_pipeline.py:444` — `article.get("url") or f"article-{investigation_id}"`
- `fact_extraction_agent.py:136` — `content.get("source_id") or "unknown"`
- `source_scorer.py:155` — `provenance.get("source_id") or "unknown"`
- `source_scorer.py:210-211` — Added `if not source_id: return self.type_defaults.get("unknown", 0.3)` guard
- `source_scorer.py:280-281` — Added `if not source_id: return None` guard in `_find_baseline_key()`

### 2. Absurdly low credibility scores (0.094-0.560 for legitimate sources)

**Root cause:** When `source_id` is `None`, domain extraction fails → type default "unknown" → 0.3. The math: `0.3 × 0.7 × 0.45 = 0.094`. Additionally, many feed sources (think tanks, defense outlets, regional media) had no baseline entries, so even valid URLs with extractable domains fell through to low defaults.

**Fix:** Added 17 missing domains to `source_credibility.py` SOURCE_BASELINES:
- NPR (0.82), France 24 (0.75), DW (0.75), CNBC (0.78), Bloomberg (0.85), SCMP (0.72)
- Foreign Policy (0.82), Foreign Affairs (0.85), War on the Rocks (0.78), The Diplomat (0.75), Responsible Statecraft (0.75)
- Defense One (0.78), Breaking Defense (0.75), Defense News (0.78), Bellingcat (0.80)
- `news.google.com` (0.6) — many articles come through Google News RSS proxy

### 3. Stale test assertions (4 test files)

Tests were written against stub implementations where `credibility_score = claim_clarity`. Updated to match real scorer behavior:

- `test_fact_classification_agent.py`:
  - Updated `high_quality_fact` fixture to use realistic URL (`https://www.reuters.com/world/article-123`) and `source_type: "wire_service"`
  - Changed score assertions from exact stub values to `pytest.approx()` with real scorer math
  - Fixed dict-vs-object access in dubious flag tests (`r.flag` → `r["flag"]`, `r.reason` → `r["reason"]`)
  - Fixed no-provenance defaults from `0.5` to `0.3`
- `test_fact_extraction_agent.py`:
  - Updated model name assertion: `"gemini-1.5-flash"` → `"gemini-3-pro-preview"`
  - Updated chunk_size assertion: `12000` → `40000`

**Test results:** 915 passed, 4 pre-existing failures (planning agent registry, synthesizer LLM, Reddit API integration).

---

## Verification Pipeline Analysis

### Why all facts are "unverifiable"

`SearchExecutor` checks `os.environ.get("SERPER_API_KEY")`. No key → mock search mode → returns empty results → every fact gets `status=unverifiable`. This cascades to the knowledge graph: `GraphIngestor` filters to `_INGESTIBLE_STATUSES = {CONFIRMED, SUPERSEDED}`, so all unverifiable facts are excluded → 0 nodes, 0 edges.

### Serper's role

Serper (serper.dev) is a Google Search API wrapper. The verification flow:
1. Dubious fact enters verification
2. `QueryGenerator` creates targeted search queries (species-specialized per flag type: PHANTOM, FOG, ANOMALY)
3. `SearchExecutor` fires queries through Serper → gets Google results
4. `EvidenceAggregator` evaluates evidence with deterministic authority-weighted voting:
   - 1 high-authority source (≥0.85) → CONFIRMED
   - 2+ independent sources → CONFIRMED
   - Credible refutation (≥0.7 authority + ≥0.7 relevance) → REFUTED
   - Else after 3 queries → UNVERIFIABLE
5. Entirely algorithmic — NO LLM calls in verification

### The `supports_claim` problem

**Critical design gap:** `SearchExecutor` hardcodes `supports_claim=True` on every `EvidenceItem` (line 137). The `EvidenceAggregator` partitions evidence into supporting/refuting based on this field. Since it's always `True`, the `refuting` list is always empty — **refutation is structurally impossible**.

Additionally, `QueryGenerator` only generates corroboration-style queries, never adversarial/refutation queries.

### Free alternatives to Serper discussed

- **`duckduckgo-search`** — zero cost, no API key, decent results. User chose this.
- Google Custom Search API — 100 queries/day free
- Brave Search API — 2,000 queries/month free
- Tavily — 1,000 queries/month free
- Gemini Grounding — already in the stack, built-in Google Search

### User decision

**Option B — snippet-based stance detection.** Scan snippets for negation signals (denied, false, disproven, no evidence, contradicts, etc.), set `supports_claim=False` when detected. No LLM cost. User explicitly rejected Option A ("accept confirmation-only and relabel") — "not compromising on the efficacy of the intended system."

---

## Pending Implementation

1. **DuckDuckGo search backend** — replace Serper dependency in `SearchExecutor`
2. **Snippet stance detection** — negation pattern matching before building `EvidenceItem`, setting `supports_claim=False` on contradiction signals
3. (Future) Refutation query variants in `QueryGenerator`
4. (Future) Consider adding `UNVERIFIABLE` to `_INGESTIBLE_STATUSES` in `GraphIngestor` so unverified-but-not-refuted facts populate the knowledge graph

---

## Pre-existing issues noted but not fixed

- `claim_type: "statement"` validation error — LLM outputs "statement" but Pydantic `Claim` schema only accepts `event`, `state`, `relationship`, `prediction`, `planned`. Facts get dropped.
- Planning agent test `test_assign_agents_without_registry` — pre-existing failure, unrelated
- Synthesizer test — needs live LLM, pre-existing
- Reddit integration tests — `asyncprawcore` compatibility issue, pre-existing
