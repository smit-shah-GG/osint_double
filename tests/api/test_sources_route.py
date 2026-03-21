"""Tests for GET /api/v1/investigations/{id}/sources endpoint.

Validates source aggregation by domain, authority_score max, article counts,
sort order, and pagination.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from osint_system.api.errors import register_error_handlers
from osint_system.api.routes.sources import router


# -- Fixtures & helpers ----------------------------------------------------


def _make_article(
    url: str,
    source_name: str = "reuters.com",
    source_type: str = "wire_service",
    authority_score: float = 0.9,
) -> dict[str, Any]:
    """Build a mock article dict matching ArticleStore structure."""
    return {
        "url": url,
        "title": f"Article from {source_name}",
        "content": "Lorem ipsum...",
        "source": {
            "name": source_name,
            "type": source_type,
            "authority_score": authority_score,
        },
        "stored_at": "2026-03-21T12:00:00Z",
    }


def _build_app(
    articles: list[dict[str, Any]],
    investigation_id: str = "inv-test",
    use_direct_stores: bool = False,
) -> FastAPI:
    """Build a minimal FastAPI app with mocked article store."""
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router)

    article_store = AsyncMock()
    article_store.retrieve_by_investigation.return_value = {
        "investigation_id": investigation_id,
        "articles": articles,
        "total_articles": len(articles),
        "returned_articles": len(articles),
    }

    if use_direct_stores:
        app.state.article_store = article_store
    else:
        app.state.investigation_stores = {
            investigation_id: {
                "article_store": article_store,
            }
        }

    return app


# -- Tests -----------------------------------------------------------------


def test_list_sources_aggregation() -> None:
    """5 articles from reuters.com + 3 from bbc.com -> 2 source entries."""
    articles = [
        _make_article(f"https://reuters.com/{i}", "reuters.com", "wire_service", 0.9)
        for i in range(5)
    ] + [
        _make_article(f"https://bbc.com/{i}", "bbc.com", "news_outlet", 0.75)
        for i in range(3)
    ]

    app = _build_app(articles)
    client = TestClient(app)

    resp = client.get("/api/v1/investigations/inv-test/sources")
    assert resp.status_code == 200

    body = resp.json()
    assert body["total"] == 2

    # Sorted by article_count descending
    data = body["data"]
    assert data[0]["name"] == "reuters.com"
    assert data[0]["article_count"] == 5
    assert data[0]["authority_score"] == 0.9
    assert data[0]["type"] == "wire_service"
    assert data[0]["domain"] == "reuters.com"

    assert data[1]["name"] == "bbc.com"
    assert data[1]["article_count"] == 3
    assert data[1]["authority_score"] == 0.75


def test_list_sources_max_authority_score() -> None:
    """Authority score is max across articles from same domain."""
    articles = [
        _make_article("https://example.com/1", "example.com", "news_outlet", 0.5),
        _make_article("https://example.com/2", "example.com", "news_outlet", 0.8),
        _make_article("https://example.com/3", "example.com", "news_outlet", 0.6),
    ]

    app = _build_app(articles)
    client = TestClient(app)

    resp = client.get("/api/v1/investigations/inv-test/sources")
    assert resp.status_code == 200

    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["authority_score"] == 0.8


def test_list_sources_empty() -> None:
    """No articles returns empty paginated response."""
    app = _build_app([])
    client = TestClient(app)

    resp = client.get("/api/v1/investigations/inv-test/sources")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
    assert resp.json()["data"] == []


def test_list_sources_pagination() -> None:
    """Pagination works correctly for sources."""
    articles = [
        _make_article("https://a.com/1", "a.com", "news_outlet", 0.5),
        _make_article("https://a.com/2", "a.com", "news_outlet", 0.5),
        _make_article("https://b.com/1", "b.com", "news_outlet", 0.7),
        _make_article("https://c.com/1", "c.com", "wire_service", 0.9),
    ]

    app = _build_app(articles)
    client = TestClient(app)

    resp = client.get(
        "/api/v1/investigations/inv-test/sources?page=1&page_size=2"
    )
    assert resp.status_code == 200

    body = resp.json()
    assert body["total"] == 3  # 3 unique domains
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert len(body["data"]) == 2


def test_list_sources_unknown_investigation() -> None:
    """Non-existent investigation returns 404."""
    app = _build_app([], investigation_id="inv-real")
    client = TestClient(app)

    resp = client.get("/api/v1/investigations/inv-unknown/sources")
    assert resp.status_code == 404


def test_list_sources_fallback_to_direct_store() -> None:
    """Resolves article store from app.state directly."""
    articles = [_make_article("https://reuters.com/1")]
    app = _build_app(articles, use_direct_stores=True)
    client = TestClient(app)

    resp = client.get("/api/v1/investigations/inv-test/sources")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_list_sources_articles_with_missing_source_skipped() -> None:
    """Articles with non-dict source are skipped; missing source yields 'unknown'."""
    articles = [
        _make_article("https://good.com/1", "good.com"),
        {"url": "https://nosource.com/1", "title": "No source"},  # empty dict -> "unknown"
        {"url": "https://bad.com/1", "source": "not a dict"},  # string -> skipped
    ]

    app = _build_app(articles)
    client = TestClient(app)

    resp = client.get("/api/v1/investigations/inv-test/sources")
    assert resp.status_code == 200
    # 2 sources: "good.com" (1 article) and "unknown" (1 article from missing source)
    assert resp.json()["total"] == 2
    names = {s["name"] for s in resp.json()["data"]}
    assert "good.com" in names
    assert "unknown" in names
