"""SQLAlchemy ORM model for articles (crawled source documents).

Maps to the ``articles`` table in PostgreSQL. Uses hybrid column+JSONB
pattern: top-level queryable fields as proper columns, nested objects
(source metadata, article metadata) as JSONB.

Includes pgvector embedding column (1024 dims for gte-large-en-v1.5)
and a tsvector computed column with GIN index for full-text search
on title + content.

The ``from_dict``/``to_dict`` methods preserve the exact dict shape
that ArticleStore currently returns, ensuring zero-breakage migration.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from osint_system.data_management.models.base import Base, TimestampMixin


class ArticleModel(TimestampMixin, Base):
    """ORM model for the ``articles`` table.

    Stores crawled articles with full metadata. Each article is scoped
    to an investigation and deduplicated by URL (via ``article_id`` which
    is a hash of the URL).

    JSONB columns store nested source and metadata dicts verbatim,
    preserving the full structure from crawler output without
    normalizing into separate tables.
    """

    __tablename__ = "articles"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # Business keys
    article_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True,
    )
    investigation_id: Mapped[str] = mapped_column(
        String(64), index=True,
    )

    # Core content columns
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    published_date: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True,
    )
    source_name: Mapped[Optional[str]] = mapped_column(
        String(256), nullable=True,
    )
    source_domain: Mapped[Optional[str]] = mapped_column(
        String(256), nullable=True,
    )
    stored_at: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True,
    )

    # Nested objects as JSONB
    source_metadata: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
    )
    article_metadata: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
    )

    # pgvector embedding (1024 dims for gte-large-en-v1.5)
    embedding = mapped_column(Vector(768), nullable=True)

    # tsvector for full-text search (generated column)
    content_tsvector = mapped_column(
        TSVECTOR(),
        Computed(
            "to_tsvector('english', COALESCE(title, '') || ' ' || COALESCE(content, ''))",
            persisted=True,
        ),
        nullable=True,
    )

    __table_args__ = (
        Index(
            "ix_articles_content_fts",
            "content_tsvector",
            postgresql_using="gin",
        ),
    )

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], investigation_id: str,
    ) -> ArticleModel:
        """Create an ArticleModel from an ArticleStore dict.

        The ArticleStore dict shape (per article_store.py):
        {
            "url": "...",
            "title": "...",
            "content": "...",
            "published_date": "...",
            "source": {"name": "...", "domain": "..."},
            "metadata": {...},
            "stored_at": "..."
        }

        Generates ``article_id`` as SHA256 of the URL for deduplication.

        Args:
            data: Article dict from ArticleStore format.
            investigation_id: Investigation scope identifier.

        Returns:
            Populated ArticleModel instance (not yet added to a session).
        """
        url = data.get("url", "")
        source = data.get("source", {}) or {}

        article_id = data.get("article_id") or hashlib.sha256(
            url.encode("utf-8")
        ).hexdigest()[:64]

        return cls(
            article_id=article_id,
            investigation_id=investigation_id,
            url=url,
            title=data.get("title"),
            content=data.get("content"),
            published_date=data.get("published_date"),
            source_name=source.get("name"),
            source_domain=source.get("domain"),
            stored_at=data.get("stored_at"),
            source_metadata=source if source else None,
            article_metadata=data.get("metadata"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to the exact dict shape ArticleStore returns.

        Output shape:
        {
            "url": "...",
            "title": "...",
            "content": "...",
            "published_date": "...",
            "source": {"name": "...", "domain": "..."},
            "metadata": {...},
            "stored_at": "..."
        }

        Returns:
            Dict matching ArticleStore's per-article format.
        """
        source: dict[str, Any] = {}
        if self.source_name is not None:
            source["name"] = self.source_name
        if self.source_domain is not None:
            source["domain"] = self.source_domain
        # Merge any extra keys from source_metadata
        if self.source_metadata and isinstance(self.source_metadata, dict):
            for k, v in self.source_metadata.items():
                if k not in source:
                    source[k] = v

        result: dict[str, Any] = {
            "url": self.url,
            "title": self.title,
            "content": self.content,
            "published_date": self.published_date,
            "source": source,
            "metadata": self.article_metadata or {},
            "stored_at": self.stored_at or (
                self.created_at.isoformat() if self.created_at else None
            ),
        }
        return result
