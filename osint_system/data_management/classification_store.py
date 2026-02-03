"""Classification storage with investigation-scoped persistence and indexed lookup.

Per Phase 7 CONTEXT.md: Classifications stored separately from facts.
Indexed for Phase 8 access patterns:
- Priority queue (ordered by priority_score) for general processing
- Flag-type indexes (all Phantoms, all Fogs, etc.) for specialized subroutines

Design follows FactStore patterns:
- Investigation-based organization (investigation_id as primary key)
- O(1) lookup by fact_id
- Thread-safe operations with asyncio locks
- Optional JSON persistence for beta
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from osint_system.data_management.schemas import (
    DubiousFlag,
    FactClassification,
    ImpactTier,
)


class ClassificationStore:
    """
    Storage adapter for fact classifications with investigation-based organization.

    Features:
    - Investigation-scoped storage (investigation_id as primary key)
    - O(1) lookup by fact_id
    - Indexed by dubious flag type for Phase 8 subroutines
    - Priority queue ordering by priority_score
    - Optional JSON persistence for beta
    - Thread-safe operations with asyncio locks

    Data structure:
    {
        "investigation_id": {
            "metadata": {...},
            "created_at": "...",
            "updated_at": "...",
            "classifications": {
                "fact_id": FactClassification dict,
                ...
            },
            "flag_index": {
                "phantom": ["fact_id", ...],
                "fog": ["fact_id", ...],
                ...
            },
            "tier_index": {
                "critical": ["fact_id", ...],
                "less_critical": ["fact_id", ...]
            }
        }
    }

    Usage:
        store = ClassificationStore()
        await store.save_classification(classification)
        result = await store.get_classification("inv-1", "fact-123")
        phantoms = await store.get_by_flag("inv-1", DubiousFlag.PHANTOM)
        queue = await store.get_priority_queue("inv-1")
    """

    def __init__(self, persistence_path: Optional[str] = None):
        """
        Initialize classification store.

        Args:
            persistence_path: Optional path to JSON file for persistence.
                            If None, storage is memory-only.
        """
        self._storage: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self.persistence_path = Path(persistence_path) if persistence_path else None
        self.logger = logger.bind(component="ClassificationStore")

        if self.persistence_path and self.persistence_path.exists():
            self._load_from_file()

        self.logger.info(
            "ClassificationStore initialized",
            persistence_enabled=self.persistence_path is not None,
        )

    def _init_investigation(self, investigation_id: str) -> None:
        """Initialize storage structure for an investigation."""
        if investigation_id not in self._storage:
            self._storage[investigation_id] = {
                "metadata": {},
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "classifications": {},
                "flag_index": {flag.value: [] for flag in DubiousFlag},
                "tier_index": {tier.value: [] for tier in ImpactTier},
            }

    async def save_classification(
        self,
        classification: FactClassification,
    ) -> Dict[str, Any]:
        """
        Save or update a classification.

        Args:
            classification: FactClassification to save

        Returns:
            Stats dict: {action, fact_id, investigation_id}
        """
        async with self._lock:
            investigation_id = classification.investigation_id
            fact_id = classification.fact_id
            self._init_investigation(investigation_id)

            inv = self._storage[investigation_id]
            is_update = fact_id in inv["classifications"]

            # Store classification as dict
            inv["classifications"][fact_id] = classification.model_dump(mode="json")

            # Update flag indexes
            self._update_flag_indexes(inv, fact_id, classification)

            # Update tier indexes
            self._update_tier_indexes(inv, fact_id, classification)

            inv["updated_at"] = datetime.now(timezone.utc).isoformat()

            if self.persistence_path:
                self._save_to_file()

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
        """
        Save multiple classifications for an investigation.

        Args:
            investigation_id: Investigation identifier
            classifications: List of FactClassification objects

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

    def _update_flag_indexes(
        self,
        inv: Dict[str, Any],
        fact_id: str,
        classification: FactClassification,
    ) -> None:
        """Update flag-type indexes for Phase 8 subroutine access."""
        # Remove from all flag indexes first (handles updates)
        for flag_list in inv["flag_index"].values():
            if fact_id in flag_list:
                flag_list.remove(fact_id)

        # Add to current flag indexes
        for flag in classification.dubious_flags:
            if fact_id not in inv["flag_index"][flag.value]:
                inv["flag_index"][flag.value].append(fact_id)

    def _update_tier_indexes(
        self,
        inv: Dict[str, Any],
        fact_id: str,
        classification: FactClassification,
    ) -> None:
        """Update impact tier indexes."""
        # Remove from all tier indexes first (handles updates)
        for tier_list in inv["tier_index"].values():
            if fact_id in tier_list:
                tier_list.remove(fact_id)

        # Add to current tier index
        tier_value = classification.impact_tier.value
        if fact_id not in inv["tier_index"][tier_value]:
            inv["tier_index"][tier_value].append(fact_id)

    async def get_classification(
        self,
        investigation_id: str,
        fact_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Get classification by fact_id. O(1) lookup.

        Args:
            investigation_id: Investigation identifier
            fact_id: Fact identifier

        Returns:
            Classification dict if found, None otherwise
        """
        async with self._lock:
            inv = self._storage.get(investigation_id, {})
            return inv.get("classifications", {}).get(fact_id)

    async def get_by_flag(
        self,
        investigation_id: str,
        flag: DubiousFlag,
    ) -> List[Dict[str, Any]]:
        """
        Get all classifications with a specific dubious flag.

        Args:
            investigation_id: Investigation identifier
            flag: DubiousFlag to filter by

        Returns:
            List of classification dicts with the specified flag
        """
        async with self._lock:
            inv = self._storage.get(investigation_id, {})
            fact_ids = inv.get("flag_index", {}).get(flag.value, [])
            classifications = inv.get("classifications", {})
            return [classifications[fid] for fid in fact_ids if fid in classifications]

    async def get_by_tier(
        self,
        investigation_id: str,
        tier: ImpactTier,
    ) -> List[Dict[str, Any]]:
        """
        Get all classifications with a specific impact tier.

        Args:
            investigation_id: Investigation identifier
            tier: ImpactTier to filter by

        Returns:
            List of classification dicts with the specified tier
        """
        async with self._lock:
            inv = self._storage.get(investigation_id, {})
            fact_ids = inv.get("tier_index", {}).get(tier.value, [])
            classifications = inv.get("classifications", {})
            return [classifications[fid] for fid in fact_ids if fid in classifications]

    async def get_priority_queue(
        self,
        investigation_id: str,
        exclude_noise: bool = True,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get classifications ordered by priority_score descending.

        Per CONTEXT.md: Priority queue for Phase 8 general processing.
        High-impact fixable claims get processed first.

        Args:
            investigation_id: Investigation identifier
            exclude_noise: If True, exclude NOISE-only facts (batch analysis only)
            limit: Maximum classifications to return

        Returns:
            List of classifications sorted by priority_score descending
        """
        async with self._lock:
            inv = self._storage.get(investigation_id, {})
            classifications = list(inv.get("classifications", {}).values())

            if exclude_noise:
                # Exclude facts where NOISE is the only flag
                noise_ids = set(inv.get("flag_index", {}).get("noise", []))
                classifications = [
                    c
                    for c in classifications
                    if not (
                        c["fact_id"] in noise_ids
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
        """
        Get all classifications with at least one dubious flag.

        Args:
            investigation_id: Investigation identifier
            exclude_noise: If True, exclude facts where NOISE is the only flag

        Returns:
            List of dubious classification dicts
        """
        async with self._lock:
            inv = self._storage.get(investigation_id, {})
            classifications = inv.get("classifications", {})

            dubious = []
            for fact_id, classification in classifications.items():
                flags = classification.get("dubious_flags", [])
                if flags:
                    if exclude_noise and "noise" in flags and len(flags) == 1:
                        # Skip if ONLY noise (batch analysis only)
                        continue
                    dubious.append(classification)

            return dubious

    async def get_critical_dubious(
        self,
        investigation_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Get high-priority facts: critical tier AND dubious (priority verification).

        Per CONTEXT.md: Critical + dubious facts get priority verification in Phase 8.
        These are the most important facts to fix.

        Args:
            investigation_id: Investigation identifier

        Returns:
            List of critical dubious classification dicts
        """
        async with self._lock:
            inv = self._storage.get(investigation_id, {})
            critical_ids = set(inv.get("tier_index", {}).get("critical", []))

            # Get all dubious fact IDs (excluding noise-only)
            dubious_ids = set()
            for flag, fact_ids in inv.get("flag_index", {}).items():
                if flag != "noise":
                    dubious_ids.update(fact_ids)

            # Also include noise facts that have other flags
            noise_ids = set(inv.get("flag_index", {}).get("noise", []))
            classifications = inv.get("classifications", {})
            for noise_id in noise_ids:
                if noise_id in classifications:
                    flags = classifications[noise_id].get("dubious_flags", [])
                    if len(flags) > 1:
                        dubious_ids.add(noise_id)

            # Intersection: critical AND dubious
            critical_dubious_ids = critical_ids & dubious_ids

            return [
                classifications[fid]
                for fid in critical_dubious_ids
                if fid in classifications
            ]

    async def get_verified_facts(
        self,
        investigation_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Get all non-dubious classifications (verified facts).

        Args:
            investigation_id: Investigation identifier

        Returns:
            List of verified (non-dubious) classification dicts
        """
        async with self._lock:
            inv = self._storage.get(investigation_id, {})
            classifications = inv.get("classifications", {})

            verified = []
            for classification in classifications.values():
                flags = classification.get("dubious_flags", [])
                if not flags:
                    verified.append(classification)

            return verified

    async def get_stats(self, investigation_id: str) -> Dict[str, Any]:
        """
        Get statistics for an investigation's classifications.

        Args:
            investigation_id: Investigation identifier

        Returns:
            Dictionary with classification statistics
        """
        async with self._lock:
            inv = self._storage.get(investigation_id, {})
            if not inv:
                return {"exists": False, "investigation_id": investigation_id}

            classifications = inv.get("classifications", {})
            flag_index = inv.get("flag_index", {})
            tier_index = inv.get("tier_index", {})

            # Count dubious (any flag)
            dubious_count = len(
                [c for c in classifications.values() if c.get("dubious_flags")]
            )

            # Count verified (no flags)
            verified_count = len(
                [c for c in classifications.values() if not c.get("dubious_flags")]
            )

            # Count critical dubious
            critical_ids = set(tier_index.get("critical", []))
            dubious_ids = set()
            for flag, fact_ids in flag_index.items():
                if flag != "noise":
                    dubious_ids.update(fact_ids)
            critical_dubious_count = len(critical_ids & dubious_ids)

            # Calculate average credibility
            cred_scores = [
                c.get("credibility_score", 0) for c in classifications.values()
            ]
            avg_credibility = sum(cred_scores) / len(cred_scores) if cred_scores else 0

            return {
                "exists": True,
                "investigation_id": investigation_id,
                "total_classifications": len(classifications),
                "critical_count": len(tier_index.get("critical", [])),
                "less_critical_count": len(tier_index.get("less_critical", [])),
                "dubious_count": dubious_count,
                "verified_count": verified_count,
                "critical_dubious_count": critical_dubious_count,
                "average_credibility": round(avg_credibility, 3),
                "flag_counts": {
                    flag: len(fact_ids) for flag, fact_ids in flag_index.items()
                },
                "created_at": inv.get("created_at"),
                "updated_at": inv.get("updated_at"),
            }

    async def update_classification_metadata(
        self,
        investigation_id: str,
        metadata: Dict[str, Any],
    ) -> bool:
        """
        Update metadata for an investigation's classification set.

        Args:
            investigation_id: Investigation identifier
            metadata: Metadata dict to merge

        Returns:
            True if successful, False if investigation not found
        """
        async with self._lock:
            if investigation_id not in self._storage:
                return False

            inv = self._storage[investigation_id]
            inv["metadata"].update(metadata)
            inv["updated_at"] = datetime.now(timezone.utc).isoformat()

            if self.persistence_path:
                self._save_to_file()

            return True

    async def delete_classification(
        self,
        investigation_id: str,
        fact_id: str,
    ) -> bool:
        """
        Delete a single classification.

        Args:
            investigation_id: Investigation identifier
            fact_id: Fact identifier

        Returns:
            True if deleted, False if not found
        """
        async with self._lock:
            inv = self._storage.get(investigation_id, {})
            if not inv or fact_id not in inv.get("classifications", {}):
                return False

            # Remove from classifications
            del inv["classifications"][fact_id]

            # Remove from flag indexes
            for flag_list in inv["flag_index"].values():
                if fact_id in flag_list:
                    flag_list.remove(fact_id)

            # Remove from tier indexes
            for tier_list in inv["tier_index"].values():
                if fact_id in tier_list:
                    tier_list.remove(fact_id)

            inv["updated_at"] = datetime.now(timezone.utc).isoformat()

            if self.persistence_path:
                self._save_to_file()

            self.logger.debug(
                f"Deleted classification", fact_id=fact_id, investigation_id=investigation_id
            )
            return True

    async def delete_investigation(self, investigation_id: str) -> bool:
        """
        Delete an investigation and all its classifications.

        Args:
            investigation_id: Investigation identifier

        Returns:
            True if deleted, False if not found
        """
        async with self._lock:
            if investigation_id not in self._storage:
                return False

            del self._storage[investigation_id]

            if self.persistence_path:
                self._save_to_file()

            self.logger.info(f"Deleted investigation classifications: {investigation_id}")
            return True

    async def list_investigations(self) -> List[Dict[str, Any]]:
        """
        List all investigations in the store.

        Returns:
            List of investigation summaries
        """
        async with self._lock:
            investigations = []
            for inv_id, inv_data in self._storage.items():
                classifications = inv_data.get("classifications", {})
                dubious_count = len(
                    [c for c in classifications.values() if c.get("dubious_flags")]
                )
                investigations.append(
                    {
                        "investigation_id": inv_id,
                        "classification_count": len(classifications),
                        "dubious_count": dubious_count,
                        "created_at": inv_data.get("created_at"),
                        "updated_at": inv_data.get("updated_at"),
                        "metadata": inv_data.get("metadata", {}),
                    }
                )
            return investigations

    async def get_storage_stats(self) -> Dict[str, Any]:
        """
        Get overall storage statistics.

        Returns:
            Dictionary with storage statistics
        """
        async with self._lock:
            total_classifications = sum(
                len(inv.get("classifications", {}))
                for inv in self._storage.values()
            )

            total_dubious = sum(
                len([c for c in inv.get("classifications", {}).values() if c.get("dubious_flags")])
                for inv in self._storage.values()
            )

            return {
                "total_investigations": len(self._storage),
                "total_classifications": total_classifications,
                "total_dubious": total_dubious,
                "persistence_enabled": self.persistence_path is not None,
                "persistence_path": str(self.persistence_path)
                if self.persistence_path
                else None,
            }

    def _save_to_file(self) -> None:
        """Save current storage to JSON file (synchronous)."""
        if not self.persistence_path:
            return

        try:
            # Ensure directory exists
            self.persistence_path.parent.mkdir(parents=True, exist_ok=True)

            # Write to file
            with open(self.persistence_path, "w") as f:
                json.dump(self._storage, f, indent=2, default=str)

            self.logger.debug(f"Persisted to {self.persistence_path}")

        except Exception as e:
            self.logger.error(f"Failed to persist to file: {e}", exc_info=True)

    def _load_from_file(self) -> None:
        """Load storage from JSON file (synchronous)."""
        if not self.persistence_path or not self.persistence_path.exists():
            return

        try:
            with open(self.persistence_path, "r") as f:
                self._storage = json.load(f)

            self.logger.info(
                f"Loaded from {self.persistence_path}",
                investigations=len(self._storage),
            )

        except Exception as e:
            self.logger.error(f"Failed to load from file: {e}", exc_info=True)
            self._storage = {}
