"""Integration tests for RedditCrawler.

Tests:
1. Initialization with mock credentials
2. crawl_investigation with authority filtering
3. Message bus integration with mock investigation request
4. Error handling for API failures
5. Authority filtering (low-score posts excluded)

Uses pytest.mark.asyncio for async tests.
Mocks asyncpraw.Reddit when credentials not available.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from osint_system.agents.crawlers.social_media_agent import RedditCrawler
from osint_system.agents.communication.bus import MessageBus
from osint_system.config.settings import settings


@pytest.fixture
def message_bus():
    """Create a MessageBus instance for testing."""
    bus = MessageBus()
    yield bus
    # Reset singleton for clean tests
    MessageBus.reset_singleton()


@pytest.fixture
def mock_submission():
    """Create a mock Reddit submission for testing."""
    submission = MagicMock()
    submission.id = "abc123"
    submission.title = "Test Post Title"
    submission.selftext = "Test post content"
    submission.url = "https://reddit.com/r/news/comments/abc123"
    submission.score = 150  # Above high-value threshold
    submission.upvote_ratio = 0.92
    submission.author = MagicMock()
    submission.author.__str__ = lambda self: "test_user"
    submission.created_utc = datetime.now(timezone.utc).timestamp()
    submission.num_comments = 50  # Above min threshold
    submission.subreddit = MagicMock()
    submission.subreddit.__str__ = lambda self: "news"
    submission.permalink = "/r/news/comments/abc123/test_post"
    submission.is_self = True
    submission.link_flair_text = "News"
    submission.distinguished = None
    submission.stickied = False
    submission.locked = False
    submission.over_18 = False
    submission.load = AsyncMock()
    submission.comments = MagicMock()
    submission.comments.replace_more = MagicMock()
    submission.comments.__getitem__ = MagicMock(return_value=[])
    return submission


@pytest.fixture
def mock_low_score_submission():
    """Create a mock submission that should be filtered out."""
    submission = MagicMock()
    submission.id = "low123"
    submission.title = "Low Score Post"
    submission.selftext = "Low quality content"
    submission.url = "https://reddit.com/r/news/comments/low123"
    submission.score = 5  # Below MIN_SCORE_THRESHOLD (10)
    submission.upvote_ratio = 0.60
    submission.author = MagicMock()
    submission.author.__str__ = lambda self: "low_user"
    submission.created_utc = datetime.now(timezone.utc).timestamp()
    submission.num_comments = 2  # Below MIN_COMMENTS_THRESHOLD (5)
    submission.subreddit = MagicMock()
    submission.subreddit.__str__ = lambda self: "news"
    submission.permalink = "/r/news/comments/low123/low_post"
    submission.is_self = True
    submission.link_flair_text = None
    submission.distinguished = None
    submission.stickied = False
    submission.locked = False
    submission.over_18 = False
    submission.load = AsyncMock()
    return submission


@pytest.fixture
def mock_deleted_author_submission():
    """Create a mock submission with deleted author."""
    submission = MagicMock()
    submission.id = "del123"
    submission.title = "Deleted Author Post"
    submission.selftext = "Author was deleted"
    submission.url = "https://reddit.com/r/news/comments/del123"
    submission.score = 100
    submission.upvote_ratio = 0.90
    submission.author = None  # Deleted author
    submission.created_utc = datetime.now(timezone.utc).timestamp()
    submission.num_comments = 20
    submission.subreddit = MagicMock()
    submission.subreddit.__str__ = lambda self: "news"
    submission.permalink = "/r/news/comments/del123/deleted_post"
    submission.is_self = True
    submission.link_flair_text = None
    submission.distinguished = None
    submission.stickied = False
    submission.locked = False
    submission.over_18 = False
    submission.load = AsyncMock()
    return submission


class TestRedditCrawlerInitialization:
    """Test RedditCrawler initialization."""

    def test_init_with_defaults(self):
        """Test initialization with default parameters."""
        crawler = RedditCrawler()
        assert crawler.name == "RedditCrawler"
        assert crawler.max_requests_per_second == 1.0
        assert crawler.reddit_client is None
        assert crawler.message_bus is not None
        assert crawler._message_subscribed is False
        # Reset message bus singleton
        MessageBus.reset_singleton()

    def test_init_with_custom_params(self, message_bus):
        """Test initialization with custom parameters."""
        crawler = RedditCrawler(
            name="CustomRedditCrawler",
            max_requests_per_second=2.0,
            message_bus=message_bus,
        )
        assert crawler.name == "CustomRedditCrawler"
        assert crawler.max_requests_per_second == 2.0
        assert crawler.message_bus is message_bus

    def test_authority_constants(self):
        """Verify authority filtering constants are correctly set."""
        assert RedditCrawler.AUTHORITY_SCORE == 0.3
        assert RedditCrawler.MIN_SCORE_THRESHOLD == 10
        assert RedditCrawler.MIN_COMMENTS_THRESHOLD == 5
        assert RedditCrawler.HIGH_VALUE_SCORE_THRESHOLD == 100
        assert RedditCrawler.DEFAULT_SUBREDDITS == ["news", "worldnews", "geopolitics"]


class TestAuthorityFiltering:
    """Test authority filtering logic."""

    def test_is_valid_author_with_valid_author(self):
        """Test that valid authors pass validation."""
        crawler = RedditCrawler()

        # Mock a valid author
        valid_author = MagicMock()
        valid_author.__str__ = lambda self: "valid_user"

        assert crawler._is_valid_author(valid_author) is True
        MessageBus.reset_singleton()

    def test_is_valid_author_with_none(self):
        """Test that None author fails validation."""
        crawler = RedditCrawler()
        assert crawler._is_valid_author(None) is False
        MessageBus.reset_singleton()

    def test_is_valid_author_with_deleted(self):
        """Test that [deleted] author fails validation."""
        crawler = RedditCrawler()

        deleted_author = MagicMock()
        deleted_author.__str__ = lambda self: "[deleted]"

        assert crawler._is_valid_author(deleted_author) is False
        MessageBus.reset_singleton()

    def test_is_valid_author_with_removed(self):
        """Test that [removed] author fails validation."""
        crawler = RedditCrawler()

        removed_author = MagicMock()
        removed_author.__str__ = lambda self: "[removed]"

        assert crawler._is_valid_author(removed_author) is False
        MessageBus.reset_singleton()


class TestMessageBusIntegration:
    """Test message bus integration."""

    @pytest.mark.asyncio
    async def test_subscription_on_context_enter(self, message_bus):
        """Test that crawler subscribes to topics when entering context."""
        crawler = RedditCrawler(message_bus=message_bus)

        # Mock Reddit client initialization
        with patch.object(crawler, '_init_reddit_client', new_callable=AsyncMock) as mock_init:
            mock_init.return_value = MagicMock()
            mock_init.return_value.close = AsyncMock()

            async with crawler:
                # Verify subscription was created
                subscriptions = message_bus.get_active_subscriptions()
                subscriber_keys = [key for keys in subscriptions.values() for key in keys]
                assert any("reddit.crawl" in key for key in subscriber_keys)
                assert crawler._message_subscribed is True

    @pytest.mark.asyncio
    async def test_unsubscription_on_context_exit(self, message_bus):
        """Test that crawler unsubscribes when exiting context."""
        crawler = RedditCrawler(message_bus=message_bus)

        with patch.object(crawler, '_init_reddit_client', new_callable=AsyncMock) as mock_init:
            mock_reddit = MagicMock()
            mock_reddit.close = AsyncMock()
            mock_init.return_value = mock_reddit

            async with crawler:
                pass  # Enter and exit context

            assert crawler._message_subscribed is False

    @pytest.mark.asyncio
    async def test_handle_crawl_request_missing_investigation_id(self, message_bus):
        """Test that crawl request without investigation_id is rejected."""
        crawler = RedditCrawler(message_bus=message_bus)

        message = {
            "id": "msg-123",
            "payload": {
                "keywords": ["test"],
            }
        }

        # Should not raise, just log warning
        await crawler.handle_crawl_request(message)
        MessageBus.reset_singleton()

    @pytest.mark.asyncio
    async def test_handle_crawl_request_missing_keywords(self, message_bus):
        """Test that crawl request without keywords is rejected."""
        crawler = RedditCrawler(message_bus=message_bus)

        message = {
            "id": "msg-123",
            "payload": {
                "investigation_id": "inv-123",
            }
        }

        # Should not raise, just log warning
        await crawler.handle_crawl_request(message)
        MessageBus.reset_singleton()


class TestCrawlInvestigation:
    """Test crawl_investigation method."""

    @pytest.mark.asyncio
    async def test_crawl_investigation_filters_low_score(
        self, mock_submission, mock_low_score_submission, message_bus
    ):
        """Test that low-score posts are filtered out."""
        crawler = RedditCrawler(message_bus=message_bus)

        # Create mock subreddit that yields both submissions
        mock_subreddit = MagicMock()

        async def mock_search(*args, **kwargs):
            yield mock_low_score_submission  # Should be filtered (score=5)
            yield mock_submission  # Should pass (score=150)

        mock_subreddit.search = mock_search

        # Mock Reddit client
        mock_reddit = MagicMock()
        mock_reddit.subreddit = AsyncMock(return_value=mock_subreddit)
        mock_reddit.close = AsyncMock()
        crawler.reddit_client = mock_reddit

        result = await crawler.crawl_investigation(
            investigation_id="test-inv-123",
            keywords=["test"],
            subreddits=["news"],  # Single subreddit for test
        )

        # Only the high-score post should be included
        assert len(result["posts"]) == 1
        assert result["posts"][0]["id"] == "abc123"
        assert result["metadata"]["total_filtered"] > 0
        MessageBus.reset_singleton()

    @pytest.mark.asyncio
    async def test_crawl_investigation_filters_deleted_author(
        self, mock_submission, mock_deleted_author_submission, message_bus
    ):
        """Test that posts with deleted authors are filtered out."""
        crawler = RedditCrawler(message_bus=message_bus)

        mock_subreddit = MagicMock()

        async def mock_search(*args, **kwargs):
            yield mock_deleted_author_submission  # Should be filtered (no author)
            yield mock_submission  # Should pass

        mock_subreddit.search = mock_search

        mock_reddit = MagicMock()
        mock_reddit.subreddit = AsyncMock(return_value=mock_subreddit)
        mock_reddit.close = AsyncMock()
        crawler.reddit_client = mock_reddit

        result = await crawler.crawl_investigation(
            investigation_id="test-inv-456",
            keywords=["test"],
            subreddits=["news"],
        )

        # Only the valid post should be included
        assert len(result["posts"]) == 1
        assert result["posts"][0]["id"] == "abc123"
        MessageBus.reset_singleton()

    @pytest.mark.asyncio
    async def test_crawl_investigation_returns_metadata(
        self, mock_submission, message_bus
    ):
        """Test that crawl_investigation returns proper metadata."""
        crawler = RedditCrawler(message_bus=message_bus)

        mock_subreddit = MagicMock()

        async def mock_search(*args, **kwargs):
            yield mock_submission

        mock_subreddit.search = mock_search

        mock_reddit = MagicMock()
        mock_reddit.subreddit = AsyncMock(return_value=mock_subreddit)
        mock_reddit.close = AsyncMock()
        crawler.reddit_client = mock_reddit

        result = await crawler.crawl_investigation(
            investigation_id="test-inv-789",
            keywords=["Syria", "conflict"],
            subreddits=["news", "worldnews"],
        )

        assert result["investigation_id"] == "test-inv-789"
        assert result["authority_score"] == 0.3
        assert "metadata" in result
        assert result["metadata"]["keywords"] == ["Syria", "conflict"]
        assert "crawled_at" in result["metadata"]
        MessageBus.reset_singleton()


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_handle_subreddit_error_gracefully(self, message_bus):
        """Test that errors in individual subreddits don't crash the crawl."""
        crawler = RedditCrawler(message_bus=message_bus)

        async def mock_subreddit_raises(name):
            if name == "news":
                raise Exception("Subreddit unavailable")
            mock_sub = MagicMock()
            async def empty_search(*args, **kwargs):
                return
                yield  # Make it an async generator that yields nothing
            mock_sub.search = empty_search
            return mock_sub

        mock_reddit = MagicMock()
        mock_reddit.subreddit = mock_subreddit_raises
        mock_reddit.close = AsyncMock()
        crawler.reddit_client = mock_reddit

        # Should not raise, should continue with other subreddits
        result = await crawler.crawl_investigation(
            investigation_id="test-error",
            keywords=["test"],
            subreddits=["news", "worldnews"],  # news will error, worldnews won't
        )

        # Should complete with partial results
        assert result["investigation_id"] == "test-error"
        assert "worldnews" in result["metadata"]["subreddits_searched"]
        MessageBus.reset_singleton()

    @pytest.mark.asyncio
    async def test_message_bus_publishes_on_error(self, message_bus):
        """Test that errors in handle_crawl_request publish to reddit.failed."""
        crawler = RedditCrawler(message_bus=message_bus)

        # Track published messages
        published_messages = []
        original_publish = message_bus.publish

        async def tracking_publish(key, message):
            published_messages.append({"key": key, "message": message})
            await original_publish(key, message)

        message_bus.publish = tracking_publish

        # Mock crawl_investigation to raise an error
        with patch.object(crawler, 'crawl_investigation', new_callable=AsyncMock) as mock_crawl:
            mock_crawl.side_effect = Exception("API Error")

            message = {
                "id": "msg-error",
                "payload": {
                    "investigation_id": "inv-error",
                    "keywords": ["test"],
                }
            }

            await crawler.handle_crawl_request(message)

        # Verify reddit.failed was published
        failed_msgs = [m for m in published_messages if m["key"] == "reddit.failed"]
        assert len(failed_msgs) == 1
        assert failed_msgs[0]["message"]["investigation_id"] == "inv-error"
        assert "API Error" in failed_msgs[0]["message"]["error"]
        MessageBus.reset_singleton()


class TestCapabilities:
    """Test capability reporting."""

    def test_get_capabilities(self):
        """Test that get_capabilities returns expected capabilities."""
        crawler = RedditCrawler()
        capabilities = crawler.get_capabilities()

        expected_capabilities = [
            "reddit_crawling",
            "subreddit_search",
            "authority_filtering",
            "comment_extraction",
            "investigation_crawling",
            "message_bus_integration",
        ]

        for cap in expected_capabilities:
            assert cap in capabilities

        MessageBus.reset_singleton()


# Skip tests that require real Reddit API credentials
@pytest.mark.skipif(
    not settings.reddit_client_id or not settings.reddit_client_secret,
    reason="Reddit API credentials not configured"
)
class TestRealRedditAPI:
    """Tests that require actual Reddit API access.

    These tests are skipped if REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET
    are not configured in the environment.
    """

    @pytest.mark.asyncio
    async def test_real_subreddit_fetch(self, message_bus):
        """Test fetching from a real subreddit."""
        crawler = RedditCrawler(message_bus=message_bus)

        async with crawler:
            result = await crawler.fetch_subreddit(
                "news",
                limit=5,
                sort="hot"
            )

            assert len(result) > 0
            # Verify post structure
            for post in result:
                assert "id" in post
                assert "title" in post
                assert "score" in post
                assert "author" in post

    @pytest.mark.asyncio
    async def test_real_crawl_investigation(self, message_bus):
        """Test a real investigation crawl."""
        crawler = RedditCrawler(message_bus=message_bus)

        async with crawler:
            result = await crawler.crawl_investigation(
                investigation_id="test-real-inv",
                keywords=["technology"],
                subreddits=["technology"],
                limit_per_subreddit=10,
            )

            assert result["investigation_id"] == "test-real-inv"
            assert result["authority_score"] == 0.3
            # May or may not have posts depending on filtering
            assert "posts" in result
            assert "metadata" in result
