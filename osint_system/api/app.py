"""FastAPI application factory for the OSINT intelligence REST API.

``create_api_app()`` returns a fully configured FastAPI instance with:

- All 6 route modules mounted (investigations, stream, facts, reports,
  sources, graph) providing 15+ endpoints under ``/api/v1``.
- CORS middleware for frontend development servers (Next.js, Vite).
- RFC 7807 error handlers (``application/problem+json``).
- ``app.state`` initialized with event bus, investigation registry, and
  empty dicts for per-investigation stores, tasks, and cancellation flags.
- A ``/api/v1/health`` endpoint for readiness probes.
- A lifespan handler that cancels all active pipeline tasks on shutdown.

Usage::

    from osint_system.api.app import create_api_app

    app = create_api_app()
    # uvicorn.run(app, host="0.0.0.0", port=8000)
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

logger = structlog.get_logger(__name__)

from osint_system.api.errors import register_error_handlers
from osint_system.api.events.event_bus import PipelineEventBus
from osint_system.api.events.investigation_registry import InvestigationRegistry
from osint_system.api.routes import (
    facts,
    graph,
    investigations,
    reports,
    sources,
    stream,
)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifespan context manager for startup/shutdown logic.

    Startup: initializes PostgreSQL connection pool and EmbeddingService.
    Shutdown: cancels active pipeline tasks, disposes database engine.
    """
    from osint_system.data_management.database import close_db, init_db

    # ── Startup ───────────────────────────────────────────────────────
    session_factory = init_db()
    app.state.session_factory = session_factory

    # EmbeddingService -- graceful degradation if sentence-transformers
    # is not installed (CI, lightweight deployments).
    embedding_service = None
    try:
        from osint_system.data_management.embeddings import EmbeddingService

        embedding_service = EmbeddingService()
    except ImportError:
        pass
    app.state.embedding_service = embedding_service

    # Wire session_factory into registry (constructed before lifespan runs)
    registry = getattr(app.state, "investigation_registry", None)
    if registry is not None:
        registry._session_factory = session_factory

    # Hydrate investigation registry from PostgreSQL (survives restarts)
    if registry is not None and hasattr(registry, "hydrate_from_db"):
        count = await registry.hydrate_from_db()
        if count:
            logger.info("investigations_loaded_from_db", count=count)

    yield

    # ── Shutdown ──────────────────────────────────────────────────────
    # Cancel active pipeline tasks
    tasks: dict[str, asyncio.Task] = getattr(
        app.state, "active_tasks", {},
    )
    pending = [t for t in tasks.values() if not t.done()]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    # Dispose database connection pool
    await close_db()


def create_api_app() -> FastAPI:
    """Create and configure the OSINT Intelligence System API.

    Returns:
        A fully wired FastAPI application ready for ``uvicorn.run()``.
    """

    app = FastAPI(
        title="OSINT Intelligence System API",
        version="2.0.0",
        description=(
            "REST API for launching, monitoring, and reviewing "
            "OSINT investigations"
        ),
        lifespan=_lifespan,
    )

    # ── CORS middleware (frontend dev servers) ────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",   # Next.js dev server
            "http://localhost:5173",   # Vite dev server
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── RFC 7807 error handlers ──────────────────────────────────────
    register_error_handlers(app)

    # ── app.state initialization ─────────────────────────────────────
    app.state.event_bus = PipelineEventBus()
    app.state.investigation_registry = InvestigationRegistry(
        session_factory=getattr(app.state, "session_factory", None),
    )
    app.state.active_tasks: dict[str, asyncio.Task] = {}  # type: ignore[annotation-unchecked]
    app.state.cancel_flags: dict[str, asyncio.Event] = {}  # type: ignore[annotation-unchecked]
    app.state.investigation_stores: dict[str, dict] = {}  # type: ignore[annotation-unchecked]
    app.state.graph_pipelines: dict = {}  # type: ignore[annotation-unchecked]
    app.state.graph_adapters: dict = {}  # type: ignore[annotation-unchecked]

    # ── Route modules ────────────────────────────────────────────────
    app.include_router(investigations.router)
    app.include_router(stream.router)
    app.include_router(facts.router)
    app.include_router(reports.router)
    app.include_router(sources.router)
    app.include_router(graph.router)

    # ── Health check ─────────────────────────────────────────────────

    @app.get("/api/v1/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        """Readiness probe for the API server."""
        return {"status": "ok"}

    return app
