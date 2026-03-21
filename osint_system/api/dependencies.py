"""FastAPI dependency injection helpers for store and service access.

Store dependencies create fresh store instances on each request using
``session_factory`` and ``embedding_service`` from ``app.state`` (set by
the lifespan handler in ``app.py``).  This ensures stores always use
the current database connection pool.

Per-investigation stores exposed via ``investigation_stores`` dict (set by
``_run_pipeline_with_events``) take precedence for active pipeline runs.

Use as FastAPI ``Depends()`` parameters::

    @router.get("/facts")
    async def list_facts(
        fact_store: FactStore = Depends(get_fact_store),
    ):
        ...
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from osint_system.api.events.event_bus import PipelineEventBus
    from osint_system.api.events.investigation_registry import InvestigationRegistry
    from osint_system.data_management.article_store import ArticleStore
    from osint_system.data_management.classification_store import ClassificationStore
    from osint_system.data_management.fact_store import FactStore
    from osint_system.data_management.verification_store import VerificationStore
    from osint_system.reporting.report_store import ReportStore


def _get_state_attr(request: Request, attr: str) -> object:
    """Extract an attribute from ``request.app.state``.

    Raises:
        AttributeError: If the attribute is not mounted on app.state.
    """
    try:
        return getattr(request.app.state, attr)
    except AttributeError:
        raise AttributeError(
            f"'{attr}' is not mounted on app.state. "
            f"Ensure it is set during app startup before routes are called."
        ) from None


def get_event_bus(request: Request) -> PipelineEventBus:
    """Return the PipelineEventBus from app.state."""
    return _get_state_attr(request, "event_bus")  # type: ignore[return-value]


def get_registry(request: Request) -> InvestigationRegistry:
    """Return the InvestigationRegistry from app.state."""
    return _get_state_attr(request, "investigation_registry")  # type: ignore[return-value]


def get_fact_store(request: Request) -> FactStore:
    """Return a FactStore backed by the app-level session factory.

    FactStore requires session_factory (mandatory) and accepts
    embedding_service (optional) for pgvector embedding on save.
    """
    from osint_system.data_management.fact_store import FactStore as _FS

    session_factory = _get_state_attr(request, "session_factory")
    embedding_service = getattr(request.app.state, "embedding_service", None)
    return _FS(
        session_factory=session_factory,  # type: ignore[arg-type]
        embedding_service=embedding_service,
    )


def get_classification_store(request: Request) -> ClassificationStore:
    """Return a ClassificationStore backed by the app-level session factory."""
    from osint_system.data_management.classification_store import (
        ClassificationStore as _CS,
    )

    session_factory = _get_state_attr(request, "session_factory")
    return _CS(session_factory=session_factory)  # type: ignore[arg-type]


def get_verification_store(request: Request) -> VerificationStore:
    """Return a VerificationStore backed by the app-level session factory."""
    from osint_system.data_management.verification_store import (
        VerificationStore as _VS,
    )

    session_factory = _get_state_attr(request, "session_factory")
    return _VS(session_factory=session_factory)  # type: ignore[arg-type]


def get_report_store(request: Request) -> ReportStore:
    """Return a ReportStore backed by the app-level session factory.

    ReportStore accepts embedding_service for pgvector embedding on
    executive summaries (STORE-05).
    """
    from osint_system.reporting.report_store import ReportStore as _RS

    session_factory = _get_state_attr(request, "session_factory")
    embedding_service = getattr(request.app.state, "embedding_service", None)
    return _RS(
        session_factory=session_factory,  # type: ignore[arg-type]
        embedding_service=embedding_service,
    )


def get_article_store(request: Request) -> ArticleStore:
    """Return an ArticleStore backed by the app-level session factory.

    ArticleStore requires session_factory (mandatory) and accepts
    embedding_service (optional) for pgvector embedding on save.
    """
    from osint_system.data_management.article_store import ArticleStore as _AS

    session_factory = _get_state_attr(request, "session_factory")
    embedding_service = getattr(request.app.state, "embedding_service", None)
    return _AS(
        session_factory=session_factory,  # type: ignore[arg-type]
        embedding_service=embedding_service,
    )
