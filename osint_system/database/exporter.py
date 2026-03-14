"""SQLite database exporter for investigation data.

Creates queryable SQLite databases from FactStore, ClassificationStore,
and VerificationStore data. The exported database uses a normalized
relational schema with proper foreign keys and indexes, enabling
analysts to query investigation data with standard SQL tools.

Per Phase 10 CONTEXT.md: "structured fact database (queryable SQLite/JSON)
for external tool consumption."

Usage:
    from osint_system.database import InvestigationExporter

    exporter = InvestigationExporter(fact_store, classification_store, verification_store)
    db_path = await exporter.export("inv-123")
    # db_path is now a queryable SQLite database
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite
import structlog

from osint_system.data_management.classification_store import ClassificationStore
from osint_system.data_management.fact_store import FactStore
from osint_system.data_management.verification_store import VerificationStore

logger = structlog.get_logger()

# Schema file lives alongside this module
_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class InvestigationExporter:
    """Creates queryable SQLite databases from investigation data.

    Reads from FactStore, ClassificationStore, and VerificationStore,
    then writes normalized tables with proper foreign keys and indexes.
    The resulting database is immediately queryable with any SQLite tool.

    Attributes:
        fact_store: Source of investigation facts.
        classification_store: Source of fact classifications.
        verification_store: Source of verification results.
        output_dir: Default directory for exported databases.
    """

    def __init__(
        self,
        fact_store: FactStore,
        classification_store: ClassificationStore,
        verification_store: VerificationStore,
        output_dir: str = "exports/",
    ) -> None:
        """Initialize InvestigationExporter.

        Args:
            fact_store: FactStore instance with investigation facts.
            classification_store: ClassificationStore instance with classifications.
            verification_store: VerificationStore instance with verification results.
            output_dir: Default output directory for exported databases.
        """
        self.fact_store = fact_store
        self.classification_store = classification_store
        self.verification_store = verification_store
        self.output_dir = Path(output_dir)
        self._log = logger.bind(component="InvestigationExporter")

    async def export(
        self,
        investigation_id: str,
        output_path: str | None = None,
    ) -> Path:
        """Export investigation data to a queryable SQLite database.

        Creates a new SQLite database with the investigation schema,
        then populates all tables from the three stores. The resulting
        .db file can be opened with DB Browser, DBeaver, or any SQLite client.

        Args:
            investigation_id: Investigation to export.
            output_path: Optional explicit output path. If None, uses
                         {output_dir}/{investigation_id}.db.

        Returns:
            Path to the created SQLite database file.
        """
        if output_path is not None:
            db_path = Path(output_path)
        else:
            db_path = self.output_dir / f"{investigation_id}.db"

        db_path.parent.mkdir(parents=True, exist_ok=True)

        # Remove existing file to get a clean export
        if db_path.exists():
            db_path.unlink()

        schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")

        async with aiosqlite.connect(str(db_path)) as db:
            # Enable foreign keys (SQLite has them off by default)
            await db.execute("PRAGMA foreign_keys = ON")

            # Create all tables from schema DDL
            await db.executescript(schema_sql)

            # Export metadata first (other tables reference it via FK)
            await self._export_metadata(db, investigation_id)

            # Export facts and collect them for source/entity extraction
            facts, fact_count = await self._export_facts(db, investigation_id)

            # Export classifications
            classification_count = await self._export_classifications(
                db, investigation_id
            )

            # Export verification results
            verification_count = await self._export_verification_results(
                db, investigation_id
            )

            # Derive source and entity tables from facts
            source_count = await self._export_sources(db, investigation_id, facts)
            entity_count = await self._export_entities(db, investigation_id, facts)

            await db.commit()

        self._log.info(
            "export_complete",
            investigation_id=investigation_id,
            db_path=str(db_path),
            facts=fact_count,
            classifications=classification_count,
            verifications=verification_count,
            sources=source_count,
            entities=entity_count,
        )

        return db_path

    async def _export_metadata(
        self,
        db: aiosqlite.Connection,
        investigation_id: str,
    ) -> None:
        """Export investigation metadata to investigation_metadata table.

        Args:
            db: Active aiosqlite connection.
            investigation_id: Investigation to export metadata for.
        """
        result = await self.fact_store.retrieve_by_investigation(investigation_id)
        metadata = result.get("metadata", {})
        now = datetime.now(timezone.utc).isoformat()

        await db.execute(
            """INSERT INTO investigation_metadata
               (investigation_id, objective, created_at, updated_at, metadata_json)
               VALUES (?, ?, ?, ?, ?)""",
            (
                investigation_id,
                metadata.get("objective", ""),
                result.get("created_at", now),
                result.get("updated_at", now),
                json.dumps(metadata, default=str),
            ),
        )

    async def _export_facts(
        self,
        db: aiosqlite.Connection,
        investigation_id: str,
    ) -> tuple[list[dict[str, Any]], int]:
        """Export facts to facts table.

        Args:
            db: Active aiosqlite connection.
            investigation_id: Investigation to export facts for.

        Returns:
            Tuple of (list of fact dicts for downstream processing, row count).
        """
        result = await self.fact_store.retrieve_by_investigation(investigation_id)
        facts = result.get("facts", [])

        for fact in facts:
            # Extract claim fields
            claim = fact.get("claim", {})
            if isinstance(claim, dict):
                claim_text = claim.get("text", "")
                assertion_type = claim.get("assertion_type", "statement")
                claim_type = claim.get("claim_type", "event")
            else:
                claim_text = str(claim)
                assertion_type = "statement"
                claim_type = "event"

            # Extract quality metrics
            quality = fact.get("quality", {}) or {}
            extraction_confidence = quality.get("extraction_confidence")
            claim_clarity = quality.get("claim_clarity")

            # Extract temporal info
            temporal = fact.get("temporal", {}) or {}
            temporal_value = temporal.get("value") if temporal else None
            temporal_precision = temporal.get("temporal_precision") if temporal else None

            # Serialize complex fields to JSON
            provenance = fact.get("provenance", {}) or {}
            entities = fact.get("entities", []) or []

            await db.execute(
                """INSERT INTO facts
                   (fact_id, investigation_id, claim_text, assertion_type,
                    claim_type, content_hash, extraction_confidence, claim_clarity,
                    temporal_value, temporal_precision, provenance_json,
                    entities_json, stored_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    fact.get("fact_id", ""),
                    investigation_id,
                    claim_text,
                    assertion_type,
                    claim_type,
                    fact.get("content_hash", ""),
                    extraction_confidence,
                    claim_clarity,
                    temporal_value,
                    temporal_precision,
                    json.dumps(provenance, default=str),
                    json.dumps(entities, default=str),
                    fact.get("stored_at", ""),
                ),
            )

        return facts, len(facts)

    async def _export_classifications(
        self,
        db: aiosqlite.Connection,
        investigation_id: str,
    ) -> int:
        """Export classifications to classifications table.

        Args:
            db: Active aiosqlite connection.
            investigation_id: Investigation to export classifications for.

        Returns:
            Number of rows exported.
        """
        classifications = await self.classification_store.get_all_classifications(
            investigation_id
        )

        for classification in classifications:
            dubious_flags = classification.get("dubious_flags", [])
            reasoning = classification.get("classification_reasoning", [])
            classified_at = classification.get("classified_at")
            if classified_at and not isinstance(classified_at, str):
                classified_at = str(classified_at)

            await db.execute(
                """INSERT INTO classifications
                   (fact_id, investigation_id, impact_tier, dubious_flags_json,
                    priority_score, credibility_score,
                    classification_reasoning_json, classified_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    classification.get("fact_id", ""),
                    investigation_id,
                    classification.get("impact_tier", "less_critical"),
                    json.dumps(dubious_flags, default=str),
                    classification.get("priority_score", 0.0),
                    classification.get("credibility_score", 0.0),
                    json.dumps(reasoning, default=str),
                    classified_at,
                ),
            )

        return len(classifications)

    async def _export_verification_results(
        self,
        db: aiosqlite.Connection,
        investigation_id: str,
    ) -> int:
        """Export verification results to verification_results table.

        Args:
            db: Active aiosqlite connection.
            investigation_id: Investigation to export results for.

        Returns:
            Number of rows exported.
        """
        results = await self.verification_store.get_all_results(investigation_id)

        for record in results:
            data = record.model_dump(mode="json")

            verified_at = data.get("verified_at")
            if verified_at and not isinstance(verified_at, str):
                verified_at = str(verified_at)

            await db.execute(
                """INSERT INTO verification_results
                   (fact_id, investigation_id, verification_status,
                    original_confidence, confidence_boost, final_confidence,
                    query_attempts, queries_used_json,
                    supporting_evidence_json, refuting_evidence_json,
                    origin_dubious_flags_json, reasoning, verified_at,
                    requires_human_review, human_review_completed)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data.get("fact_id", ""),
                    investigation_id,
                    data.get("status", "pending"),
                    data.get("original_confidence", 0.0),
                    data.get("confidence_boost", 0.0),
                    data.get("final_confidence", 0.0),
                    data.get("query_attempts", 0),
                    json.dumps(data.get("queries_used", []), default=str),
                    json.dumps(data.get("supporting_evidence", []), default=str),
                    json.dumps(data.get("refuting_evidence", []), default=str),
                    json.dumps(data.get("origin_dubious_flags", []), default=str),
                    data.get("reasoning", ""),
                    verified_at,
                    1 if data.get("requires_human_review", False) else 0,
                    1 if data.get("human_review_completed", False) else 0,
                ),
            )

        return len(results)

    async def _export_sources(
        self,
        db: aiosqlite.Connection,
        investigation_id: str,
        facts: list[dict[str, Any]],
    ) -> int:
        """Build and export source inventory from fact provenance data.

        Groups facts by source_id, counts facts per source, and extracts
        source metadata from provenance.

        Args:
            db: Active aiosqlite connection.
            investigation_id: Investigation scope.
            facts: List of fact dicts (already fetched for facts table).

        Returns:
            Number of source rows exported.
        """
        sources: dict[str, dict[str, Any]] = {}

        for fact in facts:
            provenance = fact.get("provenance", {}) or {}
            if not isinstance(provenance, dict):
                continue

            source_id = provenance.get("source_id")
            if not source_id:
                continue

            if source_id not in sources:
                # Extract source metadata from provenance
                source_type = provenance.get("source_type", "unknown")
                # Derive domain from source_id or attribution chain
                source_domain = provenance.get("source_domain", "")
                # Estimate authority from source type
                authority_map = {
                    "wire_service": 0.9,
                    "official_statement": 0.85,
                    "news_outlet": 0.5,
                    "social_media": 0.3,
                    "academic": 0.8,
                    "document": 0.6,
                    "eyewitness": 0.7,
                    "unknown": 0.4,
                }
                authority_score = authority_map.get(source_type, 0.4)

                sources[source_id] = {
                    "source_id": source_id,
                    "source_domain": source_domain,
                    "source_type": source_type,
                    "authority_score": authority_score,
                    "fact_count": 0,
                }

            sources[source_id]["fact_count"] += 1

        for source in sources.values():
            await db.execute(
                """INSERT INTO sources
                   (source_id, source_domain, source_type, authority_score,
                    fact_count, investigation_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    source["source_id"],
                    source["source_domain"],
                    source["source_type"],
                    source["authority_score"],
                    source["fact_count"],
                    investigation_id,
                ),
            )

        return len(sources)

    async def _export_entities(
        self,
        db: aiosqlite.Connection,
        investigation_id: str,
        facts: list[dict[str, Any]],
    ) -> int:
        """Extract and export unique entities from fact entity lists.

        Groups entities by canonical name (or text if no canonical),
        tracks which fact_ids mention each entity.

        Args:
            db: Active aiosqlite connection.
            investigation_id: Investigation scope.
            facts: List of fact dicts (already fetched for facts table).

        Returns:
            Number of entity rows exported.
        """
        # entity_key -> entity metadata
        entities: dict[str, dict[str, Any]] = {}

        for fact in facts:
            fact_id = fact.get("fact_id", "")
            entity_list = fact.get("entities", []) or []

            for entity in entity_list:
                if not isinstance(entity, dict):
                    continue

                entity_id = entity.get("id", "")
                name = entity.get("text", "")
                canonical = entity.get("canonical", name)
                entity_type = entity.get("type", "")

                # Use canonical as grouping key for deduplication
                entity_key = f"{canonical or name}:{entity_type}"

                if entity_key not in entities:
                    entities[entity_key] = {
                        # Use entity_key as database ID since entity.id
                        # (E1, E2, etc.) is per-fact local, not globally unique
                        "entity_id": entity_key,
                        "name": name,
                        "canonical": canonical,
                        "entity_type": entity_type,
                        "fact_ids": [],
                    }

                if fact_id not in entities[entity_key]["fact_ids"]:
                    entities[entity_key]["fact_ids"].append(fact_id)

        for entity in entities.values():
            await db.execute(
                """INSERT INTO entities
                   (entity_id, investigation_id, name, canonical,
                    entity_type, fact_ids_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    entity["entity_id"],
                    investigation_id,
                    entity["name"],
                    entity["canonical"],
                    entity["entity_type"],
                    json.dumps(entity["fact_ids"]),
                ),
            )

        return len(entities)
