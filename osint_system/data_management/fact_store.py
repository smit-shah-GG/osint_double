"""Fact storage adapter for persisting extracted facts with investigation-based organization.

Features:
- In-memory storage with optional JSON persistence for beta
- Investigation-based organization (investigation_id as primary key)
- O(1) lookup by fact_id and content_hash
- Variant linking for semantic duplicates (preserves corroboration signal)
- Source indexing for provenance tracking
- Thread-safe operations with asyncio locks

Design follows CONTEXT.md principles:
- Multiple sources reporting same claim is different from one source (corroboration)
- Full provenance preserved when linking variants
- Detail over compactness: collapsed variants still traceable
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger


class FactStore:
    """
    Storage adapter for fact persistence with investigation-based organization.

    For beta: Uses in-memory storage with optional JSON file persistence.
    For production: Would be replaced with database backend.

    Data structure:
    {
        "investigation_id": {
            "metadata": {...},
            "created_at": "...",
            "updated_at": "...",
            "facts": {
                "fact_id": {
                    "fact_id": "...",
                    "content_hash": "...",
                    "claim": {...},
                    "variants": ["variant_id_1", ...],
                    "stored_at": "..."
                },
                ...
            }
        }
    }

    Indexes:
    - _fact_index: fact_id -> (investigation_id, fact) for O(1) lookup
    - _hash_index: content_hash -> list[fact_id] for dedup detection
    - _source_index: source_id -> list[fact_id] for provenance queries

    Features:
    - Investigation-scoped fact storage
    - O(1) lookup by fact_id and content_hash
    - Variant linking for semantic duplicates
    - Optional persistence to JSON
    """

    def __init__(self, persistence_path: Optional[str] = None):
        """
        Initialize fact store.

        Args:
            persistence_path: Optional path to JSON file for persistence.
                            If None, storage is memory-only.
        """
        # Primary storage: investigation_id -> investigation data
        self._storage: Dict[str, Dict[str, Any]] = {}

        # O(1) indexes
        self._fact_index: Dict[str, tuple[str, Dict[str, Any]]] = {}  # fact_id -> (inv_id, fact)
        self._hash_index: Dict[str, List[str]] = {}  # content_hash -> list[fact_id]
        self._source_index: Dict[str, List[str]] = {}  # source_id -> list[fact_id]

        self._lock = asyncio.Lock()
        self.persistence_path = Path(persistence_path) if persistence_path else None
        self.logger = logger.bind(component="FactStore")

        # Load from persistence if available
        if self.persistence_path and self.persistence_path.exists():
            self._load_from_file()

        self.logger.info(
            "FactStore initialized",
            persistence_enabled=self.persistence_path is not None
        )

    async def save_facts(
        self,
        investigation_id: str,
        facts: List[Dict[str, Any]],
        investigation_metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Save facts for a specific investigation.

        Detects duplicates by content_hash and links them as variants.
        Different fact_ids with same hash are variant instances.

        Args:
            investigation_id: Unique investigation identifier
            facts: List of fact dictionaries (ExtractedFact-like dicts)
            investigation_metadata: Optional metadata about the investigation

        Returns:
            Dictionary with save statistics:
            - saved: Number of new facts saved
            - updated: Number of facts updated (variant linked)
            - skipped: Number skipped (same fact_id already exists)
            - total: Total facts in investigation after save
        """
        async with self._lock:
            # Initialize investigation if doesn't exist
            if investigation_id not in self._storage:
                self._storage[investigation_id] = {
                    "metadata": investigation_metadata or {},
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "facts": {}
                }

            investigation = self._storage[investigation_id]
            stored_facts = investigation["facts"]

            saved_count = 0
            updated_count = 0
            skipped_count = 0

            for fact in facts:
                fact_id = fact.get("fact_id")
                content_hash = fact.get("content_hash", "")
                source_id = self._extract_source_id(fact)

                if not fact_id:
                    self.logger.warning("Fact missing fact_id, skipping")
                    skipped_count += 1
                    continue

                # Check if this exact fact_id already exists
                if fact_id in stored_facts:
                    self.logger.debug(f"Fact {fact_id} already exists, skipping")
                    skipped_count += 1
                    continue

                # Add storage timestamp and ensure variants list exists
                fact_with_metadata = {
                    **fact,
                    "stored_at": datetime.now(timezone.utc).isoformat(),
                    "variants": fact.get("variants", [])
                }

                # Check for hash duplicates - link as variants
                if content_hash and content_hash in self._hash_index:
                    existing_fact_ids = self._hash_index[content_hash]
                    # Find canonical fact (first one stored in this investigation)
                    canonical_id = None
                    for existing_id in existing_fact_ids:
                        if existing_id in stored_facts:
                            canonical_id = existing_id
                            break

                    if canonical_id:
                        # Link this fact as variant of canonical
                        canonical_fact = stored_facts[canonical_id]
                        if fact_id not in canonical_fact["variants"]:
                            canonical_fact["variants"].append(fact_id)
                        # Also mark the new fact as linked
                        if canonical_id not in fact_with_metadata["variants"]:
                            fact_with_metadata["variants"].append(canonical_id)
                        updated_count += 1
                        self.logger.debug(
                            f"Linked {fact_id} as variant of {canonical_id}"
                        )

                # Store the fact
                stored_facts[fact_id] = fact_with_metadata
                saved_count += 1

                # Update indexes
                self._fact_index[fact_id] = (investigation_id, fact_with_metadata)

                if content_hash:
                    if content_hash not in self._hash_index:
                        self._hash_index[content_hash] = []
                    self._hash_index[content_hash].append(fact_id)

                if source_id:
                    if source_id not in self._source_index:
                        self._source_index[source_id] = []
                    self._source_index[source_id].append(fact_id)

                self.logger.debug(f"Saved fact: {fact_id}")

            # Update investigation metadata
            investigation["updated_at"] = datetime.now(timezone.utc).isoformat()

            # Persist if enabled
            if self.persistence_path:
                self._save_to_file()

            stats = {
                "saved": saved_count,
                "updated": updated_count,
                "skipped": skipped_count,
                "total": len(stored_facts)
            }

            self.logger.info(
                f"Saved facts for investigation {investigation_id}",
                **stats
            )

            return stats

    async def get_fact(
        self,
        investigation_id: str,
        fact_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve a single fact by ID.

        O(1) lookup using fact index.

        Args:
            investigation_id: Investigation identifier
            fact_id: Fact identifier

        Returns:
            Fact dictionary if found, None otherwise
        """
        async with self._lock:
            if fact_id in self._fact_index:
                inv_id, fact = self._fact_index[fact_id]
                if inv_id == investigation_id:
                    return fact
            return None

    async def get_fact_by_id(self, fact_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a fact by ID without specifying investigation.

        O(1) lookup using fact index.

        Args:
            fact_id: Fact identifier

        Returns:
            Fact dictionary if found, None otherwise
        """
        async with self._lock:
            if fact_id in self._fact_index:
                _, fact = self._fact_index[fact_id]
                return fact
            return None

    async def get_facts_by_hash(
        self,
        content_hash: str,
        investigation_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve all facts with a given content hash.

        O(1) lookup using hash index.

        Args:
            content_hash: SHA256 content hash
            investigation_id: Optional filter by investigation

        Returns:
            List of fact dictionaries with matching hash
        """
        async with self._lock:
            if content_hash not in self._hash_index:
                return []

            facts = []
            for fact_id in self._hash_index[content_hash]:
                if fact_id in self._fact_index:
                    inv_id, fact = self._fact_index[fact_id]
                    if investigation_id is None or inv_id == investigation_id:
                        facts.append(fact)
            return facts

    async def get_facts_by_source(
        self,
        source_id: str,
        investigation_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve all facts from a given source.

        O(1) index lookup followed by fact retrieval.

        Args:
            source_id: Source identifier
            investigation_id: Optional filter by investigation

        Returns:
            List of fact dictionaries from the source
        """
        async with self._lock:
            if source_id not in self._source_index:
                return []

            facts = []
            for fact_id in self._source_index[source_id]:
                if fact_id in self._fact_index:
                    inv_id, fact = self._fact_index[fact_id]
                    if investigation_id is None or inv_id == investigation_id:
                        facts.append(fact)
            return facts

    async def retrieve_by_investigation(
        self,
        investigation_id: str,
        limit: Optional[int] = None,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Retrieve all facts for a specific investigation.

        Args:
            investigation_id: Investigation identifier
            limit: Maximum number of facts to return (None = all)
            offset: Number of facts to skip

        Returns:
            Dictionary with investigation data:
            - investigation_id: ID
            - metadata: Investigation metadata
            - facts: List of fact dictionaries
            - total_facts: Total count
            - returned_facts: Count in this response
        """
        async with self._lock:
            if investigation_id not in self._storage:
                return {
                    "investigation_id": investigation_id,
                    "metadata": {},
                    "facts": [],
                    "total_facts": 0,
                    "returned_facts": 0
                }

            investigation = self._storage[investigation_id]
            all_facts = list(investigation["facts"].values())

            # Apply pagination
            if limit:
                selected_facts = all_facts[offset:offset + limit]
            else:
                selected_facts = all_facts[offset:]

            return {
                "investigation_id": investigation_id,
                "metadata": investigation["metadata"],
                "created_at": investigation.get("created_at"),
                "updated_at": investigation.get("updated_at"),
                "facts": selected_facts,
                "total_facts": len(all_facts),
                "returned_facts": len(selected_facts)
            }

    async def check_hash_exists(
        self,
        content_hash: str,
        investigation_id: Optional[str] = None
    ) -> bool:
        """
        Check if a content hash exists.

        O(1) lookup using hash index.

        Args:
            content_hash: SHA256 content hash to check
            investigation_id: Optional filter by investigation

        Returns:
            True if hash exists, False otherwise
        """
        async with self._lock:
            if content_hash not in self._hash_index:
                return False

            if investigation_id is None:
                return True

            # Check if any fact with this hash is in the investigation
            for fact_id in self._hash_index[content_hash]:
                if fact_id in self._fact_index:
                    inv_id, _ = self._fact_index[fact_id]
                    if inv_id == investigation_id:
                        return True
            return False

    async def get_stats(self, investigation_id: str) -> Dict[str, Any]:
        """
        Get statistics for an investigation.

        Args:
            investigation_id: Investigation identifier

        Returns:
            Dictionary with statistics
        """
        async with self._lock:
            if investigation_id not in self._storage:
                return {
                    "exists": False,
                    "investigation_id": investigation_id
                }

            investigation = self._storage[investigation_id]
            facts = investigation["facts"]

            # Calculate statistics
            source_counts: Dict[str, int] = {}
            variant_count = 0
            hash_collision_count = 0
            unique_hashes = set()

            for fact in facts.values():
                # Count sources
                source_id = self._extract_source_id(fact)
                if source_id:
                    source_counts[source_id] = source_counts.get(source_id, 0) + 1

                # Count variants
                variants = fact.get("variants", [])
                if variants:
                    variant_count += 1

                # Track unique hashes
                content_hash = fact.get("content_hash", "")
                if content_hash:
                    if content_hash in unique_hashes:
                        hash_collision_count += 1
                    unique_hashes.add(content_hash)

            return {
                "exists": True,
                "investigation_id": investigation_id,
                "total_facts": len(facts),
                "unique_claims": len(unique_hashes),
                "facts_with_variants": variant_count,
                "created_at": investigation.get("created_at"),
                "updated_at": investigation.get("updated_at"),
                "source_breakdown": source_counts,
                "metadata": investigation["metadata"]
            }

    async def list_investigations(self) -> List[Dict[str, Any]]:
        """
        List all investigations in the store.

        Returns:
            List of investigation summaries
        """
        async with self._lock:
            investigations = []
            for inv_id, inv_data in self._storage.items():
                investigations.append({
                    "investigation_id": inv_id,
                    "fact_count": len(inv_data["facts"]),
                    "created_at": inv_data.get("created_at"),
                    "updated_at": inv_data.get("updated_at"),
                    "metadata": inv_data["metadata"]
                })
            return investigations

    async def delete_investigation(self, investigation_id: str) -> bool:
        """
        Delete an investigation and all its facts.

        Args:
            investigation_id: Investigation identifier

        Returns:
            True if deleted, False if not found
        """
        async with self._lock:
            if investigation_id not in self._storage:
                return False

            # Remove from all indexes
            facts = self._storage[investigation_id]["facts"]
            for fact_id, fact in facts.items():
                # Remove from fact index
                if fact_id in self._fact_index:
                    del self._fact_index[fact_id]

                # Remove from hash index
                content_hash = fact.get("content_hash", "")
                if content_hash and content_hash in self._hash_index:
                    self._hash_index[content_hash] = [
                        fid for fid in self._hash_index[content_hash]
                        if fid != fact_id
                    ]
                    if not self._hash_index[content_hash]:
                        del self._hash_index[content_hash]

                # Remove from source index
                source_id = self._extract_source_id(fact)
                if source_id and source_id in self._source_index:
                    self._source_index[source_id] = [
                        fid for fid in self._source_index[source_id]
                        if fid != fact_id
                    ]
                    if not self._source_index[source_id]:
                        del self._source_index[source_id]

            # Remove investigation
            del self._storage[investigation_id]

            # Persist if enabled
            if self.persistence_path:
                self._save_to_file()

            self.logger.info(f"Deleted investigation: {investigation_id}")
            return True

    async def link_variants(
        self,
        investigation_id: str,
        canonical_id: str,
        variant_ids: List[str]
    ) -> bool:
        """
        Link multiple facts as variants of a canonical fact.

        Used for semantic duplicates detected by FactConsolidator.

        Args:
            investigation_id: Investigation identifier
            canonical_id: The canonical fact ID
            variant_ids: List of variant fact IDs

        Returns:
            True if successful, False if canonical not found
        """
        async with self._lock:
            if investigation_id not in self._storage:
                return False

            facts = self._storage[investigation_id]["facts"]
            if canonical_id not in facts:
                return False

            canonical = facts[canonical_id]
            existing_variants = set(canonical.get("variants", []))

            for variant_id in variant_ids:
                if variant_id != canonical_id and variant_id in facts:
                    existing_variants.add(variant_id)
                    # Also update the variant to reference canonical
                    variant = facts[variant_id]
                    if canonical_id not in variant.get("variants", []):
                        if "variants" not in variant:
                            variant["variants"] = []
                        variant["variants"].append(canonical_id)

            canonical["variants"] = list(existing_variants)

            # Persist if enabled
            if self.persistence_path:
                self._save_to_file()

            return True

    async def get_storage_stats(self) -> Dict[str, Any]:
        """
        Get overall storage statistics.

        Returns:
            Dictionary with storage statistics
        """
        async with self._lock:
            total_facts = sum(
                len(inv["facts"])
                for inv in self._storage.values()
            )

            return {
                "total_investigations": len(self._storage),
                "total_facts": total_facts,
                "indexed_fact_ids": len(self._fact_index),
                "indexed_hashes": len(self._hash_index),
                "indexed_sources": len(self._source_index),
                "persistence_enabled": self.persistence_path is not None,
                "persistence_path": str(self.persistence_path) if self.persistence_path else None
            }

    def _extract_source_id(self, fact: Dict[str, Any]) -> Optional[str]:
        """Extract source_id from fact provenance."""
        provenance = fact.get("provenance", {})
        if isinstance(provenance, dict):
            return provenance.get("source_id")
        return None

    def _save_to_file(self) -> None:
        """Save current storage to JSON file (synchronous)."""
        if not self.persistence_path:
            return

        try:
            # Ensure directory exists
            self.persistence_path.parent.mkdir(parents=True, exist_ok=True)

            # Prepare serializable data
            data = {}
            for inv_id, inv_data in self._storage.items():
                data[inv_id] = {
                    "metadata": inv_data["metadata"],
                    "created_at": inv_data["created_at"],
                    "updated_at": inv_data["updated_at"],
                    "facts": inv_data["facts"]
                }

            # Write to file
            with open(self.persistence_path, 'w') as f:
                json.dump(data, f, indent=2, default=str)

            self.logger.debug(f"Persisted to {self.persistence_path}")

        except Exception as e:
            self.logger.error(f"Failed to persist to file: {e}", exc_info=True)

    def _load_from_file(self) -> None:
        """Load storage from JSON file and rebuild indexes (synchronous)."""
        if not self.persistence_path or not self.persistence_path.exists():
            return

        try:
            with open(self.persistence_path, 'r') as f:
                data = json.load(f)

            # Restore storage
            self._storage = {}
            for inv_id, inv_data in data.items():
                self._storage[inv_id] = {
                    "metadata": inv_data.get("metadata", {}),
                    "created_at": inv_data.get("created_at", ""),
                    "updated_at": inv_data.get("updated_at", ""),
                    "facts": inv_data.get("facts", {})
                }

            # Rebuild indexes
            self._rebuild_indexes()

            self.logger.info(
                f"Loaded from {self.persistence_path}",
                investigations=len(self._storage),
                facts=len(self._fact_index)
            )

        except Exception as e:
            self.logger.error(f"Failed to load from file: {e}", exc_info=True)
            self._storage = {}
            self._fact_index = {}
            self._hash_index = {}
            self._source_index = {}

    def _rebuild_indexes(self) -> None:
        """Rebuild all indexes from storage (called after loading from file)."""
        self._fact_index = {}
        self._hash_index = {}
        self._source_index = {}

        for inv_id, inv_data in self._storage.items():
            for fact_id, fact in inv_data["facts"].items():
                # Fact index
                self._fact_index[fact_id] = (inv_id, fact)

                # Hash index
                content_hash = fact.get("content_hash", "")
                if content_hash:
                    if content_hash not in self._hash_index:
                        self._hash_index[content_hash] = []
                    self._hash_index[content_hash].append(fact_id)

                # Source index
                source_id = self._extract_source_id(fact)
                if source_id:
                    if source_id not in self._source_index:
                        self._source_index[source_id] = []
                    self._source_index[source_id].append(fact_id)
