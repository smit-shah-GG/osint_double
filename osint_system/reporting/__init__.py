"""Report generation and rendering for intelligence products.

Provides the full reporting pipeline: AnalysisSynthesis -> Markdown
(via Jinja2 templates) -> PDF (via mistune + WeasyPrint). Includes
versioned report storage with content hashing for diff detection.

Key exports:
- ReportGenerator: Assembles Markdown reports from AnalysisSynthesis
- PDFRenderer: Converts Markdown to styled PDF (graceful fallback)
- ReportStore: Versioned report storage with content deduplication
- ReportRecord: Immutable record of a generated report version
"""

from osint_system.reporting.pdf_renderer import PDFRenderer
from osint_system.reporting.report_generator import ReportGenerator

__all__ = [
    "PDFRenderer",
    "ReportGenerator",
]
