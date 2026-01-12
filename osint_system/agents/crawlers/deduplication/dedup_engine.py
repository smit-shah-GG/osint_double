"""Three-layer deduplication engine for article processing.

Implements deduplication at three levels:
1. URL-based deduplication (exact URL matches)
2. Content hash deduplication (exact content matches)
3. Semantic similarity deduplication (similar content detection)
"""

import hashlib
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass, field
import logging
from datetime import datetime

try:
    from semhash import generate_hash, compare_hashes
    SEMHASH_AVAILABLE = True
except ImportError:
    SEMHASH_AVAILABLE = False
    # Fallback implementation
    def generate_hash(text: str) -> str:
        """Fallback: Simple hash generation."""
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def compare_hashes(hash1: str, hash2: str) -> float:
        """Fallback: Basic comparison (exact match only)."""
        return 1.0 if hash1 == hash2 else 0.0


logger = logging.getLogger(__name__)


@dataclass
class DeduplicationStats:
    """Statistics tracking for deduplication process."""
    total_processed: int = 0
    url_duplicates: int = 0
    content_duplicates: int = 0
    semantic_duplicates: int = 0
    unique_articles: int = 0

    def to_dict(self) -> Dict[str, int]:
        """Convert stats to dictionary."""
        return {
            "total_processed": self.total_processed,
            "url_duplicates": self.url_duplicates,
            "content_duplicates": self.content_duplicates,
            "semantic_duplicates": self.semantic_duplicates,
            "unique_articles": self.unique_articles
        }


@dataclass
class Article:
    """Article data structure for deduplication."""
    url: str
    title: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    published_date: Optional[datetime] = None
    source: Optional[str] = None


class DeduplicationEngine:
    """Three-layer deduplication engine for article processing.

    Implements progressive deduplication:
    - Layer 1: URL-based (O(1) lookup using set)
    - Layer 2: Content hash (SHA256 for exact matches)
    - Layer 3: Semantic similarity (SemHash with configurable threshold)
    """

    def __init__(self, semantic_threshold: float = 0.85, enable_stats: bool = True):
        """Initialize deduplication engine.

        Args:
            semantic_threshold: Similarity threshold for semantic deduplication (0.0-1.0)
            enable_stats: Whether to track deduplication statistics
        """
        self.semantic_threshold = semantic_threshold
        self.enable_stats = enable_stats

        # Layer 1: URL tracking
        self.seen_urls: set = set()

        # Layer 2: Content hash tracking
        self.content_hashes: Dict[str, str] = {}  # hash -> first URL

        # Layer 3: Semantic hash tracking
        self.semantic_hashes: Dict[str, Tuple[str, str]] = {}  # sem_hash -> (URL, content)

        # Statistics
        self.stats = DeduplicationStats()

        # Log initialization
        logger.info(f"DeduplicationEngine initialized (semantic_threshold={semantic_threshold}, "
                   f"semhash_available={SEMHASH_AVAILABLE})")
        if not SEMHASH_AVAILABLE:
            # Info level since it's optional
            logger.info("SemHash library not available - using fallback implementation")

    def _compute_content_hash(self, content: str) -> str:
        """Compute SHA256 hash of content.

        Args:
            content: Text content to hash

        Returns:
            Hexadecimal hash string
        """
        # Normalize content: strip whitespace, lowercase
        normalized = content.strip().lower()
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

    def _compute_semantic_hash(self, content: str) -> str:
        """Compute semantic hash of content.

        Args:
            content: Text content to hash

        Returns:
            Semantic hash string
        """
        # Use first 500 chars for semantic hash to optimize performance
        truncated = content[:500] if len(content) > 500 else content
        return generate_hash(truncated)

    def _check_semantic_similarity(self, sem_hash: str, content: str) -> Optional[str]:
        """Check if content is semantically similar to existing articles.

        Args:
            sem_hash: Semantic hash of new content
            content: Full content for comparison

        Returns:
            URL of similar article if found, None otherwise
        """
        for stored_hash, (stored_url, stored_content) in self.semantic_hashes.items():
            similarity = compare_hashes(sem_hash, stored_hash)

            if similarity >= self.semantic_threshold:
                logger.debug(f"Semantic match found: similarity={similarity:.2f}, "
                           f"url={stored_url[:50]}...")
                return stored_url

        return None

    def is_duplicate(self, article: Article) -> Tuple[bool, str]:
        """Check if article is a duplicate using three-layer strategy.

        Args:
            article: Article to check

        Returns:
            Tuple of (is_duplicate, reason)
        """
        # Layer 1: URL-based deduplication
        if article.url in self.seen_urls:
            if self.enable_stats:
                self.stats.url_duplicates += 1
            return True, "url_duplicate"

        # Layer 2: Content hash deduplication
        content_hash = self._compute_content_hash(article.content)
        if content_hash in self.content_hashes:
            if self.enable_stats:
                self.stats.content_duplicates += 1
            original_url = self.content_hashes[content_hash]
            logger.debug(f"Content duplicate detected: {article.url} == {original_url}")
            return True, "content_duplicate"

        # Layer 3: Semantic similarity deduplication
        sem_hash = self._compute_semantic_hash(article.content)
        similar_url = self._check_semantic_similarity(sem_hash, article.content)
        if similar_url:
            if self.enable_stats:
                self.stats.semantic_duplicates += 1
            logger.debug(f"Semantic duplicate detected: {article.url} ~~ {similar_url}")
            return True, "semantic_duplicate"

        # Not a duplicate - store for future comparisons
        self.seen_urls.add(article.url)
        self.content_hashes[content_hash] = article.url
        self.semantic_hashes[sem_hash] = (article.url, article.content[:500])

        return False, "unique"

    def deduplicate_articles(self, articles: List[Article]) -> Tuple[List[Article], DeduplicationStats]:
        """Deduplicate a batch of articles.

        Args:
            articles: List of articles to deduplicate

        Returns:
            Tuple of (unique_articles, statistics)
        """
        unique_articles = []

        if self.enable_stats:
            self.stats.total_processed += len(articles)

        for article in articles:
            is_dup, reason = self.is_duplicate(article)

            if not is_dup:
                unique_articles.append(article)
                if self.enable_stats:
                    self.stats.unique_articles += 1
            else:
                logger.debug(f"Filtered duplicate ({reason}): {article.title[:50]}...")

        logger.info(f"Deduplication complete: {len(unique_articles)}/{len(articles)} unique articles")

        return unique_articles, self.stats

    def reset_stats(self):
        """Reset deduplication statistics."""
        self.stats = DeduplicationStats()

    def clear_cache(self, keep_stats: bool = False):
        """Clear all cached data.

        Args:
            keep_stats: Whether to preserve statistics
        """
        self.seen_urls.clear()
        self.content_hashes.clear()
        self.semantic_hashes.clear()

        if not keep_stats:
            self.reset_stats()

        logger.info("Deduplication cache cleared")