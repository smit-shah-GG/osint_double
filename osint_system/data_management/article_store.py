"""Article storage adapter for persisting fetched articles with investigation-based organization.

Features:
- In-memory storage with optional JSON persistence for beta
- Investigation-based organization (investigation_id as primary key)
- Fast URL-based indexing for duplicate checks
- Timestamp-based retrieval for recent articles
- Thread-safe operations with asyncio locks
"""

import asyncio
import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from pathlib import Path
from loguru import logger


class ArticleStore:
    """
    Storage adapter for article persistence with investigation-based organization.

    For beta: Uses in-memory storage with optional JSON file persistence.
    For production: Would be replaced with database backend.

    Data structure:
    {
        "investigation_id": {
            "metadata": {...},
            "articles": [
                {
                    "url": "...",
                    "title": "...",
                    "content": "...",
                    "published_date": "...",
                    "source": {...},
                    "metadata": {...},
                    "stored_at": "..."
                },
                ...
            ]
        }
    }

    Features:
    - Investigation-scoped article storage
    - Fast URL-based duplicate detection
    - Timestamp-based queries
    - Optional persistence to JSON
    """

    def __init__(self, persistence_path: Optional[str] = None):
        """
        Initialize article store.

        Args:
            persistence_path: Optional path to JSON file for persistence.
                            If None, storage is memory-only.
        """
        self._storage: Dict[str, Dict[str, Any]] = {}
        self._url_index: Dict[str, str] = {}  # url -> investigation_id mapping
        self._lock = asyncio.Lock()
        self.persistence_path = Path(persistence_path) if persistence_path else None
        self.logger = logger.bind(component="ArticleStore")

        # Load from persistence if available
        if self.persistence_path and self.persistence_path.exists():
            self._load_from_file()

        self.logger.info(
            "ArticleStore initialized",
            persistence_enabled=self.persistence_path is not None
        )

    async def save_articles(
        self,
        investigation_id: str,
        articles: List[Dict[str, Any]],
        investigation_metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Save articles for a specific investigation.

        Deduplicates against existing articles in the investigation using URL index.
        Updates existing articles if URL already exists.

        Args:
            investigation_id: Unique investigation identifier
            articles: List of article dictionaries with full metadata
            investigation_metadata: Optional metadata about the investigation

        Returns:
            Dictionary with save statistics:
            - saved: Number of new articles saved
            - updated: Number of existing articles updated
            - duplicates: Number of duplicates skipped
            - total: Total articles in investigation after save
        """
        async with self._lock:
            # Initialize investigation if doesn't exist
            if investigation_id not in self._storage:
                self._storage[investigation_id] = {
                    "metadata": investigation_metadata or {},
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "articles": []
                }

            investigation = self._storage[investigation_id]
            existing_articles = investigation["articles"]

            # Build URL to index mapping for this investigation
            existing_urls = {article["url"]: idx for idx, article in enumerate(existing_articles)}

            saved_count = 0
            updated_count = 0
            duplicate_count = 0

            for article in articles:
                url = article.get("url", "")
                if not url:
                    self.logger.warning("Article missing URL, skipping", article_title=article.get("title"))
                    continue

                # Add storage timestamp
                article_with_timestamp = {
                    **article,
                    "stored_at": datetime.now(timezone.utc).isoformat()
                }

                if url in existing_urls:
                    # Update existing article
                    idx = existing_urls[url]
                    existing_articles[idx] = article_with_timestamp
                    updated_count += 1
                    self.logger.debug(f"Updated article: {url}")
                else:
                    # Add new article
                    existing_articles.append(article_with_timestamp)
                    self._url_index[url] = investigation_id
                    saved_count += 1
                    self.logger.debug(f"Saved new article: {url}")

            # Update investigation metadata
            investigation["updated_at"] = datetime.now(timezone.utc).isoformat()
            investigation["article_count"] = len(existing_articles)

            # Persist if enabled
            if self.persistence_path:
                self._save_to_file()

            stats = {
                "saved": saved_count,
                "updated": updated_count,
                "duplicates": duplicate_count,
                "total": len(existing_articles)
            }

            self.logger.info(
                f"Saved articles for investigation {investigation_id}",
                **stats
            )

            return stats

    async def retrieve_by_investigation(
        self,
        investigation_id: str,
        limit: Optional[int] = None,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Retrieve articles for a specific investigation.

        Args:
            investigation_id: Investigation identifier
            limit: Maximum number of articles to return (None = all)
            offset: Number of articles to skip

        Returns:
            Dictionary with investigation data:
            - investigation_id: ID
            - metadata: Investigation metadata
            - articles: List of articles
            - total_articles: Total count
            - returned_articles: Count of articles in this response
        """
        async with self._lock:
            if investigation_id not in self._storage:
                return {
                    "investigation_id": investigation_id,
                    "metadata": {},
                    "articles": [],
                    "total_articles": 0,
                    "returned_articles": 0
                }

            investigation = self._storage[investigation_id]
            all_articles = investigation["articles"]

            # Apply pagination
            if limit:
                selected_articles = all_articles[offset:offset + limit]
            else:
                selected_articles = all_articles[offset:]

            return {
                "investigation_id": investigation_id,
                "metadata": investigation["metadata"],
                "created_at": investigation.get("created_at"),
                "updated_at": investigation.get("updated_at"),
                "articles": selected_articles,
                "total_articles": len(all_articles),
                "returned_articles": len(selected_articles)
            }

    async def retrieve_recent_articles(
        self,
        investigation_id: str,
        since: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve recent articles from an investigation.

        Args:
            investigation_id: Investigation identifier
            since: ISO timestamp - only return articles stored after this time
            limit: Maximum number of articles to return

        Returns:
            List of articles sorted by stored_at (newest first)
        """
        async with self._lock:
            if investigation_id not in self._storage:
                return []

            articles = self._storage[investigation_id]["articles"]

            # Filter by timestamp if provided
            if since:
                since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
                articles = [
                    a for a in articles
                    if datetime.fromisoformat(a["stored_at"].replace("Z", "+00:00")) > since_dt
                ]

            # Sort by stored_at descending (newest first)
            sorted_articles = sorted(
                articles,
                key=lambda a: a.get("stored_at", ""),
                reverse=True
            )

            # Apply limit
            if limit:
                sorted_articles = sorted_articles[:limit]

            return sorted_articles

    async def check_url_exists(self, url: str) -> Optional[str]:
        """
        Check if a URL exists in any investigation.

        Args:
            url: Article URL to check

        Returns:
            Investigation ID if URL exists, None otherwise
        """
        async with self._lock:
            return self._url_index.get(url)

    async def get_investigation_stats(self, investigation_id: str) -> Dict[str, Any]:
        """
        Get statistics for an investigation.

        Args:
            investigation_id: Investigation identifier

        Returns:
            Dictionary with statistics
        """
        async with self._lock:
            if investigation_id not in self._storage:
                return {
                    "exists": False,
                    "investigation_id": investigation_id
                }

            investigation = self._storage[investigation_id]
            articles = investigation["articles"]

            # Calculate statistics
            source_counts: Dict[str, int] = {}
            for article in articles:
                source_name = article.get("source", {}).get("name", "Unknown")
                source_counts[source_name] = source_counts.get(source_name, 0) + 1

            return {
                "exists": True,
                "investigation_id": investigation_id,
                "total_articles": len(articles),
                "created_at": investigation.get("created_at"),
                "updated_at": investigation.get("updated_at"),
                "source_breakdown": source_counts,
                "metadata": investigation["metadata"]
            }

    async def list_investigations(self) -> List[Dict[str, Any]]:
        """
        List all investigations in the store.

        Returns:
            List of investigation summaries
        """
        async with self._lock:
            investigations = []
            for inv_id, inv_data in self._storage.items():
                investigations.append({
                    "investigation_id": inv_id,
                    "article_count": len(inv_data["articles"]),
                    "created_at": inv_data.get("created_at"),
                    "updated_at": inv_data.get("updated_at"),
                    "metadata": inv_data["metadata"]
                })

            return investigations

    async def delete_investigation(self, investigation_id: str) -> bool:
        """
        Delete an investigation and all its articles.

        Args:
            investigation_id: Investigation identifier

        Returns:
            True if deleted, False if not found
        """
        async with self._lock:
            if investigation_id not in self._storage:
                return False

            # Remove from URL index
            articles = self._storage[investigation_id]["articles"]
            for article in articles:
                url = article.get("url")
                if url and url in self._url_index:
                    del self._url_index[url]

            # Remove investigation
            del self._storage[investigation_id]

            # Persist if enabled
            if self.persistence_path:
                self._save_to_file()

            self.logger.info(f"Deleted investigation: {investigation_id}")
            return True

    def _save_to_file(self) -> None:
        """Save current storage to JSON file (synchronous)."""
        if not self.persistence_path:
            return

        try:
            # Ensure directory exists
            self.persistence_path.parent.mkdir(parents=True, exist_ok=True)

            # Write to file
            with open(self.persistence_path, 'w') as f:
                json.dump(self._storage, f, indent=2)

            self.logger.debug(f"Persisted to {self.persistence_path}")

        except Exception as e:
            self.logger.error(f"Failed to persist to file: {e}", exc_info=True)

    def _load_from_file(self) -> None:
        """Load storage from JSON file (synchronous)."""
        if not self.persistence_path or not self.persistence_path.exists():
            return

        try:
            with open(self.persistence_path, 'r') as f:
                self._storage = json.load(f)

            # Rebuild URL index
            self._url_index = {}
            for inv_id, inv_data in self._storage.items():
                for article in inv_data.get("articles", []):
                    url = article.get("url")
                    if url:
                        self._url_index[url] = inv_id

            self.logger.info(
                f"Loaded from {self.persistence_path}",
                investigations=len(self._storage),
                articles=len(self._url_index)
            )

        except Exception as e:
            self.logger.error(f"Failed to load from file: {e}", exc_info=True)
            self._storage = {}
            self._url_index = {}

    async def get_storage_stats(self) -> Dict[str, Any]:
        """
        Get overall storage statistics.

        Returns:
            Dictionary with storage statistics
        """
        async with self._lock:
            total_articles = sum(
                len(inv["articles"])
                for inv in self._storage.values()
            )

            return {
                "total_investigations": len(self._storage),
                "total_articles": total_articles,
                "unique_urls": len(self._url_index),
                "persistence_enabled": self.persistence_path is not None,
                "persistence_path": str(self.persistence_path) if self.persistence_path else None
            }
