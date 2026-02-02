"""Extraction pipeline bridging crawler output to fact extraction and consolidation.

This pipeline orchestrates the full article-to-fact flow:
1. Read articles from ArticleStore for an investigation
2. Transform articles to extraction format
3. Extract facts via FactExtractionAgent
4. Consolidate facts via FactConsolidator
5. Store results in FactStore

Features:
- Configurable batch processing
- Article-to-content transformation
- Processing statistics and progress tracking
- Error handling with partial recovery
- Single article and full investigation modes
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger


@dataclass
class PipelineStats:
    """Statistics tracking for pipeline execution."""

    articles_processed: int = 0
    articles_failed: int = 0
    facts_extracted: int = 0
    facts_consolidated: int = 0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert stats to dictionary."""
        return {
            "articles_processed": self.articles_processed,
            "articles_failed": self.articles_failed,
            "facts_extracted": self.facts_extracted,
            "facts_consolidated": self.facts_consolidated,
            "error_count": len(self.errors),
        }


class ExtractionPipeline:
    """
    Pipeline for extracting facts from crawler output.

    Wires together ArticleStore -> FactExtractionAgent -> FactConsolidator -> FactStore
    to provide end-to-end article-to-fact processing.

    Usage:
        pipeline = ExtractionPipeline()
        result = await pipeline.process_investigation('inv-001')
        print(f"Extracted {result['facts_extracted']} facts")

    Or for single article:
        facts = await pipeline.process_article(article_dict, 'inv-001')

    Attributes:
        article_store: ArticleStore instance for reading crawler output
        extraction_agent: FactExtractionAgent for LLM-powered extraction
        consolidator: FactConsolidator for dedup and storage
        batch_size: Number of articles to process in each batch
    """

    DEFAULT_BATCH_SIZE = 10

    def __init__(
        self,
        article_store: Optional["ArticleStore"] = None,  # noqa: F821
        extraction_agent: Optional["FactExtractionAgent"] = None,  # noqa: F821
        consolidator: Optional["FactConsolidator"] = None,  # noqa: F821
        fact_store: Optional["FactStore"] = None,  # noqa: F821
        batch_size: int = DEFAULT_BATCH_SIZE,
    ):
        """
        Initialize extraction pipeline.

        Args:
            article_store: ArticleStore for reading articles. Auto-creates if None.
            extraction_agent: FactExtractionAgent for extraction. Auto-creates if None.
            consolidator: FactConsolidator for dedup/storage. Auto-creates if None.
            fact_store: FactStore for persistence. Auto-creates if None.
            batch_size: Number of articles to process per batch.
        """
        # Lazy initialization - only import when needed
        self._article_store = article_store
        self._extraction_agent = extraction_agent
        self._consolidator = consolidator
        self._fact_store = fact_store
        self.batch_size = batch_size

        self.logger = logger.bind(component="ExtractionPipeline")
        self.stats = PipelineStats()

        self.logger.info(
            "ExtractionPipeline initialized",
            batch_size=batch_size,
            article_store_provided=article_store is not None,
            extraction_agent_provided=extraction_agent is not None,
            consolidator_provided=consolidator is not None,
        )

    @property
    def article_store(self):
        """Lazy-load ArticleStore on first access."""
        if self._article_store is None:
            from osint_system.data_management.article_store import ArticleStore
            self._article_store = ArticleStore()
        return self._article_store

    @property
    def extraction_agent(self):
        """Lazy-load FactExtractionAgent on first access."""
        if self._extraction_agent is None:
            from osint_system.agents.sifters import FactExtractionAgent
            self._extraction_agent = FactExtractionAgent()
        return self._extraction_agent

    @property
    def fact_store(self):
        """Lazy-load FactStore on first access."""
        if self._fact_store is None:
            from osint_system.data_management.fact_store import FactStore
            self._fact_store = FactStore()
        return self._fact_store

    @property
    def consolidator(self):
        """Lazy-load FactConsolidator on first access."""
        if self._consolidator is None:
            from osint_system.agents.sifters import FactConsolidator
            self._consolidator = FactConsolidator(fact_store=self.fact_store)
        return self._consolidator

    async def process_investigation(
        self,
        investigation_id: str,
        limit: Optional[int] = None,
        skip_consolidation: bool = False,
    ) -> Dict[str, Any]:
        """
        Process all articles for an investigation through fact extraction.

        Reads articles from ArticleStore, extracts facts via LLM, consolidates
        and deduplicates, then stores in FactStore.

        Args:
            investigation_id: Investigation identifier
            limit: Optional limit on number of articles to process
            skip_consolidation: If True, skip consolidation and return raw facts

        Returns:
            Dictionary with processing statistics:
            - investigation_id: ID processed
            - articles_processed: Number of articles successfully processed
            - articles_failed: Number of articles that failed extraction
            - facts_extracted: Total facts extracted (pre-consolidation)
            - facts_consolidated: Total facts after consolidation
            - error_count: Number of errors encountered
            - duration_seconds: Time taken
        """
        start_time = datetime.now(timezone.utc)
        self.stats = PipelineStats()  # Reset stats

        self.logger.info(
            f"Starting extraction pipeline for {investigation_id}",
            limit=limit,
        )

        # Retrieve articles from ArticleStore
        article_data = await self.article_store.retrieve_by_investigation(
            investigation_id, limit=limit
        )

        articles = article_data.get("articles", [])

        if not articles:
            self.logger.warning(
                f"No articles found for investigation {investigation_id}"
            )
            return {
                "investigation_id": investigation_id,
                **self.stats.to_dict(),
                "duration_seconds": 0,
            }

        self.logger.info(
            f"Processing {len(articles)} articles for {investigation_id}"
        )

        # Process articles in batches
        all_facts: List[Dict[str, Any]] = []

        for batch_start in range(0, len(articles), self.batch_size):
            batch_end = min(batch_start + self.batch_size, len(articles))
            batch = articles[batch_start:batch_end]

            self.logger.debug(
                f"Processing batch {batch_start//self.batch_size + 1}: "
                f"articles {batch_start+1}-{batch_end}"
            )

            batch_facts = await self._process_batch(batch, investigation_id)
            all_facts.extend(batch_facts)

        self.stats.facts_extracted = len(all_facts)

        # Consolidate facts
        if all_facts and not skip_consolidation:
            consolidated = await self._consolidate_facts(all_facts, investigation_id)
            self.stats.facts_consolidated = len(consolidated)
        else:
            self.stats.facts_consolidated = len(all_facts)

        # Calculate duration
        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()

        result = {
            "investigation_id": investigation_id,
            **self.stats.to_dict(),
            "duration_seconds": round(duration, 2),
        }

        self.logger.info(
            f"Extraction pipeline complete for {investigation_id}",
            **result,
        )

        return result

    async def process_article(
        self,
        article: Dict[str, Any],
        investigation_id: str,
        consolidate: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Process a single article through fact extraction.

        Args:
            article: Article dictionary with url, title, content, source, etc.
            investigation_id: Investigation identifier
            consolidate: If True, consolidate with existing facts

        Returns:
            List of extracted (and optionally consolidated) fact dictionaries
        """
        self.stats = PipelineStats()  # Reset stats

        # Transform and extract
        content = self._article_to_content(article, investigation_id)
        facts = await self._extract_from_content(content)

        if not facts:
            self.stats.articles_failed = 1
            return []

        self.stats.articles_processed = 1
        self.stats.facts_extracted = len(facts)

        # Consolidate if requested
        if consolidate and facts:
            consolidated = await self._consolidate_facts(facts, investigation_id)
            self.stats.facts_consolidated = len(consolidated)
            return consolidated

        self.stats.facts_consolidated = len(facts)
        return facts

    async def _process_batch(
        self,
        articles: List[Dict[str, Any]],
        investigation_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Process a batch of articles through extraction.

        Uses concurrent extraction for efficiency.

        Args:
            articles: List of article dictionaries
            investigation_id: Investigation identifier

        Returns:
            List of extracted facts from all articles
        """
        tasks = []
        for article in articles:
            content = self._article_to_content(article, investigation_id)
            tasks.append(self._extract_with_error_handling(content))

        results = await asyncio.gather(*tasks)

        all_facts: List[Dict[str, Any]] = []
        for facts in results:
            if facts is not None:
                all_facts.extend(facts)
                self.stats.articles_processed += 1
            else:
                self.stats.articles_failed += 1

        return all_facts

    async def _extract_with_error_handling(
        self,
        content: Dict[str, Any],
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Extract facts with error handling wrapper.

        Args:
            content: Content dictionary for extraction

        Returns:
            List of facts if successful, None if failed
        """
        try:
            facts = await self.extraction_agent.sift(content)
            return facts
        except Exception as e:
            error_msg = f"Extraction failed for {content.get('source_id')}: {e}"
            self.logger.warning(error_msg)
            self.stats.errors.append(error_msg)
            return None

    async def _extract_from_content(
        self,
        content: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Extract facts from prepared content.

        Args:
            content: Content dictionary with text, source_id, etc.

        Returns:
            List of extracted fact dictionaries
        """
        try:
            facts = await self.extraction_agent.sift(content)
            return facts
        except Exception as e:
            error_msg = f"Extraction failed: {e}"
            self.logger.warning(error_msg)
            self.stats.errors.append(error_msg)
            return []

    async def _consolidate_facts(
        self,
        facts: List[Dict[str, Any]],
        investigation_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Consolidate facts through deduplication and variant linking.

        Args:
            facts: List of extracted facts
            investigation_id: Investigation identifier

        Returns:
            List of consolidated facts
        """
        try:
            consolidated = await self.consolidator.sift({
                "facts": facts,
                "investigation_id": investigation_id,
            })
            return consolidated
        except Exception as e:
            error_msg = f"Consolidation failed: {e}"
            self.logger.error(error_msg, exc_info=True)
            self.stats.errors.append(error_msg)
            # Return original facts if consolidation fails
            return facts

    def _article_to_content(
        self,
        article: Dict[str, Any],
        investigation_id: str,
    ) -> Dict[str, Any]:
        """
        Transform article dictionary to extraction content format.

        Maps ArticleStore article format to FactExtractionAgent content format.

        ArticleStore format:
        {
            'url': 'https://...',
            'title': 'Article Title',
            'content': 'Full text...',
            'published_date': '2024-03-15T...',
            'source': {'name': 'Reuters', 'type': 'wire_service', ...},
            'metadata': {...}
        }

        Extraction content format:
        {
            'text': 'Full text...',
            'source_id': 'https://...',
            'source_type': 'wire_service',
            'publication_date': '2024-03-15',
            'metadata': {...}
        }

        Args:
            article: Article dictionary from ArticleStore
            investigation_id: Investigation identifier

        Returns:
            Content dictionary for FactExtractionAgent
        """
        # Extract source type from source metadata
        source = article.get("source", {})
        source_type = "unknown"

        if isinstance(source, dict):
            source_type = source.get("type", source.get("name", "unknown"))
        elif isinstance(source, str):
            source_type = source

        # Extract publication date
        pub_date = article.get("published_date", "")
        if pub_date and "T" in pub_date:
            # Extract just the date portion
            pub_date = pub_date.split("T")[0]

        # Build content text from title + content
        title = article.get("title", "")
        content_text = article.get("content", "")

        # Prepend title if available (provides context)
        if title and content_text:
            full_text = f"{title}\n\n{content_text}"
        else:
            full_text = content_text or title

        return {
            "text": full_text,
            "source_id": article.get("url", f"article-{investigation_id}"),
            "source_type": source_type,
            "publication_date": pub_date,
            "metadata": {
                "investigation_id": investigation_id,
                "article_title": title,
                "article_url": article.get("url", ""),
                "source_name": source.get("name", "") if isinstance(source, dict) else source,
                **article.get("metadata", {}),
            },
        }

    def get_pipeline_status(self) -> Dict[str, Any]:
        """
        Get current pipeline status and configuration.

        Returns:
            Dictionary with pipeline status
        """
        return {
            "batch_size": self.batch_size,
            "article_store_ready": self._article_store is not None,
            "extraction_agent_ready": self._extraction_agent is not None,
            "consolidator_ready": self._consolidator is not None,
            "fact_store_ready": self._fact_store is not None,
            "last_stats": self.stats.to_dict(),
        }

    def get_errors(self) -> List[str]:
        """
        Get list of errors from last pipeline run.

        Returns:
            List of error messages
        """
        return self.stats.errors.copy()
