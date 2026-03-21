"""One-time migration script: JSON investigation data -> PostgreSQL.

Scans the ``data/`` directory for investigation directories (pattern
``inv-*``), reads JSON files written by the original in-memory stores,
and inserts records into PostgreSQL via the ORM models.

Idempotent: uses ON CONFLICT DO NOTHING to skip already-migrated records.
Running twice is safe and will not create duplicates.

Usage:
    uv run python scripts/migrate_json_to_postgres.py
    uv run python scripts/migrate_json_to_postgres.py --dry-run
    uv run python scripts/migrate_json_to_postgres.py --data-dir /path/to/data
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("migrate_json_to_postgres")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_article_id(url: str) -> str:
    """Deterministic article_id from URL (SHA256 hex, matches ArticleModel)."""
    return hashlib.sha256(url.encode()).hexdigest()


def _compute_entity_id(investigation_id: str, canonical: str, entity_type: str) -> str:
    """Deterministic entity_id hash (matches FactStore entity extraction)."""
    key = f"{investigation_id}:{canonical}:{entity_type}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _compute_content_hash(content: str) -> str:
    """SHA256 of content string (matches ArticleModel and ReportModel)."""
    return hashlib.sha256(content.encode()).hexdigest()


def _parse_dt(value: Any) -> datetime | None:
    """Parse an ISO datetime string to a timezone-aware datetime, or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        # Python 3.11 fromisoformat handles Z suffix
        s = s.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Migration functions
# ---------------------------------------------------------------------------

async def migrate_articles(
    session_factory: Any,
    investigation_id: str,
    articles_data: list[dict[str, Any]],
    embedding_service: Any | None = None,
) -> int:
    """Insert articles into PostgreSQL. Returns count inserted."""
    from osint_system.data_management.models.article import ArticleModel

    count = 0
    async with session_factory() as session:
        async with session.begin():
            for article in articles_data:
                url = article.get("url", "")
                if not url:
                    continue

                # Use from_dict which handles column mapping correctly
                model = ArticleModel.from_dict(article, investigation_id)

                # Generate embedding if service available
                if embedding_service and model.content:
                    try:
                        text = f"{model.title or ''} {model.content}"[:2000]
                        model.embedding = embedding_service.embed_sync(text)
                    except Exception:
                        pass

                # Upsert via ON CONFLICT on article_id (unique)
                stmt = pg_insert(ArticleModel).values(
                    article_id=model.article_id,
                    investigation_id=model.investigation_id,
                    url=model.url,
                    title=model.title,
                    content=model.content,
                    published_date=model.published_date,
                    source_name=model.source_name,
                    source_domain=model.source_domain,
                    stored_at=model.stored_at,
                    source_metadata=model.source_metadata,
                    article_metadata=model.article_metadata,
                    embedding=model.embedding,
                ).on_conflict_do_nothing(index_elements=["article_id"])

                result = await session.execute(stmt)
                if result.rowcount > 0:
                    count += 1

    return count


async def migrate_facts(
    session_factory: Any,
    investigation_id: str,
    facts_data: dict[str, dict[str, Any]],
    embedding_service: Any | None = None,
) -> tuple[int, int]:
    """Insert facts and extract entities. Returns (facts_count, entities_count)."""
    from osint_system.data_management.models.entity import EntityModel
    from osint_system.data_management.models.fact import FactModel

    fact_count = 0
    entity_count = 0

    async with session_factory() as session:
        async with session.begin():
            for fact_id, fact in facts_data.items():
                claim = fact.get("claim", {})
                claim_text = claim.get("text", "") if isinstance(claim, dict) else ""

                # Build embedding
                embedding = None
                if embedding_service and claim_text:
                    try:
                        embedding = embedding_service.embed_sync(claim_text[:2000])
                    except Exception:
                        pass

                stmt = pg_insert(FactModel).values(
                    investigation_id=investigation_id,
                    fact_id=fact_id,
                    content_hash=fact.get("content_hash", ""),
                    claim_text=claim_text,
                    assertion_type=(
                        claim.get("assertion_type", "statement")
                        if isinstance(claim, dict)
                        else "statement"
                    ),
                    claim_clarity=float(claim.get("claim_clarity", 0.5)) if isinstance(claim, dict) else 0.5,
                    extraction_confidence=float(fact.get("quality", {}).get("extraction_confidence", 0.5) if isinstance(fact.get("quality"), dict) else 0.5),
                    source_url=fact.get("provenance", {}).get("source_url", "") if isinstance(fact.get("provenance"), dict) else "",
                    entities=fact.get("entities", []),
                    temporal=fact.get("temporal"),
                    numeric=fact.get("numeric"),
                    provenance=fact.get("provenance"),
                    quality_metrics=fact.get("quality"),
                    relationships=fact.get("relationships"),
                    variants=fact.get("variants", []),
                    claim_data=claim if isinstance(claim, dict) else {},
                    stored_at=fact.get("stored_at"),
                    embedding=embedding,
                ).on_conflict_do_nothing(index_elements=["fact_id"])

                result = await session.execute(stmt)
                if result.rowcount > 0:
                    fact_count += 1

                # Entity extraction
                entities_list = fact.get("entities", [])
                if isinstance(entities_list, list):
                    for entity_dict in entities_list:
                        if not isinstance(entity_dict, dict):
                            continue
                        name = entity_dict.get("text", entity_dict.get("name", ""))
                        entity_type = entity_dict.get("type", "UNKNOWN")
                        canonical = entity_dict.get("canonical", name)
                        if not name:
                            continue

                        eid = _compute_entity_id(
                            investigation_id, canonical, entity_type
                        )

                        ent_embedding = None
                        if embedding_service and canonical:
                            try:
                                ent_embedding = embedding_service.embed_sync(canonical)
                            except Exception:
                                pass

                        ent_stmt = pg_insert(EntityModel).values(
                            investigation_id=investigation_id,
                            entity_id=eid,
                            name=name,
                            entity_type=entity_type,
                            canonical=canonical,
                            entity_metadata=entity_dict.get("metadata"),
                            embedding=ent_embedding,
                        ).on_conflict_do_nothing(index_elements=["entity_id"])

                        ent_result = await session.execute(ent_stmt)
                        if ent_result.rowcount > 0:
                            entity_count += 1

    return fact_count, entity_count


async def migrate_classifications(
    session_factory: Any,
    investigation_id: str,
    classifications_data: dict[str, dict[str, Any]],
) -> int:
    """Insert classifications into PostgreSQL. Returns count inserted."""
    from osint_system.data_management.models.classification import ClassificationModel

    count = 0
    async with session_factory() as session:
        async with session.begin():
            for fact_id, cls_dict in classifications_data.items():
                cls_id = hashlib.sha256(
                    f"{investigation_id}:{fact_id}".encode()
                ).hexdigest()[:16]

                stmt = pg_insert(ClassificationModel).values(
                    investigation_id=investigation_id,
                    fact_id=fact_id,
                    tier=cls_dict.get("impact_tier", "less_critical"),
                    priority_score=cls_dict.get("priority_score", 0.0),
                    credibility_score=cls_dict.get("credibility_score", 0.0),
                    dubious_flags=cls_dict.get("dubious_flags", []),
                    credibility_breakdown=cls_dict.get("credibility_breakdown"),
                    classification_reasoning=cls_dict.get("classification_reasoning"),
                    impact_reasoning=cls_dict.get("impact_reasoning"),
                    history=cls_dict.get("history", []),
                    classification_data=cls_dict,
                ).on_conflict_do_nothing(
                    index_elements=["investigation_id", "fact_id"]
                )

                result = await session.execute(stmt)
                if result.rowcount > 0:
                    count += 1

    return count


async def migrate_verifications(
    session_factory: Any,
    investigation_id: str,
    verifications_data: dict[str, dict[str, Any]],
) -> int:
    """Insert verifications into PostgreSQL. Returns count inserted."""
    from osint_system.data_management.models.verification import VerificationModel

    count = 0
    async with session_factory() as session:
        async with session.begin():
            for fact_id, ver_dict in verifications_data.items():
                ver_id = hashlib.sha256(
                    f"{investigation_id}:{fact_id}".encode()
                ).hexdigest()[:16]

                stmt = pg_insert(VerificationModel).values(
                    investigation_id=investigation_id,
                    fact_id=fact_id,
                    status=ver_dict.get("status", "pending"),
                    final_confidence=ver_dict.get("final_confidence", 0.0),
                    original_confidence=ver_dict.get("original_confidence", 0.0),
                    confidence_boost=ver_dict.get("confidence_boost", 0.0),
                    supporting_evidence=ver_dict.get("supporting_evidence", []),
                    refuting_evidence=ver_dict.get("refuting_evidence", []),
                    queries_used=ver_dict.get("queries_used", []),
                    search_count=ver_dict.get("query_attempts", 0),
                    origin_dubious_flags=ver_dict.get("origin_dubious_flags", []),
                    reasoning=ver_dict.get("reasoning"),
                    verification_data=ver_dict,
                ).on_conflict_do_nothing(
                    index_elements=["investigation_id", "fact_id"]
                )

                result = await session.execute(stmt)
                if result.rowcount > 0:
                    count += 1

    return count


async def migrate_reports(
    session_factory: Any,
    investigation_id: str,
    reports_data: list[dict[str, Any]],
    embedding_service: Any | None = None,
) -> int:
    """Insert reports into PostgreSQL. Returns count inserted."""
    from osint_system.data_management.models.report import ReportModel

    count = 0
    async with session_factory() as session:
        async with session.begin():
            for report in reports_data:
                version = report.get("version", 1)
                report_id = hashlib.sha256(
                    f"{investigation_id}:v{version}".encode()
                ).hexdigest()[:16]

                content_hash = report.get("content_hash", "")
                synthesis_summary = report.get("synthesis_summary", {})

                # Embedding from executive summary
                embedding = None
                exec_summary = synthesis_summary.get("executive_summary", "")
                if embedding_service and exec_summary:
                    try:
                        embedding = embedding_service.embed_sync(
                            exec_summary[:2000]
                        )
                    except Exception:
                        pass

                # Read markdown content from file if path exists
                markdown_content = ""
                md_path = report.get("markdown_path")
                if md_path and Path(md_path).exists():
                    markdown_content = Path(md_path).read_text(encoding="utf-8")

                stmt = pg_insert(ReportModel).values(
                    investigation_id=investigation_id,
                    version=version,
                    content_hash=content_hash or _compute_content_hash(
                        markdown_content
                    ),
                    markdown_content=markdown_content,
                    markdown_path=str(md_path) if md_path else None,
                    synthesis_summary=synthesis_summary,
                    generated_at=_parse_dt(report.get("generated_at")),
                    embedding=embedding,
                ).on_conflict_do_nothing(index_elements=["investigation_id", "version"])

                result = await session.execute(stmt)
                if result.rowcount > 0:
                    count += 1

    return count


# ---------------------------------------------------------------------------
# Main migration orchestrator
# ---------------------------------------------------------------------------

async def run_migration(
    data_dir: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Scan data_dir for investigation directories and migrate to PostgreSQL.

    Args:
        data_dir: Root data directory containing ``inv-*`` subdirectories.
        dry_run: If True, scan and report but do not insert.

    Returns:
        Summary dict with total counts.
    """
    from osint_system.data_management.database import init_db

    if not data_dir.exists():
        logger.info("No data directory found at %s", data_dir)
        return {"investigations": 0, "error": "No data directory found"}

    # Discover investigation directories
    inv_dirs = sorted(
        d
        for d in data_dir.iterdir()
        if d.is_dir() and d.name.startswith("inv-")
    )

    if not inv_dirs:
        logger.info("No investigation directories found in %s", data_dir)
        return {"investigations": 0}

    logger.info("Found %d investigation directories", len(inv_dirs))

    if dry_run:
        for d in inv_dirs:
            files = [f.name for f in d.iterdir() if f.suffix == ".json"]
            logger.info("  [DRY RUN] %s: %s", d.name, ", ".join(files) or "empty")
        return {"investigations": len(inv_dirs), "dry_run": True}

    # Initialize database
    session_factory = init_db()

    # Optional embedding service
    embedding_service = None
    try:
        from osint_system.data_management.embeddings import EmbeddingService

        embedding_service = EmbeddingService()
        logger.info("EmbeddingService loaded -- embeddings will be generated")
    except ImportError:
        logger.info("sentence-transformers not installed -- skipping embeddings")

    totals = {
        "investigations": 0,
        "articles": 0,
        "facts": 0,
        "entities": 0,
        "classifications": 0,
        "verifications": 0,
        "reports": 0,
    }

    for inv_dir in inv_dirs:
        investigation_id = inv_dir.name
        logger.info("Migrating investigation %s ...", investigation_id)

        # Articles
        articles_path = inv_dir / "articles.json"
        if articles_path.exists():
            with open(articles_path) as f:
                raw = json.load(f)
            # Format: {investigation_id: {articles: [...], ...}}
            inv_data = raw.get(investigation_id, {})
            articles_list = inv_data.get("articles", [])
            n = await migrate_articles(
                session_factory, investigation_id, articles_list,
                embedding_service,
            )
            totals["articles"] += n
            logger.info("  Articles: %d migrated", n)

        # Facts
        facts_path = inv_dir / "facts.json"
        if facts_path.exists():
            with open(facts_path) as f:
                raw = json.load(f)
            inv_data = raw.get(investigation_id, {})
            facts_dict = inv_data.get("facts", {})
            nf, ne = await migrate_facts(
                session_factory, investigation_id, facts_dict,
                embedding_service,
            )
            totals["facts"] += nf
            totals["entities"] += ne
            logger.info("  Facts: %d migrated, Entities: %d extracted", nf, ne)

        # Classifications
        cls_path = inv_dir / "classifications.json"
        if cls_path.exists():
            with open(cls_path) as f:
                raw = json.load(f)
            inv_data = raw.get(investigation_id, {})
            cls_dict = inv_data.get("classifications", {})
            n = await migrate_classifications(
                session_factory, investigation_id, cls_dict,
            )
            totals["classifications"] += n
            logger.info("  Classifications: %d migrated", n)

        # Verifications
        ver_path = inv_dir / "verifications.json"
        if ver_path.exists():
            with open(ver_path) as f:
                raw = json.load(f)
            # Format: {investigation_id: {fact_id: {...}, ...}}
            inv_data = raw.get(investigation_id, {})
            if isinstance(inv_data, dict):
                n = await migrate_verifications(
                    session_factory, investigation_id, inv_data,
                )
                totals["verifications"] += n
                logger.info("  Verifications: %d migrated", n)

        # Reports
        reports_path = inv_dir / "reports.json"
        if reports_path.exists():
            with open(reports_path) as f:
                raw = json.load(f)
            # Format: {investigation_id: [...]}
            reports_list = raw.get(investigation_id, [])
            if isinstance(reports_list, list):
                n = await migrate_reports(
                    session_factory, investigation_id, reports_list,
                    embedding_service,
                )
                totals["reports"] += n
                logger.info("  Reports: %d migrated", n)

        totals["investigations"] += 1

    logger.info("=" * 60)
    logger.info("Migration complete:")
    for key, value in totals.items():
        logger.info("  %-20s %d", key, value)

    return totals


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate JSON investigation data to PostgreSQL",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Root data directory (default: data/)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan and report without inserting",
    )
    args = parser.parse_args()

    # Load .env
    try:
        from dotenv import load_dotenv

        env_path = Path(__file__).resolve().parent.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path)
    except ImportError:
        pass

    result = asyncio.run(run_migration(args.data_dir, dry_run=args.dry_run))
    if result.get("error"):
        sys.exit(1)


if __name__ == "__main__":
    main()
