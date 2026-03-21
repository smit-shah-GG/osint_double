"""Launch the OSINT system in API mode or dashboard mode.

Usage:
    uv run python -m osint_system.serve
        -> Boots the REST API on port 8000 (all endpoints, new investigations)

    uv run python -m osint_system.serve <investigation_id>
        -> Boots the HTMX dashboard for viewing existing investigation data

API mode starts a full-featured server with SSE streaming, investigation
lifecycle management, and real-time pipeline events. Dashboard mode loads
persisted store data from ``data/<investigation_id>/*.json`` files written
by the InvestigationRunner.
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
    """Boot the HTMX dashboard for viewing existing investigation data."""
    import uvicorn

    from osint_system.config.analysis_config import AnalysisConfig
    from osint_system.dashboard import create_app
    from osint_system.data_management.classification_store import ClassificationStore
    from osint_system.data_management.fact_store import FactStore
    from osint_system.data_management.verification_store import VerificationStore
    from osint_system.reporting import ReportGenerator
    from osint_system.reporting.report_store import ReportStore

    store_dir = Path("data") / investigation_id

    if not store_dir.exists():
        print(f"Error: No data found at {store_dir}")
        print("Run an investigation first with:")
        print(f'  uv run python -m osint_system.cli.main investigate "your topic"')
        sys.exit(1)

    config = AnalysisConfig.from_env()

    # Load stores from persisted JSON files
    articles_path = str(store_dir / "articles.json")
    facts_path = str(store_dir / "facts.json")
    classifications_path = str(store_dir / "classifications.json")
    verifications_path = str(store_dir / "verifications.json")
    reports_path = str(store_dir / "reports.json")

    fact_store = FactStore(persistence_path=facts_path)
    classification_store = ClassificationStore(persistence_path=classifications_path)
    verification_store = VerificationStore(persistence_path=verifications_path)
    report_store = ReportStore(persistence_path=reports_path)

    print("=" * 60)
    print("  OSINT Intelligence System -- Dashboard Mode")
    print("=" * 60)
    print()
    print(f"  Investigation: {investigation_id}")
    print(f"  Store dir:     {store_dir}")
    for p in [articles_path, facts_path, classifications_path, verifications_path, reports_path]:
        exists = Path(p).exists()
        print(f"  {'OK' if exists else 'MISSING'}: {Path(p).name}")
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
