"""FastAPI application factory with store dependency injection.

Creates the dashboard app with all route modules, static file serving,
and Jinja2 template rendering. Stores are injected via constructor
arguments and mounted on app.state for route-level access.

Usage:
    from osint_system.dashboard import create_app

    app = create_app(fact_store=fs, classification_store=cs)
    # Or with defaults:
    app = create_app()
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from osint_system.dashboard.routes import (
    api,
    facts,
    investigations,
    monitoring,
    reports,
)
from osint_system.data_management.classification_store import ClassificationStore
from osint_system.data_management.fact_store import FactStore
from osint_system.data_management.verification_store import VerificationStore
from osint_system.reporting.report_store import ReportStore

if TYPE_CHECKING:
    from osint_system.config.analysis_config import AnalysisConfig
    from osint_system.pipeline.analysis_pipeline import AnalysisPipeline
    from osint_system.reporting.report_generator import ReportGenerator

# Resolve template and static directories relative to this module
_PACKAGE_DIR = Path(__file__).parent
_TEMPLATES_DIR = _PACKAGE_DIR / "templates"
_STATIC_DIR = _PACKAGE_DIR / "static"


def create_app(
    fact_store: FactStore | None = None,
    classification_store: ClassificationStore | None = None,
    verification_store: VerificationStore | None = None,
    report_store: ReportStore | None = None,
    report_generator: Any | None = None,
    analysis_pipeline: Any | None = None,
    config: Any | None = None,
) -> FastAPI:
    """Create and configure the OSINT Dashboard FastAPI application.

    Mounts static files, sets up Jinja2 templates, injects store
    dependencies onto app.state, and includes all route modules.

    Args:
        fact_store: Shared fact store. Creates empty instance if None.
        classification_store: Shared classification store. Creates empty if None.
        verification_store: Shared verification store. Creates empty if None.
        report_store: Shared report store. Creates empty if None.
        report_generator: Optional ReportGenerator for on-demand generation.
        analysis_pipeline: Optional AnalysisPipeline for full analysis runs.
        config: Optional AnalysisConfig for dashboard settings.

    Returns:
        Configured FastAPI application.
    """
    app = FastAPI(title="OSINT Dashboard")

    # Mount static files
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Set up Jinja2 templates
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    # Inject dependencies onto app.state
    app.state.fact_store = fact_store or FactStore()
    app.state.classification_store = classification_store or ClassificationStore()
    app.state.verification_store = verification_store or VerificationStore()
    app.state.report_store = report_store or ReportStore()
    app.state.report_generator = report_generator
    app.state.analysis_pipeline = analysis_pipeline
    app.state.templates = templates
    app.state.config = config

    # Include route modules
    app.include_router(investigations.router, prefix="", tags=["investigations"])
    app.include_router(facts.router, prefix="/facts", tags=["facts"])
    app.include_router(reports.router, prefix="/reports", tags=["reports"])
    app.include_router(monitoring.router, prefix="/monitoring", tags=["monitoring"])
    app.include_router(api.router, prefix="/api", tags=["api"])

    # Health check endpoint
    @app.get("/health")
    async def health_check() -> dict[str, str]:
        """Return service health status."""
        return {"status": "ok"}

    return app


def run_dashboard(
    host: str = "127.0.0.1",
    port: int = 8080,
    **kwargs: Any,
) -> None:
    """CLI entry point: start the dashboard server via uvicorn.

    Args:
        host: Network interface to bind to.
        port: TCP port to listen on.
        **kwargs: Forwarded to create_app() (store overrides, config, etc.).
    """
    import uvicorn

    app = create_app(**kwargs)
    uvicorn.run(app, host=host, port=port)
