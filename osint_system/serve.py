"""Launch the OSINT dashboard server with persisted investigation data.

Usage:
    uv run python -m osint_system.serve <investigation_id>

Loads store data from data/<investigation_id>/*.json files written by
the InvestigationRunner.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
    except ImportError:
        pass

    if len(sys.argv) < 2:
        print("Usage: uv run python -m osint_system.serve <investigation_id>")
        print("\nAvailable investigations:")
        data_dir = Path("data")
        if data_dir.exists():
            for d in sorted(data_dir.iterdir()):
                if d.is_dir() and d.name.startswith("inv-"):
                    files = list(d.glob("*.json"))
                    print(f"  {d.name}  ({len(files)} store files)")
        sys.exit(1)

    investigation_id = sys.argv[1]
    store_dir = Path("data") / investigation_id

    if not store_dir.exists():
        print(f"Error: No data found at {store_dir}")
        print("Run an investigation first with:")
        print(f'  uv run python -m osint_system.cli.main investigate "your topic"')
        sys.exit(1)

    from osint_system.config.analysis_config import AnalysisConfig
    from osint_system.data_management.article_store import ArticleStore
    from osint_system.data_management.classification_store import ClassificationStore
    from osint_system.data_management.fact_store import FactStore
    from osint_system.data_management.verification_store import VerificationStore
    from osint_system.reporting import ReportGenerator
    from osint_system.reporting.report_store import ReportStore
    from osint_system.dashboard import create_app

    import uvicorn

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

    print(f"Loaded investigation: {investigation_id}")
    print(f"  Store dir: {store_dir}")
    for p in [articles_path, facts_path, classifications_path, verifications_path, reports_path]:
        exists = Path(p).exists()
        print(f"  {'OK' if exists else 'MISSING'}: {Path(p).name}")

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
    print(f"\nDashboard: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
