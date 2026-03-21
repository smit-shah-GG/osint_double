"""Source inventory endpoint with authority scores.

Aggregates articles by source domain from ``ArticleStore``, computing
per-domain article counts and max authority scores. Sorted by article
count descending (most-used sources first).

Endpoints:
    GET /investigations/{investigation_id}/sources
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from osint_system.api.errors import NotFoundError
from osint_system.api.schemas import PaginatedResponse, SourceResponse

router = APIRouter(prefix="/api/v1")


# -- Helpers ---------------------------------------------------------------


def _get_article_store(request: Request, investigation_id: str) -> Any:
    """Resolve the ArticleStore for an investigation.

    Checks ``app.state.investigation_stores[investigation_id]`` first,
    falls back to ``app.state.article_store``.

    Raises:
        NotFoundError: If no article store is available.
    """
    inv_stores = getattr(request.app.state, "investigation_stores", {})
    if investigation_id in inv_stores:
        store = inv_stores[investigation_id].get("article_store")
        if store is not None:
            return store

    store = getattr(request.app.state, "article_store", None)
    if store is not None:
        return store

    raise NotFoundError(
        detail=f"Investigation '{investigation_id}' not found.",
    )


def _aggregate_sources(articles: list[dict[str, Any]]) -> list[SourceResponse]:
    """Aggregate articles by source domain.

    Groups articles by ``source.name`` (domain), counts per domain, and
    takes the max ``authority_score`` per domain. Returns list sorted by
    article_count descending.
    """
    # Accumulator: domain -> {type, max_score, count}
    domain_map: dict[str, dict[str, Any]] = {}

    for article in articles:
        source = article.get("source", {})
        if not isinstance(source, dict):
            continue

        domain = source.get("name", "unknown")
        source_type = source.get("type", "unknown")
        authority_score = source.get("authority_score", 0.0)

        if domain not in domain_map:
            domain_map[domain] = {
                "type": source_type,
                "max_score": authority_score,
                "count": 0,
            }

        entry = domain_map[domain]
        entry["count"] += 1
        if authority_score > entry["max_score"]:
            entry["max_score"] = authority_score

    # Build SourceResponse list sorted by count descending
    result: list[SourceResponse] = []
    for domain, info in domain_map.items():
        result.append(
            SourceResponse(
                name=domain,
                type=info["type"],
                authority_score=info["max_score"],
                article_count=info["count"],
                domain=domain,
            )
        )

    result.sort(key=lambda s: s.article_count, reverse=True)
    return result


# -- Endpoints -------------------------------------------------------------


@router.get(
    "/investigations/{investigation_id}/sources",
    response_model=PaginatedResponse[SourceResponse],
)
async def list_sources(
    request: Request,
    investigation_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
) -> PaginatedResponse[SourceResponse]:
    """List source inventory with article counts and authority scores."""
    article_store = _get_article_store(request, investigation_id)

    result = await article_store.retrieve_by_investigation(investigation_id)
    articles: list[dict[str, Any]] = result.get("articles", [])

    sources = _aggregate_sources(articles)
    return PaginatedResponse[SourceResponse].from_items(sources, page, page_size)
