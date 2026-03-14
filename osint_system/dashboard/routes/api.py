"""JSON API endpoints for HTMX partial page updates.

GET /api/investigation/{investigation_id}/stats — JSON stats for polling.
GET /api/investigation/{investigation_id}/facts — HTML partial of fact table.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter()


@router.get("/investigation/{investigation_id}/stats")
async def investigation_stats(
    request: Request,
    investigation_id: str,
) -> JSONResponse:
    """Return JSON stats for HTMX polling updates.

    Aggregates fact, classification, and verification statistics for
    a single investigation. Used by monitoring dashboard auto-refresh.
    """
    fact_store = request.app.state.fact_store
    classification_store = request.app.state.classification_store
    verification_store = request.app.state.verification_store

    fact_stats = await fact_store.get_stats(investigation_id)
    class_stats = await classification_store.get_stats(investigation_id)
    ver_stats = await verification_store.get_stats(investigation_id)

    response: dict[str, Any] = {
        "investigation_id": investigation_id,
        "fact_count": fact_stats.get("total_facts", 0),
        "classification": {
            "total": class_stats.get("total_classifications", 0),
            "critical": class_stats.get("critical_count", 0),
            "less_critical": class_stats.get("less_critical_count", 0),
            "dubious": class_stats.get("dubious_count", 0),
            "verified": class_stats.get("verified_count", 0),
        },
        "verification": {
            "total": ver_stats.get("total", 0),
            "status_counts": ver_stats.get("status_counts", {}),
            "pending_review": ver_stats.get("pending_review", 0),
        },
    }

    return JSONResponse(content=response)


@router.get("/investigation/{investigation_id}/facts", response_class=HTMLResponse)
async def investigation_facts_partial(
    request: Request,
    investigation_id: str,
) -> HTMLResponse:
    """Return HTML partial of fact table for HTMX swap.

    Renders a minimal fact table fragment without the base layout,
    suitable for hx-swap="innerHTML" updates.
    """
    fact_store = request.app.state.fact_store
    classification_store = request.app.state.classification_store
    verification_store = request.app.state.verification_store
    templates = request.app.state.templates

    fact_data = await fact_store.retrieve_by_investigation(investigation_id)
    raw_facts = fact_data.get("facts", [])

    # Build lookups
    all_classifications = await classification_store.get_all_classifications(
        investigation_id,
    )
    class_lookup: dict[str, dict[str, Any]] = {
        c["fact_id"]: c for c in all_classifications
    }

    all_verifications = await verification_store.get_all_results(investigation_id)
    ver_lookup: dict[str, Any] = {
        r.fact_id: r for r in all_verifications
    }

    rows: list[dict[str, Any]] = []
    for fact in raw_facts[:50]:  # Limit partial to 50 rows
        fact_id = fact.get("fact_id", "")
        classification = class_lookup.get(fact_id, {})
        verification = ver_lookup.get(fact_id)

        ver_status = "pending"
        if verification is not None:
            ver_status = (
                verification.status.value
                if hasattr(verification.status, "value")
                else str(verification.status)
            )

        rows.append({
            "fact_id": fact_id,
            "claim": _truncate(fact.get("claim_text", str(fact.get("claim", ""))), 80),
            "impact_tier": classification.get("impact_tier", "unknown"),
            "verification_status": ver_status,
        })

    # Return a simple HTML table fragment
    table_html = _render_fact_table_html(rows)
    return HTMLResponse(content=table_html)


def _truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _render_fact_table_html(rows: list[dict[str, Any]]) -> str:
    """Render a minimal fact table as raw HTML for HTMX partial swap."""
    if not rows:
        return "<p>No facts found.</p>"

    lines = [
        '<table class="data-table">',
        "<thead><tr>"
        "<th>Fact ID</th><th>Claim</th><th>Tier</th><th>Status</th>"
        "</tr></thead>",
        "<tbody>",
    ]
    for row in rows:
        status_class = f"status-{row['verification_status']}"
        tier_class = f"tier-{row['impact_tier']}"
        lines.append(
            f'<tr>'
            f'<td class="mono">{row["fact_id"]}</td>'
            f'<td>{row["claim"]}</td>'
            f'<td class="{tier_class}">{row["impact_tier"]}</td>'
            f'<td class="badge {status_class}">{row["verification_status"]}</td>'
            f'</tr>'
        )
    lines.append("</tbody></table>")
    return "\n".join(lines)
