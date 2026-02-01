"""Integration tests for extended crawler cohort coordination.

Tests the complete crawler coordination flow:
1. Multiple crawlers (Reddit, Document, Web) working together
2. Message bus coordination between crawlers
3. URL deduplication across crawlers
4. Authority scoring for source ranking
5. Context sharing for entity discovery

Uses mocked external APIs to avoid real network calls during testing.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from osint_system.agents.crawlers.social_media_agent import RedditCrawler
from osint_system.agents.crawlers.document_scraper_agent import DocumentCrawler
from osint_system.agents.crawlers.web_crawler import HybridWebCrawler
from osint_system.agents.crawlers.coordination.url_manager import URLManager
from osint_system.agents.crawlers.coordination.authority_scorer import AuthorityScorer
from osint_system.agents.crawlers.coordination.context_coordinator import ContextCoordinator
from osint_system.agents.communication.bus import MessageBus


@pytest.fixture
def message_bus():
    """Create a fresh MessageBus instance for testing."""
    MessageBus.reset_singleton()
    bus = MessageBus()
    yield bus
    MessageBus.reset_singleton()


@pytest.fixture
def url_manager():
    """Create URLManager instance."""
    return URLManager()


@pytest.fixture
def authority_scorer():
    """Create AuthorityScorer instance."""
    return AuthorityScorer()


@pytest.fixture
def context_coordinator(message_bus):
    """Create ContextCoordinator with message bus."""
    return ContextCoordinator(message_bus=message_bus, enable_broadcast=True)


class TestURLManager:
    """Tests for URL deduplication and normalization."""

    def test_url_normalization_removes_tracking_params(self, url_manager):
        """Test that tracking parameters are stripped during normalization."""
        url_with_tracking = "https://example.com/article?utm_source=twitter&utm_medium=social&id=123"
        normalized = url_manager.normalize_url(url_with_tracking)

        assert "utm_source" not in normalized
        assert "utm_medium" not in normalized
        assert "id=123" in normalized

    def test_url_normalization_handles_case(self, url_manager):
        """Test domain case normalization."""
        url1 = "https://EXAMPLE.COM/Article"
        url2 = "https://example.com/Article"

        normalized1 = url_manager.normalize_url(url1)
        normalized2 = url_manager.normalize_url(url2)

        assert normalized1 == normalized2

    def test_duplicate_detection_within_investigation(self, url_manager):
        """Test O(1) duplicate detection within same investigation."""
        investigation_id = "test_inv_001"
        url = "https://example.com/article1"

        # First add should succeed (not duplicate)
        assert url_manager.add_url(url, investigation_id) is True

        # Second add should fail (duplicate)
        assert url_manager.is_duplicate(url, investigation_id) is True
        assert url_manager.add_url(url, investigation_id) is False

    def test_same_url_different_investigations(self, url_manager):
        """Test that same URL can appear in different investigations."""
        url = "https://example.com/shared-article"

        # Add to first investigation
        assert url_manager.add_url(url, "inv_001") is True

        # Same URL should be allowed in different investigation
        assert url_manager.add_url(url, "inv_002") is True

        # But duplicate in same investigation
        assert url_manager.is_duplicate(url, "inv_001") is True

    def test_extract_domain(self, url_manager):
        """Test domain extraction for authority scoring."""
        assert url_manager.extract_domain("https://www.reuters.com/article") == "www.reuters.com"
        assert url_manager.extract_domain("https://bbc.com/news") == "bbc.com"


class TestAuthorityScorer:
    """Tests for source authority scoring."""

    def test_high_authority_domains(self, authority_scorer):
        """Test that wire services get high authority scores."""
        reuters_score = authority_scorer.calculate_score("https://www.reuters.com/article")
        ap_score = authority_scorer.calculate_score("https://apnews.com/article")

        assert reuters_score >= 0.85
        assert ap_score >= 0.85

    def test_government_domain_authority(self, authority_scorer):
        """Test that .gov domains get high authority."""
        gov_score = authority_scorer.calculate_score("https://state.gov/report.pdf")
        assert gov_score >= 0.8

    def test_social_media_lower_authority(self, authority_scorer):
        """Test that social media gets lower authority scores."""
        reddit_score = authority_scorer.calculate_score("https://reddit.com/r/news/123")
        assert reddit_score < 0.5

    def test_metadata_signal_enhancement(self, authority_scorer):
        """Test that metadata signals can boost score."""
        base_score = authority_scorer.calculate_score("https://example.com/article")

        enhanced_score = authority_scorer.calculate_score(
            "https://example.com/article",
            metadata={
                "author_verified": True,
                "publication_date": "2024-01-01",
                "engagement_metrics": {"score": 150, "comments": 75},
            },
        )

        assert enhanced_score > base_score

    def test_domain_category_classification(self, authority_scorer):
        """Test domain categorization."""
        assert authority_scorer.get_domain_category("https://state.gov/report") == "official"
        assert authority_scorer.get_domain_category("https://reuters.com/news") == "news"
        assert authority_scorer.get_domain_category("https://reddit.com/r/news") == "social"
        assert authority_scorer.get_domain_category("https://randomsite.com") == "unknown"


class TestContextCoordinator:
    """Tests for context sharing between crawlers."""

    @pytest.mark.asyncio
    async def test_entity_discovery_tracking(self, context_coordinator):
        """Test that entity discoveries are tracked."""
        await context_coordinator.share_discovery(
            entity="Ukraine",
            entity_type="location",
            source_url="https://reuters.com/article1",
            source_crawler="NewsFeedAgent",
            investigation_id="test_001",
            context="Conflict in Ukraine continues...",
        )

        # Verify entity is tracked
        entities = context_coordinator.get_investigation_entities("test_001")
        assert "ukraine" in entities

    @pytest.mark.asyncio
    async def test_cross_reference_finds_entities(self, context_coordinator):
        """Test cross-referencing content against known entities."""
        # Register some entities
        await context_coordinator.share_discovery(
            entity="Russia",
            entity_type="location",
            source_url="https://bbc.com/news1",
            source_crawler="NewsFeedAgent",
            investigation_id="test_002",
        )
        await context_coordinator.share_discovery(
            entity="Putin",
            entity_type="person",
            source_url="https://reuters.com/news1",
            source_crawler="NewsFeedAgent",
            investigation_id="test_002",
        )

        # Cross-reference new content
        content = "The situation in Russia remains tense as Putin addresses the nation."
        found = context_coordinator.cross_reference(content)

        assert "russia" in found
        assert "putin" in found

    @pytest.mark.asyncio
    async def test_related_sources_retrieval(self, context_coordinator):
        """Test getting sources that mention an entity."""
        entity = "NATO"
        investigation_id = "test_003"

        # Multiple sources mention NATO
        await context_coordinator.share_discovery(
            entity=entity,
            entity_type="organization",
            source_url="https://reuters.com/nato1",
            source_crawler="NewsFeedAgent",
            investigation_id=investigation_id,
        )
        await context_coordinator.share_discovery(
            entity=entity,
            entity_type="organization",
            source_url="https://bbc.com/nato2",
            source_crawler="WebCrawler",
            investigation_id=investigation_id,
        )

        sources = context_coordinator.get_related_sources(entity)
        assert len(sources) == 2
        assert "https://reuters.com/nato1" in sources
        assert "https://bbc.com/nato2" in sources


class TestCrawlerCoordination:
    """Integration tests for crawler cohort coordination."""

    @pytest.mark.asyncio
    async def test_parallel_crawler_execution(self, message_bus, url_manager, authority_scorer):
        """Test multiple crawlers can run in parallel via asyncio.gather."""
        investigation_id = "parallel_test_001"
        keywords = ["Ukraine", "conflict"]

        # Create mock fetch results
        mock_reddit_result = {
            "investigation_id": investigation_id,
            "posts": [
                {
                    "id": "reddit_post_1",
                    "title": "Ukraine conflict update",
                    "url": "https://reddit.com/r/news/abc123",
                    "score": 150,
                    "authority_score": 0.3,
                }
            ],
            "metadata": {"posts_returned": 1},
        }

        mock_document_result = {
            "success": True,
            "content": "UN report on Ukraine humanitarian situation...",
            "document_type": "pdf",
            "source_url": "https://un.org/report.pdf",
        }

        mock_web_result = {
            "success": True,
            "html": "<html><body>Latest news about Ukraine conflict</body></html>",
            "url": "https://bbc.com/ukraine-news",
            "rendered": False,
        }

        # Create crawlers with mocked methods
        with patch.object(RedditCrawler, "_init_reddit_client", return_value=MagicMock()):
            reddit_crawler = RedditCrawler(message_bus=message_bus)
            reddit_crawler.crawl_investigation = AsyncMock(return_value=mock_reddit_result)

        doc_crawler = DocumentCrawler()
        doc_crawler.process_document = AsyncMock(return_value=mock_document_result)

        web_crawler = HybridWebCrawler(message_bus=message_bus, use_playwright=False)
        web_crawler.fetch = AsyncMock(return_value=mock_web_result)

        # Run crawlers in parallel
        results = await asyncio.gather(
            reddit_crawler.crawl_investigation(investigation_id, keywords),
            doc_crawler.process_document("https://un.org/report.pdf"),
            web_crawler.fetch("https://bbc.com/ukraine-news"),
        )

        # Verify all results returned
        assert len(results) == 3
        assert results[0]["posts"][0]["title"] == "Ukraine conflict update"
        assert results[1]["document_type"] == "pdf"
        assert results[2]["success"] is True

    @pytest.mark.asyncio
    async def test_url_deduplication_across_crawlers(
        self,
        message_bus,
        url_manager,
    ):
        """Test that URLManager prevents duplicate fetches across crawlers."""
        investigation_id = "dedup_test_001"

        # Simulate URL discovery by different crawlers
        url = "https://reuters.com/shared-article"

        # First crawler discovers URL
        is_new = url_manager.add_url(url, investigation_id)
        assert is_new is True

        # Second crawler checks same URL - should be duplicate
        is_duplicate = url_manager.is_duplicate(url, investigation_id)
        assert is_duplicate is True

        # Verify URL count
        assert url_manager.get_url_count(investigation_id) == 1

    @pytest.mark.asyncio
    async def test_authority_scoring_ranks_sources(
        self,
        authority_scorer,
    ):
        """Test that authority scoring correctly ranks diverse sources."""
        sources = [
            {"url": "https://reddit.com/r/news/post1", "type": "reddit"},
            {"url": "https://reuters.com/article1", "type": "news"},
            {"url": "https://state.gov/report.pdf", "type": "government"},
            {"url": "https://randomsite.xyz/article", "type": "unknown"},
        ]

        # Score all sources
        scored_sources = []
        for source in sources:
            score = authority_scorer.calculate_score(source["url"])
            scored_sources.append({"url": source["url"], "score": score})

        # Sort by score descending
        scored_sources.sort(key=lambda x: x["score"], reverse=True)

        # Verify ranking: gov/news should be higher than social/unknown
        assert "state.gov" in scored_sources[0]["url"] or "reuters.com" in scored_sources[0]["url"]
        assert "reddit.com" in scored_sources[-1]["url"] or "randomsite" in scored_sources[-1]["url"]

    @pytest.mark.asyncio
    async def test_context_sharing_between_crawlers(
        self,
        message_bus,
        context_coordinator,
    ):
        """Test that crawlers can share discovered entities via context coordinator."""
        investigation_id = "context_test_001"

        # Simulate RedditCrawler discovering an entity
        await context_coordinator.share_discovery(
            entity="Volodymyr Zelenskyy",
            entity_type="person",
            source_url="https://reddit.com/r/news/post1",
            source_crawler="RedditCrawler",
            investigation_id=investigation_id,
            context="Zelenskyy addresses parliament",
        )

        # Simulate NewsFeedAgent discovering same entity from different source
        await context_coordinator.share_discovery(
            entity="Volodymyr Zelenskyy",
            entity_type="person",
            source_url="https://bbc.com/ukraine-zelenskyy",
            source_crawler="NewsFeedAgent",
            investigation_id=investigation_id,
            context="President Zelenskyy meets with allies",
        )

        # Verify entity is tracked with multiple sources
        sources = context_coordinator.get_related_sources("Volodymyr Zelenskyy")
        assert len(sources) == 2

        # Verify cross-referencing works (content must contain full entity name)
        new_content = "Volodymyr Zelenskyy announced new policies today"
        found = context_coordinator.cross_reference(new_content)
        assert "volodymyr zelenskyy" in found


class TestMessageBusIntegration:
    """Tests for message bus coordination between crawlers."""

    @pytest.mark.asyncio
    async def test_crawler_completion_messages(self, message_bus):
        """Test that crawlers can publish completion messages."""
        completion_messages = []

        async def track_completion(msg):
            if "crawler.complete" in msg.get("key", ""):
                completion_messages.append(msg)

        message_bus.subscribe_to_pattern(
            subscriber_name="completion_tracker",
            pattern="crawler.complete",
            callback=track_completion,
        )

        # Simulate crawler publishing completion
        await message_bus.publish(
            "crawler.complete",
            {
                "agent": "RedditCrawler",
                "investigation_id": "test_001",
                "post_count": 25,
                "authority_score": 0.3,
            },
        )

        # Allow message propagation
        await asyncio.sleep(0.1)

        assert len(completion_messages) >= 1
        assert completion_messages[0]["payload"]["agent"] == "RedditCrawler"

    @pytest.mark.asyncio
    async def test_context_update_broadcast(self, message_bus, context_coordinator):
        """Test that context updates are broadcast via message bus."""
        context_updates = []

        async def track_context(msg):
            if "context.update" in msg.get("key", ""):
                context_updates.append(msg)

        message_bus.subscribe_to_pattern(
            subscriber_name="context_tracker",
            pattern="context.update",
            callback=track_context,
        )

        # Share a discovery (should broadcast)
        await context_coordinator.share_discovery(
            entity="Test Entity",
            entity_type="organization",
            source_url="https://example.com/article",
            source_crawler="TestCrawler",
            investigation_id="broadcast_test",
        )

        # Allow message propagation
        await asyncio.sleep(0.1)

        assert len(context_updates) >= 1
        assert context_updates[0]["payload"]["entity"] == "Test Entity"


class TestInvestigationWorkflow:
    """End-to-end investigation workflow tests."""

    @pytest.mark.asyncio
    async def test_ukraine_conflict_investigation_mock(
        self,
        message_bus,
        url_manager,
        authority_scorer,
        context_coordinator,
    ):
        """
        Test complete investigation workflow with mocked crawlers.

        Simulates an investigation into "Ukraine conflict" using:
        - RedditCrawler for social media posts
        - DocumentCrawler for PDF reports
        - HybridWebCrawler for news sites
        """
        investigation_id = "ukraine_conflict_001"
        keywords = ["Ukraine", "conflict", "military"]

        # Simulate discoveries from each crawler

        # 1. Reddit finds discussion posts
        reddit_urls = [
            "https://reddit.com/r/worldnews/post1",
            "https://reddit.com/r/geopolitics/post2",
        ]
        for url in reddit_urls:
            url_manager.add_url(url, investigation_id)
            await context_coordinator.share_discovery(
                entity="Ukraine",
                entity_type="location",
                source_url=url,
                source_crawler="RedditCrawler",
                investigation_id=investigation_id,
            )

        # 2. Document crawler finds UN report
        doc_url = "https://un.org/ukraine-report.pdf"
        url_manager.add_url(doc_url, investigation_id)
        await context_coordinator.share_discovery(
            entity="United Nations",
            entity_type="organization",
            source_url=doc_url,
            source_crawler="DocumentCrawler",
            investigation_id=investigation_id,
        )

        # 3. Web crawler finds news articles
        news_urls = [
            "https://reuters.com/ukraine-update",
            "https://bbc.com/ukraine-latest",
        ]
        for url in news_urls:
            url_manager.add_url(url, investigation_id)

        # Verify URL tracking
        assert url_manager.get_url_count(investigation_id) == 5

        # Verify duplicate prevention
        assert url_manager.is_duplicate("https://reuters.com/ukraine-update", investigation_id) is True

        # Verify entity tracking
        entities = context_coordinator.get_investigation_entities(investigation_id)
        assert "ukraine" in entities
        assert "united nations" in entities

        # Verify authority scoring
        scores = []
        for url in [reddit_urls[0], doc_url, news_urls[0]]:
            scores.append({
                "url": url,
                "score": authority_scorer.calculate_score(url),
            })

        # Reuters should score higher than Reddit
        reuters_score = next(s["score"] for s in scores if "reuters" in s["url"])
        reddit_score = next(s["score"] for s in scores if "reddit" in s["url"])
        assert reuters_score > reddit_score


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
