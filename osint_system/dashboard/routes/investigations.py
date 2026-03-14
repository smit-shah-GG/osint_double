"""Investigation list and detail routes.

GET / — Investigation list with fact counts, classification and
         verification summaries, and report availability.
GET /investigation/{investigation_id} — Detail view with full stats,
         fact list, and links to reports / fact browser.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def investigation_list(request: Request) -> HTMLResponse:
    """Render investigation list page.

    Fetches all investigations from fact_store, enriches each with
    classification and verification stats, and checks report availability.
    """
    fact_store = request.app.state.fact_store
    classification_store = request.app.state.classification_store
    verification_store = request.app.state.verification_store
    report_store = request.app.state.report_store
    templates = request.app.state.templates

    investigations_raw = await fact_store.list_investigations()

    enriched: list[dict[str, Any]] = []
    for inv in investigations_raw:
        inv_id = inv["investigation_id"]

        # Classification stats
        class_stats = await classification_store.get_stats(inv_id)

        # Verification stats (per-investigation — VerificationStore has no global method)
        ver_stats = await verification_store.get_stats(inv_id)

        # Report availability
        latest_report = await report_store.get_latest(inv_id)

        enriched.append({
            "investigation_id": inv_id,
            "fact_count": inv.get("fact_count", 0),
            "created_at": inv.get("created_at", ""),
            "updated_at": inv.get("updated_at", ""),
            "critical_count": class_stats.get("critical_count", 0),
            "less_critical_count": class_stats.get("less_critical_count", 0),
            "dubious_count": class_stats.get("dubious_count", 0),
            "verified_count": class_stats.get("verified_count", 0),
            "verification_total": ver_stats.get("total", 0),
            "verification_status_counts": ver_stats.get("status_counts", {}),
            "pending_review": ver_stats.get("pending_review", 0),
            "has_report": latest_report is not None,
            "report_version": latest_report.version if latest_report else None,
        })

    return templates.TemplateResponse(
        request,
        "investigations/list.html",
        {"investigations": enriched},
    )


@router.get("/investigation/{investigation_id}", response_class=HTMLResponse)
async def investigation_detail(
    request: Request,
    investigation_id: str,
) -> HTMLResponse:
    """Render investigation detail page with facts, stats, and report link.

    Aggregates data from fact_store, classification_store,
    verification_store, and report_store for the given investigation.
    Handles nonexistent investigations gracefully with empty data.
    """
    fact_store = request.app.state.fact_store
    classification_store = request.app.state.classification_store
    verification_store = request.app.state.verification_store
    report_store = request.app.state.report_store
    templates = request.app.state.templates

    # Fetch facts
    fact_data = await fact_store.retrieve_by_investigation(investigation_id)
    facts = fact_data.get("facts", [])
    total_facts = fact_data.get("total_facts", 0)

    # Classification stats
    class_stats = await classification_store.get_stats(investigation_id)

    # Verification stats
    ver_stats = await verification_store.get_stats(investigation_id)

    # Report availability
    latest_report = await report_store.get_latest(investigation_id)

    context: dict[str, Any] = {
        "investigation_id": investigation_id,
        "facts": facts,
        "total_facts": total_facts,
        "class_stats": class_stats,
        "ver_stats": ver_stats,
        "has_report": latest_report is not None,
        "report_version": latest_report.version if latest_report else None,
        "report_generated_at": (
            latest_report.generated_at.isoformat() if latest_report else None
        ),
    }

    return templates.TemplateResponse(
        request,
        "investigations/detail.html",
        context,
    )
