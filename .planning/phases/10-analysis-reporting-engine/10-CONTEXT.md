# Phase 10: Analysis & Reporting Engine - Context

**Gathered:** 2026-03-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Generate intelligence products from verified facts with multiple output formats and a dashboard interface. This phase consumes the full pipeline output (facts, classifications, verification results, knowledge graph) and produces actionable intelligence reports, a portable investigation database, and a local web dashboard for monitoring and exploration.

</domain>

<decisions>
## Implementation Decisions

### Report structure & content
- Executive brief leads the report: 1-2 paragraph executive summary, followed by key findings, evidence sections, confidence assessment, timeline
- IC-style confidence language in prose sections ("low/moderate/high confidence"), numeric scores in evidence tables and appendices
- Clean prose in report body — detailed evidence trail in appendix with fact IDs and source links
- Dedicated "Contradictions & Unresolved Questions" section highlighting where sources disagree
- Data tables for timeline summary, entity relationships, and source inventory (no embedded diagrams — dashboard handles visuals)

### Output formats & delivery
- Database output: structured fact database (queryable SQLite/JSON) for external tool consumption + full investigation archive (facts, classifications, verification results, graph) for reproducibility
- Report formats for beta: Markdown (.md) and PDF
- Auto-generate summary report when verification pipeline completes, plus on-demand for custom reports
- Versioned snapshots: each generation creates a new version, user can diff between versions

### Dashboard scope & interaction
- Local web dashboard (Flask/FastAPI + simple frontend) — no terminal UI
- Both investigation monitoring (pipeline progress, fact counts, verification status) and results exploration (navigate facts, entity relationships, read reports)
- Basic graph visualization is nice-to-have, not core — tables and reports are primary
- Investigation list view: switch between investigations, compare results

### Synthesis depth & analytical voice
- Full intelligence product: key judgments, alternative analyses, implications, forecasts — comparable to IC analytical products
- Analyst briefing voice: professional but accessible, like a senior analyst briefing a decision-maker
- Always generate alternative hypotheses (2-3 interpretations) for any finding with moderate or low confidence
- Cross-investigation pattern detection via knowledge graph: recurring actors, escalation trends, entity connections across investigations

### Claude's Discretion
- Web framework choice for dashboard (Flask vs FastAPI)
- Frontend approach (minimal JS, HTMX, or lightweight framework)
- PDF generation library
- Specific Gemini prompt templates for synthesis and assessment generation
- Dashboard styling and layout details
- Version storage format for report snapshots

</decisions>

<specifics>
## Specific Ideas

- Reports should read like an analyst briefing a decision-maker — authoritative but not academic
- Alternative hypotheses section should feel like IC's "Alternative Analysis" — not wishy-washy, but structured competing interpretations
- The investigation archive should be self-contained enough that someone could reproduce the analysis from the archive alone
- Dashboard should feel functional and data-dense, not decorative — this is a tool for analysts, not a marketing page

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 10-analysis-reporting-engine*
*Context gathered: 2026-03-13*
