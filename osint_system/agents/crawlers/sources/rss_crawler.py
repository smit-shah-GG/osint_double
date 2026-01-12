"""RSS/Atom feed parser and normalizer using feedparser."""

from typing import Optional, Any
from datetime import datetime, timezone
import feedparser
from dateutil import parser as dateutil_parser
from loguru import logger


class RSSCrawler:
    """
    Parse and normalize RSS/Atom feeds using feedparser.

    Handles all RSS variants (0.91, 1.0, 2.0) and Atom feeds through
    feedparser's normalization. Automatically detects and corrects encoding
    issues, provides graceful fallbacks for malformed feeds, and normalizes
    dates to ISO 8601 format.

    The feedparser library is the industry standard for feed parsing because:
    - Handles 20+ years of real-world RSS/Atom variants
    - Automatically detects and corrects encoding issues
    - Normalizes inconsistent feed structures to common format
    - Graceful degradation for malformed feeds (continues on errors)
    - Used by major aggregators (Google News, Feedly, etc.)

    Attributes:
        logger: Loguru logger for debugging feed parsing issues
    """

    def __init__(self):
        """Initialize RSS crawler."""
        # Configure feedparser for maximum compatibility
        feedparser._PREFERRED_XML_PARSERS = []  # Use fastest available parser
        feedparser.RESOLVE_RELATIVE_URIS = False  # Don't modify URLs
        feedparser.SANITIZE_HTML = False  # Preserve original content
        self.logger = logger.bind(module="RSSCrawler")
        self.logger.debug("RSSCrawler initialized")

    async def parse_feed(self, feed_url_or_content: str) -> dict:
        """
        Parse RSS/Atom feed from URL or content string.

        Feedparser handles the detection and parsing of all feed formats
        automatically. Supports:
        - RSS 0.91, 0.92, 2.0
        - RDF/RSS 1.0
        - Atom 0.3, 1.0
        - CDF, OPML
        - Invalid/malformed feeds (returns what can be parsed)

        Args:
            feed_url_or_content: Either a URL string or raw feed content

        Returns:
            Dictionary containing:
            - success: Boolean indicating if parsing succeeded
            - feed_title: Extracted feed title
            - feed_link: Feed homepage URL
            - feed_description: Feed description
            - entries: List of parsed feed entries
            - error: Error message if parsing failed (optional)
            - parsing_errors: Any warnings during parsing (optional)

        Example:
            # Parse from URL
            result = await crawler.parse_feed('http://feeds.bbci.co.uk/news/rss.xml')

            # Parse from content
            with open('feed.xml') as f:
                result = await crawler.parse_feed(f.read())
        """
        try:
            self.logger.debug(
                "Parsing feed",
                content_length=len(feed_url_or_content)
                if isinstance(feed_url_or_content, str)
                else "url",
            )

            # feedparser.parse() handles both URLs and content
            parsed = feedparser.parse(feed_url_or_content)

            # Check for critical parsing errors
            if parsed.bozo and parsed.bozo_exception:
                self.logger.warning(
                    "Feed parsing had issues (may still be partially valid)",
                    exception=str(parsed.bozo_exception),
                    bozo=parsed.bozo,
                )

            # Extract feed-level metadata
            feed_info = {
                "success": len(parsed.entries) > 0 or parsed.bozo == False,
                "feed_title": parsed.feed.get("title", "Unknown Feed"),
                "feed_link": parsed.feed.get("link", ""),
                "feed_description": parsed.feed.get("description", ""),
                "entries": [],
                "encoding": parsed.encoding,
                "bozo": parsed.bozo,
            }

            # Extract entries with normalized metadata
            for entry in parsed.entries:
                normalized_entry = self._normalize_entry(entry, feed_info["feed_title"])
                feed_info["entries"].append(normalized_entry)

            self.logger.info(
                "Feed parsed successfully",
                title=feed_info["feed_title"],
                entry_count=len(feed_info["entries"]),
                encoding=parsed.encoding,
            )

            return feed_info

        except Exception as e:
            error_msg = f"Failed to parse feed: {str(e)}"
            self.logger.error(error_msg, error=str(e))
            return {
                "success": False,
                "feed_title": None,
                "feed_link": None,
                "feed_description": None,
                "entries": [],
                "error": error_msg,
            }

    def _normalize_entry(self, entry: dict, feed_title: str) -> dict:
        """
        Normalize feed entry to consistent schema.

        Extracts common fields and normalizes their formats regardless of
        RSS version or Atom variant used. Handles missing fields gracefully
        with appropriate defaults.

        Args:
            entry: Raw feedparser entry dictionary
            feed_title: Parent feed title for context

        Returns:
            Normalized entry dictionary with:
            - title: Article title
            - link: Article URL
            - published_date: ISO 8601 timestamp
            - summary: Article summary/description
            - author: Article author
            - source: Feed source name
            - tags: List of category/tag strings
            - content: Full content if available
            - id: Unique entry ID
        """
        try:
            # Extract and normalize title
            title = entry.get("title", "No title")

            # Extract link (handle multiple variations)
            link = entry.get("link", "")
            if not link and "links" in entry:
                # Some feeds use links array
                for link_obj in entry.get("links", []):
                    if link_obj.get("rel") in ["alternate", None]:
                        link = link_obj.get("href", "")
                        if link:
                            break

            # Extract and normalize publication date
            published_date = self._parse_date(entry)

            # Extract summary (handles various field names)
            summary = entry.get("summary", "")
            if not summary:
                summary = entry.get("description", "")

            # Extract author
            author = ""
            if "author" in entry:
                author = entry.get("author", "")
            elif "author_detail" in entry:
                author = entry.get("author_detail", {}).get("name", "")

            # Extract tags/categories
            tags = []
            if "tags" in entry:
                tags = [tag.get("term", "") for tag in entry.get("tags", [])]
            elif "category" in entry:
                tags = [entry.get("category", "")]

            # Extract full content if available
            content = ""
            if "content" in entry:
                content_list = entry.get("content", [])
                if content_list and isinstance(content_list, list):
                    content = content_list[0].get("value", "")

            # Generate unique ID
            entry_id = entry.get("id", link or title)

            return {
                "title": title,
                "link": link,
                "published_date": published_date,
                "summary": summary,
                "author": author,
                "source": feed_title,
                "tags": [t for t in tags if t],  # Filter empty strings
                "content": content,
                "id": entry_id,
            }

        except Exception as e:
            self.logger.error("Error normalizing entry", error=str(e))
            return {
                "title": entry.get("title", "Parse error"),
                "link": entry.get("link", ""),
                "published_date": None,
                "summary": "",
                "author": "",
                "source": feed_title,
                "tags": [],
                "content": "",
                "id": "",
            }

    def _parse_date(self, entry: dict) -> Optional[str]:
        """
        Parse and normalize publication date from feed entry.

        Handles various date formats found in RSS/Atom feeds:
        - RFC 2822 (RSS 2.0 default): "Mon, 06 Sep 2021 00:01:00 +0000"
        - ISO 8601 (Atom default): "2021-09-06T00:01:00Z"
        - Unix timestamp: 1630880460
        - Various other formats

        Uses dateutil.parser for robust parsing across formats.

        Args:
            entry: Feed entry dictionary with potential date fields

        Returns:
            ISO 8601 formatted datetime string, or None if unparseable
        """
        # Try standard feedparser date field first
        if "published_parsed" in entry and entry.get("published_parsed"):
            try:
                dt = datetime(*entry["published_parsed"][:6], tzinfo=timezone.utc)
                return dt.isoformat()
            except (TypeError, ValueError):
                pass

        # Fallback to other date fields
        date_sources = [
            entry.get("published"),
            entry.get("updated"),
            entry.get("date"),
        ]

        for date_str in date_sources:
            if not date_str:
                continue
            try:
                # dateutil.parser handles most common formats
                dt = dateutil_parser.parse(date_str)
                # Ensure timezone-aware
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.isoformat()
            except (ValueError, TypeError, AttributeError):
                continue

        self.logger.debug(
            "Could not parse date for entry",
            title=entry.get("title", "Unknown"),
        )
        return None

    def get_feed_metadata(self, parsed_feed: dict) -> dict:
        """
        Extract feed-level metadata for source credibility assessment.

        Provides information useful for evaluating source credibility and
        deduplication.

        Args:
            parsed_feed: Result from parse_feed()

        Returns:
            Dictionary containing:
            - title: Feed title
            - link: Feed homepage
            - description: Feed description
            - entry_count: Number of parsed entries
            - encoding: Detected encoding
            - was_malformed: Whether feed had parsing issues
        """
        return {
            "title": parsed_feed.get("feed_title", "Unknown"),
            "link": parsed_feed.get("feed_link", ""),
            "description": parsed_feed.get("feed_description", ""),
            "entry_count": len(parsed_feed.get("entries", [])),
            "encoding": parsed_feed.get("encoding", "unknown"),
            "was_malformed": parsed_feed.get("bozo", False),
        }
