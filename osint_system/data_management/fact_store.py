"""PostgreSQL-backed fact storage with optional embedding and entity extraction.

Replaces the original in-memory+JSON FactStore with SQLAlchemy async
sessions against PostgreSQL.  All public method signatures and return
types are identical to the original implementation.

Embedding wiring:
    If ``EmbeddingService`` is injected, ``save_facts()`` generates a
    1024-dim vector from ``claim_text`` and writes it to
    ``FactModel.embedding`` for pgvector semantic search.

Entity extraction:
    On each fact save, the JSONB ``entities`` array is iterated and each
    entity is upserted into the ``entities`` table via ``EntityModel``.
    This ensures the entities table is populated incrementally as facts
    are ingested -- no separate population step is needed.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from loguru import logger
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from osint_system.data_management.embeddings import EmbeddingService

from osint_system.data_management.models.entity import EntityModel
from osint_system.data_management.models.fact import FactModel

# Stdlib logger for entity extraction warnings (loguru for main flow)
_log = logging.getLogger(__name__)


class FactStore:
    """PostgreSQL-backed storage for extracted facts.

    Provides investigation-scoped persistence with content-hash
    deduplication, variant linking, and entity extraction.

    Args:
        session_factory: An ``async_sessionmaker[AsyncSession]`` obtained
            from ``database.init_db()``.
        embedding_service: Optional ``EmbeddingService`` for populating
            the pgvector embedding column on each fact at save time.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedding_service: Optional[EmbeddingService] = None,
    ) -> None:
        self._session_factory = session_factory
        self._embedding_service = embedding_service
        self.logger = logger.bind(component="FactStore")
        self.logger.info(
            "FactStore initialized (PostgreSQL)",
            embedding_enabled=embedding_service is not None,
        )

    # ------------------------------------------------------------------
    # save_facts
    # ------------------------------------------------------------------

    async def save_facts(
        self,
        investigation_id: str,
        facts: List[Dict[str, Any]],
        investigation_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Save facts for a specific investigation.

        Detects duplicates by ``fact_id`` (unique constraint).  Content-hash
        collisions trigger variant linking.

        Args:
            investigation_id: Unique investigation identifier.
            facts: List of fact dicts (ExtractedFact-like).
            investigation_metadata: Unused (kept for interface compat).

        Returns:
            Dict with saved, updated, skipped, total counts.
        """
        saved_count = 0
        updated_count = 0
        skipped_count = 0

        async with self._session_factory() as session:
            async with session.begin():
                for fact_data in facts:
                    fact_id = fact_data.get("fact_id")
                    if not fact_id:
                        self.logger.warning("Fact missing fact_id, skipping")
                        skipped_count += 1
                        continue

                    # Check if this exact fact_id already exists
                    existing = (
                        await session.execute(
                            select(FactModel).where(FactModel.fact_id == fact_id)
                        )
                    ).scalar_one_or_none()

                    if existing is not None:
                        self.logger.debug(f"Fact {fact_id} already exists, skipping")
                        skipped_count += 1
                        continue

                    # Stamp storage time and ensure variants list
                    enriched = {
                        **fact_data,
                        "stored_at": datetime.now(timezone.utc).isoformat(),
                        "variants": fact_data.get("variants", []),
                    }

                    model = FactModel.from_dict(enriched, investigation_id)

                    # Generate embedding if service available
                    if self._embedding_service is not None:
                        model.embedding = await self._embedding_service.embed(
                            model.claim_text
                        )

                    # Variant linking: check for hash duplicates within
                    # this investigation
                    content_hash = model.content_hash
                    if content_hash:
                        hash_matches = (
                            await session.execute(
                                select(FactModel).where(
                                    FactModel.content_hash == content_hash,
                                    FactModel.investigation_id == investigation_id,
                                )
                            )
                        ).scalars().all()

                        if hash_matches:
                            canonical = hash_matches[0]
                            # Append this fact_id to canonical's variants
                            canonical_variants = list(canonical.variants or [])
                            if fact_id not in canonical_variants:
                                canonical_variants.append(fact_id)
                                canonical.variants = canonical_variants

                            # Link back: mark canonical in new fact's variants
                            new_variants = list(model.variants or [])
                            if canonical.fact_id not in new_variants:
                                new_variants.append(canonical.fact_id)
                                model.variants = new_variants

                            updated_count += 1
                            self.logger.debug(
                                f"Linked {fact_id} as variant of {canonical.fact_id}"
                            )

                    session.add(model)
                    saved_count += 1

                    # ---- Entity extraction ----
                    await self._extract_and_upsert_entities(
                        session, investigation_id, enriched
                    )

                    self.logger.debug(f"Saved fact: {fact_id}")

            # Total facts for this investigation (outside transaction)
            total_q = (
                select(func.count())
                .select_from(FactModel)
                .where(FactModel.investigation_id == investigation_id)
            )
            total = (await session.execute(total_q)).scalar() or 0

        stats: Dict[str, Any] = {
            "saved": saved_count,
            "updated": updated_count,
            "skipped": skipped_count,
            "total": total,
        }
        self.logger.info(
            f"Saved facts for investigation {investigation_id}",
            **stats,
        )
        return stats

    # ------------------------------------------------------------------
    # Entity extraction helper
    # ------------------------------------------------------------------

    async def _extract_and_upsert_entities(
        self,
        session: AsyncSession,
        investigation_id: str,
        fact_data: Dict[str, Any],
    ) -> None:
        """Extract entities from a fact dict and upsert into entities table.

        Iterates the ``entities`` list from the fact JSONB and performs
        INSERT ON CONFLICT DO UPDATE for each entity.  Failures are logged
        but do not abort the fact save.

        Args:
            session: Active session (inside a transaction).
            investigation_id: Investigation scope.
            fact_data: Full fact dict containing ``entities`` list.
        """
        entities_raw = fact_data.get("entities", [])
        if not entities_raw:
            return

        for ent in entities_raw:
            try:
                if not isinstance(ent, dict):
                    continue

                name = ent.get("text", ent.get("name", ""))
                entity_type = ent.get("type", ent.get("entity_type", ""))
                canonical = ent.get("canonical", name)

                if not name:
                    continue

                # Deterministic entity_id from (investigation, canonical, type)
                hash_input = f"{investigation_id}:{canonical}:{entity_type}"
                entity_id = hashlib.sha256(
                    hash_input.encode("utf-8")
                ).hexdigest()[:64]

                # Collect metadata
                metadata: Dict[str, Any] = {}
                if ent.get("cluster_id"):
                    metadata["cluster_id"] = ent["cluster_id"]
                if ent.get("id"):
                    metadata["marker_id"] = ent["id"]

                # Prepare embedding if service available
                embedding = None
                if self._embedding_service is not None:
                    embedding = await self._embedding_service.embed(canonical or name)

                stmt = pg_insert(EntityModel).values(
                    entity_id=entity_id,
                    investigation_id=investigation_id,
                    name=name,
                    entity_type=entity_type or None,
                    canonical=canonical,
                    entity_metadata=metadata if metadata else None,
                    embedding=embedding,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["entity_id"],
                    set_={
                        "updated_at": func.now(),
                    },
                )
                await session.execute(stmt)

            except Exception:
                _log.warning(
                    "Failed to extract/upsert entity from fact",
                    exc_info=True,
                )

    # ------------------------------------------------------------------
    # get_fact
    # ------------------------------------------------------------------

    async def get_fact(
        self,
        investigation_id: str,
        fact_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve a single fact by ID within an investigation.

        Args:
            investigation_id: Investigation identifier.
            fact_id: Fact identifier.

        Returns:
            Fact dict if found, None otherwise.
        """
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(FactModel).where(
                        FactModel.fact_id == fact_id,
                        FactModel.investigation_id == investigation_id,
                    )
                )
            ).scalar_one_or_none()

            return row.to_dict() if row else None

    # ------------------------------------------------------------------
    # get_fact_by_id
    # ------------------------------------------------------------------

    async def get_fact_by_id(self, fact_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a fact by ID without specifying investigation.

        Args:
            fact_id: Fact identifier.

        Returns:
            Fact dict if found, None otherwise.
        """
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(FactModel).where(FactModel.fact_id == fact_id)
                )
            ).scalar_one_or_none()

            return row.to_dict() if row else None

    # ------------------------------------------------------------------
    # get_facts_by_hash
    # ------------------------------------------------------------------

    async def get_facts_by_hash(
        self,
        content_hash: str,
        investigation_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve all facts with a given content hash.

        Args:
            content_hash: SHA256 content hash.
            investigation_id: Optional filter by investigation.

        Returns:
            List of fact dicts with matching hash.
        """
        async with self._session_factory() as session:
            q = select(FactModel).where(FactModel.content_hash == content_hash)

            if investigation_id is not None:
                q = q.where(FactModel.investigation_id == investigation_id)

            rows = (await session.execute(q)).scalars().all()
            return [row.to_dict() for row in rows]

    # ------------------------------------------------------------------
    # get_facts_by_source
    # ------------------------------------------------------------------

    async def get_facts_by_source(
        self,
        source_id: str,
        investigation_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve all facts from a given source.

        Uses JSONB containment query on the provenance column.

        Args:
            source_id: Source identifier (typically URL).
            investigation_id: Optional filter by investigation.

        Returns:
            List of fact dicts from the source.
        """
        async with self._session_factory() as session:
            # provenance is JSONB with {"source_id": "..."} structure
            q = select(FactModel).where(
                FactModel.provenance["source_id"].astext == source_id,
            )

            if investigation_id is not None:
                q = q.where(FactModel.investigation_id == investigation_id)

            rows = (await session.execute(q)).scalars().all()
            return [row.to_dict() for row in rows]

    # ------------------------------------------------------------------
    # retrieve_by_investigation
    # ------------------------------------------------------------------

    async def retrieve_by_investigation(
        self,
        investigation_id: str,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Retrieve all facts for a specific investigation.

        Args:
            investigation_id: Investigation identifier.
            limit: Max facts to return (None = all).
            offset: Number of facts to skip.

        Returns:
            Dict with investigation_id, metadata, facts list,
            total_facts, returned_facts.
        """
        async with self._session_factory() as session:
            count_q = (
                select(func.count())
                .select_from(FactModel)
                .where(FactModel.investigation_id == investigation_id)
            )
            total = (await session.execute(count_q)).scalar() or 0

            if total == 0:
                return {
                    "investigation_id": investigation_id,
                    "metadata": {},
                    "facts": [],
                    "total_facts": 0,
                    "returned_facts": 0,
                }

            q = (
                select(FactModel)
                .where(FactModel.investigation_id == investigation_id)
                .order_by(FactModel.id)
                .offset(offset)
            )
            if limit:
                q = q.limit(limit)

            rows = (await session.execute(q)).scalars().all()
            facts = [row.to_dict() for row in rows]

            return {
                "investigation_id": investigation_id,
                "metadata": {},
                "created_at": None,
                "updated_at": None,
                "facts": facts,
                "total_facts": total,
                "returned_facts": len(facts),
            }

    # ------------------------------------------------------------------
    # check_hash_exists
    # ------------------------------------------------------------------

    async def check_hash_exists(
        self,
        content_hash: str,
        investigation_id: Optional[str] = None,
    ) -> bool:
        """Check if a content hash exists.

        Args:
            content_hash: SHA256 content hash to check.
            investigation_id: Optional filter by investigation.

        Returns:
            True if hash exists, False otherwise.
        """
        async with self._session_factory() as session:
            q = select(func.count()).select_from(FactModel).where(
                FactModel.content_hash == content_hash,
            )
            if investigation_id is not None:
                q = q.where(FactModel.investigation_id == investigation_id)

            count = (await session.execute(q)).scalar() or 0
            return count > 0

    # ------------------------------------------------------------------
    # get_stats
    # ------------------------------------------------------------------

    async def get_stats(self, investigation_id: str) -> Dict[str, Any]:
        """Get statistics for an investigation.

        Args:
            investigation_id: Investigation identifier.

        Returns:
            Dict with exists flag, counts, and source breakdown.
        """
        async with self._session_factory() as session:
            q = select(FactModel).where(
                FactModel.investigation_id == investigation_id,
            )
            rows = (await session.execute(q)).scalars().all()

            if not rows:
                return {
                    "exists": False,
                    "investigation_id": investigation_id,
                }

            source_counts: Dict[str, int] = {}
            variant_count = 0
            unique_hashes: set[str] = set()
            hash_collision_count = 0

            for row in rows:
                # Source breakdown from provenance JSONB
                prov = row.provenance
                if isinstance(prov, dict):
                    src = prov.get("source_id", "")
                    if src:
                        source_counts[src] = source_counts.get(src, 0) + 1

                # Variant tracking
                if row.variants:
                    variant_count += 1

                # Unique hashes
                ch = row.content_hash or ""
                if ch:
                    if ch in unique_hashes:
                        hash_collision_count += 1
                    unique_hashes.add(ch)

            return {
                "exists": True,
                "investigation_id": investigation_id,
                "total_facts": len(rows),
                "unique_claims": len(unique_hashes),
                "facts_with_variants": variant_count,
                "created_at": None,
                "updated_at": None,
                "source_breakdown": source_counts,
                "metadata": {},
            }

    # ------------------------------------------------------------------
    # list_investigations
    # ------------------------------------------------------------------

    async def list_investigations(self) -> List[Dict[str, Any]]:
        """List all investigations in the store.

        Returns:
            List of investigation summary dicts.
        """
        async with self._session_factory() as session:
            q = (
                select(
                    FactModel.investigation_id,
                    func.count().label("cnt"),
                )
                .group_by(FactModel.investigation_id)
            )
            rows = (await session.execute(q)).all()

            return [
                {
                    "investigation_id": row.investigation_id,
                    "fact_count": row.cnt,
                    "created_at": None,
                    "updated_at": None,
                    "metadata": {},
                }
                for row in rows
            ]

    # ------------------------------------------------------------------
    # delete_investigation
    # ------------------------------------------------------------------

    async def delete_investigation(self, investigation_id: str) -> bool:
        """Delete an investigation and all its facts.

        Also deletes associated entities for the investigation.

        Args:
            investigation_id: Investigation identifier.

        Returns:
            True if any rows deleted, False if not found.
        """
        async with self._session_factory() as session:
            async with session.begin():
                # Delete entities first (no FK, but maintain consistency)
                await session.execute(
                    delete(EntityModel).where(
                        EntityModel.investigation_id == investigation_id,
                    )
                )
                # Delete facts
                result = await session.execute(
                    delete(FactModel).where(
                        FactModel.investigation_id == investigation_id,
                    )
                )

        deleted = (result.rowcount or 0) > 0
        if deleted:
            self.logger.info(f"Deleted investigation: {investigation_id}")
        return deleted

    # ------------------------------------------------------------------
    # link_variants
    # ------------------------------------------------------------------

    async def link_variants(
        self,
        investigation_id: str,
        canonical_id: str,
        variant_ids: List[str],
    ) -> bool:
        """Link multiple facts as variants of a canonical fact.

        Args:
            investigation_id: Investigation identifier.
            canonical_id: The canonical fact ID.
            variant_ids: List of variant fact IDs.

        Returns:
            True if successful, False if canonical not found.
        """
        async with self._session_factory() as session:
            async with session.begin():
                # Load canonical
                canonical = (
                    await session.execute(
                        select(FactModel).where(
                            FactModel.fact_id == canonical_id,
                            FactModel.investigation_id == investigation_id,
                        )
                    )
                ).scalar_one_or_none()

                if canonical is None:
                    return False

                existing_variants = set(canonical.variants or [])

                for variant_id in variant_ids:
                    if variant_id == canonical_id:
                        continue

                    # Verify variant exists in this investigation
                    variant_row = (
                        await session.execute(
                            select(FactModel).where(
                                FactModel.fact_id == variant_id,
                                FactModel.investigation_id == investigation_id,
                            )
                        )
                    ).scalar_one_or_none()

                    if variant_row is None:
                        continue

                    existing_variants.add(variant_id)

                    # Also update the variant to reference canonical
                    var_variants = list(variant_row.variants or [])
                    if canonical_id not in var_variants:
                        var_variants.append(canonical_id)
                        variant_row.variants = var_variants

                canonical.variants = list(existing_variants)

        return True

    # ------------------------------------------------------------------
    # get_storage_stats
    # ------------------------------------------------------------------

    async def get_storage_stats(self) -> Dict[str, Any]:
        """Get overall storage statistics.

        Returns:
            Dict with total_investigations, total_facts, indexed counts.
        """
        async with self._session_factory() as session:
            inv_q = select(
                func.count(func.distinct(FactModel.investigation_id)),
            )
            total_inv = (await session.execute(inv_q)).scalar() or 0

            fact_q = select(func.count()).select_from(FactModel)
            total_facts = (await session.execute(fact_q)).scalar() or 0

            hash_q = select(
                func.count(func.distinct(FactModel.content_hash)),
            )
            indexed_hashes = (await session.execute(hash_q)).scalar() or 0

            source_q = select(
                func.count(func.distinct(FactModel.source_url)),
            ).where(FactModel.source_url.isnot(None))
            indexed_sources = (await session.execute(source_q)).scalar() or 0

            return {
                "total_investigations": total_inv,
                "total_facts": total_facts,
                "indexed_fact_ids": total_facts,
                "indexed_hashes": indexed_hashes,
                "indexed_sources": indexed_sources,
                "persistence_enabled": True,
                "persistence_path": "PostgreSQL",
            }

    # ------------------------------------------------------------------
    # _extract_source_id (kept for internal compat)
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_source_id(fact: Dict[str, Any]) -> Optional[str]:
        """Extract source_id from fact provenance."""
        provenance = fact.get("provenance", {})
        if isinstance(provenance, dict):
            return provenance.get("source_id")
        return None
