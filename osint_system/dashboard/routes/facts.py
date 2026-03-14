"""Fact browsing and filtering routes.

GET /facts/{investigation_id} — Paginated fact table with tier and
    status filtering. Supports HTMX partial page updates via filter
    dropdowns that reload the fact table without full page navigation.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

router = APIRouter()

_PAGE_SIZE = 50


@router.get("/{investigation_id}", response_class=HTMLResponse)
async def facts_list(
    request: Request,
    investigation_id: str,
    tier: Optional[str] = Query(default=None, description="Filter by impact tier"),
    status: Optional[str] = Query(default=None, description="Filter by verification status"),
    page: int = Query(default=1, ge=1, description="Page number"),
) -> HTMLResponse:
    """Render paginated fact list with optional filtering.

    Fetches facts from fact_store, joins with classification and
    verification data, applies tier/status filters, and paginates.

    Args:
        investigation_id: Investigation scope.
        tier: Optional impact tier filter (critical / less_critical).
        status: Optional verification status filter (confirmed / refuted / dubious / all).
        page: 1-based page number for pagination.
    """
    fact_store = request.app.state.fact_store
    classification_store = request.app.state.classification_store
    verification_store = request.app.state.verification_store
    templates = request.app.state.templates

    # Fetch all facts for the investigation
    fact_data = await fact_store.retrieve_by_investigation(investigation_id)
    raw_facts = fact_data.get("facts", [])

    # Build classification lookup: fact_id -> classification dict
    all_classifications = await classification_store.get_all_classifications(
        investigation_id,
    )
    class_lookup: dict[str, dict[str, Any]] = {
        c["fact_id"]: c for c in all_classifications
    }

    # Build verification lookup: fact_id -> record
    all_verifications = await verification_store.get_all_results(investigation_id)
    ver_lookup: dict[str, Any] = {
        r.fact_id: r for r in all_verifications
    }

    # Enrich facts with classification and verification data
    enriched: list[dict[str, Any]] = []
    for fact in raw_facts:
        fact_id = fact.get("fact_id", "")
        classification = class_lookup.get(fact_id, {})
        verification = ver_lookup.get(fact_id)

        impact_tier = classification.get("impact_tier", "unknown")
        ver_status = "pending"
        ver_confidence = None
        if verification is not None:
            ver_status = (
                verification.status.value
                if hasattr(verification.status, "value")
                else str(verification.status)
            )
            ver_confidence = getattr(verification, "final_confidence", None)

        enriched.append({
            "fact_id": fact_id,
            "claim": _truncate(fact.get("claim_text", str(fact.get("claim", ""))), 120),
            "full_claim": fact.get("claim_text", str(fact.get("claim", ""))),
            "impact_tier": impact_tier,
            "verification_status": ver_status,
            "confidence": ver_confidence,
            "source": _extract_source(fact),
            "extraction_confidence": fact.get("extraction_confidence"),
        })

    # Apply tier filter
    if tier and tier != "all":
        enriched = [f for f in enriched if f["impact_tier"] == tier]

    # Apply status filter
    if status and status != "all":
        if status == "dubious":
            enriched = [
                f for f in enriched
                if f["verification_status"] in ("pending", "in_progress", "unverifiable")
            ]
        else:
            enriched = [f for f in enriched if f["verification_status"] == status]

    # Paginate
    total = len(enriched)
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = min(page, total_pages)
    start = (page - 1) * _PAGE_SIZE
    page_facts = enriched[start : start + _PAGE_SIZE]

    context: dict[str, Any] = {
        "investigation_id": investigation_id,
        "facts": page_facts,
        "total_facts": total,
        "page": page,
        "total_pages": total_pages,
        "current_tier": tier or "all",
        "current_status": status or "all",
    }

    return templates.TemplateResponse(request, "facts/list.html", context)


def _truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis if it exceeds max_len."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _extract_source(fact: dict[str, Any]) -> str:
    """Extract a human-readable source label from fact provenance."""
    provenance = fact.get("provenance", {})
    if isinstance(provenance, dict):
        return provenance.get("source_id", provenance.get("source_url", "unknown"))
    return str(provenance) if provenance else "unknown"
