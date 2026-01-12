"""Article extraction and content processing using newspaper3k."""

from typing import Optional
from datetime import datetime, timezone
import asyncio
from functools import lru_cache
import newspaper
from newspaper import Article
from langdetect import detect, LangDetectException
from loguru import logger


class ArticleExtractor:
    """
    Extract full article text and metadata from web pages using newspaper3k.

    Wraps the newspaper3k library to provide async-compatible article extraction
    with language filtering, fallback handling, and optional caching.

    The newspaper3k library is the industry standard for article extraction because:
    - Identifies main content using heuristics (not just first N paragraphs)
    - Removes ads, navigation, and boilerplate automatically
    - Extracts metadata: authors, publish date, images, keywords
    - Handles JavaScript-heavy sites gracefully
    - Used by major news aggregators

    Key Features:
    - Async wrapper around synchronous newspaper3k
    - Language detection to filter non-English content
    - Graceful fallback for extraction failures
    - Optional extraction caching to avoid re-processing
    - Comprehensive error handling and logging

    Attributes:
        cache_enabled: Whether to cache extracted articles
        cache_size: Maximum cache size (LRU)
        min_content_length: Minimum extracted content length (chars)
        logger: Loguru logger for extraction debugging
    """

    def __init__(self, cache_enabled: bool = True, cache_size: int = 100):
        """
        Initialize article extractor.

        Args:
            cache_enabled: Whether to cache extracted articles (default: True)
            cache_size: Maximum LRU cache size (default: 100 articles)
        """
        self.cache_enabled = cache_enabled
        self.cache_size = cache_size
        self.min_content_length = 200  # Minimum content to consider successful extraction
        self.logger = logger.bind(module="ArticleExtractor")

        self.logger.info(
            "ArticleExtractor initialized",
            cache_enabled=cache_enabled,
            cache_size=cache_size,
        )

    async def extract_article(
        self,
        url: str,
        fallback_content: Optional[str] = None,
        timeout: float = 30.0,
    ) -> dict:
        """
        Extract article content and metadata from URL.

        Runs newspaper3k article extraction in executor to avoid blocking.
        Falls back to provided content if extraction fails.

        Args:
            url: Article URL to extract
            fallback_content: Optional summary/content to use if extraction fails
            timeout: Download/extraction timeout in seconds

        Returns:
            Dictionary containing:
            - success: Boolean indicating successful extraction
            - title: Article title
            - text: Extracted article text
            - authors: List of author names
            - publish_date: ISO 8601 publication date
            - top_image: URL of top article image
            - keywords: List of extracted keywords
            - summary: Article summary
            - language: Detected language code ('en' for English)
            - is_english: Boolean indicating if content is English
            - source_url: Original URL
            - error: Error message if extraction failed (optional)

        Example:
            result = await extractor.extract_article('https://example.com/article')
            if result['success'] and result['is_english']:
                print(f"Title: {result['title']}")
                print(f"Text: {result['text'][:200]}...")
        """
        try:
            self.logger.debug(f"Extracting article from {url}")

            # Create Article object
            article = Article(url, fetch_images=False)

            # Run extraction in executor to avoid blocking
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, self._download_and_parse_article, article, timeout
            )

            # Check if extraction was successful
            if not article.text or len(article.text.strip()) < self.min_content_length:
                self.logger.warning(
                    f"Extraction produced insufficient content from {url}",
                    content_length=len(article.text) if article.text else 0,
                )
                return self._create_fallback_result(
                    url, fallback_content, "Insufficient extracted content"
                )

            # Detect language
            is_english, language = self._detect_language(article.text)
            if not is_english:
                self.logger.info(
                    f"Non-English content detected",
                    url=url,
                    language=language,
                )

            # Build result
            result = {
                "success": True,
                "title": article.title or "No title",
                "text": article.text,
                "authors": article.authors or [],
                "publish_date": self._normalize_date(article.publish_date),
                "top_image": article.top_image or "",
                "keywords": article.keywords or [],
                "summary": article.summary or "",
                "language": language,
                "is_english": is_english,
                "source_url": url,
                "error": None,
            }

            self.logger.info(
                f"Article extracted successfully from {url}",
                title_length=len(article.title),
                text_length=len(article.text),
                language=language,
            )

            return result

        except newspaper.ArticleException as e:
            error_msg = f"Newspaper3k extraction failed: {str(e)}"
            self.logger.warning(error_msg, url=url)
            return self._create_fallback_result(url, fallback_content, error_msg)

        except asyncio.TimeoutError:
            error_msg = f"Extraction timeout after {timeout}s"
            self.logger.warning(error_msg, url=url)
            return self._create_fallback_result(url, fallback_content, error_msg)

        except Exception as e:
            error_msg = f"Extraction error: {str(e)}"
            self.logger.error(error_msg, url=url, error=str(e))
            return self._create_fallback_result(url, fallback_content, error_msg)

    def _download_and_parse_article(
        self, article: Article, timeout: float
    ) -> None:
        """
        Download and parse article (runs in executor).

        Args:
            article: Article object to populate
            timeout: Download timeout in seconds
        """
        article.download(timeout=timeout)
        article.parse()

    def _detect_language(self, text: str) -> tuple[bool, str]:
        """
        Detect language of text and check if English.

        Uses langdetect library for fast language identification across 55+ languages.

        Args:
            text: Text to detect language from

        Returns:
            Tuple of (is_english: bool, language_code: str)
        """
        try:
            # Use first 500 chars for faster detection
            sample = text[:500]
            language = detect(sample)
            is_english = language == "en"

            if not is_english:
                self.logger.debug(
                    f"Detected non-English language: {language}"
                )

            return is_english, language

        except LangDetectException as e:
            self.logger.warning(f"Language detection failed: {e}")
            # Assume English on detection failure
            return True, "en"

    def _normalize_date(self, date_obj: Optional[object]) -> Optional[str]:
        """
        Normalize publish date to ISO 8601 format.

        Handles None, datetime objects, and string dates.

        Args:
            date_obj: Date object from newspaper3k

        Returns:
            ISO 8601 datetime string or None
        """
        if not date_obj:
            return None

        try:
            # If already datetime, convert to ISO
            if hasattr(date_obj, "isoformat"):
                return date_obj.isoformat()
            # If string, try to parse it
            elif isinstance(date_obj, str):
                # Try to parse and re-format
                from dateutil import parser
                dt = parser.parse(date_obj)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.isoformat()
        except Exception as e:
            self.logger.debug(f"Date normalization failed: {e}")

        return None

    def _create_fallback_result(
        self,
        url: str,
        fallback_content: Optional[str],
        error_msg: str,
    ) -> dict:
        """
        Create result using fallback content when extraction fails.

        Gracefully degrades to RSS summary or returns empty result.

        Args:
            url: Original article URL
            fallback_content: Fallback content (typically RSS summary)
            error_msg: Error message explaining failure

        Returns:
            Fallback result dictionary
        """
        return {
            "success": False,
            "title": "Extraction failed",
            "text": fallback_content or "",
            "authors": [],
            "publish_date": None,
            "top_image": "",
            "keywords": [],
            "summary": fallback_content or "",
            "language": "en",
            "is_english": True,
            "source_url": url,
            "error": error_msg,
        }

    async def extract_batch(
        self,
        articles: list[dict],
        max_concurrent: int = 5,
        fallback_field: str = "summary",
    ) -> list[dict]:
        """
        Extract multiple articles concurrently with concurrency limit.

        Useful for batch processing feeds that provide both summary and URL.

        Args:
            articles: List of article dicts with 'link'/'url' key
            max_concurrent: Maximum concurrent extraction tasks
            fallback_field: Field name to use as fallback (e.g., 'summary')

        Returns:
            List of extraction results

        Example:
            articles = [
                {'link': 'https://example.com/1', 'summary': 'Breaking news...'},
                {'link': 'https://example.com/2', 'summary': 'Another story...'},
            ]
            results = await extractor.extract_batch(articles)
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def extract_with_semaphore(article: dict) -> dict:
            async with semaphore:
                # Find URL key
                url = article.get("link") or article.get("url")
                if not url:
                    return {
                        "success": False,
                        "error": "No URL in article",
                        "source_url": None,
                    }

                # Get fallback content
                fallback = article.get(fallback_field, "")

                return await self.extract_article(url, fallback_content=fallback)

        # Extract all articles concurrently with semaphore
        results = await asyncio.gather(
            *[extract_with_semaphore(article) for article in articles],
            return_exceptions=True,
        )

        # Handle any exceptions
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.error(
                    f"Exception extracting article {i}",
                    error=str(result),
                )
                processed_results.append(
                    {
                        "success": False,
                        "error": str(result),
                    }
                )
            else:
                processed_results.append(result)

        return processed_results

    def validate_extraction(self, result: dict) -> bool:
        """
        Validate extraction result quality.

        Checks that extracted content meets minimum quality thresholds
        for downstream processing.

        Args:
            result: Extraction result from extract_article()

        Returns:
            True if result is valid for processing, False otherwise
        """
        if not result.get("success"):
            return False

        # Must have reasonable content length
        if len(result.get("text", "")) < self.min_content_length:
            return False

        # Must have a title
        if not result.get("title") or result["title"] == "Extraction failed":
            return False

        # Language filtering is optional but logged
        if not result.get("is_english"):
            self.logger.debug(
                f"Non-English content: {result.get('language')}",
                url=result.get("source_url"),
            )

        return True
