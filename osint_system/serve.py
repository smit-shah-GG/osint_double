"""Launch the OSINT system in API mode or dashboard mode.

Usage:
    uv run python -m osint_system.serve
        -> Boots the REST API on port 8000 (all endpoints, new investigations)

    uv run python -m osint_system.serve <investigation_id>
        -> Boots the HTMX dashboard for viewing existing investigation data

API mode starts a full-featured server with SSE streaming, investigation
lifecycle management, and real-time pipeline events. Dashboard mode connects
to the same PostgreSQL database used by the InvestigationRunner.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _run_api_mode() -> None:
    """Boot the REST API server with all endpoints."""
    import uvicorn

    from osint_system.api.app import create_api_app

    app = create_api_app()

    host = "0.0.0.0"
    port = 8000

    print("=" * 60)
    print("  OSINT Intelligence System -- API Mode")
    print("=" * 60)
    print()
    print(f"  Server:   http://{host}:{port}")
    print(f"  Docs:     http://localhost:{port}/docs")
    print(f"  OpenAPI:  http://localhost:{port}/openapi.json")
    print(f"  Health:   http://localhost:{port}/api/v1/health")
    print()
    print("  Endpoints:")
    print("    POST   /api/v1/investigations         Launch investigation")
    print("    GET    /api/v1/investigations         List investigations")
    print("    GET    /api/v1/investigations/{id}    Investigation detail")
    print("    DELETE /api/v1/investigations/{id}    Remove investigation")
    print("    POST   /api/v1/investigations/{id}/cancel      Cancel")
    print("    POST   /api/v1/investigations/{id}/regenerate  Regenerate")
    print("    GET    /api/v1/investigations/{id}/stream      SSE events")
    print("    GET    /api/v1/investigations/{id}/facts       Facts list")
    print("    GET    /api/v1/investigations/{id}/facts/{fid} Fact detail")
    print("    GET    /api/v1/investigations/{id}/reports     Report list")
    print("    GET    /api/v1/investigations/{id}/reports/latest  Latest")
    print("    GET    /api/v1/investigations/{id}/reports/{v} Version")
    print("    GET    /api/v1/investigations/{id}/sources     Sources")
    print("    GET    /api/v1/investigations/{id}/graph/nodes Graph nodes")
    print("    GET    /api/v1/investigations/{id}/graph/edges Graph edges")
    print("    GET    /api/v1/investigations/{id}/graph/query Graph query")
    print("    GET    /api/v1/health                          Health check")
    print()
    print("=" * 60)

    uvicorn.run(app, host=host, port=port)


def _run_dashboard_mode(investigation_id: str) -> None:
    """Boot the HTMX dashboard for viewing existing investigation data.

    Connects to PostgreSQL via init_db() and queries the given
    investigation_id. No JSON files needed -- data lives in the database.
    """
    import uvicorn

    from osint_system.config.analysis_config import AnalysisConfig
    from osint_system.dashboard import create_app
    from osint_system.data_management.classification_store import ClassificationStore
    from osint_system.data_management.database import init_db
    from osint_system.data_management.fact_store import FactStore
    from osint_system.data_management.verification_store import VerificationStore
    from osint_system.reporting import ReportGenerator
    from osint_system.reporting.report_store import ReportStore

    config = AnalysisConfig.from_env()

    # Initialize database and create stores backed by PostgreSQL
    session_factory = init_db()

    fact_store = FactStore(session_factory=session_factory)
    classification_store = ClassificationStore(session_factory=session_factory)
    verification_store = VerificationStore(session_factory=session_factory)
    report_store = ReportStore(session_factory=session_factory)

    print("=" * 60)
    print("  OSINT Intelligence System -- Dashboard Mode")
    print("=" * 60)
    print()
    print(f"  Investigation: {investigation_id}")
    print(f"  Backend:       PostgreSQL")
    print()

    app = create_app(
        fact_store=fact_store,
        classification_store=classification_store,
        verification_store=verification_store,
        report_store=report_store,
        report_generator=ReportGenerator(config=config),
        config=config,
    )

    host = config.dashboard_host
    port = config.dashboard_port
    print(f"  Dashboard: http://{host}:{port}")
    print("=" * 60)
    uvicorn.run(app, host=host, port=port)


def main() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
    except ImportError:
        pass

    if len(sys.argv) < 2:
        # No arguments -> API mode
        _run_api_mode()
    else:
        # With investigation_id -> Dashboard mode
        _run_dashboard_mode(sys.argv[1])


if __name__ == "__main__":
    main()
