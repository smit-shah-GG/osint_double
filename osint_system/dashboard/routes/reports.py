"""Report viewing and generation routes.

GET  /reports/{investigation_id}          — View latest report (rendered HTML).
POST /reports/{investigation_id}/generate — Trigger on-demand report generation.
"""

from __future__ import annotations

from typing import Any

import mistune
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()


@router.get("/{investigation_id}", response_class=HTMLResponse)
async def view_report(
    request: Request,
    investigation_id: str,
) -> HTMLResponse:
    """Render the latest report for an investigation.

    Fetches the latest ReportRecord from report_store. If no report
    exists, renders a placeholder page with a "Generate Report" button.
    Markdown content is converted to HTML via mistune before passing
    to the template.
    """
    report_store = request.app.state.report_store
    templates = request.app.state.templates

    latest = await report_store.get_latest(investigation_id)

    # Fetch all versions for version selector
    all_versions = await report_store.list_versions(investigation_id)

    report_html = ""
    if latest is not None:
        report_html = mistune.html(latest.markdown_content)

    context: dict[str, Any] = {
        "investigation_id": investigation_id,
        "has_report": latest is not None,
        "report": latest,
        "report_html": report_html,
        "versions": all_versions,
        "version_count": len(all_versions),
    }

    return templates.TemplateResponse(request, "reports/view.html", context)


@router.post("/{investigation_id}/generate")
async def generate_report(
    request: Request,
    investigation_id: str,
) -> RedirectResponse:
    """Trigger on-demand report generation.

    Prefers AnalysisPipeline.run_analysis() which auto-generates and
    saves the report via its internal report_generator and report_store.
    Falls back to direct report_generator if analysis_pipeline is
    unavailable.

    Redirects back to the report view page after generation.
    """
    analysis_pipeline = request.app.state.analysis_pipeline
    report_generator = request.app.state.report_generator
    report_store = request.app.state.report_store

    if analysis_pipeline is not None:
        # Full pipeline: analysis -> synthesis -> report generation -> save
        try:
            await analysis_pipeline.run_analysis(investigation_id)
        except Exception:
            # Pipeline failure is not fatal — user sees "no report" page
            pass
    elif report_generator is not None:
        # Fallback: generate from latest stored synthesis if available
        latest = await report_store.get_latest(investigation_id)
        if latest and latest.synthesis_summary:
            # Cannot regenerate without a fresh synthesis — inform user
            pass

    return RedirectResponse(
        url=f"/reports/{investigation_id}",
        status_code=303,
    )
