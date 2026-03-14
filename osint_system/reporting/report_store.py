"""Versioned report storage with content hashing for diff detection.

Manages immutable report snapshots keyed by investigation_id. Each
save_report call computes a SHA256 content hash; if the hash matches the
latest version, the save is skipped (content deduplication). Version
numbers auto-increment per investigation.

Optional JSON persistence allows report metadata to survive process
restarts. In-memory storage uses asyncio.Lock for thread safety.

Usage:
    from osint_system.reporting import ReportStore

    store = ReportStore(output_dir="reports/")
    record = await store.save_report("inv-123", markdown_content)
    print(record.version, record.content_hash)

    latest = await store.get_latest("inv-123")
    changed = await store.has_changed("inv-123", new_content)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, Field

from osint_system.analysis.schemas import AnalysisSynthesis

logger = structlog.get_logger(__name__)


class ReportRecord(BaseModel):
    """Immutable record of a generated report version.

    Each record captures the full Markdown content, its SHA256 hash
    for change detection, file paths for saved artifacts, and summary
    statistics from the synthesis that produced it.

    Attributes:
        investigation_id: Investigation scope identifier.
        version: Auto-incrementing version number (1-based).
        content_hash: SHA256 hex digest of the Markdown content.
        markdown_content: Full Markdown source text.
        markdown_path: Path to the saved .md file, if written to disk.
        pdf_path: Path to the saved .pdf file, if rendered.
        generated_at: Timestamp when this version was generated.
        synthesis_summary: Summary statistics extracted from the synthesis
            (judgment count, confidence level, fact count, etc.).
    """

    investigation_id: str = Field(
        ..., description="Investigation scope identifier"
    )
    version: int = Field(
        ..., ge=1, description="Auto-incrementing version number"
    )
    content_hash: str = Field(
        ..., description="SHA256 hex digest of Markdown content"
    )
    markdown_content: str = Field(
        ..., description="Full Markdown source text"
    )
    markdown_path: str | None = Field(
        default=None, description="Path to saved .md file"
    )
    pdf_path: str | None = Field(
        default=None, description="Path to saved .pdf file"
    )
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when this version was generated",
    )
    synthesis_summary: dict[str, Any] = Field(
        default_factory=dict,
        description="Summary statistics from the synthesis",
    )


class ReportStore:
    """Versioned report storage with content deduplication.

    Stores ReportRecord instances in memory, keyed by investigation_id.
    Each investigation maintains an ordered list of versions. Content
    hashing via SHA256 prevents duplicate versions when the Markdown
    content has not changed.

    Thread safety is provided by asyncio.Lock. Optional JSON persistence
    writes report metadata (excluding full Markdown content for size)
    to a file for process restart recovery.

    Attributes:
        output_dir: Base directory for report file output.
        persistence_path: Optional path for JSON metadata persistence.
    """

    def __init__(
        self,
        output_dir: str = "reports/",
        persistence_path: str | None = None,
    ) -> None:
        """Initialize the report store.

        Args:
            output_dir: Base directory for report file output.
            persistence_path: Optional path for JSON metadata persistence.
                If provided, report metadata is written to this file
                after each save_report call.
        """
        self.output_dir = output_dir
        self.persistence_path = persistence_path
        self._reports: dict[str, list[ReportRecord]] = {}
        self._lock = asyncio.Lock()

        logger.info(
            "report_store.initialized",
            output_dir=output_dir,
            persistence_path=persistence_path,
        )

    @staticmethod
    def _compute_hash(content: str) -> str:
        """Compute SHA256 hex digest of content string.

        Args:
            content: String to hash.

        Returns:
            Lowercase hex digest string.
        """
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _extract_synthesis_summary(
        self, synthesis: AnalysisSynthesis | None
    ) -> dict[str, Any]:
        """Extract summary statistics from an AnalysisSynthesis.

        Args:
            synthesis: The analysis synthesis, or None.

        Returns:
            Dictionary with key summary statistics.
        """
        if synthesis is None:
            return {}

        return {
            "investigation_id": synthesis.investigation_id,
            "judgment_count": len(synthesis.key_judgments),
            "alternative_count": len(synthesis.alternative_hypotheses),
            "contradiction_count": len(synthesis.contradictions),
            "overall_confidence_level": synthesis.overall_confidence.level,
            "overall_confidence_numeric": synthesis.overall_confidence.numeric,
            "fact_count": synthesis.snapshot.fact_count,
            "confirmed_count": synthesis.snapshot.confirmed_count,
            "source_count": len(synthesis.snapshot.source_inventory),
            "model_version": synthesis.model_version,
        }

    async def _persist(self) -> None:
        """Write report metadata to JSON file if persistence_path is configured.

        Writes a slimmed-down version of each record (without full
        markdown_content) to avoid excessive file sizes.
        """
        if self.persistence_path is None:
            return

        def _write() -> None:
            path = Path(self.persistence_path)  # type: ignore[arg-type]
            path.parent.mkdir(parents=True, exist_ok=True)

            # Slim records: exclude full markdown_content for file size
            data: dict[str, list[dict[str, Any]]] = {}
            for inv_id, records in self._reports.items():
                data[inv_id] = []
                for record in records:
                    slim = record.model_dump(mode="json")
                    slim.pop("markdown_content", None)
                    data[inv_id].append(slim)

            path.write_text(
                json.dumps(data, indent=2, default=str),
                encoding="utf-8",
            )

        await asyncio.to_thread(_write)

        logger.debug(
            "report_store.persisted",
            path=self.persistence_path,
        )

    async def save_report(
        self,
        investigation_id: str,
        markdown_content: str,
        synthesis: AnalysisSynthesis | None = None,
        markdown_path: str | None = None,
        pdf_path: str | None = None,
    ) -> ReportRecord:
        """Save a report version with content deduplication.

        Computes the SHA256 hash of the Markdown content. If the hash
        matches the latest stored version for this investigation, the
        save is skipped and the existing record is returned. Otherwise,
        a new version is created with an incremented version number.

        Args:
            investigation_id: Investigation scope identifier.
            markdown_content: Full Markdown report source.
            synthesis: Optional AnalysisSynthesis for summary extraction.
            markdown_path: Path to saved .md file, if any.
            pdf_path: Path to saved .pdf file, if any.

        Returns:
            The ReportRecord for this version (new or existing).
        """
        content_hash = self._compute_hash(markdown_content)

        async with self._lock:
            versions = self._reports.get(investigation_id, [])

            # Check for content deduplication
            if versions:
                latest = versions[-1]
                if latest.content_hash == content_hash:
                    logger.info(
                        "report_store.skipped_unchanged",
                        investigation_id=investigation_id,
                        version=latest.version,
                        content_hash=content_hash[:12],
                    )
                    return latest

            # Determine next version number
            next_version = (versions[-1].version + 1) if versions else 1

            # Extract synthesis summary
            summary = self._extract_synthesis_summary(synthesis)

            record = ReportRecord(
                investigation_id=investigation_id,
                version=next_version,
                content_hash=content_hash,
                markdown_content=markdown_content,
                markdown_path=markdown_path,
                pdf_path=pdf_path,
                synthesis_summary=summary,
            )

            if investigation_id not in self._reports:
                self._reports[investigation_id] = []
            self._reports[investigation_id].append(record)

            logger.info(
                "report_store.saved",
                investigation_id=investigation_id,
                version=next_version,
                content_hash=content_hash[:12],
            )

        # Persist outside the lock to avoid holding it during I/O
        await self._persist()

        return record

    async def get_latest(
        self, investigation_id: str
    ) -> ReportRecord | None:
        """Return the most recent report version for an investigation.

        Args:
            investigation_id: Investigation scope identifier.

        Returns:
            The latest ReportRecord, or None if no reports exist.
        """
        async with self._lock:
            versions = self._reports.get(investigation_id, [])
            return versions[-1] if versions else None

    async def get_version(
        self, investigation_id: str, version: int
    ) -> ReportRecord | None:
        """Return a specific report version by number.

        Args:
            investigation_id: Investigation scope identifier.
            version: Version number to retrieve (1-based).

        Returns:
            The ReportRecord for that version, or None if not found.
        """
        async with self._lock:
            versions = self._reports.get(investigation_id, [])
            for record in versions:
                if record.version == version:
                    return record
            return None

    async def list_versions(
        self, investigation_id: str
    ) -> list[ReportRecord]:
        """Return all report versions for an investigation.

        Args:
            investigation_id: Investigation scope identifier.

        Returns:
            List of ReportRecords ordered by version number (ascending).
        """
        async with self._lock:
            return list(self._reports.get(investigation_id, []))

    async def has_changed(
        self, investigation_id: str, markdown_content: str
    ) -> bool:
        """Check if new content differs from the latest stored version.

        Compares SHA256 hashes. Returns True if the content is different
        from the latest stored version, or if no previous version exists.

        Args:
            investigation_id: Investigation scope identifier.
            markdown_content: New Markdown content to compare.

        Returns:
            True if content has changed (or no previous version exists).
        """
        content_hash = self._compute_hash(markdown_content)

        async with self._lock:
            versions = self._reports.get(investigation_id, [])
            if not versions:
                return True
            return versions[-1].content_hash != content_hash

    async def list_investigations(self) -> list[dict[str, Any]]:
        """Return summary of all investigations with report metadata.

        Provides a high-level view of all stored investigations including
        report counts and latest version info.

        Returns:
            List of dicts with investigation_id, report_count,
            latest_version, latest_generated_at, and latest_confidence.
        """
        async with self._lock:
            result: list[dict[str, Any]] = []
            for inv_id, versions in self._reports.items():
                latest = versions[-1] if versions else None
                entry: dict[str, Any] = {
                    "investigation_id": inv_id,
                    "report_count": len(versions),
                    "latest_version": latest.version if latest else 0,
                    "latest_generated_at": (
                        latest.generated_at.isoformat() if latest else None
                    ),
                    "latest_confidence": latest.synthesis_summary.get(
                        "overall_confidence_level", "N/A"
                    ) if latest else "N/A",
                }
                result.append(entry)
            return result
