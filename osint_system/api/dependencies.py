"""FastAPI dependency injection helpers for store and service access.

Each function extracts a store or service from ``request.app.state``,
raising ``AttributeError`` with a clear message if the dependency has
not been mounted.  Use as FastAPI ``Depends()`` parameters::

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
    """Return the FactStore from app.state."""
    return _get_state_attr(request, "fact_store")  # type: ignore[return-value]


def get_classification_store(request: Request) -> ClassificationStore:
    """Return the ClassificationStore from app.state."""
    return _get_state_attr(request, "classification_store")  # type: ignore[return-value]


def get_verification_store(request: Request) -> VerificationStore:
    """Return the VerificationStore from app.state."""
    return _get_state_attr(request, "verification_store")  # type: ignore[return-value]


def get_report_store(request: Request) -> ReportStore:
    """Return the ReportStore from app.state."""
    return _get_state_attr(request, "report_store")  # type: ignore[return-value]


def get_article_store(request: Request) -> ArticleStore:
    """Return the ArticleStore from app.state."""
    return _get_state_attr(request, "article_store")  # type: ignore[return-value]
