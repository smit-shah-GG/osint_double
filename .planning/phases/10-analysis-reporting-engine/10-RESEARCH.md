# Phase 10: Analysis & Reporting Engine - Research

**Researched:** 2026-03-13
**Domain:** LLM-powered intelligence report generation, database export, web dashboard
**Confidence:** HIGH (primarily internal architecture patterns + verified library choices)

## Summary

Phase 10 is the final pipeline layer: it consumes all upstream data (facts, classifications, verification results, knowledge graph) and produces three outputs: intelligence reports (Markdown + PDF), a portable investigation database (SQLite + JSON archive), and a local web dashboard for monitoring and exploration.

The research focused on five areas: (1) selecting the web framework and frontend stack for the dashboard, (2) choosing the PDF generation pipeline, (3) designing the LLM synthesis architecture for IC-style intelligence products, (4) determining the database export approach, and (5) ensuring the report versioning and snapshot system is sound.

The existing codebase already provides all the data sources Phase 10 needs through well-defined async APIs (FactStore, ClassificationStore, VerificationStore, GraphPipeline). Phase 10's primary challenge is orchestrating LLM synthesis across multiple structured data sources and producing coherent, IC-style analytical prose.

**Primary recommendation:** Use FastAPI + Jinja2 + HTMX for the dashboard. Use WeasyPrint for PDF generation (Markdown -> HTML via mistune -> CSS-styled PDF). Use aiosqlite for the SQLite investigation database. Follow the existing pipeline pattern (lazy init, event-driven, standalone mode) for the AnalysisPipeline.

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | >=0.135.1 | Web dashboard framework | Async-native (matches existing codebase), built-in SSE support, auto-generated API docs, 5-10x faster than Flask |
| Jinja2 | >=3.1.6 | Server-side HTML templating | Standard Python template engine, ships with FastAPI, battle-tested |
| HTMX | 2.0 (CDN) | Frontend interactivity | 10KB, zero build step, server-side rendering, SSE/WebSocket support, no JS framework needed |
| WeasyPrint | >=68.1 | HTML/CSS -> PDF | CSS layout engine for PDF, professional output, active development, supports custom stylesheets |
| mistune | >=3.0 | Markdown -> HTML | Fastest Python Markdown parser, CommonMark-compatible, extensible renderer |
| aiosqlite | >=0.22.1 | Async SQLite for investigation database | Async bridge to sqlite3, non-blocking on event loop, backup/export support |
| uvicorn | >=0.30 | ASGI server for dashboard | Production ASGI server, pairs with FastAPI |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| sse-starlette | >=3.3.2 | SSE fallback if FastAPI built-in SSE is insufficient | Only if native FastAPI SSE (0.135+) lacks needed features |
| python-multipart | >=0.0.6 | Form data handling for dashboard | Required for any file upload or form POST endpoints |
| DaisyUI / Pico CSS | latest | Minimal CSS framework for dashboard | Styling without heavy framework; DaisyUI for Tailwind-based, Pico for classless |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| WeasyPrint | fpdf2 (2.8.7) | fpdf2 is pure-Python (no system deps) but only supports basic markdown formatting, not full HTML/CSS layout. WeasyPrint produces professional reports with CSS but needs system libs (pango, cairo). Use fpdf2 only if WeasyPrint system deps are a blocker. |
| WeasyPrint | reportlab | More mature but commercial license for advanced features. Overkill for markdown-derived reports. |
| FastAPI | Flask | Flask is synchronous (WSGI), would conflict with the async-first architecture. The codebase uses asyncio locks, async stores, async pipeline. Flask async support is bolted-on, not native. |
| HTMX | React/Vue | Massive increase in complexity, build toolchain, bundle size. Dashboard is data-dense tables and reports, not a complex SPA. HTMX handles this with zero client-side state management. |
| mistune | markdown (stdlib) | 60x slower than mistune, fewer extension points |
| aiosqlite | raw sqlite3 | sqlite3 blocks the event loop. aiosqlite uses a dedicated thread per connection. |

**Installation:**
```bash
uv pip install fastapi uvicorn jinja2 htmx weasyprint mistune aiosqlite python-multipart
```

Note: WeasyPrint requires system dependencies:
- **Debian/Ubuntu:** `apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0`
- **macOS:** `brew install pango`
- **Alpine:** May need manual library path configuration

## Architecture Patterns

### Recommended Project Structure

```
osint_system/
├── agents/sifters/
│   └── analysis_reporting_agent.py    # AnalysisReportingAgent (BaseSifter subclass)
├── pipeline/
│   └── analysis_pipeline.py           # AnalysisPipeline (follows VerificationPipeline/GraphPipeline pattern)
├── analysis/                          # NEW: Analysis engine components
│   ├── __init__.py
│   ├── synthesizer.py                 # LLM synthesis orchestrator (key judgments, alternative hypotheses)
│   ├── pattern_detector.py            # Cross-fact and cross-investigation pattern detection
│   ├── confidence_assessor.py         # IC-style confidence language generation
│   └── contradiction_analyzer.py      # Identifies unresolved contradictions across facts
├── reporting/                         # NEW: Report generation components
│   ├── __init__.py
│   ├── report_generator.py            # Markdown report assembly from analysis output
│   ├── pdf_renderer.py                # Markdown -> HTML -> PDF via mistune + WeasyPrint
│   ├── report_store.py                # Versioned report storage with diff support
│   ├── templates/                     # Jinja2 templates for report sections
│   │   ├── intelligence_report.md.j2  # Full intelligence product template
│   │   ├── executive_brief.md.j2      # Executive summary template
│   │   └── evidence_appendix.md.j2    # Evidence trail appendix template
│   └── styles/
│       └── report.css                 # CSS for PDF rendering
├── database/                          # NEW: Investigation database export
│   ├── __init__.py
│   ├── schema.sql                     # SQLite schema definition
│   ├── exporter.py                    # Export investigation data to SQLite
│   └── archive.py                     # Full investigation archive (JSON bundle)
├── dashboard/                         # NEW: Web dashboard
│   ├── __init__.py
│   ├── app.py                         # FastAPI application factory
│   ├── routes/                        # Route modules
│   │   ├── investigations.py          # Investigation list/detail views
│   │   ├── facts.py                   # Fact browsing and filtering
│   │   ├── reports.py                 # Report viewing and generation
│   │   ├── monitoring.py              # Pipeline progress monitoring
│   │   └── api.py                     # JSON API endpoints for HTMX
│   ├── templates/                     # Jinja2 HTML templates
│   │   ├── base.html                  # Base layout with HTMX + CSS
│   │   ├── investigations/
│   │   ├── facts/
│   │   ├── reports/
│   │   └── monitoring/
│   └── static/                        # Static assets (minimal)
│       └── styles.css
└── config/
    └── analysis_config.py             # Analysis/reporting configuration
```

### Pattern 1: Pipeline Event Chain Extension

**What:** Phase 10 extends the existing event-driven pipeline chain.
**When to use:** Automatic report generation when the pipeline completes.

The existing chain is:
```
classification.complete -> verification -> verification.complete -> graph
```

Phase 10 adds:
```
graph.ingested -> analysis -> analysis.complete -> report_generation
```

**Example (following existing VerificationPipeline/GraphPipeline pattern):**
```python
class AnalysisPipeline:
    """Orchestrates graph.ingested -> analysis -> report generation.

    Follows same pattern as VerificationPipeline and GraphPipeline:
    lazy-init, event-driven + standalone mode, shared stores.
    """

    def __init__(
        self,
        fact_store: Optional[FactStore] = None,
        classification_store: Optional[ClassificationStore] = None,
        verification_store: Optional[VerificationStore] = None,
        graph_pipeline: Optional[GraphPipeline] = None,
        config: Optional[AnalysisConfig] = None,
    ) -> None:
        self._fact_store = fact_store
        self._classification_store = classification_store
        self._verification_store = verification_store
        self._graph_pipeline = graph_pipeline
        self._config = config
        self._logger = structlog.get_logger().bind(component="AnalysisPipeline")

    async def on_graph_ingested(
        self,
        investigation_id: str,
        ingestion_summary: dict[str, Any],
    ) -> dict[str, Any]:
        """Handler for graph.ingested events."""
        # 1. Gather all data from stores
        # 2. Run synthesis (LLM calls)
        # 3. Generate report
        # 4. Export database
        # 5. Publish analysis.complete event
        ...

    async def run_analysis(self, investigation_id: str) -> dict[str, Any]:
        """Standalone mode: run analysis for an investigation."""
        ...

    def register_with_pipeline(self, investigation_pipeline: Any) -> None:
        """Register as handler for graph.ingested events."""
        ...
```

### Pattern 2: LLM Synthesis with Structured Output

**What:** Use Gemini with structured Pydantic output schemas for each report section.
**When to use:** Every LLM call in the synthesis pipeline.

```python
# Define structured output for key judgments
class KeyJudgment(BaseModel):
    judgment: str = Field(..., description="The analytical judgment statement")
    confidence: Literal["low", "moderate", "high"] = Field(
        ..., description="IC-style confidence level"
    )
    confidence_numeric: float = Field(..., ge=0.0, le=1.0)
    supporting_fact_ids: list[str] = Field(default_factory=list)
    reasoning: str = Field(..., description="Analytical reasoning chain")

class AlternativeHypothesis(BaseModel):
    hypothesis: str
    likelihood: Literal["unlikely", "possible", "plausible"]
    supporting_evidence: list[str]
    weaknesses: list[str]

class AnalysisSynthesis(BaseModel):
    """Full synthesis output from LLM analysis."""
    executive_summary: str
    key_judgments: list[KeyJudgment]
    alternative_hypotheses: list[AlternativeHypothesis]
    contradictions: list[str]
    implications: list[str]
    forecasts: list[str]
```

### Pattern 3: Data Aggregation Before LLM

**What:** Aggregate and pre-structure all investigation data before sending to LLM.
**When to use:** Before every synthesis LLM call.

The LLM should receive a structured context document, not raw store dumps. The aggregator pulls from all four stores and the graph, then builds a structured context:

```python
class InvestigationContext:
    """Pre-aggregated investigation data for LLM synthesis."""

    async def build(
        self,
        investigation_id: str,
        fact_store: FactStore,
        classification_store: ClassificationStore,
        verification_store: VerificationStore,
        graph_pipeline: GraphPipeline,
    ) -> dict[str, Any]:
        """Build complete investigation context.

        Returns structured dict with:
        - confirmed_facts: Facts with CONFIRMED verification status
        - refuted_facts: Facts that were REFUTED
        - unverifiable_facts: Facts marked UNVERIFIABLE
        - critical_facts: CRITICAL tier classifications
        - contradictions: CONTRADICTS edges from graph
        - entity_network: Key entities and their connections
        - timeline: Temporal ordering of events
        - source_inventory: All sources with credibility scores
        - corroboration_clusters: Groups of mutually supporting facts
        """
```

### Pattern 4: Report Template Composition

**What:** Use Jinja2 templates for Markdown report generation, then render to PDF.
**When to use:** Report assembly from synthesis output.

```python
# Jinja2 Markdown template for intelligence report
REPORT_TEMPLATE = """
# Intelligence Report: {{ investigation.title }}

**Report Version:** {{ version }}
**Generated:** {{ generated_at }}
**Classification:** {{ classification_level }}

## Executive Summary

{{ synthesis.executive_summary }}

## Key Judgments

{% for judgment in synthesis.key_judgments %}
{{ loop.index }}. **{{ judgment.confidence | upper }} CONFIDENCE:** {{ judgment.judgment }}
   - *Basis:* {{ judgment.reasoning }}
{% endfor %}

## Evidence & Analysis

{% for section in evidence_sections %}
### {{ section.title }}

{{ section.narrative }}

| Fact ID | Claim | Confidence | Source |
|---------|-------|------------|--------|
{% for fact in section.facts %}
| {{ fact.fact_id[:8] }} | {{ fact.claim_text }} | {{ fact.confidence }} | {{ fact.source }} |
{% endfor %}
{% endfor %}

## Alternative Analysis

{% for alt in synthesis.alternative_hypotheses %}
### Hypothesis {{ loop.index }}: {{ alt.hypothesis }}
- **Likelihood:** {{ alt.likelihood }}
- **Supporting:** {{ alt.supporting_evidence | join(', ') }}
- **Weaknesses:** {{ alt.weaknesses | join(', ') }}
{% endfor %}

## Contradictions & Unresolved Questions

{% for c in synthesis.contradictions %}
- {{ c }}
{% endfor %}

---

## Appendix A: Evidence Trail

{% for fact in all_facts %}
### {{ fact.fact_id }}
- **Claim:** {{ fact.claim_text }}
- **Source:** {{ fact.source_url }}
- **Verification:** {{ fact.verification_status }}
- **Confidence:** {{ fact.final_confidence }}
{% endfor %}
"""
```

### Pattern 5: Dashboard SSE for Pipeline Monitoring

**What:** Use FastAPI's built-in SSE to stream pipeline progress to the dashboard.
**When to use:** Investigation monitoring view.

```python
from fastapi import FastAPI
from fastapi.sse import EventSourceResponse, ServerSentEvent

@app.get("/investigations/{inv_id}/progress", response_class=EventSourceResponse)
async def stream_progress(inv_id: str):
    """Stream pipeline progress via SSE."""
    async def event_generator():
        # Subscribe to message bus events for this investigation
        while True:
            event = await get_next_pipeline_event(inv_id)
            if event is None:
                break
            yield ServerSentEvent(
                data=event,
                event="pipeline_update",
            )
    return event_generator()
```

HTMX consumes this with zero JavaScript:
```html
<div hx-ext="sse" sse-connect="/investigations/inv-1/progress" sse-swap="pipeline_update">
    <!-- Pipeline status updates appear here automatically -->
</div>
```

### Pattern 6: Report Versioning via Timestamped Snapshots

**What:** Each report generation creates an immutable snapshot with a version number.
**When to use:** Every auto-generated and on-demand report.

```python
class ReportVersion(BaseModel):
    version: int
    investigation_id: str
    generated_at: datetime
    trigger: Literal["auto", "on_demand"]
    content_md: str      # Full Markdown content
    content_hash: str    # SHA256 of content_md for diff detection
    synthesis_input_hash: str  # Hash of input data (detect if data changed)

class ReportStore:
    """Versioned report storage with diff support.

    Reports stored as: {output_dir}/{investigation_id}/v{version}/report.md
    """
    async def save_version(self, report: ReportVersion) -> None: ...
    async def get_version(self, investigation_id: str, version: int) -> ReportVersion: ...
    async def get_latest(self, investigation_id: str) -> ReportVersion: ...
    async def diff_versions(self, investigation_id: str, v1: int, v2: int) -> str: ...
```

### Anti-Patterns to Avoid

- **Single LLM call for entire report:** The context window will overflow with a full investigation. Break synthesis into sections: executive summary, key judgments, alternative analysis, etc. Each gets its own focused prompt with relevant subset of facts.
- **Storing reports only as PDF:** Always store the Markdown source. PDF is a rendering artifact. The source enables diffing, re-rendering, and template evolution.
- **Dashboard polling for updates:** Use SSE (server push), not client-side setInterval polling. FastAPI has native SSE support since 0.135.0.
- **Embedding graph visualization in reports:** Per CONTEXT.md decision, the dashboard handles visuals; reports use data tables. Do not try to embed D3/graphviz in PDFs.
- **Blocking the event loop with PDF generation:** WeasyPrint is CPU-bound. Run it in a thread pool executor (`asyncio.to_thread(weasyprint.HTML(...).write_pdf, ...)`) or a process pool for large reports.
- **Monolithic dashboard app.py:** Split routes into modules (investigations, facts, reports, monitoring) from the start. The dashboard will grow.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Markdown -> HTML | Custom parser | mistune (3.x) | CommonMark compliance, extensible renderer, 60x faster than `markdown` lib |
| HTML -> PDF | Custom layout engine | WeasyPrint | CSS layout engine is thousands of lines of code. WeasyPrint handles pagination, headers, footers, page breaks. |
| Async SQLite | Thread management | aiosqlite | Handles the asyncio-sqlite3 bridge correctly with a dedicated thread per connection |
| Server-sent events | Custom streaming response | FastAPI built-in SSE (EventSourceResponse) | Protocol compliance (keep-alive, Content-Type, reconnection) is tricky to get right |
| HTML templating | String concatenation | Jinja2 | Auto-escaping, template inheritance, filters, macros |
| Report diff | Custom text differ | Python stdlib `difflib` | `difflib.unified_diff` produces standard unified diff format. No external dep needed. |
| CSS styling | Custom CSS | Pico CSS or classless CSS | Analyst dashboard should be functional, not custom-designed. Pico CSS gives semantic HTML styling with zero classes. |

**Key insight:** The report generation pipeline is fundamentally a data transformation: `stores -> structured context -> LLM synthesis -> Jinja2 templates -> Markdown -> HTML -> PDF`. Each step has a well-tested library. The only custom code is the synthesis prompts and the data aggregation logic.

## Common Pitfalls

### Pitfall 1: LLM Context Window Overflow

**What goes wrong:** Trying to feed the entire investigation (100+ facts, all classifications, all verification results, full graph) into a single Gemini prompt.
**Why it happens:** Desire for "the LLM sees everything" completeness.
**How to avoid:** Pre-aggregate data. Build a structured context document that summarizes rather than dumps. Key numbers: Gemini 1.5 Pro has a 2M token context, but quality degrades significantly beyond ~100K tokens. Target 10K-30K tokens per synthesis prompt by selecting only relevant facts for each report section.
**Warning signs:** Synthesis outputs become generic, miss specific details, or hallucinate connections not in the data.

### Pitfall 2: WeasyPrint System Dependency Failures

**What goes wrong:** WeasyPrint fails to install or render because system libraries (Pango, HarfBuzz, Cairo) are missing.
**Why it happens:** WeasyPrint wraps native C libraries via ctypes. Pure `pip install` is not sufficient.
**How to avoid:** Document system dependencies in installation instructions. Consider Docker for CI. Provide a fallback: if WeasyPrint is unavailable, degrade gracefully to Markdown-only output.
**Warning signs:** `OSError: dlopen() failed to load a library: pango` on first PDF render.

### Pitfall 3: Blocking the Event Loop with PDF Generation

**What goes wrong:** WeasyPrint's `write_pdf()` is CPU-bound and blocks the async event loop, freezing the dashboard and pipeline.
**Why it happens:** WeasyPrint has no async API.
**How to avoid:** Always run WeasyPrint in `asyncio.to_thread()`:
```python
pdf_bytes = await asyncio.to_thread(
    weasyprint.HTML(string=html_content).write_pdf
)
```
**Warning signs:** Dashboard becomes unresponsive during report generation.

### Pitfall 4: IC Confidence Language Drift

**What goes wrong:** LLM uses non-standard confidence language ("we think", "probably", "it seems") instead of IC-standard terms ("low/moderate/high confidence", "we assess", "we judge").
**Why it happens:** Gemini's default style is conversational, not analytical.
**How to avoid:** Use highly specific prompt templates with examples of IC-style language. Include a "DO NOT USE" list of casual phrases. Validate output against a regex/keyword check before accepting.
**Warning signs:** Reports read like blog posts instead of intelligence briefings.

### Pitfall 5: SQLite Write Contention

**What goes wrong:** Multiple async tasks try to write to the same SQLite file simultaneously.
**Why it happens:** SQLite has a single-writer lock. aiosqlite uses one thread, but if multiple coroutines share a connection, writes serialize.
**How to avoid:** Use a single aiosqlite connection per export operation. The investigation database export is a one-shot write operation, not a concurrent access pattern. Write the entire investigation atomically, then close.
**Warning signs:** `sqlite3.OperationalError: database is locked`.

### Pitfall 6: Report Template Brittleness

**What goes wrong:** Jinja2 templates break when the synthesis output schema changes (missing field, changed type).
**Why it happens:** Templates assume exact schema shape.
**How to avoid:** Use Jinja2's `default` filter liberally: `{{ synthesis.executive_summary | default('No summary available') }}`. Validate the synthesis Pydantic model before passing to templates.
**Warning signs:** `UndefinedError` in Jinja2 rendering.

## Code Examples

### Data Aggregation from Existing Stores

```python
# Source: Internal codebase patterns (FactStore, ClassificationStore, VerificationStore APIs)
async def aggregate_investigation_data(
    investigation_id: str,
    fact_store: FactStore,
    classification_store: ClassificationStore,
    verification_store: VerificationStore,
    graph_pipeline: GraphPipeline,
) -> dict[str, Any]:
    """Aggregate all investigation data for analysis.

    Pulls from all four data sources in parallel.
    """
    # Parallel data retrieval
    facts_result, class_stats, verif_results = await asyncio.gather(
        fact_store.retrieve_by_investigation(investigation_id),
        classification_store.get_stats(investigation_id),
        verification_store.get_all_results(investigation_id),
    )

    # Get verified facts (confirmed by verification)
    confirmed = await verification_store.get_by_status(
        investigation_id, VerificationStatus.CONFIRMED
    )

    # Get critical tier facts
    critical = await classification_store.get_by_tier(
        investigation_id, ImpactTier.CRITICAL
    )

    # Get corroboration clusters from graph
    corroboration = await graph_pipeline.query(
        "corroboration_clusters",
        investigation_id=investigation_id,
    )

    return {
        "investigation_id": investigation_id,
        "all_facts": facts_result["facts"],
        "total_facts": facts_result["total_facts"],
        "confirmed_facts": [r for r in confirmed],
        "critical_facts": critical,
        "verification_results": verif_results,
        "classification_stats": class_stats,
        "corroboration_clusters": corroboration.to_dict(),
    }
```

### SQLite Investigation Database Export

```python
# Source: aiosqlite API (https://aiosqlite.omnilib.dev)
import aiosqlite

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS investigation (
    id TEXT PRIMARY KEY,
    title TEXT,
    created_at TEXT,
    metadata TEXT  -- JSON blob
);

CREATE TABLE IF NOT EXISTS facts (
    fact_id TEXT PRIMARY KEY,
    investigation_id TEXT REFERENCES investigation(id),
    claim_text TEXT NOT NULL,
    assertion_type TEXT,
    claim_type TEXT,
    content_hash TEXT,
    extraction_confidence REAL,
    claim_clarity REAL,
    source_url TEXT,
    source_type TEXT,
    stored_at TEXT
);

CREATE TABLE IF NOT EXISTS classifications (
    fact_id TEXT PRIMARY KEY REFERENCES facts(fact_id),
    investigation_id TEXT REFERENCES investigation(id),
    impact_tier TEXT NOT NULL,
    dubious_flags TEXT,  -- JSON array
    priority_score REAL,
    credibility_score REAL,
    classified_at TEXT
);

CREATE TABLE IF NOT EXISTS verification_results (
    fact_id TEXT PRIMARY KEY REFERENCES facts(fact_id),
    investigation_id TEXT REFERENCES investigation(id),
    status TEXT NOT NULL,
    original_confidence REAL,
    final_confidence REAL,
    query_attempts INTEGER,
    reasoning TEXT,
    verified_at TEXT
);

CREATE TABLE IF NOT EXISTS evidence_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_id TEXT REFERENCES verification_results(fact_id),
    source_url TEXT,
    source_domain TEXT,
    source_type TEXT,
    authority_score REAL,
    snippet TEXT,
    supports_claim BOOLEAN,
    relevance_score REAL
);

CREATE INDEX IF NOT EXISTS idx_facts_investigation ON facts(investigation_id);
CREATE INDEX IF NOT EXISTS idx_facts_hash ON facts(content_hash);
CREATE INDEX IF NOT EXISTS idx_class_tier ON classifications(impact_tier);
CREATE INDEX IF NOT EXISTS idx_verif_status ON verification_results(status);
"""

async def export_investigation_db(
    investigation_id: str,
    output_path: str,
    fact_store: FactStore,
    classification_store: ClassificationStore,
    verification_store: VerificationStore,
) -> str:
    """Export investigation to self-contained SQLite database."""
    async with aiosqlite.connect(output_path) as db:
        await db.executescript(SCHEMA_SQL)
        # ... insert all investigation data ...
        await db.commit()
    return output_path
```

### Markdown -> PDF Pipeline

```python
# Source: mistune docs + WeasyPrint docs
import asyncio
import mistune
import weasyprint

async def render_report_pdf(
    markdown_content: str,
    css_path: str,
    output_path: str,
) -> str:
    """Render Markdown report to PDF via HTML intermediate.

    Pipeline: Markdown -> HTML (mistune) -> Styled HTML (CSS) -> PDF (WeasyPrint)

    WeasyPrint is CPU-bound, so runs in thread pool to avoid
    blocking the event loop.
    """
    # Step 1: Markdown -> HTML
    html_body = mistune.html(markdown_content)

    # Step 2: Wrap in full HTML document with CSS
    full_html = f"""<!DOCTYPE html>
    <html>
    <head><link rel="stylesheet" href="file://{css_path}"></head>
    <body>{html_body}</body>
    </html>"""

    # Step 3: HTML -> PDF (CPU-bound, run in thread)
    def _generate_pdf():
        weasyprint.HTML(string=full_html).write_pdf(output_path)

    await asyncio.to_thread(_generate_pdf)
    return output_path
```

### FastAPI Dashboard Application Factory

```python
# Source: FastAPI official docs (https://fastapi.tiangolo.com)
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

def create_dashboard_app(
    fact_store: FactStore,
    classification_store: ClassificationStore,
    verification_store: VerificationStore,
    graph_pipeline: GraphPipeline,
) -> FastAPI:
    """Create FastAPI dashboard application.

    Uses application factory pattern for testability.
    Stores are injected as dependencies, not created internally.
    """
    app = FastAPI(title="OSINT Investigation Dashboard")

    # Mount static files and templates
    app.mount("/static", StaticFiles(directory="dashboard/static"))
    templates = Jinja2Templates(directory="dashboard/templates")

    # Store references in app state for dependency injection
    app.state.fact_store = fact_store
    app.state.classification_store = classification_store
    app.state.verification_store = verification_store
    app.state.graph_pipeline = graph_pipeline

    # Register route modules
    from dashboard.routes import investigations, facts, reports, monitoring
    app.include_router(investigations.router)
    app.include_router(facts.router)
    app.include_router(reports.router)
    app.include_router(monitoring.router)

    return app
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Flask + jQuery polling | FastAPI + HTMX + SSE | FastAPI SSE in 0.135.0 (late 2025) | No client JS needed for real-time updates |
| ReportLab for PDF | WeasyPrint (CSS-based) | WeasyPrint 50+ (2022+) | CSS-styled PDFs, easier to maintain than programmatic layout |
| Custom Markdown parser | mistune 3.x | mistune 3.0 (2023) | CommonMark-compliant, plugin system, 60x faster than markdown lib |
| Synchronous SQLite | aiosqlite | aiosqlite 0.17+ (2021+) | Non-blocking SQLite access in async codebase |
| sse-starlette for SSE | FastAPI built-in EventSourceResponse | FastAPI 0.135.0 | First-class SSE support, no third-party dependency needed |

**Deprecated/outdated:**
- `fpdf` (original): Dead project, replaced by `fpdf2`
- `pdfkit`/`wkhtmltopdf`: Requires headless Chrome/wkhtmltopdf binary, WeasyPrint is pure-Python + native libs
- Flask-SSE: Flask's async story is weak; FastAPI native SSE is the modern approach

## Open Questions

1. **Graph visualization in dashboard (nice-to-have)**
   - What we know: CONTEXT.md says "basic graph visualization is nice-to-have, not core." Tables and reports are primary.
   - What's unclear: If/when graph viz is added, which library? Options include vis.js, Cytoscape.js, or D3.js force-directed graph.
   - Recommendation: Defer entirely from beta. If needed later, Cytoscape.js has the best data-driven graph API and HTMX can load the container. But this is explicitly out of scope per CONTEXT.md decisions.

2. **Cross-investigation pattern detection performance**
   - What we know: CONTEXT.md calls for "recurring actors, escalation trends, entity connections across investigations."
   - What's unclear: With many investigations, graph queries spanning all investigations could be expensive on NetworkX.
   - Recommendation: Implement as a separate on-demand analysis, not part of the auto-generated report. Use the GraphAdapter's `cross_investigation_matching` config flag.

3. **Gemini prompt token budget per report section**
   - What we know: Gemini 1.5 Pro has 2M context, but quality degrades beyond ~100K. Cost per 1M tokens matters.
   - What's unclear: Exact token counts for typical investigation contexts. Need to measure during implementation.
   - Recommendation: Start with aggressive summarization (10K tokens per section context). Add a token counter to the synthesis prompts using the existing `GeminiClient.count_tokens()` method. Log and iterate.

4. **Report CSS styling specifics**
   - What we know: CONTEXT.md says "functional and data-dense, not decorative."
   - What's unclear: Exact CSS for professional intelligence report appearance.
   - Recommendation: Start with a minimal CSS file (~100 lines): clean serif font for body, monospace for data, bordered tables, page break rules. Iterate based on output quality. No framework needed for PDF CSS.

## Sources

### Primary (HIGH confidence)
- FastAPI official docs - SSE tutorial, version 0.135+ (https://fastapi.tiangolo.com/tutorial/server-sent-events/)
- WeasyPrint PyPI - v68.1, Python >=3.10 (https://pypi.org/project/weasyprint/)
- fpdf2 PyPI - v2.8.7, Markdown support (https://pypi.org/project/fpdf2/)
- aiosqlite PyPI - v0.22.1, Python >=3.9 (https://pypi.org/project/aiosqlite/)
- FastAPI PyPI - v0.135.1 (https://pypi.org/project/fastapi/)
- Jinja2 PyPI - v3.1.6 (https://pypi.org/project/Jinja2/)
- Existing codebase: FactStore, ClassificationStore, VerificationStore, GraphPipeline, MessageBus APIs (read directly)

### Secondary (MEDIUM confidence)
- LlamaIndex blog on LLM report generation building blocks (https://www.llamaindex.ai/blog/building-blocks-of-llm-report-generation-beyond-basic-rag)
- FastAPI + HTMX + Jinja2 dashboard patterns (multiple 2025 articles: testdriven.io, johal.in, medium.com)
- WeasyPrint system dependency requirements (https://doc.courtbouillon.org/weasyprint/stable/first_steps.html)

### Tertiary (LOW confidence)
- Performance claims for HTMX vs React (92% lower TTI) - single source, not independently verified
- FastAPI 5-10x faster than Flask claims - varies significantly by workload, should not be taken at face value for this use case

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries verified on PyPI with current versions, API compatibility confirmed with codebase
- Architecture: HIGH - Follows established patterns already in the codebase (pipeline pattern, store pattern, config pattern)
- Pitfalls: HIGH - WeasyPrint system deps and event loop blocking are well-documented issues; IC language drift is specific to this domain
- Dashboard: MEDIUM - FastAPI + HTMX pattern is well-documented but the specific SSE integration with MessageBus needs implementation validation
- LLM Synthesis: MEDIUM - Report generation patterns are established, but the specific IC-style prompt engineering requires iteration

**Research date:** 2026-03-13
**Valid until:** 2026-04-13 (30 days - stack is stable, no fast-moving components)
