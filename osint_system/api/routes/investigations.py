"""Investigation lifecycle endpoints: CRUD, launch, cancel, regenerate.

Provides six endpoints on ``APIRouter(prefix="/api/v1")``:

1. POST   /investigations               -- create & launch (202)
2. GET    /investigations               -- paginated list
3. GET    /investigations/{id}          -- detail
4. DELETE /investigations/{id}          -- remove (204)
5. POST   /investigations/{id}/cancel   -- signal cancellation
6. POST   /investigations/{id}/regenerate -- re-run synthesis (202)

The ``_run_pipeline_with_events`` wrapper orchestrates ``InvestigationRunner``
phases individually so it can emit events at phase boundaries and check a
cancellation flag between phases.  The runner is NOT modified -- the wrapper
IS the orchestrator for API-launched investigations.
"""

from __future__ import annotations

import asyncio
import time
import traceback
from typing import Any

import structlog
from fastapi import APIRouter, Query, Request, Response

from osint_system.api.errors import ConflictError, NotFoundError
from osint_system.api.events.event_models import EventType
from osint_system.api.events.investigation_registry import (
    Investigation,
    InvestigationStatus,
)
from osint_system.api.schemas import (
    InvestigationResponse,
    LaunchRequest,
    PaginatedResponse,
    RegenerateRequest,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1")


# ── Helpers ──────────────────────────────────────────────────────────


def _investigation_to_response(inv: Investigation) -> InvestigationResponse:
    """Map an ``Investigation`` dataclass to an ``InvestigationResponse``."""
    return InvestigationResponse(
        id=inv.id,
        objective=inv.objective,
        status=inv.status.value,
        params=inv.params,
        created_at=inv.created_at,
        updated_at=inv.updated_at,
        stream_url=f"/api/v1/investigations/{inv.id}/stream",
        stats=inv.stats or None,
        error=inv.error,
    )


# ── Pipeline wrapper ─────────────────────────────────────────────────


async def _run_pipeline_with_events(
    investigation_id: str,
    body: LaunchRequest,
    app_state: Any,
) -> None:
    """Run pipeline phases with event emission and cancellation checks.

    This wrapper calls runner phases individually rather than ``runner.run()``
    because it needs to:
    1. Emit structured events between phases.
    2. Check the cancellation flag between phases.
    3. Retain stores and graph pipeline on ``app_state`` for API read access.

    The runner itself is NOT modified -- this wrapper IS the orchestrator
    for API-launched investigations (RESEARCH.md anti-pattern: do not modify
    InvestigationRunner directly).
    """
    from osint_system.runner import InvestigationRunner

    event_bus = app_state.event_bus
    registry = app_state.investigation_registry

    # Transition PENDING -> RUNNING
    await registry.transition(
        investigation_id,
        expected_status=InvestigationStatus.PENDING,
        new_status=InvestigationStatus.RUNNING,
    )

    # Create cancellation flag
    cancel_event = asyncio.Event()
    app_state.cancel_flags[investigation_id] = cancel_event

    runner: InvestigationRunner | None = None

    try:
        runner = InvestigationRunner(
            objective=body.objective,
            investigation_id=investigation_id,
        )

        # Expose stores for API read access (facts, reports, etc.)
        app_state.investigation_stores[investigation_id] = {
            "fact_store": runner.fact_store,
            "classification_store": runner.classification_store,
            "verification_store": runner.verification_store,
            "report_store": runner.report_store,
            "article_store": runner.article_store,
        }

        cumulative_stats: dict[str, int] = {}

        # Define phase sequence: (name, callable, stats_extractor)
        phases: list[
            tuple[str, Any, Any]
        ] = [
            ("crawl", runner._phase_crawl, None),
            ("extract", runner._phase_extract, None),
            ("classify", runner._phase_classify, None),
            ("verify", runner._phase_verify, None),
            ("graph", runner._phase_graph, None),
            ("analyze", runner._phase_analyze, None),
        ]

        # Track inter-phase results for phases that pass data forward
        extract_result: dict[str, Any] = {}
        classification_summary: dict[str, Any] = {}
        verification_summary: dict[str, Any] = {}

        for phase_name, _, _ in phases:
            # Check cancellation
            if cancel_event.is_set():
                logger.info(
                    "pipeline_cancelled",
                    investigation_id=investigation_id,
                    cancelled_before=phase_name,
                )
                break

            # Emit phase_started
            event_bus.emit(
                investigation_id,
                EventType.PHASE_STARTED.value,
                {"phase": phase_name},
            )

            phase_start = time.monotonic()

            try:
                if phase_name == "crawl":
                    await runner._phase_crawl()
                elif phase_name == "extract":
                    extract_result = await runner._phase_extract()
                    cumulative_stats["facts_extracted"] = extract_result.get(
                        "facts_extracted", 0
                    )
                elif phase_name == "classify":
                    classification_summary = await runner._phase_classify()
                    cumulative_stats["classified"] = classification_summary.get(
                        "total", 0
                    )
                elif phase_name == "verify":
                    verification_summary = await runner._phase_verify(
                        classification_summary
                    )
                    cumulative_stats["verified"] = verification_summary.get(
                        "total_verified", 0
                    )
                    cumulative_stats["confirmed"] = verification_summary.get(
                        "confirmed", 0
                    )
                elif phase_name == "graph":
                    ingestion_stats = await runner._phase_graph(verification_summary)
                    cumulative_stats["nodes"] = ingestion_stats.get(
                        "nodes_merged", 0
                    )
                    # Retain graph pipeline for Graph API (Pitfall 6)
                    if hasattr(runner, "graph_pipeline"):
                        app_state.graph_pipelines[investigation_id] = (
                            runner.graph_pipeline
                        )
                elif phase_name == "analyze":
                    await runner._phase_analyze()

            except Exception as phase_exc:
                # Phase failure => pipeline failure
                elapsed_ms = int((time.monotonic() - phase_start) * 1000)
                event_bus.emit(
                    investigation_id,
                    EventType.PHASE_COMPLETED.value,
                    {
                        "phase": phase_name,
                        "elapsed_ms": elapsed_ms,
                        "error": str(phase_exc),
                    },
                )
                raise

            elapsed_ms = int((time.monotonic() - phase_start) * 1000)

            # Emit phase_completed
            event_bus.emit(
                investigation_id,
                EventType.PHASE_COMPLETED.value,
                {
                    "phase": phase_name,
                    "elapsed_ms": elapsed_ms,
                    **cumulative_stats,
                },
            )

            # Emit progress event with cumulative stats
            event_bus.emit(
                investigation_id,
                EventType.PHASE_PROGRESS.value,
                {"completed_phase": phase_name, **cumulative_stats},
            )

        # Pipeline completed (or cancelled above via break)
        if cancel_event.is_set():
            # Already transitioned to CANCELLED by the cancel endpoint
            event_bus.emit(
                investigation_id,
                EventType.PIPELINE_ERROR.value,
                {"reason": "cancelled"},
            )
        else:
            await registry.transition(
                investigation_id,
                expected_status=InvestigationStatus.RUNNING,
                new_status=InvestigationStatus.COMPLETED,
                stats=cumulative_stats,
            )
            event_bus.emit(
                investigation_id,
                EventType.PIPELINE_COMPLETED.value,
                cumulative_stats,
            )

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error(
            "pipeline_failed",
            investigation_id=investigation_id,
            error=error_msg,
            traceback=traceback.format_exc(),
        )
        try:
            await registry.transition(
                investigation_id,
                expected_status=InvestigationStatus.RUNNING,
                new_status=InvestigationStatus.FAILED,
                error=error_msg,
            )
        except ConflictError:
            # Already transitioned (e.g. cancelled concurrently)
            pass

        event_bus.emit(
            investigation_id,
            EventType.PIPELINE_ERROR.value,
            {"error": error_msg},
        )

    finally:
        # Cleanup cancel flag, retain stores for API access
        app_state.cancel_flags.pop(investigation_id, None)


async def _regenerate_pipeline(
    investigation_id: str,
    body: RegenerateRequest,
    app_state: Any,
) -> None:
    """Re-run only the analysis/synthesis phase with existing stores.

    Uses the retained stores from the original run (fact_store,
    classification_store, verification_store) to produce a new report version.
    """
    from osint_system.config.analysis_config import AnalysisConfig
    from osint_system.pipeline.analysis_pipeline import AnalysisPipeline
    from osint_system.reporting import ReportGenerator

    event_bus = app_state.event_bus
    registry = app_state.investigation_registry

    stores = app_state.investigation_stores.get(investigation_id)
    if not stores:
        await registry.transition(
            investigation_id,
            expected_status=InvestigationStatus.RUNNING,
            new_status=InvestigationStatus.FAILED,
            error="Investigation stores not found for regeneration.",
        )
        event_bus.emit(
            investigation_id,
            EventType.PIPELINE_ERROR.value,
            {"error": "Investigation stores not found for regeneration."},
        )
        return

    try:
        config = AnalysisConfig.from_env()
        report_generator = ReportGenerator(config=config)

        pipeline = AnalysisPipeline(
            fact_store=stores["fact_store"],
            classification_store=stores["classification_store"],
            verification_store=stores["verification_store"],
            report_generator=report_generator,
            report_store=stores["report_store"],
            config=config,
        )

        event_bus.emit(
            investigation_id,
            EventType.PHASE_STARTED.value,
            {"phase": "regenerate"},
        )

        phase_start = time.monotonic()
        await pipeline.run_analysis(investigation_id)
        elapsed_ms = int((time.monotonic() - phase_start) * 1000)

        event_bus.emit(
            investigation_id,
            EventType.PHASE_COMPLETED.value,
            {"phase": "regenerate", "elapsed_ms": elapsed_ms},
        )

        await registry.transition(
            investigation_id,
            expected_status=InvestigationStatus.RUNNING,
            new_status=InvestigationStatus.COMPLETED,
        )
        event_bus.emit(
            investigation_id,
            EventType.PIPELINE_COMPLETED.value,
            {"regenerated": True},
        )

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error(
            "regeneration_failed",
            investigation_id=investigation_id,
            error=error_msg,
        )
        try:
            await registry.transition(
                investigation_id,
                expected_status=InvestigationStatus.RUNNING,
                new_status=InvestigationStatus.FAILED,
                error=error_msg,
            )
        except ConflictError:
            pass

        event_bus.emit(
            investigation_id,
            EventType.PIPELINE_ERROR.value,
            {"error": error_msg},
        )


# ── Endpoints ────────────────────────────────────────────────────────


@router.post("/investigations", status_code=202)
async def create_investigation(
    request: Request,
    body: LaunchRequest,
) -> InvestigationResponse:
    """Create a new investigation and launch the pipeline.

    Returns 202 Accepted with the investigation entity and a ``stream_url``
    for real-time SSE progress.
    """
    registry = request.app.state.investigation_registry

    investigation = registry.create(
        objective=body.objective,
        params=body.model_dump(exclude={"objective"}, exclude_none=True),
    )

    # Launch pipeline as background async task (Pitfall 1: store reference)
    task = asyncio.create_task(
        _run_pipeline_with_events(investigation.id, body, request.app.state)
    )

    # Store task reference to prevent GC (RESEARCH.md Pitfall 1)
    if not hasattr(request.app.state, "active_tasks"):
        request.app.state.active_tasks = {}
    request.app.state.active_tasks[investigation.id] = task

    # Remove from active_tasks on completion
    task.add_done_callback(
        lambda _t, inv_id=investigation.id: request.app.state.active_tasks.pop(
            inv_id, None
        )
    )

    return _investigation_to_response(investigation)


@router.get("/investigations")
async def list_investigations(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
) -> PaginatedResponse[InvestigationResponse]:
    """List all investigations with pagination.

    Merges in-memory registry (active/recent) with PostgreSQL-persisted
    investigations discovered via distinct investigation_id in articles table.
    """
    registry = request.app.state.investigation_registry
    all_investigations = registry.list_all()
    known_ids = {inv.id for inv in all_investigations}

    # Discover persisted investigations not in registry (e.g. migrated data)
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is not None:
        from sqlalchemy import distinct, select
        from osint_system.data_management.models.article import ArticleModel

        try:
            async with session_factory() as session:
                result = await session.execute(
                    select(distinct(ArticleModel.investigation_id))
                )
                db_inv_ids = {row[0] for row in result.all()}

                for inv_id in db_inv_ids - known_ids:
                    all_investigations.append(
                        Investigation(
                            id=inv_id,
                            objective="(migrated investigation)",
                            status=InvestigationStatus.COMPLETED,
                        )
                    )
        except Exception as e:
            logger.debug("db_investigation_discovery_failed", error=str(e))

    all_investigations.sort(key=lambda inv: inv.created_at, reverse=True)
    responses = [_investigation_to_response(inv) for inv in all_investigations]
    return PaginatedResponse.from_items(responses, page, page_size)


@router.get("/investigations/{investigation_id}")
async def get_investigation(
    request: Request,
    investigation_id: str,
) -> InvestigationResponse:
    """Get a single investigation by ID."""
    registry = request.app.state.investigation_registry
    investigation = registry.get(investigation_id)
    if investigation is None:
        raise NotFoundError(
            detail=f"Investigation '{investigation_id}' not found.",
        )
    return _investigation_to_response(investigation)


@router.delete(
    "/investigations/{investigation_id}",
    status_code=204,
    response_class=Response,
)
async def delete_investigation(
    request: Request,
    investigation_id: str,
) -> None:
    """Delete an investigation.

    If the investigation is currently running, cancels it first.
    Returns 204 No Content on success.
    """
    registry = request.app.state.investigation_registry
    event_bus = request.app.state.event_bus

    investigation = registry.get(investigation_id)
    if investigation is None:
        raise NotFoundError(
            detail=f"Investigation '{investigation_id}' not found.",
        )

    # Cancel if running
    if investigation.status == InvestigationStatus.RUNNING:
        cancel_flags = getattr(request.app.state, "cancel_flags", {})
        flag = cancel_flags.get(investigation_id)
        if flag is not None:
            flag.set()
        # Cancel the asyncio task
        active_tasks = getattr(request.app.state, "active_tasks", {})
        task = active_tasks.get(investigation_id)
        if task is not None and not task.done():
            task.cancel()

    # Delete from registry
    deleted = registry.delete(investigation_id)
    if not deleted:
        raise NotFoundError(
            detail=f"Investigation '{investigation_id}' not found.",
        )

    # Clean up event bus
    event_bus.clear(investigation_id)

    # Clean up investigation stores
    investigation_stores = getattr(request.app.state, "investigation_stores", {})
    investigation_stores.pop(investigation_id, None)

    # Clean up graph pipelines
    graph_pipelines = getattr(request.app.state, "graph_pipelines", {})
    graph_pipelines.pop(investigation_id, None)


@router.post("/investigations/{investigation_id}/cancel")
async def cancel_investigation(
    request: Request,
    investigation_id: str,
) -> InvestigationResponse:
    """Cancel a running investigation.

    Sets the cancellation flag so the pipeline wrapper stops at the next
    phase boundary.  Transitions status from RUNNING to CANCELLED.
    """
    registry = request.app.state.investigation_registry
    event_bus = request.app.state.event_bus

    investigation = registry.get(investigation_id)
    if investigation is None:
        raise NotFoundError(
            detail=f"Investigation '{investigation_id}' not found.",
        )

    if investigation.status != InvestigationStatus.RUNNING:
        raise ConflictError(
            detail=(
                f"Cannot cancel investigation in '{investigation.status.value}' state. "
                f"Only RUNNING investigations can be cancelled."
            ),
        )

    # Signal cancellation to pipeline wrapper
    cancel_flags = getattr(request.app.state, "cancel_flags", {})
    flag = cancel_flags.get(investigation_id)
    if flag is not None:
        flag.set()

    # Transition RUNNING -> CANCELLED
    updated = await registry.transition(
        investigation_id,
        expected_status=InvestigationStatus.RUNNING,
        new_status=InvestigationStatus.CANCELLED,
    )

    # Emit cancellation event
    event_bus.emit(
        investigation_id,
        EventType.PIPELINE_ERROR.value,
        {"reason": "cancelled"},
    )

    return _investigation_to_response(updated)


@router.post("/investigations/{investigation_id}/regenerate", status_code=202)
async def regenerate_investigation(
    request: Request,
    investigation_id: str,
    body: RegenerateRequest,
) -> InvestigationResponse:
    """Re-run synthesis with optional model override.

    Only allowed for COMPLETED investigations.  Creates a new report version
    using existing facts, classifications, and verifications.
    """
    registry = request.app.state.investigation_registry

    investigation = registry.get(investigation_id)
    if investigation is None:
        raise NotFoundError(
            detail=f"Investigation '{investigation_id}' not found.",
        )

    if investigation.status != InvestigationStatus.COMPLETED:
        raise ConflictError(
            detail=(
                f"Cannot regenerate investigation in '{investigation.status.value}' "
                f"state. Only COMPLETED investigations can be regenerated."
            ),
        )

    # We need to transition back to RUNNING for regeneration.
    # Add a temporary transition: COMPLETED -> RUNNING for regeneration.
    # Since the registry disallows COMPLETED -> RUNNING, we reset status directly
    # under lock to avoid modifying the transition graph globally.
    async with registry._lock:
        investigation.status = InvestigationStatus.RUNNING
        investigation.updated_at = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        )

    # Launch regeneration as background task
    task = asyncio.create_task(
        _regenerate_pipeline(investigation_id, body, request.app.state)
    )

    if not hasattr(request.app.state, "active_tasks"):
        request.app.state.active_tasks = {}
    request.app.state.active_tasks[investigation_id] = task
    task.add_done_callback(
        lambda _t, inv_id=investigation_id: request.app.state.active_tasks.pop(
            inv_id, None
        )
    )

    return _investigation_to_response(investigation)
