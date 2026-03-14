"""Tests for ReportGenerator and PDFRenderer.

Validates that the Jinja2 template rendering produces complete IC-style
Markdown reports from AnalysisSynthesis data, and that PDFRenderer
correctly wraps HTML with embedded CSS.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from osint_system.analysis.schemas import (
    AlternativeHypothesis,
    AnalysisSynthesis,
    ConfidenceAssessment,
    ContradictionEntry,
    InvestigationSnapshot,
    KeyJudgment,
    SourceInventoryEntry,
    TimelineEntry,
)
from osint_system.reporting.pdf_renderer import PDFRenderer
from osint_system.reporting.report_generator import ReportGenerator


@pytest.fixture
def snapshot() -> InvestigationSnapshot:
    """InvestigationSnapshot with realistic mock data."""
    return InvestigationSnapshot(
        investigation_id="inv-test-001",
        objective="Assess military buildup in eastern region",
        facts=[
            {
                "fact_id": "fact-001",
                "claim_text": "Satellite imagery shows 15 new armored vehicles at base X",
                "extraction_confidence": 0.92,
                "provenance": {
                    "source_url": "https://imagery.example.com/report-123",
                    "source_id": "imagery.example.com",
                },
                "entities": [
                    {"name": "Base X", "type": "LOC"},
                    {"name": "Eastern Command", "type": "ORG"},
                ],
            },
            {
                "fact_id": "fact-002",
                "claim_text": "Local media reports increased military convoy activity",
                "extraction_confidence": 0.78,
                "provenance": {
                    "source_url": "https://localnews.example.com/article/456",
                    "source_id": "localnews.example.com",
                },
                "entities": [],
            },
            {
                "fact_id": "fact-003",
                "claim_text": "Defense ministry denies troop buildup",
                "extraction_confidence": 0.95,
                "provenance": {
                    "source_url": "https://gov.example.com/press/789",
                    "source_id": "gov.example.com",
                },
            },
        ],
        classifications=[
            {"fact_id": "fact-001", "credibility_score": 0.88},
            {"fact_id": "fact-002", "credibility_score": 0.65},
            {"fact_id": "fact-003", "credibility_score": 0.90},
        ],
        verification_results=[
            {"fact_id": "fact-001", "status": "CONFIRMED"},
            {"fact_id": "fact-002", "status": "PENDING"},
            {"fact_id": "fact-003", "status": "CONFIRMED"},
        ],
        fact_count=3,
        confirmed_count=2,
        refuted_count=0,
        unverifiable_count=0,
        dubious_count=0,
        source_inventory=[
            SourceInventoryEntry(
                source_id="imagery.example.com",
                source_domain="imagery.example.com",
                source_type="satellite_imagery",
                authority_score=0.90,
                fact_count=1,
                last_accessed="2024-03-15T12:00:00Z",
            ),
            SourceInventoryEntry(
                source_id="localnews.example.com",
                source_domain="localnews.example.com",
                source_type="news_outlet",
                authority_score=0.65,
                fact_count=1,
                last_accessed="2024-03-15T11:30:00Z",
            ),
            SourceInventoryEntry(
                source_id="gov.example.com",
                source_domain="gov.example.com",
                source_type="government",
                authority_score=0.85,
                fact_count=1,
                last_accessed="2024-03-15T13:00:00Z",
            ),
        ],
        timeline_entries=[
            TimelineEntry(
                timestamp="2024-03-10",
                event="First satellite imagery shows vehicle movement",
                fact_ids=["fact-001"],
                confidence=ConfidenceAssessment(
                    level="high",
                    numeric=0.90,
                    reasoning="High-resolution imagery",
                    source_count=1,
                    highest_authority=0.90,
                ),
            ),
            TimelineEntry(
                timestamp="2024-03-12",
                event="Local media reports convoy activity",
                fact_ids=["fact-002"],
                confidence=ConfidenceAssessment(
                    level="moderate",
                    numeric=0.65,
                    reasoning="Single source local reporting",
                    source_count=1,
                    highest_authority=0.65,
                ),
            ),
        ],
    )


@pytest.fixture
def synthesis(snapshot: InvestigationSnapshot) -> AnalysisSynthesis:
    """Full AnalysisSynthesis with 3 judgments, 2 alternatives, 1 contradiction."""
    return AnalysisSynthesis(
        investigation_id="inv-test-001",
        executive_summary=(
            "We assess with moderate confidence that a significant military "
            "buildup is occurring in the eastern region. Satellite imagery "
            "confirms vehicle staging at Base X, corroborated by local media "
            "reports of increased convoy activity. The defense ministry denial "
            "is inconsistent with observed evidence."
        ),
        key_judgments=[
            KeyJudgment(
                judgment="Military buildup at Base X is ongoing and significant",
                confidence=ConfidenceAssessment(
                    level="high",
                    numeric=0.88,
                    reasoning="Satellite imagery corroborated by local reporting",
                    source_count=2,
                    highest_authority=0.90,
                ),
                supporting_fact_ids=["fact-001", "fact-002"],
                reasoning=(
                    "High-resolution satellite imagery shows 15 new armored "
                    "vehicles at Base X. Local media independently reports "
                    "increased convoy activity on roads leading to the base."
                ),
            ),
            KeyJudgment(
                judgment="Official denial lacks credibility",
                confidence=ConfidenceAssessment(
                    level="moderate",
                    numeric=0.72,
                    reasoning="Denial contradicts observed evidence from multiple sources",
                    source_count=3,
                    highest_authority=0.90,
                ),
                supporting_fact_ids=["fact-001", "fact-002", "fact-003"],
                reasoning=(
                    "The defense ministry denial directly contradicts satellite "
                    "imagery and local media reports. Pattern consistent with "
                    "historical information operations."
                ),
            ),
            KeyJudgment(
                judgment="Buildup likely precedes operational deployment",
                confidence=ConfidenceAssessment(
                    level="moderate",
                    numeric=0.65,
                    reasoning="Historical pattern analysis suggests preparation phase",
                    source_count=2,
                    highest_authority=0.90,
                ),
                supporting_fact_ids=["fact-001"],
                reasoning=(
                    "The staging pattern at Base X matches historical indicators "
                    "of pre-deployment preparation observed in prior incidents."
                ),
            ),
        ],
        alternative_hypotheses=[
            AlternativeHypothesis(
                hypothesis="Vehicle movement is routine rotation, not buildup",
                likelihood="possible",
                supporting_evidence=[
                    "Annual rotation cycle coincides with current timeline",
                    "No corresponding diplomatic escalation observed",
                ],
                weaknesses=[
                    "Vehicle count exceeds routine rotation by 3x",
                    "Equipment types inconsistent with standard rotation",
                ],
            ),
            AlternativeHypothesis(
                hypothesis="Buildup is defensive posturing, not offensive preparation",
                likelihood="plausible",
                supporting_evidence=[
                    "Recent border incidents may warrant defensive response",
                    "No offensive logistics infrastructure observed",
                ],
                weaknesses=[
                    "Armored vehicles suggest offensive capability",
                    "Base X is historically used for offensive staging",
                ],
            ),
        ],
        contradictions=[
            ContradictionEntry(
                description="Defense ministry denial contradicts satellite imagery",
                fact_ids=["fact-001", "fact-003"],
                resolution_status="unresolved",
                resolution_notes="",
            ),
        ],
        implications=[
            "Regional security posture may require reassessment",
            "Allied forces should increase surveillance of Base X approaches",
            "Diplomatic channels should be activated to de-escalate",
        ],
        forecasts=[
            "Operational deployment within 30-60 days if buildup continues",
            "Additional vehicle staging likely at secondary bases",
        ],
        overall_confidence=ConfidenceAssessment(
            level="moderate",
            numeric=0.72,
            reasoning=(
                "Strong imagery evidence but limited human intelligence. "
                "Source diversity is moderate with 3 independent sources."
            ),
            source_count=3,
            highest_authority=0.90,
        ),
        source_assessment=(
            "Predominantly open-source; 1 satellite imagery provider, "
            "1 local news outlet, 1 government press office. No closed-source "
            "intelligence available for corroboration."
        ),
        snapshot=snapshot,
        generated_at=datetime(2024, 3, 15, 14, 0, 0, tzinfo=timezone.utc),
        model_version="gemini-1.5-pro",
        version=1,
    )


@pytest.fixture
def generator() -> ReportGenerator:
    """ReportGenerator with default template directory."""
    return ReportGenerator()


class TestGenerateMarkdown:
    """Tests for generate_markdown output content."""

    def test_generate_markdown_returns_string(
        self, generator: ReportGenerator, synthesis: AnalysisSynthesis
    ) -> None:
        """generate_markdown returns a non-empty string."""
        result = generator.generate_markdown(synthesis)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_markdown_contains_executive_summary(
        self, generator: ReportGenerator, synthesis: AnalysisSynthesis
    ) -> None:
        """Output contains the executive summary text."""
        result = generator.generate_markdown(synthesis)
        assert "Executive Summary" in result
        assert "moderate confidence" in result
        assert "military buildup" in result.lower()

    def test_markdown_contains_key_findings(
        self, generator: ReportGenerator, synthesis: AnalysisSynthesis
    ) -> None:
        """Output has Key Findings section with all 3 judgments."""
        result = generator.generate_markdown(synthesis)
        assert "## Key Findings" in result
        assert "Finding 1:" in result
        assert "Finding 2:" in result
        assert "Finding 3:" in result
        assert "Military buildup at Base X" in result
        assert "Official denial lacks credibility" in result
        assert "Buildup likely precedes operational deployment" in result

    def test_markdown_contains_alternatives(
        self, generator: ReportGenerator, synthesis: AnalysisSynthesis
    ) -> None:
        """Output has Alternative Analyses section with both hypotheses."""
        result = generator.generate_markdown(synthesis)
        assert "## Alternative Analyses" in result
        assert "Hypothesis 1:" in result
        assert "Hypothesis 2:" in result
        assert "routine rotation" in result
        assert "defensive posturing" in result

    def test_markdown_contains_contradictions(
        self, generator: ReportGenerator, synthesis: AnalysisSynthesis
    ) -> None:
        """Output has Contradictions section with the contradiction."""
        result = generator.generate_markdown(synthesis)
        assert "Contradictions" in result
        assert "Defense ministry denial contradicts satellite imagery" in result
        assert "fact-001" in result
        assert "fact-003" in result

    def test_markdown_contains_source_table(
        self, generator: ReportGenerator, synthesis: AnalysisSynthesis
    ) -> None:
        """Output has markdown table with source inventory."""
        result = generator.generate_markdown(synthesis)
        assert "## Source Inventory" in result
        assert "imagery.example.com" in result
        assert "localnews.example.com" in result
        assert "gov.example.com" in result
        assert "satellite_imagery" in result
        assert "0.90" in result

    def test_markdown_contains_timeline_table(
        self, generator: ReportGenerator, synthesis: AnalysisSynthesis
    ) -> None:
        """Output has timeline table with entries."""
        result = generator.generate_markdown(synthesis)
        assert "## Timeline Summary" in result
        assert "2024-03-10" in result
        assert "2024-03-12" in result
        assert "satellite imagery shows vehicle movement" in result

    def test_markdown_contains_evidence_appendix(
        self, generator: ReportGenerator, synthesis: AnalysisSynthesis
    ) -> None:
        """Output has Evidence Trail appendix with all facts."""
        result = generator.generate_markdown(synthesis)
        assert "Appendix: Evidence Trail" in result
        assert "fact-001" in result
        assert "fact-002" in result
        assert "fact-003" in result
        assert "Satellite imagery shows 15 new armored vehicles" in result
        assert "CONFIRMED" in result
        assert "PENDING" in result

    def test_markdown_contains_confidence_assessment(
        self, generator: ReportGenerator, synthesis: AnalysisSynthesis
    ) -> None:
        """Output has Confidence Assessment section."""
        result = generator.generate_markdown(synthesis)
        assert "## Confidence Assessment" in result
        assert "Moderate" in result
        assert "72%" in result

    def test_markdown_contains_implications(
        self, generator: ReportGenerator, synthesis: AnalysisSynthesis
    ) -> None:
        """Output has implications and forecasts."""
        result = generator.generate_markdown(synthesis)
        assert "Strategic Implications" in result
        assert "Forecasts" in result
        assert "de-escalate" in result
        assert "30-60 days" in result

    def test_markdown_contains_classification_banner(
        self, generator: ReportGenerator, synthesis: AnalysisSynthesis
    ) -> None:
        """Output has classification marking."""
        result = generator.generate_markdown(synthesis)
        assert "UNCLASSIFIED // FOR OFFICIAL USE ONLY" in result


class TestGenerateExecutiveBrief:
    """Tests for generate_executive_brief output."""

    def test_generate_executive_brief(
        self, generator: ReportGenerator, synthesis: AnalysisSynthesis
    ) -> None:
        """Executive brief is shorter than full report."""
        full_report = generator.generate_markdown(synthesis)
        brief = generator.generate_executive_brief(synthesis)

        assert isinstance(brief, str)
        assert len(brief) > 0
        assert len(brief) < len(full_report)
        assert "Executive Summary" in brief
        assert "moderate confidence" in brief

    def test_executive_brief_contains_statistics(
        self, generator: ReportGenerator, synthesis: AnalysisSynthesis
    ) -> None:
        """Executive brief includes key statistics table."""
        brief = generator.generate_executive_brief(synthesis)
        assert "Key Statistics" in brief
        assert "Total Facts Analyzed" in brief


class TestSaveMarkdown:
    """Tests for save_markdown file I/O."""

    @pytest.mark.asyncio
    async def test_save_markdown(
        self,
        generator: ReportGenerator,
        synthesis: AnalysisSynthesis,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        """save_markdown creates file on disk."""
        markdown = generator.generate_markdown(synthesis)
        output_path = tmp_path / "reports" / "test-report.md"

        result = await generator.save_markdown(markdown, output_path)

        assert result.exists()
        content = result.read_text(encoding="utf-8")
        assert "Intelligence Report" in content
        assert len(content) == len(markdown)


class TestPDFRendererWrapHtml:
    """Tests for PDFRenderer._wrap_html method."""

    def test_pdf_renderer_wrap_html(self) -> None:
        """_wrap_html returns valid HTML document with style tag."""
        renderer = PDFRenderer()
        body = "<h1>Test Report</h1><p>Content here</p>"
        result = renderer._wrap_html(body)

        assert "<!DOCTYPE html>" in result
        assert "<html" in result
        assert "<head>" in result
        assert "<style>" in result
        assert "</style>" in result
        assert "<body>" in result
        assert "Test Report" in result
        assert "</html>" in result

    def test_pdf_renderer_embeds_css(self) -> None:
        """_wrap_html embeds CSS from the stylesheet file."""
        renderer = PDFRenderer()
        result = renderer._wrap_html("<p>test</p>")

        # Should contain CSS content from report.css
        assert "@page" in result
        assert "font-family" in result
