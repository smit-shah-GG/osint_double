"""Pipeline monitoring routes.

GET /monitoring/status — System overview with aggregated stats from
    FactStore, ClassificationStore, and per-investigation verification
    stats (VerificationStore has no global get_storage_stats).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/status", response_class=HTMLResponse)
async def monitoring_status(request: Request) -> HTMLResponse:
    """Render the pipeline monitoring dashboard.

    Aggregates statistics from:
    - FactStore.get_storage_stats() — global fact counts
    - ClassificationStore.get_storage_stats() — global classification counts
    - VerificationStore.get_stats(inv_id) — per-investigation verification
      stats, iterated over all known investigations and summed

    VerificationStore does NOT have a global get_storage_stats() method,
    so we iterate fact_store.list_investigations() and aggregate manually.
    """
    fact_store = request.app.state.fact_store
    classification_store = request.app.state.classification_store
    verification_store = request.app.state.verification_store
    report_store = request.app.state.report_store
    templates = request.app.state.templates

    # Global stats from stores that support it
    fact_stats = await fact_store.get_storage_stats()
    class_stats = await classification_store.get_storage_stats()

    # Aggregate verification stats per investigation
    investigations = await fact_store.list_investigations()
    total_verified = 0
    total_verification_records = 0
    total_pending_review = 0
    aggregated_status_counts: dict[str, int] = {}
    per_investigation: list[dict[str, Any]] = []

    for inv in investigations:
        inv_id = inv["investigation_id"]
        ver_stats = await verification_store.get_stats(inv_id)

        inv_total = ver_stats.get("total", 0)
        total_verification_records += inv_total
        total_pending_review += ver_stats.get("pending_review", 0)

        status_counts = ver_stats.get("status_counts", {})
        for status_key, count in status_counts.items():
            aggregated_status_counts[status_key] = (
                aggregated_status_counts.get(status_key, 0) + count
            )

        confirmed_count = status_counts.get("confirmed", 0)
        total_verified += confirmed_count

        # Check report availability
        latest_report = await report_store.get_latest(inv_id)

        per_investigation.append({
            "investigation_id": inv_id,
            "fact_count": inv.get("fact_count", 0),
            "verified_count": confirmed_count,
            "pending_count": ver_stats.get("pending_review", 0),
            "total_verifications": inv_total,
            "report_status": "available" if latest_report else "not generated",
        })

    context: dict[str, Any] = {
        "fact_stats": fact_stats,
        "class_stats": class_stats,
        "total_investigations": fact_stats.get("total_investigations", 0),
        "total_facts": fact_stats.get("total_facts", 0),
        "total_classifications": class_stats.get("total_classifications", 0),
        "total_verification_records": total_verification_records,
        "total_verified": total_verified,
        "total_pending_review": total_pending_review,
        "aggregated_status_counts": aggregated_status_counts,
        "per_investigation": per_investigation,
    }

    return templates.TemplateResponse(request, "monitoring/status.html", context)
