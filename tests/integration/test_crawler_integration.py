"""Integration tests for crawler coordination between Planning Agent and News Crawler.

Tests the complete flow:
1. Planning Agent creates investigation
2. Planning Agent triggers NewsFeedAgent via message bus
3. NewsFeedAgent fetches and deduplicates articles
4. NewsFeedAgent stores articles in ArticleStore
5. NewsFeedAgent notifies Planning Agent via crawler.complete
6. Investigation status updated and ready for sifter agents
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from osint_system.agents.planning_agent import PlanningOrchestrator
from osint_system.agents.crawlers.newsfeed_agent import NewsFeedAgent
from osint_system.data_management.article_store import ArticleStore
from osint_system.agents.communication.bus import MessageBus
from osint_system.agents.registry import AgentRegistry


@pytest.fixture
def message_bus():
    """Create a MessageBus instance for testing."""
    bus = MessageBus()
    yield bus
    # Reset singleton for clean tests
    MessageBus.reset_singleton()


@pytest.fixture
def article_store():
    """Create an ArticleStore instance for testing."""
    return ArticleStore()


@pytest.fixture
def agent_registry():
    """Create an AgentRegistry instance for testing."""
    return AgentRegistry()


@pytest.fixture
async def planning_agent(message_bus, agent_registry):
    """Create a PlanningOrchestrator with message bus."""
    agent = PlanningOrchestrator(
        registry=agent_registry,
        message_bus=message_bus,
        max_refinements=3
    )
    return agent


@pytest.fixture
async def news_agent(message_bus, article_store):
    """Create a NewsFeedAgent with message bus and article store."""
    agent = NewsFeedAgent(
        message_bus=message_bus,
        article_store=article_store
    )
    return agent


@pytest.mark.asyncio
async def test_crawler_message_subscription():
    """Test that NewsFeedAgent subscribes to message bus topics."""
    message_bus = MessageBus()
    article_store = ArticleStore()
    news_agent = NewsFeedAgent(
        message_bus=message_bus,
        article_store=article_store
    )

    async with news_agent:
        # Verify subscriptions exist
        subscriptions = news_agent.message_bus.get_active_subscriptions()
        subscriber_keys = [key for keys in subscriptions.values() for key in keys]

        assert any("investigation.start" in key for key in subscriber_keys)
        assert any("crawler.fetch" in key for key in subscriber_keys)

    # Cleanup
    MessageBus.reset_singleton()


@pytest.mark.asyncio
async def test_planning_agent_triggers_crawler():
    """Test that Planning Agent triggers crawler execution for news-related tasks."""
    # Create shared message bus
    message_bus = MessageBus()

    # Track published messages
    published_messages = []
    original_publish = message_bus.publish

    async def tracking_publish(key, message):
        published_messages.append({"key": key, "message": message})
        await original_publish(key, message)

    message_bus.publish = tracking_publish

    # Create planning agent
    planning_agent = PlanningOrchestrator(
        message_bus=message_bus,
        max_refinements=3
    )

    # Create objective that should trigger news crawling
    objective = "Investigate recent political developments in Ukraine"

    # Build state with news-related subtasks
    state = {
        "objective": objective,
        "subtasks": [
            {
                "id": "ST-001",
                "description": "Find recent news articles about Ukraine",
                "priority": 9,
                "suggested_sources": ["news"],
                "status": "pending"
            }
        ],
        "messages": []
    }

    # Trigger assignment (which should trigger crawler)
    result = await planning_agent.assign_agents(state)

    # Verify investigation.start was published
    investigation_start_messages = [
        msg for msg in published_messages
        if msg["key"] == "investigation.start"
    ]

    assert len(investigation_start_messages) > 0, "No investigation.start message published"

    start_msg = investigation_start_messages[0]["message"]
    assert "investigation_id" in start_msg
    assert "query" in start_msg
    assert "objective" in start_msg

    # Cleanup
    MessageBus.reset_singleton()


@pytest.mark.asyncio
async def test_full_crawler_pipeline_with_mock():
    """Test complete pipeline from Planning Agent to ArticleStore with mocked RSS/API."""
    # Create shared infrastructure
    message_bus = MessageBus()
    article_store = ArticleStore()

    # Create agents
    planning_agent = PlanningOrchestrator(
        message_bus=message_bus,
        max_refinements=3
    )

    news_agent = NewsFeedAgent(
        message_bus=message_bus,
        article_store=article_store
    )

    # Mock RSS and API fetching to avoid external calls
    mock_articles = [
        {
            "title": "Test Article 1",
            "url": "https://example.com/article1",
            "content": "Test content about Ukraine politics",
            "published_date": datetime.now(timezone.utc).isoformat(),
            "source": {"name": "MockNews", "type": "rss"},
            "metadata": {"test": True}
        },
        {
            "title": "Test Article 2",
            "url": "https://example.com/article2",
            "content": "More test content about Ukraine",
            "published_date": datetime.now(timezone.utc).isoformat(),
            "source": {"name": "MockAPI", "type": "api"},
            "metadata": {"test": True}
        }
    ]

    # Mock the fetch_investigation_data method
    async def mock_fetch(*args, **kwargs):
        return {
            "success": True,
            "articles": mock_articles,
            "rss_articles": 1,
            "api_articles": 1,
            "total_articles": 2,
            "dedup_stats": {"duplicates_removed": 0},
            "source_breakdown": {"MockNews": 1, "MockAPI": 1},
            "errors": []
        }

    news_agent.fetch_investigation_data = mock_fetch

    # Track crawler completion messages
    completion_messages = []

    async def track_completion(message):
        if message.get("key") == "crawler.complete":
            completion_messages.append(message)

    # Subscribe to completion messages
    message_bus.subscribe_to_pattern(
        subscriber_name="test_tracker",
        pattern="crawler.complete",
        callback=track_completion
    )

    # Initialize news agent (subscribes to topics)
    async with news_agent:
        # Create investigation objective
        objective = "Investigate recent political developments in Ukraine"

        # Planning agent creates subtasks and triggers crawler
        state = {
            "objective": objective,
            "subtasks": [
                {
                    "id": "ST-001",
                    "description": "Find recent news articles about Ukraine",
                    "priority": 9,
                    "suggested_sources": ["news"],
                    "status": "pending"
                }
            ],
            "messages": []
        }

        # Trigger assignment (publishes investigation.start)
        await planning_agent.assign_agents(state)

        # Wait for async message handling
        await asyncio.sleep(0.5)

        # Verify articles were stored
        investigation_id = list(article_store._storage.keys())[0]  # Get the generated ID
        stored_data = await article_store.retrieve_by_investigation(investigation_id)

        assert stored_data["total_articles"] == 2, "Articles not stored correctly"
        assert len(stored_data["articles"]) == 2

        # Verify completion message was sent
        await asyncio.sleep(0.2)  # Allow time for message propagation
        assert len(completion_messages) > 0, "No crawler.complete message received"

        completion_msg = completion_messages[0]["payload"]
        assert completion_msg["agent"] == "NewsFeedAgent"
        assert completion_msg["article_count"] == 2

    # Cleanup
    MessageBus.reset_singleton()


@pytest.mark.asyncio
async def test_crawler_failure_handling():
    """Test that crawler failures are properly reported via message bus."""
    # Create shared infrastructure
    message_bus = MessageBus()
    article_store = ArticleStore()

    news_agent = NewsFeedAgent(
        message_bus=message_bus,
        article_store=article_store
    )

    # Mock fetch to fail
    async def mock_fetch_fail(*args, **kwargs):
        return {
            "success": False,
            "articles": [],
            "errors": ["Mock fetch error"],
            "total_articles": 0
        }

    news_agent.fetch_investigation_data = mock_fetch_fail

    # Track failure messages
    failure_messages = []

    async def track_failure(message):
        if message.get("key") == "crawler.failed":
            failure_messages.append(message)

    message_bus.subscribe_to_pattern(
        subscriber_name="test_failure_tracker",
        pattern="crawler.failed",
        callback=track_failure
    )

    # Initialize and trigger fetch
    async with news_agent:
        # Publish investigation start directly
        await message_bus.publish(
            "investigation.start",
            {
                "investigation_id": "test_fail_001",
                "query": "test query",
                "objective": "test objective"
            }
        )

        # Wait for handling
        await asyncio.sleep(0.5)

        # Verify failure was reported
        assert len(failure_messages) > 0, "No crawler.failed message received"

        failure_msg = failure_messages[0]["payload"]
        assert failure_msg["agent"] == "NewsFeedAgent"
        assert failure_msg["investigation_id"] == "test_fail_001"

    # Cleanup
    MessageBus.reset_singleton()


@pytest.mark.asyncio
async def test_article_storage_and_retrieval():
    """Test that articles are properly stored and can be retrieved."""
    article_store = ArticleStore()

    # Create test articles
    test_articles = [
        {
            "title": "Test Article",
            "url": "https://example.com/test",
            "content": "Test content",
            "published_date": datetime.now(timezone.utc).isoformat(),
            "source": {"name": "TestSource"},
            "metadata": {}
        }
    ]

    # Save articles
    stats = await article_store.save_articles(
        investigation_id="test_inv_001",
        articles=test_articles,
        investigation_metadata={"query": "test"}
    )

    assert stats["saved"] == 1
    assert stats["total"] == 1

    # Retrieve articles
    result = await article_store.retrieve_by_investigation("test_inv_001")

    # Ensure result is a dictionary with 'articles' key, not a list (UAT-002 fix)
    assert isinstance(result, dict), "ArticleStore should return a dictionary, not a list"
    assert "articles" in result, "Result must have 'articles' key"
    assert result["total_articles"] == 1
    assert len(result["articles"]) == 1
    assert result["articles"][0]["title"] == "Test Article"

    # Test URL duplicate detection
    stats2 = await article_store.save_articles(
        investigation_id="test_inv_001",
        articles=test_articles  # Same article again
    )

    assert stats2["updated"] == 1, "Duplicate should be updated, not added"
    assert stats2["saved"] == 0

    result2 = await article_store.retrieve_by_investigation("test_inv_001")
    assert result2["total_articles"] == 1, "Total should still be 1 after duplicate"


@pytest.mark.asyncio
async def test_investigation_statistics():
    """Test that investigation statistics are properly tracked."""
    article_store = ArticleStore()

    # Create articles from different sources
    articles = [
        {
            "title": f"Article {i}",
            "url": f"https://example.com/article{i}",
            "content": "Content",
            "published_date": datetime.now(timezone.utc).isoformat(),
            "source": {"name": "Source A" if i < 3 else "Source B"},
            "metadata": {}
        }
        for i in range(5)
    ]

    await article_store.save_articles(
        investigation_id="test_stats_001",
        articles=articles
    )

    # Get statistics
    stats = await article_store.get_investigation_stats("test_stats_001")

    assert stats["exists"] is True
    assert stats["total_articles"] == 5
    assert "Source A" in stats["source_breakdown"]
    assert "Source B" in stats["source_breakdown"]
    assert stats["source_breakdown"]["Source A"] == 3
    assert stats["source_breakdown"]["Source B"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
