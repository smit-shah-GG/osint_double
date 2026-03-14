"""Self-contained JSON archive for investigation data.

Creates JSON bundles containing all investigation data (facts,
classifications, verification results) with schema versioning
and statistics. Archives are designed for reproducibility: given
an archive, someone can reconstruct the complete investigation.

Per Phase 10 CONTEXT.md: "full investigation archive (facts,
classifications, verification results, graph) for reproducibility."

Usage:
    from osint_system.database import InvestigationArchive

    archive = InvestigationArchive(fact_store, classification_store, verification_store)
    path = await archive.create_archive("inv-123")

    # Later, load and validate
    data = await InvestigationArchive.load_archive(path)
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from osint_system.data_management.classification_store import ClassificationStore
from osint_system.data_management.fact_store import FactStore
from osint_system.data_management.verification_store import VerificationStore

logger = structlog.get_logger()

# Supported schema versions for load validation
_SUPPORTED_VERSIONS = {"1.0"}

# Required top-level keys in a valid archive
_REQUIRED_KEYS = {"schema_version", "archive_type", "investigation_id", "data"}


class InvestigationArchive:
    """Produces self-contained JSON bundles for investigation reproducibility.

    The archive contains all data needed to reconstruct an investigation:
    facts, classifications, verification results, metadata, and statistics.
    Schema versioning enables forward-compatible archive loading.

    Attributes:
        fact_store: Source of investigation facts.
        classification_store: Source of fact classifications.
        verification_store: Source of verification results.
        output_dir: Default directory for archive files.
    """

    def __init__(
        self,
        fact_store: FactStore,
        classification_store: ClassificationStore,
        verification_store: VerificationStore,
        output_dir: str = "exports/",
    ) -> None:
        """Initialize InvestigationArchive.

        Args:
            fact_store: FactStore instance with investigation facts.
            classification_store: ClassificationStore with classifications.
            verification_store: VerificationStore with verification results.
            output_dir: Default output directory for archive files.
        """
        self.fact_store = fact_store
        self.classification_store = classification_store
        self.verification_store = verification_store
        self.output_dir = Path(output_dir)
        self._log = logger.bind(component="InvestigationArchive")

    async def create_archive(
        self,
        investigation_id: str,
        output_path: str | None = None,
    ) -> Path:
        """Create a self-contained JSON archive of the investigation.

        Fetches all data from the three stores, computes statistics,
        and writes a versioned JSON file. The archive includes enough
        metadata to reconstruct the investigation from scratch.

        Args:
            investigation_id: Investigation to archive.
            output_path: Optional explicit output path. If None, uses
                         {output_dir}/{investigation_id}_archive.json.

        Returns:
            Path to the created archive JSON file.
        """
        if output_path is not None:
            archive_path = Path(output_path)
        else:
            archive_path = self.output_dir / f"{investigation_id}_archive.json"

        archive_path.parent.mkdir(parents=True, exist_ok=True)

        # Fetch investigation metadata and facts
        fact_result = await self.fact_store.retrieve_by_investigation(investigation_id)
        facts = fact_result.get("facts", [])
        metadata = fact_result.get("metadata", {})

        # Fetch classifications
        classifications = await self.classification_store.get_all_classifications(
            investigation_id
        )

        # Fetch verification results and serialize to dicts
        verification_records = await self.verification_store.get_all_results(
            investigation_id
        )
        verification_dicts = [
            record.model_dump(mode="json") for record in verification_records
        ]

        # Compute statistics from collected data
        statistics = self._compute_statistics(
            facts, classifications, verification_dicts
        )

        # Build the archive structure
        archive = {
            "schema_version": "1.0",
            "archive_type": "investigation_archive",
            "investigation_id": investigation_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "system_version": "0.1.0",
            "data": {
                "investigation_metadata": {
                    "investigation_id": investigation_id,
                    "objective": metadata.get("objective", ""),
                    "created_at": fact_result.get("created_at", ""),
                    "updated_at": fact_result.get("updated_at", ""),
                    "metadata": metadata,
                },
                "facts": facts,
                "classifications": classifications,
                "verification_results": verification_dicts,
            },
            "statistics": statistics,
        }

        with open(archive_path, "w", encoding="utf-8") as f:
            json.dump(archive, f, indent=2, default=str)

        self._log.info(
            "archive_created",
            investigation_id=investigation_id,
            archive_path=str(archive_path),
            **statistics,
        )

        return archive_path

    @staticmethod
    async def load_archive(archive_path: str | Path) -> dict[str, Any]:
        """Load and validate an investigation archive from JSON.

        Reads the archive file, validates the schema version is
        supported, and checks for required keys.

        Args:
            archive_path: Path to the archive JSON file.

        Returns:
            The complete archive dict.

        Raises:
            ValueError: If schema_version is unsupported or required
                        keys are missing.
            FileNotFoundError: If the archive file does not exist.
        """
        archive_path = Path(archive_path)

        with open(archive_path, "r", encoding="utf-8") as f:
            archive = json.load(f)

        # Validate required keys
        missing_keys = _REQUIRED_KEYS - set(archive.keys())
        if missing_keys:
            raise ValueError(
                f"Archive is missing required keys: {missing_keys}"
            )

        # Validate schema version
        version = archive.get("schema_version")
        if version not in _SUPPORTED_VERSIONS:
            raise ValueError(
                f"Unsupported archive schema version '{version}'. "
                f"Supported: {_SUPPORTED_VERSIONS}"
            )

        return archive

    @staticmethod
    def _compute_statistics(
        facts: list[dict[str, Any]],
        classifications: list[dict[str, Any]],
        verifications: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Compute summary statistics from investigation data.

        Counts facts, classifications, and verification results by status.

        Args:
            facts: List of fact dicts.
            classifications: List of classification dicts.
            verifications: List of verification result dicts.

        Returns:
            Statistics dict with counts and breakdowns.
        """
        confirmed_count = sum(
            1 for v in verifications if v.get("status") == "confirmed"
        )
        refuted_count = sum(
            1 for v in verifications if v.get("status") == "refuted"
        )
        # Count dubious as unverifiable + superseded (not definitively resolved)
        dubious_count = sum(
            1
            for v in verifications
            if v.get("status") in ("unverifiable", "pending", "in_progress")
        )

        return {
            "fact_count": len(facts),
            "classification_count": len(classifications),
            "verification_count": len(verifications),
            "confirmed_count": confirmed_count,
            "refuted_count": refuted_count,
            "dubious_count": dubious_count,
        }
