#!/usr/bin/env python3
"""Example script demonstrating the extended crawler cohort in action.

This script shows how the crawler cohort works together to investigate
a topic, coordinating through the message bus and sharing discoveries.

Usage:
    uv run python examples/run_extended_investigation.py "topic to investigate"
    uv run python examples/run_extended_investigation.py "Ukraine conflict"

The script demonstrates:
1. MessageBus initialization for crawler coordination
2. PlanningAgent decomposing the objective into subtasks
3. Multiple crawlers (Reddit, Document, Web) working in parallel
4. URLManager preventing duplicate fetches
5. AuthorityScorer ranking sources by credibility
6. ContextCoordinator sharing discovered entities
7. Results aggregation with authority scores
"""

import argparse
import asyncio
import sys
from datetime import datetime
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

# Configure logging before other imports
import structlog

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.dev.ConsoleRenderer(colors=True),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


async def run_investigation_demo(topic: str, use_real_apis: bool = False):
    """
    Run a demonstration investigation with the extended crawler cohort.

    Args:
        topic: The investigation topic/query
        use_real_apis: If True, attempt real API calls (requires credentials)
                       If False (default), use mocked responses
    """
    logger.info("Starting extended investigation demo", topic=topic)

    # Import components
    from osint_system.agents.communication.bus import MessageBus
    from osint_system.agents.crawlers.coordination.url_manager import URLManager
    from osint_system.agents.crawlers.coordination.authority_scorer import AuthorityScorer
    from osint_system.agents.crawlers.coordination.context_coordinator import ContextCoordinator

    # Reset and create shared infrastructure
    MessageBus.reset_singleton()
    message_bus = MessageBus()
    url_manager = URLManager()
    authority_scorer = AuthorityScorer()
    context_coordinator = ContextCoordinator(message_bus=message_bus, enable_broadcast=True)

    # Track crawler results
    all_results = {
        "reddit": [],
        "document": [],
        "web": [],
        "news": [],
    }

    # Track completion messages
    completion_events = []

    async def track_completion(msg):
        """Track crawler completion messages."""
        completion_events.append(msg)
        logger.info(
            "Crawler completed",
            crawler=msg.get("payload", {}).get("agent"),
            count=msg.get("payload", {}).get("article_count", 0),
        )

    # Subscribe to completion messages
    message_bus.subscribe_to_pattern(
        subscriber_name="demo_tracker",
        pattern="crawler.complete",
        callback=track_completion,
    )

    # Create investigation ID
    import hashlib
    investigation_id = hashlib.md5(topic.encode()).hexdigest()[:16]

    logger.info("Investigation initialized", investigation_id=investigation_id)

    # Simulate crawler results (or use real APIs if enabled)
    if not use_real_apis:
        logger.info("Using mocked crawler responses (set --real-apis to use actual APIs)")
        results = await run_mocked_crawlers(
            topic=topic,
            investigation_id=investigation_id,
            message_bus=message_bus,
            url_manager=url_manager,
            authority_scorer=authority_scorer,
            context_coordinator=context_coordinator,
        )
    else:
        logger.info("Using real API calls (may require credentials)")
        results = await run_real_crawlers(
            topic=topic,
            investigation_id=investigation_id,
            message_bus=message_bus,
            url_manager=url_manager,
            authority_scorer=authority_scorer,
            context_coordinator=context_coordinator,
        )

    # Wait for message propagation
    await asyncio.sleep(0.2)

    # Print results summary
    print_results_summary(
        results=results,
        investigation_id=investigation_id,
        url_manager=url_manager,
        authority_scorer=authority_scorer,
        context_coordinator=context_coordinator,
    )

    # Cleanup
    MessageBus.reset_singleton()

    logger.info("Investigation demo complete")


async def run_mocked_crawlers(
    topic: str,
    investigation_id: str,
    message_bus,
    url_manager,
    authority_scorer,
    context_coordinator,
) -> dict:
    """Run crawlers with mocked responses for demonstration."""

    results = {
        "reddit_posts": [],
        "documents": [],
        "web_pages": [],
        "entities_discovered": [],
    }

    logger.info("Running mocked crawler cohort")

    # Extract keywords from topic
    keywords = [w.lower() for w in topic.split() if len(w) > 3]

    # Simulate Reddit posts
    mock_reddit_posts = [
        {
            "id": "reddit_1",
            "title": f"Discussion: {topic} latest developments",
            "url": f"https://reddit.com/r/worldnews/comments/abc123/{topic.lower().replace(' ', '_')}",
            "score": 1500,
            "num_comments": 245,
            "subreddit": "worldnews",
            "author": "informed_citizen",
            "content": f"Here's a summary of the latest {topic} developments...",
        },
        {
            "id": "reddit_2",
            "title": f"Analysis: Understanding the {topic}",
            "url": f"https://reddit.com/r/geopolitics/comments/def456/analysis_{topic.lower().replace(' ', '_')}",
            "score": 890,
            "num_comments": 156,
            "subreddit": "geopolitics",
            "author": "policy_analyst",
            "content": f"In-depth analysis of {topic} implications...",
        },
    ]

    for post in mock_reddit_posts:
        # Add to URL manager (check deduplication)
        if url_manager.add_url(post["url"], investigation_id):
            # Calculate authority score
            score = authority_scorer.calculate_score(
                post["url"],
                metadata={
                    "engagement_metrics": {
                        "score": post["score"],
                        "comments": post["num_comments"],
                    }
                },
            )
            post["authority_score"] = score
            results["reddit_posts"].append(post)

            logger.debug(
                "Reddit post collected",
                title=post["title"][:50],
                authority_score=f"{score:.2f}",
            )

    # Simulate document discoveries
    mock_documents = [
        {
            "url": f"https://un.org/reports/{topic.lower().replace(' ', '-')}-assessment.pdf",
            "title": f"UN Assessment: {topic}",
            "document_type": "pdf",
            "source": "United Nations",
            "content": f"Official UN assessment of {topic} situation...",
        },
        {
            "url": f"https://state.gov/reports/{topic.lower().replace(' ', '-')}.html",
            "title": f"State Department Report on {topic}",
            "document_type": "web",
            "source": "US State Department",
            "content": f"Department analysis of {topic}...",
        },
    ]

    for doc in mock_documents:
        if url_manager.add_url(doc["url"], investigation_id):
            score = authority_scorer.calculate_score(doc["url"])
            doc["authority_score"] = score
            results["documents"].append(doc)

            logger.debug(
                "Document collected",
                source=doc["source"],
                authority_score=f"{score:.2f}",
            )

    # Simulate news article discoveries
    mock_news = [
        {
            "url": f"https://reuters.com/world/{topic.lower().replace(' ', '-')}-update",
            "title": f"Reuters: {topic} Update",
            "source": "Reuters",
            "content": f"Breaking news on {topic}...",
        },
        {
            "url": f"https://bbc.com/news/{topic.lower().replace(' ', '-')}",
            "title": f"BBC: {topic} Coverage",
            "source": "BBC",
            "content": f"Comprehensive coverage of {topic}...",
        },
    ]

    for article in mock_news:
        if url_manager.add_url(article["url"], investigation_id):
            score = authority_scorer.calculate_score(article["url"])
            article["authority_score"] = score
            results["web_pages"].append(article)

            logger.debug(
                "News article collected",
                source=article["source"],
                authority_score=f"{score:.2f}",
            )

    # Share discovered entities via context coordinator
    entities_to_share = [
        {"entity": topic, "entity_type": "topic"},
    ]

    # Extract potential entities from topic
    for word in keywords:
        if word.istitle() or len(word) > 5:
            entities_to_share.append({"entity": word, "entity_type": "keyword"})

    for entity_info in entities_to_share:
        await context_coordinator.share_discovery(
            entity=entity_info["entity"],
            entity_type=entity_info["entity_type"],
            source_url=f"https://example.com/{entity_info['entity']}",
            source_crawler="DemoCrawler",
            investigation_id=investigation_id,
            context=f"Entity discovered during {topic} investigation",
        )
        results["entities_discovered"].append(entity_info["entity"])

    # Publish completion message
    await message_bus.publish(
        "crawler.complete",
        {
            "agent": "DemoCrawler",
            "investigation_id": investigation_id,
            "article_count": len(results["reddit_posts"]) + len(results["documents"]) + len(results["web_pages"]),
            "entity_count": len(results["entities_discovered"]),
        },
    )

    return results


async def run_real_crawlers(
    topic: str,
    investigation_id: str,
    message_bus,
    url_manager,
    authority_scorer,
    context_coordinator,
) -> dict:
    """Run crawlers with real API calls (requires credentials)."""

    results = {
        "reddit_posts": [],
        "documents": [],
        "web_pages": [],
        "entities_discovered": [],
    }

    logger.warning(
        "Real API mode selected - this requires configured credentials",
        reddit="REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET",
        newsapi="NEWS_API_KEY",
    )

    # Import crawlers
    from osint_system.agents.crawlers.social_media_agent import RedditCrawler
    from osint_system.agents.crawlers.document_scraper_agent import DocumentCrawler
    from osint_system.agents.crawlers.web_crawler import HybridWebCrawler

    keywords = [w for w in topic.split() if len(w) > 3]

    # Try Reddit crawler
    try:
        logger.info("Attempting Reddit crawl...")
        reddit_crawler = RedditCrawler(message_bus=message_bus)
        async with reddit_crawler:
            reddit_result = await reddit_crawler.crawl_investigation(
                investigation_id=investigation_id,
                keywords=keywords,
                limit_per_subreddit=10,
            )

            for post in reddit_result.get("posts", []):
                if url_manager.add_url(post["permalink"], investigation_id):
                    score = authority_scorer.calculate_score(
                        post["permalink"],
                        metadata={
                            "engagement_metrics": {
                                "score": post.get("score", 0),
                                "comments": post.get("num_comments", 0),
                            }
                        },
                    )
                    post["authority_score"] = score
                    results["reddit_posts"].append(post)

            logger.info("Reddit crawl complete", posts=len(results["reddit_posts"]))

    except Exception as e:
        logger.warning(f"Reddit crawl failed: {e}")

    # Try web crawler for news sites
    try:
        logger.info("Attempting web crawl...")
        web_crawler = HybridWebCrawler(message_bus=message_bus, use_playwright=False)

        # Fetch from known news URLs
        news_urls = [
            f"https://news.google.com/search?q={topic.replace(' ', '+')}",
        ]

        for url in news_urls:
            result = await web_crawler.fetch(url)
            if result.get("success"):
                if url_manager.add_url(url, investigation_id):
                    score = authority_scorer.calculate_score(url)
                    results["web_pages"].append({
                        "url": url,
                        "authority_score": score,
                        "content_length": len(result.get("html", "")),
                    })

        await web_crawler.close()
        logger.info("Web crawl complete", pages=len(results["web_pages"]))

    except Exception as e:
        logger.warning(f"Web crawl failed: {e}")

    # Publish completion
    await message_bus.publish(
        "crawler.complete",
        {
            "agent": "RealCrawlers",
            "investigation_id": investigation_id,
            "article_count": len(results["reddit_posts"]) + len(results["web_pages"]),
        },
    )

    return results


def print_results_summary(
    results: dict,
    investigation_id: str,
    url_manager,
    authority_scorer,
    context_coordinator,
):
    """Print a formatted summary of investigation results."""

    print("\n" + "=" * 70)
    print(f"INVESTIGATION RESULTS: {investigation_id}")
    print("=" * 70)

    # URL Manager stats
    print(f"\nURL DEDUPLICATION:")
    print(f"  Unique URLs collected: {url_manager.get_url_count(investigation_id)}")

    # Reddit posts
    reddit_posts = results.get("reddit_posts", [])
    if reddit_posts:
        print(f"\nREDDIT POSTS ({len(reddit_posts)}):")
        # Sort by authority score
        sorted_posts = sorted(reddit_posts, key=lambda x: x.get("authority_score", 0), reverse=True)
        for post in sorted_posts[:5]:
            print(f"  [{post.get('authority_score', 0):.2f}] {post.get('title', 'Untitled')[:60]}")
            print(f"         r/{post.get('subreddit', 'unknown')} | Score: {post.get('score', 0)}")

    # Documents
    documents = results.get("documents", [])
    if documents:
        print(f"\nDOCUMENTS ({len(documents)}):")
        sorted_docs = sorted(documents, key=lambda x: x.get("authority_score", 0), reverse=True)
        for doc in sorted_docs[:5]:
            print(f"  [{doc.get('authority_score', 0):.2f}] {doc.get('title', 'Untitled')[:60]}")
            print(f"         Source: {doc.get('source', 'Unknown')}")

    # Web pages
    web_pages = results.get("web_pages", [])
    if web_pages:
        print(f"\nNEWS/WEB PAGES ({len(web_pages)}):")
        sorted_pages = sorted(web_pages, key=lambda x: x.get("authority_score", 0), reverse=True)
        for page in sorted_pages[:5]:
            print(f"  [{page.get('authority_score', 0):.2f}] {page.get('title', page.get('url', 'Untitled'))[:60]}")
            print(f"         Source: {page.get('source', 'Web')}")

    # Context coordinator stats
    entities = context_coordinator.get_investigation_entities(investigation_id)
    print(f"\nDISCOVERED ENTITIES ({len(entities)}):")
    for entity in list(entities)[:10]:
        sources = context_coordinator.get_related_sources(entity)
        print(f"  - {entity} (mentioned in {len(sources)} sources)")

    # Authority score distribution
    all_scores = []
    for post in reddit_posts:
        all_scores.append(("Reddit", post.get("authority_score", 0)))
    for doc in documents:
        all_scores.append(("Document", doc.get("authority_score", 0)))
    for page in web_pages:
        all_scores.append(("News/Web", page.get("authority_score", 0)))

    if all_scores:
        print(f"\nAUTHORITY SCORE SUMMARY:")
        avg_score = sum(s[1] for s in all_scores) / len(all_scores)
        max_score = max(s[1] for s in all_scores)
        min_score = min(s[1] for s in all_scores)
        print(f"  Average: {avg_score:.2f}")
        print(f"  Highest: {max_score:.2f}")
        print(f"  Lowest:  {min_score:.2f}")

    print("\n" + "=" * 70)


def main():
    """Main entry point for the example script."""
    parser = argparse.ArgumentParser(
        description="Run an extended crawler cohort investigation demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    uv run python examples/run_extended_investigation.py "Ukraine conflict"
    uv run python examples/run_extended_investigation.py "climate change policy" --real-apis
        """,
    )

    parser.add_argument(
        "topic",
        help="Investigation topic/query",
    )

    parser.add_argument(
        "--real-apis",
        action="store_true",
        help="Use real API calls (requires credentials)",
    )

    args = parser.parse_args()

    # Run the investigation
    asyncio.run(run_investigation_demo(
        topic=args.topic,
        use_real_apis=args.real_apis,
    ))


if __name__ == "__main__":
    main()
