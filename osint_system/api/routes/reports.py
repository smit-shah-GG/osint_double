"""Report retrieval and version listing endpoints.

Serves intelligence reports with version history. Maps internal
``ReportRecord`` Pydantic models to flat ``ReportResponse`` / ``ReportVersionSummary``
API schemas.

Endpoints:
    GET /investigations/{investigation_id}/reports/latest
    GET /investigations/{investigation_id}/reports
    GET /investigations/{investigation_id}/reports/{version}
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from osint_system.api.errors import NotFoundError
from osint_system.api.schemas import (
    PaginatedResponse,
    ReportResponse,
    ReportVersionSummary,
)

router = APIRouter(prefix="/api/v1")


# -- Helpers ---------------------------------------------------------------


def _get_report_store(request: Request, investigation_id: str) -> Any:
    """Resolve the ReportStore for an investigation.

    Checks ``app.state.investigation_stores[investigation_id]`` first,
    falls back to ``app.state.report_store``.

    Raises:
        NotFoundError: If no report store is available for the investigation.
    """
    inv_stores = getattr(request.app.state, "investigation_stores", {})
    if investigation_id in inv_stores:
        store = inv_stores[investigation_id].get("report_store")
        if store is not None:
            return store

    store = getattr(request.app.state, "report_store", None)
    if store is not None:
        return store

    raise NotFoundError(
        detail=f"Investigation '{investigation_id}' not found.",
    )


def _record_to_response(record: Any) -> ReportResponse:
    """Map a ReportRecord to ReportResponse."""
    return ReportResponse(
        investigation_id=record.investigation_id,
        version=record.version,
        content=record.markdown_content,
        model_used=record.synthesis_summary.get("model_version"),
        created_at=record.generated_at,
        metadata=record.synthesis_summary or None,
    )


def _record_to_summary(record: Any) -> ReportVersionSummary:
    """Map a ReportRecord to ReportVersionSummary."""
    return ReportVersionSummary(
        version=record.version,
        created_at=record.generated_at,
        model_used=record.synthesis_summary.get("model_version"),
    )


# -- Endpoints -------------------------------------------------------------


@router.get(
    "/investigations/{investigation_id}/reports/latest",
    response_model=ReportResponse,
)
async def get_latest_report(
    request: Request,
    investigation_id: str,
) -> ReportResponse:
    """Retrieve the most recent report version for an investigation."""
    report_store = _get_report_store(request, investigation_id)

    record = await report_store.get_latest(investigation_id)
    if record is None:
        raise NotFoundError(
            detail=f"No reports found for investigation '{investigation_id}'.",
        )

    return _record_to_response(record)


@router.get(
    "/investigations/{investigation_id}/reports",
    response_model=PaginatedResponse[ReportVersionSummary],
)
async def list_report_versions(
    request: Request,
    investigation_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
) -> PaginatedResponse[ReportVersionSummary]:
    """List all report versions for an investigation."""
    report_store = _get_report_store(request, investigation_id)

    records = await report_store.list_versions(investigation_id)
    if not records:
        # Return empty paginated response (not 404 -- investigation may exist
        # but have no reports yet)
        return PaginatedResponse[ReportVersionSummary].from_items([], page, page_size)

    summaries = [_record_to_summary(r) for r in records]
    return PaginatedResponse[ReportVersionSummary].from_items(
        summaries, page, page_size
    )


@router.get(
    "/investigations/{investigation_id}/reports/{version}",
    response_model=ReportResponse,
)
async def get_report_version(
    request: Request,
    investigation_id: str,
    version: int,
) -> ReportResponse:
    """Retrieve a specific report version by version number."""
    report_store = _get_report_store(request, investigation_id)

    record = await report_store.get_version(investigation_id, version)
    if record is None:
        raise NotFoundError(
            detail=f"Report version {version} not found for investigation '{investigation_id}'.",
        )

    return _record_to_response(record)
