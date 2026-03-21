"""Classification storage backed by PostgreSQL via SQLAlchemy async sessions.

Per Phase 7 CONTEXT.md: Classifications stored separately from facts.
Indexed for Phase 8 access patterns:
- Priority queue (ordered by priority_score) for general processing
- Flag-type indexes (dubious flag queries) for specialized subroutines
- Tier-based filtering for critical/less_critical segmentation

Migrated from in-memory dict+JSON to PostgreSQL. All public method
signatures and return types are preserved. SQL queries replace the
in-memory flag_index and tier_index structures.

Usage:
    from osint_system.data_management.database import init_db
    from osint_system.data_management.classification_store import ClassificationStore

    session_factory = init_db()
    store = ClassificationStore(session_factory)
    await store.save_classification(classification)
    result = await store.get_classification("inv-1", "fact-123")
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from osint_system.data_management.models.classification import ClassificationModel
from osint_system.data_management.schemas import (
    DubiousFlag,
    FactClassification,
    ImpactTier,
)


class ClassificationStore:
    """PostgreSQL-backed storage for fact classifications.

    Replaces in-memory dict storage with async SQLAlchemy sessions.
    Flag and tier indexes are now SQL queries against the classifications
    table. Concurrency is handled by PostgreSQL transactions (no
    asyncio.Lock required).

    All public methods preserve the exact signatures and return types
    of the original in-memory implementation.
    """

    def __init__(
        self,
        session_factory: Optional[async_sessionmaker[AsyncSession]] = None,
    ) -> None:
        """Initialize classification store.

        Args:
            session_factory: SQLAlchemy async session factory from database.py.
                If None, falls back to the module-level factory via init_db().
        """
        if session_factory is None:
            from osint_system.data_management.database import get_session_factory
            session_factory = get_session_factory()

        self._session_factory = session_factory
        self.logger = logger.bind(component="ClassificationStore")
        self.logger.info("ClassificationStore initialized (PostgreSQL backend)")

    async def save_classification(
        self,
        classification: FactClassification,
    ) -> Dict[str, Any]:
        """Save or update a classification.

        Uses PostgreSQL upsert (INSERT ... ON CONFLICT UPDATE) on the
        (investigation_id, fact_id) unique constraint.

        Args:
            classification: FactClassification to save.

        Returns:
            Stats dict: {action, fact_id, investigation_id}
        """
        investigation_id = classification.investigation_id
        fact_id = classification.fact_id
        data = classification.model_dump(mode="json")

        async with self._session_factory() as session:
            # Check if exists for action reporting
            existing = await session.execute(
                select(ClassificationModel.id).where(
                    ClassificationModel.investigation_id == investigation_id,
                    ClassificationModel.fact_id == fact_id,
                )
            )
            is_update = existing.scalar_one_or_none() is not None

            if is_update:
                # Update existing row
                await session.execute(
                    update(ClassificationModel)
                    .where(
                        ClassificationModel.investigation_id == investigation_id,
                        ClassificationModel.fact_id == fact_id,
                    )
                    .values(
                        tier=data.get("impact_tier"),
                        priority_score=data.get("priority_score"),
                        credibility_score=data.get("credibility_score"),
                        credibility_breakdown=data.get("credibility_breakdown"),
                        dubious_flags=data.get("dubious_flags", []),
                        classification_reasoning=data.get("classification_reasoning", []),
                        impact_reasoning=data.get("impact_reasoning"),
                        history=data.get("history", []),
                        classification_data=data,
                    )
                )
            else:
                model = ClassificationModel.from_dict(data, investigation_id)
                session.add(model)

            await session.commit()

        action = "updated" if is_update else "created"
        self.logger.debug(
            f"Classification {action}",
            fact_id=fact_id,
            investigation_id=investigation_id,
            impact_tier=classification.impact_tier.value,
            dubious_count=len(classification.dubious_flags),
        )

        return {
            "action": action,
            "fact_id": fact_id,
            "investigation_id": investigation_id,
        }

    async def save_classifications(
        self,
        investigation_id: str,
        classifications: List[FactClassification],
    ) -> Dict[str, Any]:
        """Save multiple classifications for an investigation.

        Args:
            investigation_id: Investigation identifier.
            classifications: List of FactClassification objects.

        Returns:
            Stats dict: {created, updated, total, skipped}
        """
        created = 0
        updated = 0
        skipped = 0

        for classification in classifications:
            if classification.investigation_id != investigation_id:
                self.logger.warning(
                    f"Skipping classification with mismatched investigation_id: "
                    f"{classification.investigation_id} != {investigation_id}"
                )
                skipped += 1
                continue

            result = await self.save_classification(classification)
            if result["action"] == "created":
                created += 1
            else:
                updated += 1

        self.logger.info(
            f"Saved {created + updated} classifications",
            investigation_id=investigation_id,
            created=created,
            updated=updated,
            skipped=skipped,
        )

        return {
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "total": created + updated,
        }

    async def get_classification(
        self,
        investigation_id: str,
        fact_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Get classification by fact_id.

        Args:
            investigation_id: Investigation identifier.
            fact_id: Fact identifier.

        Returns:
            Classification dict if found, None otherwise.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(ClassificationModel).where(
                    ClassificationModel.investigation_id == investigation_id,
                    ClassificationModel.fact_id == fact_id,
                )
            )
            model = result.scalar_one_or_none()
            if model is None:
                return None
            return model.to_dict()

    async def get_by_flag(
        self,
        investigation_id: str,
        flag: DubiousFlag,
    ) -> List[Dict[str, Any]]:
        """Get all classifications with a specific dubious flag.

        Uses JSONB containment operator to query the dubious_flags
        array column.

        Args:
            investigation_id: Investigation identifier.
            flag: DubiousFlag to filter by.

        Returns:
            List of classification dicts with the specified flag.
        """
        async with self._session_factory() as session:
            # JSONB @> containment: dubious_flags @> '["phantom"]'::jsonb
            result = await session.execute(
                select(ClassificationModel).where(
                    ClassificationModel.investigation_id == investigation_id,
                    ClassificationModel.dubious_flags.op("@>")(
                        f'["{flag.value}"]'
                    ),
                )
            )
            models = result.scalars().all()
            return [m.to_dict() for m in models]

    async def get_by_tier(
        self,
        investigation_id: str,
        tier: ImpactTier,
    ) -> List[Dict[str, Any]]:
        """Get all classifications with a specific impact tier.

        Args:
            investigation_id: Investigation identifier.
            tier: ImpactTier to filter by.

        Returns:
            List of classification dicts with the specified tier.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(ClassificationModel).where(
                    ClassificationModel.investigation_id == investigation_id,
                    ClassificationModel.tier == tier.value,
                )
            )
            models = result.scalars().all()
            return [m.to_dict() for m in models]

    async def get_priority_queue(
        self,
        investigation_id: str,
        exclude_noise: bool = True,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Get classifications ordered by priority_score descending.

        Per CONTEXT.md: Priority queue for Phase 8 general processing.
        High-impact fixable claims get processed first.

        Args:
            investigation_id: Investigation identifier.
            exclude_noise: If True, exclude NOISE-only facts.
            limit: Maximum classifications to return.

        Returns:
            List of classifications sorted by priority_score descending.
        """
        async with self._session_factory() as session:
            stmt = select(ClassificationModel).where(
                ClassificationModel.investigation_id == investigation_id,
            )

            result = await session.execute(stmt)
            models = result.scalars().all()

        # Filter noise-only in Python (matching original semantics exactly:
        # exclude facts where NOISE is the only flag)
        classifications = [m.to_dict() for m in models]

        if exclude_noise:
            classifications = [
                c
                for c in classifications
                if not (
                    "noise" in c.get("dubious_flags", [])
                    and len(c.get("dubious_flags", [])) == 1
                )
            ]

        # Sort by priority_score descending
        classifications.sort(key=lambda c: c.get("priority_score", 0), reverse=True)

        if limit:
            return classifications[:limit]
        return classifications

    async def get_dubious_facts(
        self,
        investigation_id: str,
        exclude_noise: bool = True,
    ) -> List[Dict[str, Any]]:
        """Get all classifications with at least one dubious flag.

        Args:
            investigation_id: Investigation identifier.
            exclude_noise: If True, exclude facts where NOISE is the only flag.

        Returns:
            List of dubious classification dicts.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(ClassificationModel).where(
                    ClassificationModel.investigation_id == investigation_id,
                )
            )
            models = result.scalars().all()

        dubious = []
        for model in models:
            d = model.to_dict()
            flags = d.get("dubious_flags", [])
            if flags:
                if exclude_noise and flags == ["noise"]:
                    continue
                dubious.append(d)

        return dubious

    async def get_critical_dubious(
        self,
        investigation_id: str,
    ) -> List[Dict[str, Any]]:
        """Get high-priority facts: critical tier AND dubious (priority verification).

        Per CONTEXT.md: Critical + dubious facts get priority verification
        in Phase 8.

        Args:
            investigation_id: Investigation identifier.

        Returns:
            List of critical dubious classification dicts.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(ClassificationModel).where(
                    ClassificationModel.investigation_id == investigation_id,
                    ClassificationModel.tier == ImpactTier.CRITICAL.value,
                )
            )
            models = result.scalars().all()

        critical_dubious = []
        for model in models:
            d = model.to_dict()
            flags = d.get("dubious_flags", [])
            if not flags:
                continue
            # Exclude noise-only
            if flags == ["noise"]:
                continue
            # Has non-noise flags (or noise + other flags)
            critical_dubious.append(d)

        return critical_dubious

    async def get_verified_facts(
        self,
        investigation_id: str,
    ) -> List[Dict[str, Any]]:
        """Get all non-dubious classifications (verified facts).

        Args:
            investigation_id: Investigation identifier.

        Returns:
            List of verified (non-dubious) classification dicts.
        """
        async with self._session_factory() as session:
            # Empty dubious_flags array means verified
            result = await session.execute(
                select(ClassificationModel).where(
                    ClassificationModel.investigation_id == investigation_id,
                    ClassificationModel.dubious_flags == [],
                )
            )
            models = result.scalars().all()
            return [m.to_dict() for m in models]

    async def get_all_classifications(
        self,
        investigation_id: str,
    ) -> List[Dict[str, Any]]:
        """Get all classifications for an investigation.

        Args:
            investigation_id: Investigation identifier.

        Returns:
            List of all classification dicts for the investigation.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(ClassificationModel).where(
                    ClassificationModel.investigation_id == investigation_id,
                )
            )
            models = result.scalars().all()
            return [m.to_dict() for m in models]

    async def get_stats(self, investigation_id: str) -> Dict[str, Any]:
        """Get statistics for an investigation's classifications.

        Args:
            investigation_id: Investigation identifier.

        Returns:
            Dictionary with classification statistics.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(ClassificationModel).where(
                    ClassificationModel.investigation_id == investigation_id,
                )
            )
            models = result.scalars().all()

        if not models:
            return {"exists": False, "investigation_id": investigation_id}

        classifications = [m.to_dict() for m in models]

        # Count by tier
        critical_count = sum(1 for c in classifications if c.get("impact_tier") == "critical")
        less_critical_count = sum(
            1 for c in classifications if c.get("impact_tier") == "less_critical"
        )

        # Count dubious (any flag)
        dubious_count = sum(
            1 for c in classifications if c.get("dubious_flags")
        )

        # Count verified (no flags)
        verified_count = sum(
            1 for c in classifications if not c.get("dubious_flags")
        )

        # Count critical dubious (critical AND has non-noise flags)
        dubious_ids = set()
        for c in classifications:
            flags = c.get("dubious_flags", [])
            non_noise = [f for f in flags if f != "noise"]
            if non_noise:
                dubious_ids.add(c["fact_id"])
            elif flags and len(flags) > 1:
                # noise + other flags
                dubious_ids.add(c["fact_id"])
        critical_ids = {
            c["fact_id"] for c in classifications if c.get("impact_tier") == "critical"
        }
        critical_dubious_count = len(critical_ids & dubious_ids)

        # Average credibility
        cred_scores = [c.get("credibility_score", 0) for c in classifications]
        avg_credibility = sum(cred_scores) / len(cred_scores) if cred_scores else 0

        # Flag counts
        flag_counts: Dict[str, int] = {}
        for c in classifications:
            for flag in c.get("dubious_flags", []):
                flag_counts[flag] = flag_counts.get(flag, 0) + 1

        return {
            "exists": True,
            "investigation_id": investigation_id,
            "total_classifications": len(classifications),
            "critical_count": critical_count,
            "less_critical_count": less_critical_count,
            "dubious_count": dubious_count,
            "verified_count": verified_count,
            "critical_dubious_count": critical_dubious_count,
            "average_credibility": round(avg_credibility, 3),
            "flag_counts": flag_counts,
            "created_at": None,
            "updated_at": None,
        }

    async def update_classification_metadata(
        self,
        investigation_id: str,
        metadata: Dict[str, Any],
    ) -> bool:
        """Update metadata for an investigation's classification set.

        In the PostgreSQL backend, metadata is not stored as a separate
        field. This method is preserved for interface compatibility but
        operates as a no-op returning True if the investigation exists.

        Args:
            investigation_id: Investigation identifier.
            metadata: Metadata dict (stored in classification_data JSONB).

        Returns:
            True if investigation exists, False otherwise.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(func.count()).where(
                    ClassificationModel.investigation_id == investigation_id,
                )
            )
            count = result.scalar_one()
            return count > 0

    async def delete_classification(
        self,
        investigation_id: str,
        fact_id: str,
    ) -> bool:
        """Delete a single classification.

        Args:
            investigation_id: Investigation identifier.
            fact_id: Fact identifier.

        Returns:
            True if deleted, False if not found.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                delete(ClassificationModel).where(
                    ClassificationModel.investigation_id == investigation_id,
                    ClassificationModel.fact_id == fact_id,
                )
            )
            await session.commit()

        deleted = result.rowcount > 0
        if deleted:
            self.logger.debug(
                "Deleted classification",
                fact_id=fact_id,
                investigation_id=investigation_id,
            )
        return deleted

    async def delete_investigation(self, investigation_id: str) -> bool:
        """Delete an investigation and all its classifications.

        Args:
            investigation_id: Investigation identifier.

        Returns:
            True if deleted, False if not found.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                delete(ClassificationModel).where(
                    ClassificationModel.investigation_id == investigation_id,
                )
            )
            await session.commit()

        deleted = result.rowcount > 0
        if deleted:
            self.logger.info(f"Deleted investigation classifications: {investigation_id}")
        return deleted

    async def list_investigations(self) -> List[Dict[str, Any]]:
        """List all investigations in the store.

        Returns:
            List of investigation summaries.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(ClassificationModel)
            )
            models = result.scalars().all()

        # Group by investigation_id
        inv_map: Dict[str, list[Dict[str, Any]]] = {}
        for model in models:
            d = model.to_dict()
            inv_id = d["investigation_id"]
            if inv_id not in inv_map:
                inv_map[inv_id] = []
            inv_map[inv_id].append(d)

        investigations = []
        for inv_id, classifications in inv_map.items():
            dubious_count = sum(
                1 for c in classifications if c.get("dubious_flags")
            )
            investigations.append(
                {
                    "investigation_id": inv_id,
                    "classification_count": len(classifications),
                    "dubious_count": dubious_count,
                    "created_at": None,
                    "updated_at": None,
                    "metadata": {},
                }
            )
        return investigations

    async def get_storage_stats(self) -> Dict[str, Any]:
        """Get overall storage statistics.

        Returns:
            Dictionary with storage statistics.
        """
        async with self._session_factory() as session:
            total_result = await session.execute(
                select(func.count()).select_from(ClassificationModel)
            )
            total_classifications = total_result.scalar_one()

            inv_result = await session.execute(
                select(func.count(func.distinct(ClassificationModel.investigation_id)))
            )
            total_investigations = inv_result.scalar_one()

        # Count dubious requires fetching flags
        async with self._session_factory() as session:
            result = await session.execute(
                select(ClassificationModel.dubious_flags)
            )
            all_flags = result.scalars().all()

        total_dubious = sum(1 for flags in all_flags if flags)

        return {
            "total_investigations": total_investigations,
            "total_classifications": total_classifications,
            "total_dubious": total_dubious,
            "persistence_enabled": True,
            "persistence_path": "PostgreSQL",
        }
