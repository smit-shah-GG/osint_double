"""Markdown report generator from AnalysisSynthesis via Jinja2 templates.

Renders IC-style intelligence reports using Jinja2 templates with
FileSystemLoader. The generated Markdown follows intelligence community
conventions: executive brief, key findings with confidence levels,
alternative analyses, contradictions, source inventory, timeline, and
a full evidence appendix.

Usage:
    from osint_system.reporting import ReportGenerator
    from osint_system.analysis import AnalysisSynthesis

    generator = ReportGenerator()
    markdown = generator.generate_markdown(synthesis)
    await generator.save_markdown(markdown, "reports/inv-123-v1.md")
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import structlog
from jinja2 import Environment, FileSystemLoader, select_autoescape

from osint_system.analysis.schemas import AnalysisSynthesis
from osint_system.config.analysis_config import AnalysisConfig

logger = structlog.get_logger(__name__)

# Default template directory: adjacent to this module
_DEFAULT_TEMPLATE_DIR = Path(__file__).parent / "templates"


class ReportGenerator:
    """Assembles Markdown intelligence reports from AnalysisSynthesis.

    Uses Jinja2 templates with FileSystemLoader for maintainable,
    non-hardcoded report structure. Templates follow IC conventions:
    executive brief -> key findings -> alternatives -> contradictions
    -> implications -> confidence assessment -> sources -> timeline
    -> evidence appendix.

    Attributes:
        config: Analysis configuration (model settings, output paths).
        env: Jinja2 template environment.
    """

    def __init__(
        self,
        config: AnalysisConfig | None = None,
        template_dir: str | Path | None = None,
    ) -> None:
        """Initialize the report generator.

        Args:
            config: Analysis engine configuration. Uses defaults if None.
            template_dir: Path to Jinja2 template directory. Defaults to
                the package's built-in templates/ directory.
        """
        self.config = config or AnalysisConfig()
        resolved_dir = Path(template_dir) if template_dir else _DEFAULT_TEMPLATE_DIR

        if not resolved_dir.is_dir():
            raise FileNotFoundError(
                f"Template directory does not exist: {resolved_dir}"
            )

        self.env = Environment(
            loader=FileSystemLoader(str(resolved_dir)),
            autoescape=select_autoescape(disabled_extensions=("md.j2",)),
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )
        logger.info(
            "report_generator.initialized",
            template_dir=str(resolved_dir),
        )

    def _build_template_context(
        self, synthesis: AnalysisSynthesis
    ) -> dict[str, Any]:
        """Extract all fields from AnalysisSynthesis for template rendering.

        Flattens nested Pydantic models into dicts suitable for Jinja2
        template access. The snapshot's facts are enriched with
        verification status and classification data for the evidence
        appendix.

        Args:
            synthesis: Complete analysis output.

        Returns:
            Template context dictionary with all report fields.
        """
        # Build verification status lookup: fact_id -> status
        verification_lookup: dict[str, str] = {}
        for vr in synthesis.snapshot.verification_results:
            fid = vr.get("fact_id", "")
            status = vr.get("status", "N/A")
            if fid:
                verification_lookup[fid] = status

        # Build classification lookup: fact_id -> credibility_score
        classification_lookup: dict[str, float] = {}
        for cl in synthesis.snapshot.classifications:
            fid = cl.get("fact_id", "")
            score = cl.get("credibility_score", 0.0)
            if fid:
                classification_lookup[fid] = score

        # Flatten facts for evidence appendix
        facts_for_appendix: list[dict[str, Any]] = []
        for fact in synthesis.snapshot.facts:
            fact_id = fact.get("fact_id", "unknown")
            claim_text = fact.get("claim_text", "")
            extraction_confidence = fact.get("extraction_confidence")
            provenance = fact.get("provenance", {})
            source_url = ""
            provenance_str = ""

            if isinstance(provenance, dict):
                source_url = provenance.get("source_url", "")
                provenance_str = provenance.get("source_id", "")
            elif isinstance(provenance, str):
                provenance_str = provenance

            # Enrich with verification status
            verification_status = verification_lookup.get(fact_id, "N/A")

            # Final confidence from classification credibility_score
            cred_score = classification_lookup.get(fact_id)
            final_confidence = (
                f"{cred_score:.2f}" if cred_score is not None else "N/A"
            )

            # Entity references
            entities = fact.get("entities", [])
            entity_str = ""
            if entities:
                if isinstance(entities, list):
                    names = []
                    for ent in entities:
                        if isinstance(ent, dict):
                            names.append(ent.get("name", str(ent)))
                        else:
                            names.append(str(ent))
                    entity_str = ", ".join(names)
                else:
                    entity_str = str(entities)

            facts_for_appendix.append(
                {
                    "fact_id": fact_id,
                    "claim_text": claim_text,
                    "extraction_confidence": (
                        f"{extraction_confidence:.2f}"
                        if extraction_confidence is not None
                        else "N/A"
                    ),
                    "verification_status": verification_status,
                    "final_confidence": final_confidence,
                    "source_url": source_url,
                    "provenance": provenance_str,
                    "entities": entity_str,
                }
            )

        # Convert Pydantic models to dicts for template access
        context: dict[str, Any] = {
            "investigation_id": synthesis.investigation_id,
            "generated_at": synthesis.generated_at.strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            ),
            "version": synthesis.version,
            "executive_summary": synthesis.executive_summary,
            "key_judgments": [
                j.model_dump() for j in synthesis.key_judgments
            ],
            "alternative_hypotheses": [
                a.model_dump() for a in synthesis.alternative_hypotheses
            ],
            "contradictions": [
                c.model_dump() for c in synthesis.contradictions
            ],
            "implications": synthesis.implications,
            "forecasts": synthesis.forecasts,
            "overall_confidence": synthesis.overall_confidence.model_dump(),
            "source_assessment": synthesis.source_assessment,
            "source_inventory": [
                s.model_dump() for s in synthesis.snapshot.source_inventory
            ],
            "timeline_entries": [
                t.model_dump() for t in synthesis.snapshot.timeline_entries
            ],
            "snapshot": synthesis.snapshot.model_dump(),
            "facts": facts_for_appendix,
        }

        return context

    def generate_markdown(self, synthesis: AnalysisSynthesis) -> str:
        """Render the full intelligence report as Markdown.

        Produces a complete IC-style report from the intelligence_report.md.j2
        template, including executive brief, key findings, alternative
        analyses, contradictions, implications, confidence assessment,
        source inventory, timeline, and evidence appendix.

        Args:
            synthesis: Complete analysis output from the synthesis engine.

        Returns:
            Rendered Markdown string.
        """
        context = self._build_template_context(synthesis)
        template = self.env.get_template("intelligence_report.md.j2")
        rendered = template.render(**context)

        logger.info(
            "report_generator.markdown_generated",
            investigation_id=synthesis.investigation_id,
            version=synthesis.version,
            length=len(rendered),
        )

        return rendered

    def generate_executive_brief(self, synthesis: AnalysisSynthesis) -> str:
        """Render only the executive summary section.

        Produces a short Markdown fragment containing just the executive
        brief with key statistics. Useful for quick overviews and
        dashboard previews.

        Args:
            synthesis: Complete analysis output from the synthesis engine.

        Returns:
            Rendered Markdown string (executive brief only).
        """
        context = self._build_template_context(synthesis)
        template = self.env.get_template("executive_brief.md.j2")
        rendered = template.render(**context)

        logger.info(
            "report_generator.executive_brief_generated",
            investigation_id=synthesis.investigation_id,
            length=len(rendered),
        )

        return rendered

    async def save_markdown(
        self, markdown: str, output_path: str | Path
    ) -> Path:
        """Write Markdown content to a file.

        Creates parent directories if they do not exist. Uses
        asyncio.to_thread to avoid blocking the event loop on file I/O.

        Args:
            markdown: Markdown string to write.
            output_path: Destination file path.

        Returns:
            Resolved Path to the written file.
        """
        path = Path(output_path)

        def _write() -> Path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(markdown, encoding="utf-8")
            return path.resolve()

        result = await asyncio.to_thread(_write)

        logger.info(
            "report_generator.markdown_saved",
            path=str(result),
            size_bytes=len(markdown.encode("utf-8")),
        )

        return result
