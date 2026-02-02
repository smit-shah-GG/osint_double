"""Tests for ExtractionPipeline.

Tests verify:
- Pipeline initialization with defaults and custom components
- Article-to-content transformation
- Empty investigation handling
- Single article processing
- Batch processing with mock extraction
- Error handling (failed article extraction)
- Pipeline status reporting
- End-to-end flow with mock data

Testing approach uses mocked components to avoid Gemini API calls.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from osint_system.pipelines.extraction_pipeline import ExtractionPipeline, PipelineStats


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_article_store():
    """Create a mock ArticleStore."""
    store = MagicMock()
    store.retrieve_by_investigation = AsyncMock(return_value={
        "investigation_id": "test-inv",
        "articles": [],
        "total_articles": 0,
        "returned_articles": 0,
    })
    return store


@pytest.fixture
def mock_extraction_agent():
    """Create a mock FactExtractionAgent."""
    agent = MagicMock()
    agent.sift = AsyncMock(return_value=[
        {
            "fact_id": str(uuid.uuid4()),
            "content_hash": "abc123",
            "claim": {"text": "Test fact claim", "assertion_type": "statement"},
            "entities": [{"id": "E1", "text": "Test", "type": "ORGANIZATION"}],
            "quality": {"extraction_confidence": 0.9, "claim_clarity": 0.85},
            "provenance": {"source_id": "test-source", "quote": "Test quote"},
        }
    ])
    return agent


@pytest.fixture
def mock_fact_consolidator():
    """Create a mock FactConsolidator."""
    consolidator = MagicMock()
    # By default, consolidator returns what it receives
    async def mock_sift(content):
        return content.get("facts", [])
    consolidator.sift = AsyncMock(side_effect=mock_sift)
    return consolidator


@pytest.fixture
def mock_fact_store():
    """Create a mock FactStore."""
    store = MagicMock()
    store.save_facts = AsyncMock(return_value={
        "saved": 1,
        "updated": 0,
        "skipped": 0,
        "total": 1,
    })
    return store


@pytest.fixture
def sample_article():
    """Create a sample article in ArticleStore format."""
    return {
        "url": "https://example.com/article-1",
        "title": "Test Article Title",
        "content": "This is the full text content of the test article. It contains multiple sentences and enough content for extraction.",
        "published_date": "2024-03-15T10:30:00Z",
        "source": {
            "name": "Reuters",
            "type": "wire_service",
            "authority_score": 0.9,
        },
        "metadata": {
            "author": "Test Author",
            "word_count": 100,
        },
        "stored_at": "2024-03-15T10:35:00Z",
    }


@pytest.fixture
def sample_articles(sample_article):
    """Create multiple sample articles."""
    articles = [sample_article]
    for i in range(2, 6):
        articles.append({
            **sample_article,
            "url": f"https://example.com/article-{i}",
            "title": f"Test Article {i}",
            "content": f"Content for article {i}. " * 20,
        })
    return articles


# ============================================================
# PipelineStats Tests
# ============================================================


class TestPipelineStats:
    """Tests for PipelineStats dataclass."""

    def test_default_initialization(self):
        """Stats initializes with zero counts."""
        stats = PipelineStats()
        assert stats.articles_processed == 0
        assert stats.articles_failed == 0
        assert stats.facts_extracted == 0
        assert stats.facts_consolidated == 0
        assert stats.errors == []

    def test_to_dict(self):
        """Stats converts to dictionary correctly."""
        stats = PipelineStats(
            articles_processed=5,
            articles_failed=1,
            facts_extracted=20,
            facts_consolidated=15,
            errors=["Error 1", "Error 2"],
        )
        result = stats.to_dict()

        assert result["articles_processed"] == 5
        assert result["articles_failed"] == 1
        assert result["facts_extracted"] == 20
        assert result["facts_consolidated"] == 15
        assert result["error_count"] == 2

    def test_errors_list_isolation(self):
        """Errors list is not shared between instances."""
        stats1 = PipelineStats()
        stats2 = PipelineStats()

        stats1.errors.append("Error")

        assert len(stats1.errors) == 1
        assert len(stats2.errors) == 0


# ============================================================
# Initialization Tests
# ============================================================


class TestPipelineInitialization:
    """Tests for ExtractionPipeline initialization."""

    def test_default_initialization(self):
        """Pipeline initializes with default settings."""
        pipeline = ExtractionPipeline()

        assert pipeline.batch_size == 10
        assert pipeline._article_store is None
        assert pipeline._extraction_agent is None
        assert pipeline._consolidator is None
        assert pipeline._fact_store is None

    def test_custom_batch_size(self):
        """Pipeline accepts custom batch size."""
        pipeline = ExtractionPipeline(batch_size=25)
        assert pipeline.batch_size == 25

    def test_injected_components(
        self,
        mock_article_store,
        mock_extraction_agent,
        mock_fact_consolidator,
        mock_fact_store,
    ):
        """Pipeline accepts injected components."""
        pipeline = ExtractionPipeline(
            article_store=mock_article_store,
            extraction_agent=mock_extraction_agent,
            consolidator=mock_fact_consolidator,
            fact_store=mock_fact_store,
        )

        # Components are set directly
        assert pipeline._article_store is mock_article_store
        assert pipeline._extraction_agent is mock_extraction_agent
        assert pipeline._consolidator is mock_fact_consolidator
        assert pipeline._fact_store is mock_fact_store

    def test_lazy_article_store_initialization(self):
        """ArticleStore is lazy-loaded on first access."""
        pipeline = ExtractionPipeline()
        assert pipeline._article_store is None

        # Access property triggers creation
        store = pipeline.article_store
        assert store is not None
        assert pipeline._article_store is store

    def test_lazy_fact_store_initialization(self):
        """FactStore is lazy-loaded on first access."""
        pipeline = ExtractionPipeline()
        assert pipeline._fact_store is None

        # Access property triggers creation
        store = pipeline.fact_store
        assert store is not None
        assert pipeline._fact_store is store


# ============================================================
# Article Transformation Tests
# ============================================================


class TestArticleTransformation:
    """Tests for article-to-content transformation."""

    def test_basic_transformation(self, sample_article):
        """Article transforms to extraction content format."""
        pipeline = ExtractionPipeline()
        content = pipeline._article_to_content(sample_article, "inv-001")

        # Text should include title and content
        assert "Test Article Title" in content["text"]
        assert "full text content" in content["text"]

        # Source ID should be URL
        assert content["source_id"] == "https://example.com/article-1"

        # Source type from source.type
        assert content["source_type"] == "wire_service"

        # Publication date extracted (date part only)
        assert content["publication_date"] == "2024-03-15"

    def test_transformation_with_missing_source_type(self):
        """Handles missing source type gracefully."""
        article = {
            "url": "https://example.com/test",
            "title": "Test",
            "content": "Test content here.",
            "source": {"name": "Unknown Source"},
        }
        pipeline = ExtractionPipeline()
        content = pipeline._article_to_content(article, "inv-001")

        # Falls back to source name
        assert content["source_type"] == "Unknown Source"

    def test_transformation_with_string_source(self):
        """Handles string source (not dict) gracefully."""
        article = {
            "url": "https://example.com/test",
            "title": "Test",
            "content": "Test content here.",
            "source": "Reuters",
        }
        pipeline = ExtractionPipeline()
        content = pipeline._article_to_content(article, "inv-001")

        assert content["source_type"] == "Reuters"

    def test_transformation_with_no_source(self):
        """Handles missing source gracefully."""
        article = {
            "url": "https://example.com/test",
            "title": "Test",
            "content": "Test content here.",
        }
        pipeline = ExtractionPipeline()
        content = pipeline._article_to_content(article, "inv-001")

        assert content["source_type"] == "unknown"

    def test_transformation_includes_metadata(self, sample_article):
        """Transformation includes article metadata."""
        pipeline = ExtractionPipeline()
        content = pipeline._article_to_content(sample_article, "inv-001")

        assert content["metadata"]["investigation_id"] == "inv-001"
        assert content["metadata"]["article_title"] == "Test Article Title"
        assert content["metadata"]["article_url"] == "https://example.com/article-1"
        assert content["metadata"]["source_name"] == "Reuters"
        # Original metadata merged
        assert content["metadata"]["author"] == "Test Author"

    def test_transformation_without_title(self):
        """Handles article without title."""
        article = {
            "url": "https://example.com/test",
            "content": "Just content, no title.",
        }
        pipeline = ExtractionPipeline()
        content = pipeline._article_to_content(article, "inv-001")

        # Text should be just content
        assert content["text"] == "Just content, no title."

    def test_transformation_with_only_title(self):
        """Handles article with only title."""
        article = {
            "url": "https://example.com/test",
            "title": "Just a title",
        }
        pipeline = ExtractionPipeline()
        content = pipeline._article_to_content(article, "inv-001")

        assert content["text"] == "Just a title"

    def test_transformation_with_no_url(self):
        """Handles article without URL."""
        article = {
            "title": "Test",
            "content": "Test content.",
        }
        pipeline = ExtractionPipeline()
        content = pipeline._article_to_content(article, "inv-001")

        # Generates fallback source_id
        assert "article-inv-001" in content["source_id"]


# ============================================================
# Empty Investigation Tests
# ============================================================


class TestEmptyInvestigation:
    """Tests for handling empty investigations."""

    @pytest.mark.asyncio
    async def test_empty_investigation(self, mock_article_store, mock_extraction_agent):
        """Pipeline handles empty investigation gracefully."""
        # Configure mock to return empty articles
        mock_article_store.retrieve_by_investigation = AsyncMock(return_value={
            "investigation_id": "empty-inv",
            "articles": [],
            "total_articles": 0,
            "returned_articles": 0,
        })

        pipeline = ExtractionPipeline(
            article_store=mock_article_store,
            extraction_agent=mock_extraction_agent,
        )

        result = await pipeline.process_investigation("empty-inv")

        assert result["investigation_id"] == "empty-inv"
        assert result["articles_processed"] == 0
        assert result["facts_extracted"] == 0
        assert result["facts_consolidated"] == 0

        # Extraction agent should not have been called
        mock_extraction_agent.sift.assert_not_called()

    @pytest.mark.asyncio
    async def test_nonexistent_investigation(self, mock_article_store, mock_extraction_agent):
        """Pipeline handles nonexistent investigation."""
        mock_article_store.retrieve_by_investigation = AsyncMock(return_value={
            "investigation_id": "nonexistent",
            "articles": [],
            "total_articles": 0,
            "returned_articles": 0,
        })

        pipeline = ExtractionPipeline(
            article_store=mock_article_store,
            extraction_agent=mock_extraction_agent,
        )

        result = await pipeline.process_investigation("nonexistent")

        assert result["articles_processed"] == 0


# ============================================================
# Single Article Processing Tests
# ============================================================


class TestSingleArticleProcessing:
    """Tests for single article processing."""

    @pytest.mark.asyncio
    async def test_process_single_article(
        self,
        sample_article,
        mock_extraction_agent,
        mock_fact_consolidator,
    ):
        """Pipeline processes single article successfully."""
        pipeline = ExtractionPipeline(
            extraction_agent=mock_extraction_agent,
            consolidator=mock_fact_consolidator,
        )

        facts = await pipeline.process_article(sample_article, "inv-001")

        assert len(facts) == 1
        assert facts[0]["claim"]["text"] == "Test fact claim"

        # Verify extraction was called
        mock_extraction_agent.sift.assert_called_once()
        call_args = mock_extraction_agent.sift.call_args[0][0]
        assert "Test Article Title" in call_args["text"]

    @pytest.mark.asyncio
    async def test_process_article_without_consolidation(
        self,
        sample_article,
        mock_extraction_agent,
        mock_fact_consolidator,
    ):
        """Pipeline can skip consolidation for single article."""
        pipeline = ExtractionPipeline(
            extraction_agent=mock_extraction_agent,
            consolidator=mock_fact_consolidator,
        )

        facts = await pipeline.process_article(
            sample_article, "inv-001", consolidate=False
        )

        assert len(facts) == 1

        # Consolidator should not have been called
        mock_fact_consolidator.sift.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_article_extraction_failure(
        self,
        sample_article,
        mock_extraction_agent,
    ):
        """Pipeline handles extraction failure for single article."""
        mock_extraction_agent.sift = AsyncMock(side_effect=Exception("Extraction error"))

        pipeline = ExtractionPipeline(extraction_agent=mock_extraction_agent)

        facts = await pipeline.process_article(sample_article, "inv-001")

        assert facts == []
        assert pipeline.stats.errors[0] == "Extraction failed: Extraction error"


# ============================================================
# Batch Processing Tests
# ============================================================


class TestBatchProcessing:
    """Tests for batch processing of articles."""

    @pytest.mark.asyncio
    async def test_batch_processing_single_batch(
        self,
        mock_article_store,
        mock_extraction_agent,
        mock_fact_consolidator,
        sample_articles,
    ):
        """Pipeline processes articles in batch."""
        mock_article_store.retrieve_by_investigation = AsyncMock(return_value={
            "investigation_id": "inv-001",
            "articles": sample_articles,
            "total_articles": len(sample_articles),
            "returned_articles": len(sample_articles),
        })

        pipeline = ExtractionPipeline(
            article_store=mock_article_store,
            extraction_agent=mock_extraction_agent,
            consolidator=mock_fact_consolidator,
            batch_size=10,  # All in one batch
        )

        result = await pipeline.process_investigation("inv-001")

        assert result["articles_processed"] == 5
        # 5 articles * 1 fact each = 5 facts
        assert result["facts_extracted"] == 5
        assert mock_extraction_agent.sift.call_count == 5

    @pytest.mark.asyncio
    async def test_batch_processing_multiple_batches(
        self,
        mock_article_store,
        mock_extraction_agent,
        mock_fact_consolidator,
        sample_articles,
    ):
        """Pipeline processes articles across multiple batches."""
        mock_article_store.retrieve_by_investigation = AsyncMock(return_value={
            "investigation_id": "inv-001",
            "articles": sample_articles,
            "total_articles": len(sample_articles),
            "returned_articles": len(sample_articles),
        })

        pipeline = ExtractionPipeline(
            article_store=mock_article_store,
            extraction_agent=mock_extraction_agent,
            consolidator=mock_fact_consolidator,
            batch_size=2,  # Forces 3 batches (2, 2, 1)
        )

        result = await pipeline.process_investigation("inv-001")

        assert result["articles_processed"] == 5
        assert mock_extraction_agent.sift.call_count == 5

    @pytest.mark.asyncio
    async def test_batch_processing_with_limit(
        self,
        mock_article_store,
        mock_extraction_agent,
        mock_fact_consolidator,
        sample_articles,
    ):
        """Pipeline respects article limit."""
        # Return limited articles
        mock_article_store.retrieve_by_investigation = AsyncMock(return_value={
            "investigation_id": "inv-001",
            "articles": sample_articles[:2],  # Only 2 articles
            "total_articles": 5,
            "returned_articles": 2,
        })

        pipeline = ExtractionPipeline(
            article_store=mock_article_store,
            extraction_agent=mock_extraction_agent,
            consolidator=mock_fact_consolidator,
        )

        result = await pipeline.process_investigation("inv-001", limit=2)

        assert result["articles_processed"] == 2
        # Verify limit was passed to store
        mock_article_store.retrieve_by_investigation.assert_called_once_with(
            "inv-001", limit=2
        )


# ============================================================
# Error Handling Tests
# ============================================================


class TestErrorHandling:
    """Tests for error handling in the pipeline."""

    @pytest.mark.asyncio
    async def test_partial_extraction_failure(
        self,
        mock_article_store,
        mock_extraction_agent,
        mock_fact_consolidator,
        sample_articles,
    ):
        """Pipeline continues when some articles fail extraction."""
        # Make some extractions fail
        call_count = 0
        async def flaky_sift(content):
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 0:
                raise Exception("Random failure")
            return [{
                "fact_id": str(uuid.uuid4()),
                "content_hash": "hash",
                "claim": {"text": "Fact"},
            }]

        mock_extraction_agent.sift = AsyncMock(side_effect=flaky_sift)

        mock_article_store.retrieve_by_investigation = AsyncMock(return_value={
            "investigation_id": "inv-001",
            "articles": sample_articles[:4],  # 4 articles
            "total_articles": 4,
            "returned_articles": 4,
        })

        pipeline = ExtractionPipeline(
            article_store=mock_article_store,
            extraction_agent=mock_extraction_agent,
            consolidator=mock_fact_consolidator,
        )

        result = await pipeline.process_investigation("inv-001")

        # 4 articles: 1 pass, 2 fail, 3 pass, 4 fail = 2 success, 2 fail
        assert result["articles_processed"] == 2
        assert result["articles_failed"] == 2
        assert result["error_count"] == 2

    @pytest.mark.asyncio
    async def test_consolidation_failure_returns_original_facts(
        self,
        mock_article_store,
        mock_extraction_agent,
        mock_fact_consolidator,
        sample_articles,
    ):
        """Pipeline returns original facts if consolidation fails."""
        mock_article_store.retrieve_by_investigation = AsyncMock(return_value={
            "investigation_id": "inv-001",
            "articles": sample_articles[:2],
            "total_articles": 2,
            "returned_articles": 2,
        })

        # Make consolidator fail
        mock_fact_consolidator.sift = AsyncMock(
            side_effect=Exception("Consolidation error")
        )

        pipeline = ExtractionPipeline(
            article_store=mock_article_store,
            extraction_agent=mock_extraction_agent,
            consolidator=mock_fact_consolidator,
        )

        result = await pipeline.process_investigation("inv-001")

        # Facts should be extracted count (not consolidated)
        assert result["facts_extracted"] == 2
        # Consolidated returns original on error
        assert result["facts_consolidated"] == 2
        assert result["error_count"] == 1

    @pytest.mark.asyncio
    async def test_error_messages_tracked(
        self,
        sample_article,
        mock_extraction_agent,
    ):
        """Error messages are tracked in pipeline stats."""
        mock_extraction_agent.sift = AsyncMock(
            side_effect=Exception("Detailed error message")
        )

        pipeline = ExtractionPipeline(extraction_agent=mock_extraction_agent)

        await pipeline.process_article(sample_article, "inv-001")

        errors = pipeline.get_errors()
        assert len(errors) == 1
        assert "Detailed error message" in errors[0]


# ============================================================
# Pipeline Status Tests
# ============================================================


class TestPipelineStatus:
    """Tests for pipeline status reporting."""

    def test_pipeline_status_default(self):
        """Pipeline reports status with defaults."""
        pipeline = ExtractionPipeline()
        status = pipeline.get_pipeline_status()

        assert status["batch_size"] == 10
        assert status["article_store_ready"] is False
        assert status["extraction_agent_ready"] is False
        assert status["consolidator_ready"] is False
        assert status["fact_store_ready"] is False

    def test_pipeline_status_after_component_init(
        self,
        mock_article_store,
        mock_extraction_agent,
    ):
        """Pipeline reports ready status after component init."""
        pipeline = ExtractionPipeline(
            article_store=mock_article_store,
            extraction_agent=mock_extraction_agent,
        )
        status = pipeline.get_pipeline_status()

        assert status["article_store_ready"] is True
        assert status["extraction_agent_ready"] is True
        assert status["consolidator_ready"] is False

    @pytest.mark.asyncio
    async def test_pipeline_status_includes_stats(
        self,
        mock_article_store,
        mock_extraction_agent,
        mock_fact_consolidator,
        sample_articles,
    ):
        """Pipeline status includes last run stats."""
        mock_article_store.retrieve_by_investigation = AsyncMock(return_value={
            "investigation_id": "inv-001",
            "articles": sample_articles[:3],
            "total_articles": 3,
            "returned_articles": 3,
        })

        pipeline = ExtractionPipeline(
            article_store=mock_article_store,
            extraction_agent=mock_extraction_agent,
            consolidator=mock_fact_consolidator,
        )

        await pipeline.process_investigation("inv-001")
        status = pipeline.get_pipeline_status()

        assert status["last_stats"]["articles_processed"] == 3
        assert status["last_stats"]["facts_extracted"] == 3


# ============================================================
# End-to-End Integration Tests (with mocks)
# ============================================================


class TestEndToEnd:
    """End-to-end integration tests with mocked components."""

    @pytest.mark.asyncio
    async def test_full_pipeline_flow(
        self,
        mock_article_store,
        mock_extraction_agent,
        mock_fact_consolidator,
        mock_fact_store,
        sample_articles,
    ):
        """Test complete pipeline flow from articles to stored facts."""
        # Configure stores
        mock_article_store.retrieve_by_investigation = AsyncMock(return_value={
            "investigation_id": "full-test",
            "articles": sample_articles,
            "total_articles": len(sample_articles),
            "returned_articles": len(sample_articles),
        })

        # Extraction returns multiple facts
        async def multi_fact_sift(content):
            return [
                {
                    "fact_id": str(uuid.uuid4()),
                    "content_hash": f"hash-{uuid.uuid4()}",
                    "claim": {"text": f"Fact from {content.get('source_id')}"},
                },
                {
                    "fact_id": str(uuid.uuid4()),
                    "content_hash": f"hash-{uuid.uuid4()}",
                    "claim": {"text": "Secondary fact"},
                },
            ]
        mock_extraction_agent.sift = AsyncMock(side_effect=multi_fact_sift)

        # Consolidator tracks what it receives
        received_facts = []
        async def tracking_sift(content):
            facts = content.get("facts", [])
            received_facts.extend(facts)
            # Simulate dedup - reduce by 20%
            return facts[:int(len(facts) * 0.8)] or facts
        mock_fact_consolidator.sift = AsyncMock(side_effect=tracking_sift)

        pipeline = ExtractionPipeline(
            article_store=mock_article_store,
            extraction_agent=mock_extraction_agent,
            consolidator=mock_fact_consolidator,
            fact_store=mock_fact_store,
        )

        result = await pipeline.process_investigation("full-test")

        # 5 articles processed
        assert result["articles_processed"] == 5

        # 5 articles * 2 facts = 10 facts extracted
        assert result["facts_extracted"] == 10

        # Consolidator received all 10 facts
        assert len(received_facts) == 10

        # Consolidation reduced by 20%
        assert result["facts_consolidated"] == 8

        # Duration is tracked
        assert result["duration_seconds"] >= 0

    @pytest.mark.asyncio
    async def test_skip_consolidation_option(
        self,
        mock_article_store,
        mock_extraction_agent,
        mock_fact_consolidator,
        sample_articles,
    ):
        """Test pipeline with skip_consolidation flag."""
        mock_article_store.retrieve_by_investigation = AsyncMock(return_value={
            "investigation_id": "skip-test",
            "articles": sample_articles[:2],
            "total_articles": 2,
            "returned_articles": 2,
        })

        pipeline = ExtractionPipeline(
            article_store=mock_article_store,
            extraction_agent=mock_extraction_agent,
            consolidator=mock_fact_consolidator,
        )

        result = await pipeline.process_investigation(
            "skip-test", skip_consolidation=True
        )

        # Consolidator should not be called
        mock_fact_consolidator.sift.assert_not_called()

        # facts_consolidated equals facts_extracted
        assert result["facts_consolidated"] == result["facts_extracted"]

    @pytest.mark.asyncio
    async def test_concurrent_extraction(
        self,
        mock_article_store,
        mock_extraction_agent,
        mock_fact_consolidator,
        sample_articles,
    ):
        """Test that extraction runs concurrently within batches."""
        extraction_times = []

        async def tracking_sift(content):
            extraction_times.append(datetime.now(timezone.utc))
            await asyncio.sleep(0.01)  # Small delay
            return [{
                "fact_id": str(uuid.uuid4()),
                "content_hash": "hash",
                "claim": {"text": "Fact"},
            }]

        mock_extraction_agent.sift = AsyncMock(side_effect=tracking_sift)
        mock_article_store.retrieve_by_investigation = AsyncMock(return_value={
            "investigation_id": "concurrent-test",
            "articles": sample_articles,  # 5 articles
            "total_articles": 5,
            "returned_articles": 5,
        })

        pipeline = ExtractionPipeline(
            article_store=mock_article_store,
            extraction_agent=mock_extraction_agent,
            consolidator=mock_fact_consolidator,
            batch_size=5,  # All in one batch
        )

        await pipeline.process_investigation("concurrent-test")

        # Verify extractions happened (5 calls)
        assert len(extraction_times) == 5

        # If concurrent, times should be close together (within same batch)
        if len(extraction_times) >= 2:
            time_diff = (extraction_times[-1] - extraction_times[0]).total_seconds()
            # Concurrent execution should be faster than sequential
            # 5 sequential at 0.01s each = 0.05s
            # Concurrent should be closer to 0.01s
            # Allow some margin for test execution overhead
            assert time_diff < 0.05
