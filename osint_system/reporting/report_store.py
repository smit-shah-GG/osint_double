"""Versioned report storage backed by PostgreSQL via SQLAlchemy async sessions.

Manages immutable report snapshots keyed by investigation_id. Each
save_report call computes a SHA256 content hash; if the hash matches the
latest version, the save is skipped (content deduplication). Version
numbers auto-increment per investigation via PostgreSQL queries.

When an EmbeddingService is provided, save_report embeds the executive
summary from the synthesis and stores the vector in the ReportModel's
pgvector Vector(1024) column for cross-investigation similarity search.

File output to output_dir is preserved for backward compatibility with
the PDF renderer and dashboard. The database is the source of truth
for report content and versioning; files are artifacts.

Usage:
    from osint_system.data_management.database import init_db
    from osint_system.reporting.report_store import ReportStore

    session_factory = init_db()
    store = ReportStore(session_factory=session_factory, output_dir="reports/")
    record = await store.save_report("inv-123", markdown_content)
    latest = await store.get_latest("inv-123")
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from osint_system.analysis.schemas import AnalysisSynthesis
from osint_system.data_management.models.report import ReportModel

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
    """PostgreSQL-backed versioned report storage with content deduplication.

    Replaces in-memory dict storage with async SQLAlchemy sessions.
    Content hashing via SHA256 prevents duplicate versions when the
    Markdown content has not changed. EmbeddingService optionally
    generates pgvector embeddings on the executive summary.

    File output to output_dir is preserved for PDF generation and
    dashboard compatibility. The database is the source of truth.

    Attributes:
        output_dir: Base directory for report file output.
    """

    def __init__(
        self,
        output_dir: str = "reports/",
        session_factory: Optional[async_sessionmaker[AsyncSession]] = None,
        embedding_service: Any = None,
    ) -> None:
        """Initialize the report store.

        Args:
            output_dir: Base directory for report file output.
            session_factory: SQLAlchemy async session factory from database.py.
                If None, falls back to the module-level factory via init_db().
            embedding_service: Optional EmbeddingService instance for
                generating pgvector embeddings on executive summaries.
                If None, embedding column is left as NULL.
        """
        if session_factory is None:
            from osint_system.data_management.database import get_session_factory
            session_factory = get_session_factory()

        self.output_dir = output_dir
        self._session_factory = session_factory
        self._embedding_service = embedding_service

        logger.info(
            "report_store.initialized",
            output_dir=output_dir,
            embedding_enabled=embedding_service is not None,
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

    def _extract_executive_summary(
        self, synthesis: AnalysisSynthesis | dict | None
    ) -> str | None:
        """Extract executive_summary text from synthesis for embedding.

        Args:
            synthesis: AnalysisSynthesis Pydantic model, dict, or None.

        Returns:
            Executive summary string, or None if not available.
        """
        if synthesis is None:
            return None

        if hasattr(synthesis, "executive_summary"):
            return synthesis.executive_summary
        elif isinstance(synthesis, dict):
            return synthesis.get("executive_summary")

        return None

    def _model_to_record(self, model: ReportModel) -> ReportRecord:
        """Convert a ReportModel ORM instance to a ReportRecord.

        Args:
            model: The ORM model instance.

        Returns:
            ReportRecord Pydantic model.
        """
        data = model.to_dict()
        return ReportRecord.model_validate(data)

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

        When an EmbeddingService is configured and synthesis contains an
        executive_summary, the summary is embedded as a 1024-dim vector
        and stored in the ReportModel's pgvector column.

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

        async with self._session_factory() as session:
            # Check for content deduplication: get latest version
            latest_result = await session.execute(
                select(ReportModel)
                .where(ReportModel.investigation_id == investigation_id)
                .order_by(ReportModel.version.desc())
                .limit(1)
            )
            latest_model = latest_result.scalar_one_or_none()

            if latest_model is not None and latest_model.content_hash == content_hash:
                logger.info(
                    "report_store.skipped_unchanged",
                    investigation_id=investigation_id,
                    version=latest_model.version,
                    content_hash=content_hash[:12],
                )
                return self._model_to_record(latest_model)

            # Determine next version number
            next_version = (latest_model.version + 1) if latest_model else 1

            # Extract synthesis summary
            summary = self._extract_synthesis_summary(synthesis)

            # Build the ORM model
            model = ReportModel(
                investigation_id=investigation_id,
                version=next_version,
                content_hash=content_hash,
                markdown_content=markdown_content,
                markdown_path=markdown_path,
                pdf_path=pdf_path,
                generated_at=datetime.now(timezone.utc),
                synthesis_summary=summary,
            )

            # Generate embedding from executive summary if service available
            if self._embedding_service is not None:
                exec_summary = self._extract_executive_summary(synthesis)
                if exec_summary:
                    embedding = await self._embedding_service.embed(exec_summary)
                    model.embedding = embedding

            session.add(model)
            await session.commit()

            logger.info(
                "report_store.saved",
                investigation_id=investigation_id,
                version=next_version,
                content_hash=content_hash[:12],
            )

            return self._model_to_record(model)

    async def get_latest(
        self, investigation_id: str
    ) -> ReportRecord | None:
        """Return the most recent report version for an investigation.

        If markdown_content is empty (should not happen with PostgreSQL
        backend), attempts to hydrate from disk.

        Args:
            investigation_id: Investigation scope identifier.

        Returns:
            The latest ReportRecord, or None if no reports exist.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(ReportModel)
                .where(ReportModel.investigation_id == investigation_id)
                .order_by(ReportModel.version.desc())
                .limit(1)
            )
            model = result.scalar_one_or_none()
            if model is None:
                return None

            record = self._model_to_record(model)

            # Hydrate markdown from disk if empty (edge case for persistence compat)
            if not record.markdown_content:
                record.markdown_content = self._load_markdown_from_disk(
                    investigation_id, record
                )

            return record

    def _load_markdown_from_disk(
        self, investigation_id: str, record: ReportRecord
    ) -> str:
        """Try to load markdown content from the report file on disk."""
        # Try markdown_path from record
        if record.markdown_path:
            p = Path(record.markdown_path)
            if p.exists():
                return p.read_text(encoding="utf-8")

        # Try standard report location: data/reports/<inv_id>.md
        standard = Path("data") / "reports" / f"{investigation_id}.md"
        if standard.exists():
            return standard.read_text(encoding="utf-8")

        return ""

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
        async with self._session_factory() as session:
            result = await session.execute(
                select(ReportModel).where(
                    ReportModel.investigation_id == investigation_id,
                    ReportModel.version == version,
                )
            )
            model = result.scalar_one_or_none()
            if model is None:
                return None
            return self._model_to_record(model)

    async def list_versions(
        self, investigation_id: str
    ) -> list[ReportRecord]:
        """Return all report versions for an investigation.

        Args:
            investigation_id: Investigation scope identifier.

        Returns:
            List of ReportRecords ordered by version number (ascending).
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(ReportModel)
                .where(ReportModel.investigation_id == investigation_id)
                .order_by(ReportModel.version.asc())
            )
            models = result.scalars().all()
            return [self._model_to_record(m) for m in models]

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

        async with self._session_factory() as session:
            result = await session.execute(
                select(ReportModel.content_hash)
                .where(ReportModel.investigation_id == investigation_id)
                .order_by(ReportModel.version.desc())
                .limit(1)
            )
            latest_hash = result.scalar_one_or_none()
            if latest_hash is None:
                return True
            return latest_hash != content_hash

    async def list_investigations(self) -> list[dict[str, Any]]:
        """Return summary of all investigations with report metadata.

        Provides a high-level view of all stored investigations including
        report counts and latest version info.

        Returns:
            List of dicts with investigation_id, report_count,
            latest_version, latest_generated_at, and latest_confidence.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(ReportModel).order_by(
                    ReportModel.investigation_id,
                    ReportModel.version.asc(),
                )
            )
            models = result.scalars().all()

        # Group by investigation_id
        inv_map: dict[str, list[ReportModel]] = {}
        for model in models:
            inv_id = model.investigation_id
            if inv_id not in inv_map:
                inv_map[inv_id] = []
            inv_map[inv_id].append(model)

        result_list: list[dict[str, Any]] = []
        for inv_id, versions in inv_map.items():
            latest = versions[-1]
            summary = latest.synthesis_summary or {}
            entry: dict[str, Any] = {
                "investigation_id": inv_id,
                "report_count": len(versions),
                "latest_version": latest.version,
                "latest_generated_at": (
                    latest.generated_at.isoformat()
                    if latest.generated_at
                    else None
                ),
                "latest_confidence": summary.get(
                    "overall_confidence_level", "N/A"
                ),
            }
            result_list.append(entry)
        return result_list

    async def get_report_count(self) -> int:
        """Get count of distinct investigations with reports.

        Returns:
            Number of distinct investigation_ids with at least one report.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(func.count(func.distinct(ReportModel.investigation_id)))
            )
            return result.scalar_one()
