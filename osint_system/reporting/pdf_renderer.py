"""Markdown to PDF renderer via mistune and WeasyPrint.

Converts Markdown intelligence reports to professionally styled PDFs.
WeasyPrint is an optional dependency: if unavailable (missing system
libraries like pango, cairo, etc.), the renderer logs a warning and
returns None, allowing callers to fall back to Markdown-only output.

Usage:
    from osint_system.reporting import PDFRenderer

    renderer = PDFRenderer()
    pdf_path = await renderer.render_pdf(markdown_content, "report.pdf")
    if pdf_path is None:
        print("WeasyPrint unavailable; PDF not generated")
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import mistune
import structlog

logger = structlog.get_logger(__name__)

# Default CSS path: adjacent styles directory
_DEFAULT_CSS_PATH = Path(__file__).parent / "styles" / "report.css"


class PDFRenderer:
    """Renders Markdown to PDF via mistune (Markdown -> HTML) and WeasyPrint (HTML -> PDF).

    The renderer embeds CSS directly into the HTML document to avoid
    file path issues with WeasyPrint's resource resolution. If WeasyPrint
    is not installed or its system dependencies are missing, render_pdf
    returns None and logs a warning.

    Attributes:
        css_path: Path to the CSS stylesheet for PDF styling.
    """

    def __init__(self, css_path: str | Path | None = None) -> None:
        """Initialize the PDF renderer.

        Args:
            css_path: Path to CSS stylesheet. Defaults to the package's
                built-in styles/report.css.
        """
        self.css_path = Path(css_path) if css_path else _DEFAULT_CSS_PATH

        if not self.css_path.is_file():
            logger.warning(
                "pdf_renderer.css_not_found",
                css_path=str(self.css_path),
            )

        logger.info(
            "pdf_renderer.initialized",
            css_path=str(self.css_path),
        )

    def _read_css(self) -> str:
        """Read the CSS stylesheet content.

        Returns:
            CSS string, or empty string if file not found.
        """
        if self.css_path.is_file():
            return self.css_path.read_text(encoding="utf-8")
        return ""

    def _wrap_html(self, body_html: str) -> str:
        """Wrap body HTML in a full document with embedded CSS.

        Embeds the stylesheet directly via a <style> tag rather than
        using a <link> element. This avoids WeasyPrint file path
        resolution issues and makes the HTML self-contained.

        Args:
            body_html: HTML fragment produced by mistune.

        Returns:
            Complete HTML document string.
        """
        css_content = self._read_css()

        return (
            "<!DOCTYPE html>\n"
            '<html lang="en">\n'
            "<head>\n"
            '  <meta charset="utf-8">\n'
            "  <title>Intelligence Report</title>\n"
            "  <style>\n"
            f"    {css_content}\n"
            "  </style>\n"
            "</head>\n"
            "<body>\n"
            f"  {body_html}\n"
            "</body>\n"
            "</html>"
        )

    async def render_pdf(
        self, markdown_content: str, output_path: str | Path
    ) -> Path | None:
        """Convert Markdown to PDF.

        Pipeline: Markdown -> HTML (mistune) -> styled HTML -> PDF (WeasyPrint).
        The WeasyPrint call runs in asyncio.to_thread to avoid blocking
        the event loop (per RESEARCH.md anti-patterns guidance).

        If WeasyPrint is not installed or its system dependencies are
        missing, logs a warning and returns None. Callers should handle
        None gracefully by falling back to Markdown-only output.

        Args:
            markdown_content: Markdown source string.
            output_path: Destination path for the PDF file.

        Returns:
            Path to the generated PDF, or None if WeasyPrint unavailable.
        """
        path = Path(output_path)

        # Step 1: Markdown -> HTML via mistune
        body_html = mistune.html(markdown_content)

        # Step 2: Wrap in full HTML document with embedded CSS
        full_html = self._wrap_html(body_html)

        # Step 3: HTML -> PDF via WeasyPrint (in thread)
        try:
            from weasyprint import HTML as WeasyHTML
        except (ImportError, OSError) as exc:
            logger.warning(
                "pdf_renderer.weasyprint_unavailable",
                error=str(exc),
                hint="Install WeasyPrint system dependencies (pango, cairo, gdk-pixbuf) for PDF output",
            )
            return None

        def _render() -> Path:
            path.parent.mkdir(parents=True, exist_ok=True)
            WeasyHTML(string=full_html).write_pdf(str(path))
            return path.resolve()

        try:
            result = await asyncio.to_thread(_render)
            logger.info(
                "pdf_renderer.pdf_generated",
                path=str(result),
                size_bytes=result.stat().st_size,
            )
            return result
        except Exception as exc:
            logger.error(
                "pdf_renderer.render_failed",
                error=str(exc),
                output_path=str(path),
            )
            return None
