"""Reddit crawler agent for social media data acquisition."""

import asyncio
from datetime import datetime, timezone
from typing import Optional, Any, Dict, List
import asyncpraw
import httpx
import aiometer
from yarl import URL
from tenacity import retry, stop_after_attempt, wait_exponential

from osint_system.agents.crawlers.base_crawler import BaseCrawler
from osint_system.config.settings import settings
from osint_system.utils.logging import get_structured_logger

logger = get_structured_logger(__name__)


class RedditCrawler(BaseCrawler):
    """
    Reddit-specific crawler using asyncpraw for API access.

    Implements intelligent rate limiting and data extraction from Reddit
    posts and comments. Uses async patterns for efficient data collection.

    Attributes:
        reddit_client: Asyncpraw Reddit client instance
        rate_limiter: Aiometer rate limiter for API calls
    """

    def __init__(
        self,
        name: str = "RedditCrawler",
        description: str = "Fetches data from Reddit subreddits and threads",
        source_configs: Optional[dict] = None,
        investigation_context: Optional[dict] = None,
        max_requests_per_second: float = 1.0,
    ):
        """
        Initialize Reddit crawler.

        Args:
            name: Crawler name
            description: Crawler description
            source_configs: Reddit-specific configurations
            investigation_context: Current investigation context
            max_requests_per_second: Rate limit for API requests
        """
        super().__init__(
            name=name,
            description=description,
            source_configs=source_configs or {},
            investigation_context=investigation_context,
        )
        self.reddit_client: Optional[asyncpraw.Reddit] = None
        self.max_requests_per_second = max_requests_per_second

    async def _init_reddit_client(self) -> asyncpraw.Reddit:
        """
        Initialize asyncpraw Reddit client with credentials.

        Returns:
            Configured Reddit client instance

        Raises:
            ValueError: If Reddit credentials are not configured
        """
        if not settings.reddit_client_id or not settings.reddit_client_secret:
            raise ValueError(
                "Reddit API credentials not configured. "
                "Please set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in .env"
            )

        return asyncpraw.Reddit(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            user_agent=settings.reddit_user_agent,
            # Read-only mode, no OAuth needed for public data
            requestor_kwargs={"session": httpx.AsyncClient()}
        )

    async def __aenter__(self):
        """Async context manager entry."""
        if not self.reddit_client:
            self.reddit_client = await self._init_reddit_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - close Reddit client."""
        if self.reddit_client:
            await self.reddit_client.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10)
    )
    async def fetch_subreddit(
        self,
        subreddit_name: str,
        limit: int = 25,
        time_filter: str = "week",
        sort: str = "hot"
    ) -> List[Dict[str, Any]]:
        """
        Fetch posts from a subreddit with rate limiting.

        Args:
            subreddit_name: Name of subreddit to fetch from
            limit: Maximum number of posts to fetch
            time_filter: Time filter (all, day, week, month, year)
            sort: Sort method (hot, new, top, rising)

        Returns:
            List of extracted post data dictionaries
        """
        if not self.reddit_client:
            self.reddit_client = await self._init_reddit_client()

        posts = []
        subreddit = await self.reddit_client.subreddit(subreddit_name)

        # Select appropriate stream based on sort method
        if sort == "hot":
            submission_stream = subreddit.hot(limit=limit)
        elif sort == "new":
            submission_stream = subreddit.new(limit=limit)
        elif sort == "top":
            submission_stream = subreddit.top(limit=limit, time_filter=time_filter)
        else:  # rising
            submission_stream = subreddit.rising(limit=limit)

        # Rate-limited async iteration using aiometer
        async def fetch_post(submission):
            """Extract data from a single submission."""
            return await self.extract_post_data(submission)

        # Process submissions with rate limiting
        async with aiometer.amap(
            fetch_post,
            submission_stream,
            max_per_second=self.max_requests_per_second
        ) as results:
            async for post_data in results:
                if post_data:
                    posts.append(post_data)

        logger.info(
            f"Fetched {len(posts)} posts from r/{subreddit_name}",
            extra={
                "subreddit": subreddit_name,
                "count": len(posts),
                "sort": sort
            }
        )

        return posts

    async def extract_post_data(self, submission) -> Dict[str, Any]:
        """
        Extract structured data from a Reddit submission.

        Args:
            submission: Asyncpraw submission object

        Returns:
            Dictionary containing post metadata and content
        """
        try:
            # Ensure we have all attributes loaded
            await submission.load()

            post_data = {
                "id": submission.id,
                "title": submission.title,
                "text": submission.selftext or "",
                "url": submission.url,
                "score": submission.score,
                "upvote_ratio": submission.upvote_ratio,
                "author": str(submission.author) if submission.author else "[deleted]",
                "created_utc": datetime.fromtimestamp(
                    submission.created_utc, tz=timezone.utc
                ).isoformat(),
                "num_comments": submission.num_comments,
                "subreddit": str(submission.subreddit),
                "permalink": f"https://reddit.com{submission.permalink}",
                "is_self": submission.is_self,
                "link_flair_text": submission.link_flair_text,
                "distinguished": submission.distinguished,
                "stickied": submission.stickied,
                "locked": submission.locked,
                "over_18": submission.over_18,
            }

            # Add domain for link posts
            if not submission.is_self and submission.url:
                try:
                    url = URL(submission.url)
                    post_data["domain"] = url.host
                except Exception:
                    post_data["domain"] = None

            return post_data

        except Exception as e:
            logger.error(
                f"Failed to extract post data: {e}",
                extra={"submission_id": getattr(submission, 'id', 'unknown')}
            )
            return {}

    async def fetch_data(self, source: str, **kwargs) -> dict:
        """
        Fetch data from Reddit based on source specification.

        Args:
            source: Subreddit name or Reddit URL
            **kwargs: Additional parameters (limit, time_filter, sort)

        Returns:
            Dictionary containing fetched posts and metadata
        """
        # Parse source to determine fetch type
        if source.startswith("r/") or not source.startswith("http"):
            # It's a subreddit name
            subreddit_name = source.replace("r/", "")
            posts = await self.fetch_subreddit(subreddit_name, **kwargs)

            return {
                "source": f"r/{subreddit_name}",
                "type": "subreddit",
                "posts": posts,
                "count": len(posts),
                "fetched_at": datetime.now(timezone.utc).isoformat()
            }
        else:
            # Handle direct Reddit URLs in future iterations
            raise NotImplementedError("Direct Reddit URL fetching not yet implemented")

    async def filter_relevance(self, data: dict) -> bool:
        """
        Determine if fetched Reddit data is relevant.

        For now, returns True for all data (minimal filtering at crawler level).
        More sophisticated filtering can be added based on investigation context.

        Args:
            data: Fetched Reddit data

        Returns:
            True if relevant, False otherwise
        """
        # Minimal filtering - let downstream agents decide relevance
        if not data.get("posts"):
            return False

        # Could add keyword matching, score thresholds, etc.
        return True

    async def extract_metadata(self, data: dict) -> dict:
        """
        Extract standardized metadata from Reddit data.

        Args:
            data: Fetched Reddit data

        Returns:
            Standardized metadata dictionary
        """
        return {
            "source_url": f"https://reddit.com/{data.get('source', '')}",
            "source_type": "reddit",
            "author": "multiple",  # Multiple authors in subreddit fetch
            "publication_date": None,  # Varies per post
            "retrieval_timestamp": data.get("fetched_at"),
            "post_count": data.get("count", 0),
            "credibility_indicators": {
                "platform": "reddit",
                "is_verified": False,  # Reddit doesn't have platform verification
                "community_size": None,  # Could fetch from subreddit info
            }
        }