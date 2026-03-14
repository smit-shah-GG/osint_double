"""Template rendering tests for HTMX integration and content correctness.

Validates that templates include required HTMX attributes, navigation
links, data table structures, and auto-refresh polling directives.
Uses Jinja2 Environment directly to test template rendering in
isolation from FastAPI route logic.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

_TEMPLATES_DIR = (
    Path(__file__).parent.parent.parent
    / "osint_system"
    / "dashboard"
    / "templates"
)


def _get_env() -> Environment:
    """Create a Jinja2 environment pointing at dashboard templates."""
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=False,
    )


def test_base_template_has_htmx_script() -> None:
    """base.html includes the HTMX script tag from CDN."""
    env = _get_env()
    template = env.get_template("base.html")
    rendered = template.render()
    assert "htmx.org" in rendered
    assert "<script" in rendered
    assert "unpkg.com/htmx.org" in rendered


def test_base_template_has_nav_links() -> None:
    """base.html has navigation links for Investigations and Monitoring."""
    env = _get_env()
    template = env.get_template("base.html")
    rendered = template.render()
    assert 'href="/"' in rendered or "href='/'" in rendered
    assert "Investigations" in rendered
    assert "/monitoring/status" in rendered
    assert "Monitoring" in rendered


def test_base_template_has_css_link() -> None:
    """base.html links to the static CSS file."""
    env = _get_env()
    template = env.get_template("base.html")
    rendered = template.render()
    assert "/static/styles.css" in rendered


def test_investigation_list_renders_cards() -> None:
    """investigations/list.html renders investigation cards from context."""
    env = _get_env()
    template = env.get_template("investigations/list.html")
    rendered = template.render(
        investigations=[
            {
                "investigation_id": "inv-test-001",
                "fact_count": 42,
                "critical_count": 5,
                "dubious_count": 8,
                "verification_total": 15,
                "has_report": True,
                "report_version": 2,
                "updated_at": "2026-03-14T10:00:00Z",
            },
            {
                "investigation_id": "inv-test-002",
                "fact_count": 10,
                "critical_count": 1,
                "dubious_count": 3,
                "verification_total": 5,
                "has_report": False,
                "report_version": None,
                "updated_at": "2026-03-13T08:00:00Z",
            },
        ],
    )
    assert "inv-test-001" in rendered
    assert "inv-test-002" in rendered
    assert "investigation-card" in rendered
    assert "42" in rendered
    assert "not generated" in rendered


def test_investigation_detail_renders_stats() -> None:
    """investigations/detail.html renders investigation stats."""
    env = _get_env()
    template = env.get_template("investigations/detail.html")
    rendered = template.render(
        investigation_id="inv-detail-test",
        total_facts=25,
        class_stats={
            "critical_count": 4,
            "dubious_count": 6,
            "verified_count": 12,
        },
        ver_stats={"total": 18},
        has_report=True,
        report_version=1,
        report_generated_at="2026-03-14T09:00:00Z",
        facts=[],
    )
    assert "inv-detail-test" in rendered
    assert "25" in rendered
    assert "Report available" in rendered or "v1" in rendered


def test_facts_list_renders_table() -> None:
    """facts/list.html renders fact table with filter controls."""
    env = _get_env()
    template = env.get_template("facts/list.html")
    rendered = template.render(
        investigation_id="inv-facts-test",
        facts=[
            {
                "fact_id": "fact-abc",
                "claim": "Test claim about geopolitics",
                "impact_tier": "critical",
                "verification_status": "confirmed",
                "confidence": 0.95,
                "source": "reuters",
            },
        ],
        total_facts=1,
        page=1,
        total_pages=1,
        current_tier="all",
        current_status="all",
    )
    assert "fact-abc" in rendered
    assert "data-table" in rendered
    assert "filter-controls" in rendered or "tier-filter" in rendered
    assert "confirmed" in rendered


def test_monitoring_status_has_auto_refresh() -> None:
    """monitoring/status.html has hx-trigger='every 10s' for auto-refresh."""
    env = _get_env()
    template = env.get_template("monitoring/status.html")
    rendered = template.render(
        total_investigations=2,
        total_facts=50,
        total_classifications=45,
        total_verification_records=30,
        total_verified=20,
        total_pending_review=3,
        aggregated_status_counts={},
        per_investigation=[
            {
                "investigation_id": "inv-mon-test",
                "fact_count": 25,
                "verified_count": 10,
                "pending_count": 2,
                "total_verifications": 15,
                "report_status": "available",
            },
        ],
        fact_stats={},
        class_stats={},
    )
    assert 'hx-trigger="every 10s"' in rendered or "every 10s" in rendered
    assert "inv-mon-test" in rendered
    assert "50" in rendered


def test_reports_view_has_regenerate_button() -> None:
    """reports/view.html has POST button for report generation."""
    env = _get_env()
    template = env.get_template("reports/view.html")

    # Test with no report
    rendered_no_report = template.render(
        investigation_id="inv-report-test",
        has_report=False,
        report=None,
        report_html="",
        versions=[],
        version_count=0,
    )
    assert "Generate Report" in rendered_no_report
    assert "No report generated" in rendered_no_report
    assert "/reports/inv-report-test/generate" in rendered_no_report

    # Test with existing report
    class MockReport:
        version = 1
        generated_at = "2026-03-14T10:00:00Z"
        content_hash = "abc123def456"

    rendered_with_report = template.render(
        investigation_id="inv-report-test",
        has_report=True,
        report=MockReport(),
        report_html="<p>Executive Summary</p>",
        versions=[MockReport()],
        version_count=1,
    )
    assert "Regenerate Report" in rendered_with_report
    assert "Executive Summary" in rendered_with_report
    assert "hx-post" in rendered_with_report


def test_facts_list_has_htmx_filter() -> None:
    """facts/list.html filter selects use hx-get for partial reload."""
    env = _get_env()
    template = env.get_template("facts/list.html")
    rendered = template.render(
        investigation_id="inv-htmx-test",
        facts=[],
        total_facts=0,
        page=1,
        total_pages=1,
        current_tier="all",
        current_status="all",
    )
    assert "hx-get" in rendered
    assert "hx-target" in rendered
