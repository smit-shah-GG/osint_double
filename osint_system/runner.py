"""Full investigation pipeline runner.

Orchestrates the complete OSINT investigation flow end-to-end:
  Objective → Crawling → Extraction → Classification →
  Verification → Graph → Analysis → Report → Dashboard

Usage:
    uv run python -m osint_system.runner "Investigate US semiconductor export controls on China"

    # Or from Python:
    from osint_system.runner import InvestigationRunner
    runner = InvestigationRunner("Investigate X")
    asyncio.run(runner.run())
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import random
from urllib.parse import urlparse

import aiohttp
import feedparser
import structlog
import trafilatura
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from osint_system.agents.crawlers.web_crawler import (
    BrowserPool, is_cloudflare_challenge, USER_AGENTS,
)

# ── stores ──────────────────────────────────────────────────────────
from osint_system.data_management.article_store import ArticleStore
from osint_system.data_management.classification_store import ClassificationStore
from osint_system.data_management.fact_store import FactStore
from osint_system.data_management.verification_store import VerificationStore

# ── pipelines ───────────────────────────────────────────────────────
from osint_system.pipelines.extraction_pipeline import ExtractionPipeline
from osint_system.pipeline.verification_pipeline import VerificationPipeline
from osint_system.pipeline.graph_pipeline import GraphPipeline
from osint_system.pipeline.analysis_pipeline import AnalysisPipeline

# ── agents ──────────────────────────────────────────────────────────
from osint_system.agents.sifters.fact_classification_agent import (
    FactClassificationAgent,
)

# ── reporting ───────────────────────────────────────────────────────
from osint_system.reporting import ReportGenerator
from osint_system.reporting.report_store import ReportStore

# ── config ──────────────────────────────────────────────────────────
from osint_system.config.analysis_config import AnalysisConfig
from osint_system.config.feed_config import ALL_FEEDS, FeedSource, PROPAGANDA_RISK

logger = structlog.get_logger(__name__)


# ────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────

def _fetch_article_sync(url: str) -> dict[str, Any] | None:
    """Fetch a single URL and extract article text via trafilatura.

    Mirrors geopol's ``extract_article_text()`` pattern: uses
    ``trafilatura.settings.use_config()`` with a tight timeout and
    MIN_OUTPUT_SIZE guard, plus ``trafilatura.fetch_url()`` for the
    download step.

    Returns an ArticleStore-compatible dict or None on failure.
    """
    from trafilatura.settings import use_config
    from urllib.parse import urlparse

    config = use_config()
    config.set("DEFAULT", "min_output_size", "200")
    # Tight timeout — prevents hanging on paywalled/slow sites.
    # Default is 30s; we cut to 12s since we're fetching 40 articles in parallel.
    config.set("DEFAULT", "download_timeout", "12")
    config.set("DEFAULT", "extraction_timeout", "15")

    try:
        downloaded = trafilatura.fetch_url(url, config=config)
        if downloaded is None:
            logger.debug("fetch_returned_none", url=url)
            return None

        text = trafilatura.extract(
            downloaded,
            favor_precision=True,
            deduplicate=True,
            include_comments=False,
            include_tables=True,
            config=config,
        )
        if not text or len(text) < 200:
            return None

        # Extract metadata (title, date) via JSON output mode — same
        # double-extract pattern geopol uses in article_processor.py
        meta_json = trafilatura.extract(
            downloaded,
            output_format="json",
            favor_precision=True,
            deduplicate=True,
            config=config,
        )
        title = ""
        pub_date = ""
        resolved_url = url
        if meta_json:
            meta_dict = json.loads(meta_json)
            title = meta_dict.get("title", "")
            pub_date = meta_dict.get("date", "")
            resolved_url = meta_dict.get("source", url) or url

        if not title:
            title = url.split("/")[-1]

        domain = urlparse(resolved_url).netloc.lower().removeprefix("www.")
        source_type = "news_outlet"
        authority = 0.6
        if any(d in domain for d in ("reuters", "apnews")):
            source_type, authority = "wire_service", 0.9
        elif domain.endswith((".gov", ".mil")):
            source_type, authority = "official_statement", 0.9
        elif domain.endswith(".edu"):
            source_type, authority = "academic", 0.85
        elif any(d in domain for d in ("bbc", "nytimes", "theguardian", "washingtonpost")):
            authority = 0.8

        return {
            "url": resolved_url,
            "title": title,
            "content": text,
            "published_date": pub_date,
            "source": {
                "name": domain,
                "type": source_type,
                "authority_score": authority,
            },
            "metadata": {
                "domain": domain,
                "content_length": len(text),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            },
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("fetch_failed", url=url, error=str(exc))
        return None


# ────────────────────────────────────────────────────────────────────
# Runner
# ────────────────────────────────────────────────────────────────────

class InvestigationRunner:
    """End-to-end OSINT investigation pipeline runner.

    Creates shared stores, orchestrates every pipeline stage sequentially,
    and provides Rich console output at each milestone.
    """

    def __init__(
        self,
        objective: str,
        investigation_id: str | None = None,
        data_dir: str = "data",
    ) -> None:
        self.objective = objective
        self.investigation_id = investigation_id or f"inv-{uuid.uuid4().hex[:8]}"
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.console = Console()

        # ── shared stores (persisted to data/<inv_id>/) ──────────────
        store_dir = self.data_dir / self.investigation_id
        store_dir.mkdir(parents=True, exist_ok=True)
        self.article_store = ArticleStore(
            persistence_path=str(store_dir / "articles.json"),
        )
        self.fact_store = FactStore(
            persistence_path=str(store_dir / "facts.json"),
        )
        self.classification_store = ClassificationStore(
            persistence_path=str(store_dir / "classifications.json"),
        )
        self.verification_store = VerificationStore(
            persistence_path=str(store_dir / "verifications.json"),
        )
        self.report_store = ReportStore(
            persistence_path=str(store_dir / "reports.json"),
        )

        # ── config ──────────────────────────────────────────────────
        self.analysis_config = AnalysisConfig.from_env()

        # ── summary stats (populated by each phase) ───────────────
        self._stats: dict[str, int] = {}

    # ================================================================
    # Public API
    # ================================================================

    async def run(self) -> str:
        """Execute the full investigation pipeline. Returns investigation_id."""
        inv = self.investigation_id

        self.console.print(Panel(
            f"[bold white]{self.objective}[/bold white]\n"
            f"[dim]ID: {inv}[/dim]",
            title="[bold blue]OSINT Investigation[/bold blue]",
            border_style="blue",
        ))

        await self._phase_crawl()
        extract_result = await self._phase_extract()
        self._stats["facts"] = extract_result.get("facts_extracted", 0)
        classification_summary = await self._phase_classify()
        self._stats["classified"] = classification_summary.get("total", 0)
        verification_summary = await self._phase_verify(classification_summary)
        self._stats["verified"] = verification_summary.get("total_verified", 0)
        self._stats["confirmed"] = verification_summary.get("confirmed", 0)
        ingestion_stats = await self._phase_graph(verification_summary)
        self._stats["nodes"] = ingestion_stats.get("nodes_merged", 0)
        await self._phase_analyze()
        self._print_summary()
        self._offer_dashboard()

        return inv

    # ================================================================
    # Phase 1 — Crawling (RSS feeds → keyword filter → trafilatura)
    # ================================================================

    # Stopwords excluded from keyword extraction
    _STOPWORDS: set[str] = {
        "a", "an", "the", "of", "on", "in", "to", "and", "or", "for",
        "is", "are", "was", "were", "be", "been", "being", "have", "has",
        "had", "do", "does", "did", "will", "would", "could", "should",
        "may", "might", "shall", "can", "with", "at", "by", "from",
        "about", "into", "through", "during", "before", "after", "above",
        "below", "between", "under", "over", "up", "down", "out", "off",
        "then", "than", "that", "this", "these", "those", "it", "its",
        "investigate", "investigation", "analyze", "analysis", "report",
        "impact", "effects", "implications", "recent", "current", "how",
        "what", "why", "when", "where", "who", "which",
    }

    def _extract_keywords(self, objective: str) -> list[str]:
        """Extract search keywords from an investigation objective.

        Splits on whitespace/punctuation, lowercases, removes stopwords,
        and keeps tokens >= 3 chars. Returns deduplicated list preserving
        insertion order.
        """
        tokens = re.split(r'[\s,;:!?\-/()\"\']+', objective.lower())
        seen: set[str] = set()
        keywords: list[str] = []
        for tok in tokens:
            tok = tok.strip(".")
            if len(tok) >= 3 and tok not in self._STOPWORDS and tok not in seen:
                seen.add(tok)
                keywords.append(tok)
        return keywords

    def _build_topic_feeds(self, keywords: list[str]) -> list[FeedSource]:
        """Generate Google News RSS search feeds targeting the investigation topic.

        Creates multiple search queries from keyword combinations so Google News
        returns pre-filtered, relevant results. This is the same pattern geopol
        uses for site-specific feeds (e.g., ``site:reuters.com+world``).
        """
        from urllib.parse import quote_plus

        base = "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q="
        feeds: list[FeedSource] = []

        # Primary: full query string (most specific)
        full_query = "+".join(keywords)
        feeds.append(FeedSource(
            f"GNews: {' '.join(keywords)}",
            f"{base}{quote_plus(full_query)}+when:7d",
            1,  # type: ignore[arg-type]
            "wire",
        ))

        # Pairwise combinations of keywords for broader coverage
        if len(keywords) >= 2:
            from itertools import combinations
            for pair in combinations(keywords, 2):
                query = "+".join(pair)
                feeds.append(FeedSource(
                    f"GNews: {' '.join(pair)}",
                    f"{base}{quote_plus(query)}+when:7d",
                    1,  # type: ignore[arg-type]
                    "wire",
                ))

        # Site-scoped queries for high-authority outlets
        high_value_sites = [
            "reuters.com", "apnews.com", "bbc.com", "nytimes.com",
            "csis.org", "brookings.edu", "scmp.com",
        ]
        for site in high_value_sites:
            query = f"site:{site}+{'+'.join(keywords[:3])}"
            feeds.append(FeedSource(
                f"GNews: {site}",
                f"{base}{quote_plus(query)}+when:30d",
                1,  # type: ignore[arg-type]
                "wire",
            ))

        return feeds

    def _entry_matches(
        self,
        title: str,
        keywords: list[str],
        *,
        min_hits: int = 1,
    ) -> bool:
        """Check whether an RSS entry title matches enough keywords."""
        title_lower = title.lower()
        hits = sum(1 for kw in keywords if kw in title_lower)
        return hits >= min_hits

    async def _resolve_gnews_urls(
        self,
        entries: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """Resolve Google News opaque URLs to actual article URLs.

        Google News RSS returns ``news.google.com/rss/articles/CBMi…`` links
        that embed the real URL in an encrypted protobuf blob. The
        ``googlenewsdecoder`` library resolves these by hitting Google's
        internal redirect endpoint.
        """
        from googlenewsdecoder import new_decoderv1

        loop = asyncio.get_running_loop()
        sem = asyncio.Semaphore(5)  # rate-limit decoder calls

        async def resolve_one(entry: dict[str, str]) -> dict[str, str] | None:
            async with sem:
                try:
                    result = await loop.run_in_executor(
                        None, new_decoderv1, entry["url"], 1,
                    )
                    if result.get("status"):
                        entry = dict(entry)  # copy
                        entry["url"] = result["decoded_url"]
                        return entry
                except Exception as exc:
                    logger.debug("gnews_decode_failed", url=entry["url"][:60], error=str(exc))
                return None

        tasks = [resolve_one(e) for e in entries]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r for r in results if isinstance(r, dict)]

    async def _poll_rss_feeds(
        self,
        feeds: list[FeedSource],
        *,
        max_concurrent: int = 12,
        timeout: int = 20,
    ) -> list[dict[str, str]]:
        """Poll RSS feeds and return flat list of entry dicts.

        Each entry: {"url": ..., "title": ..., "published": ..., "source": ...}
        Uses aiohttp + feedparser, same pattern as the geopol RSS daemon.
        """
        semaphore = asyncio.Semaphore(max_concurrent)
        all_entries: list[dict[str, str]] = []

        async def fetch_one(feed: FeedSource) -> list[dict[str, str]]:
            async with semaphore:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            feed.url,
                            timeout=aiohttp.ClientTimeout(total=timeout),
                            headers={"User-Agent": "OSINT-Runner/1.0"},
                        ) as resp:
                            if resp.status != 200:
                                logger.debug(
                                    "feed_http_error",
                                    feed=feed.name,
                                    status=resp.status,
                                )
                                return []
                            body = await resp.text()
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    logger.debug("feed_fetch_failed", feed=feed.name, error=str(exc))
                    return []

            # feedparser is synchronous — offload to executor
            loop = asyncio.get_running_loop()
            parsed = await loop.run_in_executor(None, feedparser.parse, body)

            entries: list[dict[str, str]] = []
            for entry in parsed.entries[:20]:  # cap per-feed
                url = getattr(entry, "link", None)
                if not url:
                    continue
                entries.append({
                    "url": url,
                    "title": getattr(entry, "title", ""),
                    "published": getattr(entry, "published", ""),
                    "source": feed.name,
                })
            return entries

        tasks = [fetch_one(f) for f in feeds]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, list):
                all_entries.extend(result)

        return all_entries

    async def _phase_crawl(self) -> None:
        self.console.print("\n[bold cyan]══ Phase 1: Crawling ══[/bold cyan]")

        keywords = self._extract_keywords(self.objective)
        self.console.print(f"  Keywords: {keywords}")

        # ── Step 1: Topic-specific Google News RSS feeds ──────────
        # These are the primary source — pre-filtered by Google for relevance.
        topic_feeds = self._build_topic_feeds(keywords)
        self.console.print(f"  Generated {len(topic_feeds)} topic-specific search feeds")
        topic_entries = await self._poll_rss_feeds(topic_feeds)
        self.console.print(f"  Topic feed entries: {len(topic_entries)}")

        # ── Step 2: Static RSS feeds (background, filtered) ──────
        # Supplement with general feeds, filtering titles for any keyword hit.
        self.console.print(f"  Polling {len(ALL_FEEDS)} static RSS feeds …")
        static_entries = await self._poll_rss_feeds(ALL_FEEDS)
        static_relevant = [
            e for e in static_entries
            if self._entry_matches(e["title"], keywords, min_hits=1)
        ]
        self.console.print(
            f"  Static feed entries: {len(static_entries)} total, "
            f"{len(static_relevant)} relevant"
        )

        # ── Step 3: Merge, dedup, cap ────────────────────────────
        # Topic entries first (higher relevance), then static supplements
        combined = topic_entries + static_relevant
        seen_urls: set[str] = set()
        deduped: list[dict[str, str]] = []
        for e in combined:
            if e["url"] not in seen_urls:
                seen_urls.add(e["url"])
                deduped.append(e)

        max_articles = 100
        if len(deduped) > max_articles:
            deduped = deduped[:max_articles]

        self.console.print(f"  Unique entries to fetch: [green]{len(deduped)}[/green]")
        for e in deduped[:10]:
            self.console.print(f"    [dim]• {e['title'][:90]}[/dim]")
        if len(deduped) > 10:
            self.console.print(f"    [dim]  … and {len(deduped) - 10} more[/dim]")

        if not deduped:
            self.console.print("[yellow]  No relevant entries found — pipeline will have no input.[/yellow]")
            return

        # ── Step 4: Resolve Google News redirect URLs ──────────
        # Google News RSS returns opaque `news.google.com/rss/articles/CBMi…`
        # URLs that don't HTTP-redirect to the source. Use googlenewsdecoder
        # to extract the real article URLs.
        gnews_prefix = "https://news.google.com/"
        gnews_entries = [e for e in deduped if e["url"].startswith(gnews_prefix)]
        direct_entries = [e for e in deduped if not e["url"].startswith(gnews_prefix)]

        if gnews_entries:
            self.console.print(f"  Resolving {len(gnews_entries)} Google News URLs …")
            resolved = await self._resolve_gnews_urls(gnews_entries)
            self.console.print(f"  Resolved: {len(resolved)}/{len(gnews_entries)}")
            deduped = resolved + direct_entries

        self.console.print(f"  Fetching {len(deduped)} articles …")
        urls = [e["url"] for e in deduped]

        loop = asyncio.get_running_loop()
        sem = asyncio.Semaphore(8)

        async def _bounded_fetch(u: str) -> dict[str, Any] | None:
            async with sem:
                return await loop.run_in_executor(None, _fetch_article_sync, u)

        articles: list[dict] = []
        failed_entries: list[dict[str, str]] = []
        tasks = [_bounded_fetch(u) for u in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for entry, r in zip(deduped, results):
            if isinstance(r, dict):
                articles.append(r)
            else:
                failed_entries.append(entry)

        self.console.print(
            f"  Fetched [green]{len(articles)}[/green] articles "
            f"from {len(urls)} URLs"
        )

        # ── BrowserPool fallback for JS-heavy / Cloudflare-blocked sites ──
        if failed_entries:
            self.console.print(
                f"  Attempting Playwright fallback for "
                f"[yellow]{len(failed_entries)}[/yellow] failed fetches ..."
            )
            browser_pool = BrowserPool(max_contexts=5)
            try:
                await browser_pool.start()
                pw_sem = asyncio.Semaphore(5)

                async def _pw_fetch(entry: dict[str, str]) -> dict[str, Any] | None:
                    async with pw_sem:
                        url = entry["url"]
                        ua = random.choice(USER_AGENTS)
                        try:
                            html = await browser_pool.fetch(url, ua, 15_000)
                            if not html:
                                return None
                            # Extract text from HTML using trafilatura
                            text = trafilatura.extract(
                                html,
                                favor_precision=True,
                                deduplicate=True,
                                include_comments=False,
                                include_tables=True,
                            )
                            if not text or len(text) < 200:
                                return None
                            domain = urlparse(url).netloc.lower().removeprefix("www.")
                            source_type = "news_outlet"
                            authority = 0.6
                            if any(d in domain for d in ("reuters", "apnews")):
                                source_type, authority = "wire_service", 0.9
                            elif domain.endswith((".gov", ".mil")):
                                source_type, authority = "official_statement", 0.9
                            elif domain.endswith(".edu"):
                                source_type, authority = "academic", 0.85
                            elif any(
                                d in domain
                                for d in ("bbc", "nytimes", "theguardian", "washingtonpost")
                            ):
                                authority = 0.8
                            return {
                                "url": url,
                                "title": entry.get("title", url.split("/")[-1]),
                                "content": text,
                                "published_date": entry.get("published", ""),
                                "source": {
                                    "name": domain,
                                    "type": source_type,
                                    "authority_score": authority,
                                },
                                "metadata": {
                                    "domain": domain,
                                    "content_source": "playwright_fallback",
                                    "content_length": len(text),
                                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                                },
                            }
                        except Exception as exc:
                            logger.debug(
                                "pw_fetch_failed",
                                url=url[:80],
                                error=str(exc),
                            )
                            return None

                pw_tasks = [_pw_fetch(e) for e in failed_entries]
                pw_results = await asyncio.gather(*pw_tasks, return_exceptions=True)
                pw_recovered = 0
                for r in pw_results:
                    if isinstance(r, dict):
                        articles.append(r)
                        pw_recovered += 1
                if pw_recovered:
                    self.console.print(
                        f"  Playwright fallback recovered: "
                        f"[green]{pw_recovered}[/green] articles"
                    )
            finally:
                await browser_pool.stop()

        if articles:
            stats = await self.article_store.save_articles(
                self.investigation_id,
                articles,
                investigation_metadata={
                    "objective": self.objective,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            self.console.print(f"  Saved: {stats.get('saved', len(articles))} articles")
            self._stats["articles"] = len(articles)

    # ================================================================
    # Phase 2 — Fact Extraction
    # ================================================================

    async def _phase_extract(self) -> dict[str, Any]:
        self.console.print("\n[bold cyan]══ Phase 2: Fact Extraction ══[/bold cyan]")

        pipeline = ExtractionPipeline(
            article_store=self.article_store,
            fact_store=self.fact_store,
        )
        result = await pipeline.process_investigation(self.investigation_id)

        self.console.print(
            f"  Articles processed: {result.get('articles_processed', 0)}\n"
            f"  Facts extracted:    {result.get('facts_extracted', 0)}\n"
            f"  After consolidation:{result.get('facts_consolidated', 0)}\n"
            f"  Duration:           {result.get('duration_seconds', 0):.1f}s"
        )
        return result

    # ================================================================
    # Phase 3 — Classification
    # ================================================================

    async def _phase_classify(self) -> dict[str, Any]:
        self.console.print("\n[bold cyan]══ Phase 3: Fact Classification ══[/bold cyan]")

        agent = FactClassificationAgent(
            classification_store=self.classification_store,
            fact_store=self.fact_store,
        )

        # Retrieve all extracted facts
        fact_data = await self.fact_store.retrieve_by_investigation(
            self.investigation_id,
        )
        facts = fact_data.get("facts", [])

        if not facts:
            self.console.print("  [yellow]No facts to classify.[/yellow]")
            return {"dubious_count": 0, "critical_count": 0, "total": 0}

        self.console.print(f"  Classifying {len(facts)} facts …")

        classifications = await agent.sift({
            "facts": facts,
            "investigation_id": self.investigation_id,
        })

        critical = sum(1 for c in classifications if c.get("impact_tier") == "critical")
        dubious = sum(1 for c in classifications if c.get("dubious_flags"))
        dubious_flags: dict[str, int] = {}
        for c in classifications:
            for flag in c.get("dubious_flags", []):
                dubious_flags[flag] = dubious_flags.get(flag, 0) + 1

        self.console.print(
            f"  Total classified:   {len(classifications)}\n"
            f"  Critical:           {critical}\n"
            f"  Dubious:            {dubious}"
        )
        if dubious_flags:
            self.console.print(f"  Dubious breakdown:  {dubious_flags}")

        return {
            "investigation_id": self.investigation_id,
            "total": len(classifications),
            "critical_count": critical,
            "dubious_count": dubious,
        }

    # ================================================================
    # Phase 4 — Verification
    # ================================================================

    async def _phase_verify(
        self,
        classification_summary: dict[str, Any],
    ) -> dict[str, Any]:
        self.console.print("\n[bold cyan]══ Phase 4: Verification ══[/bold cyan]")

        pipeline = VerificationPipeline(
            classification_store=self.classification_store,
            fact_store=self.fact_store,
            verification_store=self.verification_store,
        )
        result = await pipeline.on_classification_complete(
            self.investigation_id,
            classification_summary,
        )

        if result.get("skipped"):
            self.console.print(f"  Skipped: {result['skipped']}")
        else:
            self.console.print(
                f"  Verified:      {result.get('total_verified', 0)}\n"
                f"  Confirmed:     {result.get('confirmed', 0)}\n"
                f"  Refuted:       {result.get('refuted', 0)}\n"
                f"  Unverifiable:  {result.get('unverifiable', 0)}"
            )
        return result

    # ================================================================
    # Phase 5 — Knowledge Graph
    # ================================================================

    async def _phase_graph(
        self,
        verification_summary: dict[str, Any],
    ) -> dict[str, Any]:
        self.console.print("\n[bold cyan]══ Phase 5: Knowledge Graph ══[/bold cyan]")

        pipeline = GraphPipeline(
            fact_store=self.fact_store,
            verification_store=self.verification_store,
            classification_store=self.classification_store,
        )
        # Force NetworkX (no Neo4j dependency)
        pipeline._config = pipeline.config
        pipeline._config.use_networkx_fallback = True

        result = await pipeline.on_verification_complete(
            self.investigation_id,
            verification_summary,
        )

        self.console.print(
            f"  Nodes:         {result.get('nodes_merged', 0)}\n"
            f"  Edges:         {result.get('edges_merged', 0)}\n"
            f"  Facts ingested:{result.get('facts_ingested', 0)}"
        )
        return result

    # ================================================================
    # Phase 6 — Analysis & Report
    # ================================================================

    async def _phase_analyze(self) -> None:
        self.console.print("\n[bold cyan]══ Phase 6: Analysis & Report Generation ══[/bold cyan]")

        report_generator = ReportGenerator(config=self.analysis_config)

        pipeline = AnalysisPipeline(
            fact_store=self.fact_store,
            classification_store=self.classification_store,
            verification_store=self.verification_store,
            report_generator=report_generator,
            report_store=self.report_store,
            config=self.analysis_config,
        )

        synthesis = await pipeline.run_analysis(self.investigation_id)

        self.console.print(
            f"  Key Judgments:        {len(synthesis.key_judgments)}\n"
            f"  Alt Hypotheses:      {len(synthesis.alternative_hypotheses)}\n"
            f"  Contradictions:      {len(synthesis.contradictions)}\n"
            f"  Confidence:          {synthesis.overall_confidence.level} "
            f"({synthesis.overall_confidence.numeric:.2f})"
        )

        # Save report to disk
        report_dir = self.data_dir / "reports"
        report_dir.mkdir(exist_ok=True)
        report_path = report_dir / f"{self.investigation_id}.md"

        latest = await self.report_store.get_latest(self.investigation_id)
        if latest and latest.markdown_content:
            report_path.write_text(latest.markdown_content, encoding="utf-8")
            self.console.print(f"\n  Report saved: [green]{report_path}[/green]")

        # Print executive summary
        if synthesis.executive_summary:
            self.console.print(Panel(
                synthesis.executive_summary[:1500],
                title="Executive Summary",
                border_style="green",
            ))

    # ================================================================
    # Summary & Dashboard
    # ================================================================

    def _print_summary(self) -> None:
        self.console.print("\n")
        table = Table(title="Investigation Complete", border_style="blue")
        table.add_column("Metric", style="cyan")
        table.add_column("Count", style="green", justify="right")

        # Use tracked stats instead of poking at store internals
        table.add_row("Articles crawled", str(self._stats.get("articles", 0)))
        table.add_row("Facts extracted", str(self._stats.get("facts", 0)))
        table.add_row("Classified", str(self._stats.get("classified", 0)))
        table.add_row("Verified", str(self._stats.get("verified", 0)))
        table.add_row("Confirmed", str(self._stats.get("confirmed", 0)))
        table.add_row("Graph nodes", str(self._stats.get("nodes", 0)))

        self.console.print(table)

    def _offer_dashboard(self) -> None:
        self.console.print(Panel(
            f"[bold]Launch the dashboard to explore results:[/bold]\n\n"
            f"  uv run python -m osint_system.serve {self.investigation_id}\n\n"
            f"Then open [blue]http://127.0.0.1:8080[/blue]",
            title="Dashboard",
            border_style="yellow",
        ))


# ────────────────────────────────────────────────────────────────────
# CLI entry point
# ────────────────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: uv run python -m osint_system.runner \"<investigation objective>\"")
        sys.exit(1)

    objective = " ".join(sys.argv[1:])

    # Ensure .env is loaded
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
    except ImportError:
        pass

    runner = InvestigationRunner(objective)
    asyncio.run(runner.run())


if __name__ == "__main__":
    main()
