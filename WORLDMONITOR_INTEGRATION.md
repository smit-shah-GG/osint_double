# World Monitor x OSINT Double: Integration Analysis

> Cross-project synergy analysis between [World Monitor](https://worldmonitor.app) (public, TypeScript real-time OSINT dashboard) and OSINT Double (private, Python multi-agent intelligence analysis engine).

---

## Table of Contents

- [Project Comparison](#project-comparison)
- [Philosophical Alignment](#philosophical-alignment)
- [Technical Integration Points](#technical-integration-points)
- [Integration Options Overview](#integration-options-overview)
- [Deep Dive: Option C — The "Analyst Monitor" Variant](#deep-dive-option-c--the-analyst-monitor-variant)
  - [UX Vision](#ux-vision)
  - [World Monitor Variant System Internals](#world-monitor-variant-system-internals)
  - [What to Build: World Monitor Side](#what-to-build-world-monitor-side)
  - [What to Build: OSINT Double Side](#what-to-build-osint-double-side)
  - [Data Flow Architecture](#data-flow-architecture)
  - [Panel Definitions](#panel-definitions)
  - [Map Layer Configuration](#map-layer-configuration)
  - [Investigation Lifecycle](#investigation-lifecycle)
  - [Shared Entity Ontology](#shared-entity-ontology)
  - [CSS Theming](#css-theming)
  - [Deployment Architecture](#deployment-architecture)
  - [Cost and Complexity Estimates](#cost-and-complexity-estimates)
  - [Critical Success Factors](#critical-success-factors)
  - [Phased Implementation Roadmap](#phased-implementation-roadmap)

---

## Project Comparison

|                    | **World Monitor**                                  | **OSINT Double**                                      |
| ------------------ | -------------------------------------------------- | ----------------------------------------------------- |
| **Core function**  | Real-time global intelligence *dashboard*          | Automated intelligence *analysis engine*              |
| **Stack**          | TypeScript, Vite, deck.gl, Vercel Edge, Tauri      | Python, LangGraph, Gemini, asyncio                    |
| **Input**          | 50+ APIs, 298 RSS domains, WebSocket streams       | 17 RSS feeds, Reddit, PDFs, web pages                 |
| **Processing**     | Keyword classification, clustering, CII scoring    | LLM-powered fact extraction, verification, classification |
| **Output**         | Interactive 3D globe + 45 dashboard panels         | Structured intelligence products (JSON/reports)       |
| **User model**     | Human analyst watching a screen                    | Automated pipeline producing verified facts           |
| **Paradigm**       | **Observe** — surface everything, let human decide | **Analyze** — extract, verify, synthesize before surfacing |
| **License**        | AGPL-3.0 (public)                                  | Private                                               |
| **Version**        | v2.5.11                                            | Alpha/Beta                                            |
| **Deployment**     | Vercel (web) + Tauri (desktop) + Railway (relay)   | CLI-only (local execution)                            |

---

## Philosophical Alignment

### Where They Align

1. **OSINT democratization** — Both exist because professional OSINT tools cost $$$. World Monitor says "100% free & open source." OSINT Double targets "$50K/year API costs vs. $500K/year per analyst."

2. **Source diversity as signal** — World Monitor layers 50+ APIs to achieve breadth. OSINT Double's `AuthorityScorer` + echo detection explicitly models that the *same claim from different sources* is corroboration, not redundancy. Both treat multi-source convergence as a core intelligence principle.

3. **Trust isn't binary** — World Monitor has a Country Instability Index with weighted multi-signal blending. OSINT Double separates `extraction_confidence` from `claim_clarity` and treats impact and trust as orthogonal dimensions. Both reject "true/false" in favor of scored confidence.

4. **Graceful degradation** — World Monitor's 4-tier LLM fallback chain (Ollama → Groq → OpenRouter → T5). OSINT Double's tiered crawlers with retry + backoff. Neither breaks when a source goes down.

### Where They Diverge

1. **Breadth vs. depth** — World Monitor monitors *everything* (36+ layers, 298 RSS domains) at surface level. OSINT Double investigates *one objective* deeply — extracting atomic facts, verifying dubious claims, tracing provenance chains. This is the fundamental complementary axis.

2. **Human-in-the-loop placement** — World Monitor puts the human *at the end* (look at the dashboard, decide what matters). OSINT Double puts the human *after synthesis* (the system already decided what matters and verified it). Different trust models for different use cases.

3. **Real-time vs. investigative** — World Monitor is a *stream* (continuous refresh, 2min–60min intervals). OSINT Double is a *batch investigation* (start objective → crawl → extract → verify → report). One is always-on TV; the other is a detective you dispatch.

4. **Presentation vs. production** — World Monitor is a presentation layer that renders data beautifully. OSINT Double is a production layer that creates verified intelligence products. Neither alone is a complete system.

### The Intelligence Cycle

Together, the two projects represent two halves of the intelligence cycle:

| Intelligence Cycle Phase | World Monitor                              | OSINT Double                                    |
| ------------------------ | ------------------------------------------ | ----------------------------------------------- |
| **Collection**           | Broad, continuous, shallow                 | Narrow, targeted, deep                          |
| **Processing**           | Clustering, keyword classification         | Fact extraction, entity resolution              |
| **Analysis**             | CII scoring, geo-convergence, trends       | Verification, credibility scoring, synthesis    |
| **Dissemination**        | Interactive dashboard (human consumption)  | Structured reports (machine-readable)           |
| **Direction**            | User-driven (pick what to look at)         | Objective-driven (system investigates autonomously) |

World Monitor **detects** what needs attention. OSINT Double **investigates** it. World Monitor **displays** the verified results. This is the classic sensor → analyst → briefing pipeline, automated.

---

## Technical Integration Points

### 1. World Monitor as a Data Source for OSINT Double

World Monitor already surfaces signals that could trigger OSINT Double investigations:

- **Country Instability Index (CII) spikes** — scored risk per country from weighted multi-signal blend
- **Keyword spike detections** — 2-hour rolling window vs. 7-day baseline flags surging terms
- **Geo-convergence detections** — multiple signal types converging on a single location
- **Focal point detections** — entity correlation across news, military, protests, markets
- **Clustered news events** with threat classification

Any of these could dispatch an investigation. The `PlanningOrchestrator` receives an objective like *"Investigate the escalating situation in [country] — CII spike detected by World Monitor"* and autonomously crawls, extracts facts, verifies, and produces a structured brief.

**Concrete mechanism**: World Monitor's `/api/intelligence/v1/get-risk-scores` endpoint returns scored countries. A lightweight bridge script could poll this and dispatch OSINT Double investigations when CII thresholds breach.

### 2. OSINT Double Feeding Verified Intelligence Back into World Monitor

World Monitor's current AI intelligence layer is:

- **World Brief**: LLM summary (unverified, no fact decomposition)
- **Threat classification**: Keyword-based with async LLM override
- **Country Brief Pages**: AI-generated analysis (single LLM pass)

OSINT Double produces **verified, structured facts** with provenance chains, confidence scores, and corroboration evidence. This is a direct quality upgrade. Imagine the Country Brief Page showing not just "AI analysis" but individually verified facts with source attribution and confidence scores.

**Concrete mechanism**: OSINT Double's `FactStore` could expose a REST API. World Monitor's Country Brief component fetches verified facts for the viewed country, rendering them alongside the existing CII ring and event timeline.

### 3. Shared Entity Model

World Monitor has extensive entity data baked into config files:

- 220+ military bases, 111 AI datacenters, 83 ports, 92 stock exchanges
- Entity extraction in clustering (`entity-extraction.ts`)

OSINT Double has a formal `EntitySchema` with types (PERSON, ORGANIZATION, LOCATION, GEOPOLITICAL_REGION), canonical forms, and coreference linking.

A shared entity ontology would let both systems speak the same language. When OSINT Double extracts `[E1:Wagner Group]` from a news article, World Monitor could instantly cross-reference it against its military bases layer.

### 4. Source Credibility Scores

OSINT Double's `AuthorityScorer` rates domains (Reuters: 0.9, .gov: 0.85, Reddit: 0.3). World Monitor has 298 whitelisted RSS domains but no explicit credibility weighting — all sources are treated as equal signal. OSINT Double's credibility model could directly improve World Monitor's clustering and threat classification.

### 5. Deduplication

Both projects independently solve deduplication:

- **World Monitor**: Haversine-based geo-dedup for protests, content dedup for AI calls
- **OSINT Double**: URL dedup + content hash + semantic dedup (0.3 similarity threshold)

OSINT Double's dedup engine is more sophisticated (semantic + hash + URL). World Monitor's is more operationally proven at scale (298 sources in production). They could share a unified approach.

---

## Integration Options Overview

### Option A: Loose Coupling (Event-Driven)

```
World Monitor (always-on dashboard)
    | webhook / polling
    v
    CII spike / keyword surge / focal point detected
    |
    v
OSINT Double (dispatched investigation)
    | verified facts + analysis
    v
World Monitor Country Brief (enriched with verified intel)
```

**Effort**: Low. A Python script bridges them. No shared codebase needed.
**Benefit**: World Monitor gains deep analysis for hotspots. OSINT Double gains automatic targeting.

### Option B: Shared Data Layer

World Monitor's Upstash Redis cache + OSINT Double's FactStore both converge on a shared database (Convex, Supabase, or PostgreSQL). Verified facts are queryable by both systems.

**Effort**: Medium. Requires schema alignment and a shared persistence layer.
**Benefit**: Real-time bidirectional data flow. World Monitor shows verification status on events.

### Option C: OSINT Double as a World Monitor Variant ("Analyst Monitor")

A 5th variant that replaces passive news panels with OSINT Double's active investigation interface. The 3D globe stays, but clicking a hotspot launches an investigation rather than showing a static brief.

**Effort**: High. Requires a web frontend for OSINT Double + deep integration.
**Benefit**: Unified product for the serious analyst.

---

## Deep Dive: Option C — The "Analyst Monitor" Variant

### UX Vision

The Analyst Monitor variant transforms World Monitor from a passive observation dashboard into an active investigation platform. The experience:

1. **The Globe** — Same 3D WebGL globe with deck.gl, but layers are investigation-aware. Hotspots pulse when an active investigation is running. Verified facts appear as pinned markers with confidence rings.

2. **Investigation Panel** — Replaces the news feed. Shows:
   - Active investigations with progress bars (coverage metrics, signal strength)
   - Investigation timeline (subtask decomposition, agent assignments, findings stream)
   - Fact cards with provenance chains and verification status badges

3. **Fact Inspector** — Click any verified fact to see:
   - Original source text with entity highlighting (`[E1:Putin]`, `[E2:Beijing]`)
   - Credibility breakdown (source authority, echo detection, corroboration count)
   - Verification evidence (supporting/refuting, with links)
   - Classification reasoning (why CRITICAL, why DUBIOUS)

4. **Trigger Modes**:
   - **Manual**: Type an objective in a search-like bar → "Investigate Chinese military activity near Taiwan"
   - **Auto-trigger**: CII spike, keyword surge, or geo-convergence detection automatically dispatches an investigation
   - **Country click**: Click any country on the globe → launches a targeted investigation for that country

5. **Existing Panels Retained**: Markets, predictions, and non-investigation panels remain available. The variant adds investigation capability on top of the base intelligence dashboard.

### World Monitor Variant System Internals

World Monitor's variant system works through coordinated configuration at multiple levels. Understanding this is essential for adding a new variant.

#### Variant Detection (`src/config/variant.ts`)

```typescript
export const SITE_VARIANT: string = (() => {
  const env = import.meta.env.VITE_VARIANT || 'full';
  if (env !== 'full') return env;
  if (typeof window !== 'undefined') {
    const stored = localStorage.getItem('worldmonitor-variant');
    if (stored === 'tech' || stored === 'full' || stored === 'finance'
        || stored === 'happy') return stored;
  }
  return env;
})();
```

`VITE_VARIANT` env var takes absolute priority for non-full builds. Only the `full` variant allows localStorage override (for desktop variant switching). Adding `'analyst'` to the accepted values is the first step.

#### Variant Config Pattern (`src/config/variants/`)

Each variant exports: `DEFAULT_PANELS`, `DEFAULT_MAP_LAYERS`, `MOBILE_DEFAULT_MAP_LAYERS`, feeds, and any variant-specific data imports. The central `panels.ts` uses ternary chains:

```typescript
export const DEFAULT_PANELS = SITE_VARIANT === 'happy' ? HAPPY_PANELS :
  SITE_VARIANT === 'tech' ? TECH_PANELS :
  SITE_VARIANT === 'finance' ? FINANCE_PANELS :
  FULL_PANELS;
```

#### Data Loading Conditional Gates (`src/app/data-loader.ts`)

Each variant selectively loads data sources:

```typescript
if (SITE_VARIANT !== 'happy') {
  tasks.push({ name: 'markets', ... });
}
if (SITE_VARIANT === 'full' || SITE_VARIANT === 'finance') {
  tasks.push({ name: 'tradePolicy', ... });
}
```

The analyst variant would add its own gate for loading investigation state from the OSINT Double backend.

#### Refresh Scheduling (`src/app/refresh-scheduler.ts`)

Similar conditional gates. The analyst variant would schedule investigation status polling alongside standard data refreshes.

#### CSS Theming (`src/styles/`)

Themes use `data-variant` attribute selectors on `:root`:

```css
:root[data-variant="happy"] {
  --bg: #FAFAF5;
  --accent: #3D4A3E;
  /* ... */
}
```

### What to Build: World Monitor Side

#### 1. Variant Config File: `src/config/variants/analyst.ts`

```typescript
import { FULL_MAP_LAYERS, FULL_MOBILE_MAP_LAYERS } from './full';

export const FEEDS = { /* inherit full variant feeds */ };

export const ANALYST_PANELS: Record<string, PanelConfig> = {
  map:               { name: 'Intelligence Globe',       enabled: true, priority: 1 },
  investigation:     { name: 'Active Investigation',     enabled: true, priority: 2 },
  'fact-stream':     { name: 'Verified Fact Stream',     enabled: true, priority: 3 },
  'fact-inspector':  { name: 'Fact Inspector',           enabled: true, priority: 4 },
  'investigation-history': { name: 'Investigation History', enabled: true, priority: 5 },
  'live-news':       { name: 'Live News',                enabled: true, priority: 6 },
  markets:           { name: 'Markets',                  enabled: true, priority: 7 },
  predictions:       { name: 'Predictions',              enabled: true, priority: 8 },
  'coverage-metrics': { name: 'Coverage Dashboard',      enabled: true, priority: 9 },
};

export const ANALYST_MAP_LAYERS: MapLayers = {
  ...FULL_MAP_LAYERS,
  verifiedFacts: true,      // new: pinned verified facts on globe
  investigations: true,     // new: investigation hotspot overlay
  factDensity: true,        // new: heatmap of fact density by region
};

export const ANALYST_MOBILE_MAP_LAYERS: MapLayers = {
  ...FULL_MOBILE_MAP_LAYERS,
  verifiedFacts: true,
  investigations: true,
};
```

#### 2. New Components (~5 new components)

| Component | Purpose | Complexity |
| --- | --- | --- |
| `InvestigationPanel.ts` | Active investigation progress, subtask tree, agent status | High |
| `FactStreamPanel.ts` | Scrolling feed of verified facts with confidence badges | Medium |
| `FactInspectorPanel.ts` | Detailed view of a single fact: provenance, evidence, classification | High |
| `InvestigationHistoryPanel.ts` | Past investigations, searchable/filterable | Medium |
| `CoverageMetricsPanel.ts` | Source diversity, geographic coverage, signal strength gauges | Medium |
| `InvestigationTriggerBar.ts` | Text input for manual investigation objectives | Low |

#### 3. New Services (~3 new service files)

| Service | Purpose |
| --- | --- |
| `services/investigation/index.ts` | HTTP client for OSINT Double REST API |
| `services/investigation/ws-client.ts` | WebSocket client for real-time investigation updates |
| `services/investigation/fact-mapper.ts` | Maps OSINT Double DTOs to World Monitor types + map markers |

#### 4. New Map Layers (~2 new deck.gl layers)

| Layer | Rendering |
| --- | --- |
| `VerifiedFactsLayer` | ScatterplotLayer with confidence-radius rings, color-coded by classification |
| `InvestigationHotspotLayer` | HeatmapLayer showing investigation coverage density |

#### 5. Update Existing Files

| File | Change |
| --- | --- |
| `src/config/variant.ts` | Add `'analyst'` to accepted variant list |
| `src/config/panels.ts` | Add `SITE_VARIANT === 'analyst' ? ANALYST_PANELS :` to ternary chain |
| `src/app/data-loader.ts` | Add analyst-variant data loading gate |
| `src/app/refresh-scheduler.ts` | Add investigation polling schedule |
| `src/App.ts` | Add analyst variant initialization + localStorage cleanup |
| `src/main.ts` | Import analyst theme CSS |
| `vite.config.ts` | Add `analyst` to `VARIANT_META` with SEO metadata |

### What to Build: OSINT Double Side

#### 1. FastAPI REST Server (`osint_system/api/`)

New package exposing OSINT Double capabilities over HTTP:

```
osint_system/api/
  __init__.py
  app.py              # FastAPI application factory
  routes/
    investigations.py # Investigation CRUD + lifecycle
    facts.py          # Fact queries
    health.py         # Health check + system status
  middleware/
    auth.py           # API key validation
    cors.py           # CORS for World Monitor origins
  dto/
    investigation.py  # InvestigationRequest/Response DTOs
    fact.py           # FactDTO, ClassificationDTO
    verification.py   # VerificationDTO
  ws/
    investigation_stream.py  # WebSocket for live investigation updates
```

#### 2. Key Endpoints

```
POST   /api/v1/investigations              # Start new investigation
GET    /api/v1/investigations              # List investigations
GET    /api/v1/investigations/{id}         # Get investigation status + summary
GET    /api/v1/investigations/{id}/facts   # List extracted facts (paginated)
GET    /api/v1/investigations/{id}/facts/{fact_id}  # Single fact + full detail
DELETE /api/v1/investigations/{id}         # Cancel investigation
WS     /api/v1/investigations/{id}/stream  # Real-time updates
GET    /api/v1/health                      # System health
```

#### 3. Data Transfer Objects

```python
class InvestigationRequest(BaseModel):
    objective: str
    trigger_source: Optional[str] = None  # "cii_spike", "keyword_surge", "manual"
    trigger_context: Optional[dict] = None  # WM context (country, CII score, keywords)
    max_refinements: int = 7
    timeout_seconds: int = 3600

class InvestigationStatus(BaseModel):
    investigation_id: str
    objective: str
    status: Literal["pending", "crawling", "extracting", "classifying",
                     "verifying", "synthesizing", "completed", "failed"]
    progress: float                  # 0.0-1.0
    coverage_metrics: CoverageDTO
    signal_strength: float
    facts_total: int
    facts_critical: int
    facts_dubious: int
    facts_verified: int
    conflicts_unresolved: int
    started_at: datetime
    updated_at: datetime

class FactDTO(BaseModel):
    fact_id: str
    claim_text: str
    assertion_type: str              # statement, denial, quote, prediction
    entities: list[EntityDTO]        # [{name, type, canonical_form}]
    temporal: Optional[TemporalDTO]  # {value, precision}
    provenance: ProvenanceDTO        # {source_url, source_name, authority, hop_count}
    confidence: float                # extraction_confidence
    clarity: float                   # claim_clarity
    classification: ClassificationDTO  # {impact_tier, dubious_flags, credibility_score}
    verification: Optional[VerificationDTO]  # if verified
    location: Optional[GeoDTO]       # {lat, lon} for map placement
```

#### 4. Persistence Layer Enhancement

Current in-memory stores need database backing for multi-request state:

```python
# Option A: SQLite for MVP (single file, zero config)
# Option B: PostgreSQL for production (concurrent access, scaling)

# Alembic migrations for schema management
# asyncpg or aiosqlite for async database access
```

#### 5. Background Task Processing

Investigations run 5-60 minutes. Need async task execution:

```python
# Option A: FastAPI BackgroundTasks (simplest, single-process)
# Option B: Celery + Redis (production, distributed)
# Option C: arq (lightweight, Redis-based, async-native)
```

#### 6. WebSocket Streaming

Real-time investigation progress to World Monitor:

```python
@router.websocket("/api/v1/investigations/{id}/stream")
async def investigation_stream(websocket: WebSocket, id: str):
    await websocket.accept()
    async for event in investigation_events(id):
        await websocket.send_json({
            "type": event.type,      # "progress", "fact_found", "classification", "verification"
            "data": event.payload,
            "timestamp": event.timestamp.isoformat()
        })
```

### Data Flow Architecture

```
                          WORLD MONITOR (TypeScript / Vercel)
 ┌─────────────────────────────────────────────────────────────────────┐
 │                                                                     │
 │  ┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐  │
 │  │  3D Globe     │    │ Investigation    │    │ Fact Stream      │  │
 │  │  + Verified   │    │ Panel            │    │ Panel            │  │
 │  │  Fact Markers │    │ (progress, tasks)│    │ (scrolling feed) │  │
 │  └──────┬───────┘    └───────┬──────────┘    └───────┬──────────┘  │
 │         │                    │                        │             │
 │         └────────────┬───────┴────────────────────────┘             │
 │                      │                                              │
 │           ┌──────────▼──────────┐                                   │
 │           │ services/            │                                   │
 │           │ investigation/       │                                   │
 │           │  index.ts (REST)     │                                   │
 │           │  ws-client.ts (WS)   │                                   │
 │           │  fact-mapper.ts      │                                   │
 │           └──────────┬──────────┘                                   │
 │                      │                                              │
 └──────────────────────┼──────────────────────────────────────────────┘
                        │  HTTPS + WSS
                        │
        ════════════════╪═══════════════════  Network Boundary
                        │
 ┌──────────────────────┼──────────────────────────────────────────────┐
 │                      │                                              │
 │           OSINT DOUBLE (Python / Railway or Fly.io)                 │
 │                      │                                              │
 │           ┌──────────▼──────────┐                                   │
 │           │ FastAPI Server       │                                   │
 │           │  /investigations     │                                   │
 │           │  /facts              │                                   │
 │           │  /ws/stream          │                                   │
 │           └──────────┬──────────┘                                   │
 │                      │                                              │
 │           ┌──────────▼──────────┐                                   │
 │           │ Coordinator          │                                   │
 │           │ → PlanningOrchestrator                                  │
 │           └──────────┬──────────┘                                   │
 │                      │                                              │
 │         ┌────────────┼────────────┐                                 │
 │         │            │            │                                 │
 │   ┌─────▼─────┐ ┌───▼────┐ ┌────▼─────┐                           │
 │   │ CRAWLERS  │ │ SIFTERS│ │VERIFIERS │                           │
 │   │ News      │ │ Extract│ │ Query    │                           │
 │   │ Reddit    │ │ Classify││ Search   │                           │
 │   │ Documents │ │ Consol.││ Evidence │                           │
 │   │ Web       │ │ Report ││ Reclass. │                           │
 │   └─────┬─────┘ └───┬────┘ └────┬─────┘                           │
 │         │            │           │                                  │
 │         └────────────┼───────────┘                                  │
 │                      │                                              │
 │           ┌──────────▼──────────┐                                   │
 │           │ PostgreSQL / SQLite  │                                   │
 │           │  facts               │                                   │
 │           │  classifications     │                                   │
 │           │  verifications       │                                   │
 │           │  investigations      │                                   │
 │           └─────────────────────┘                                   │
 │                                                                     │
 └─────────────────────────────────────────────────────────────────────┘
```

### Panel Definitions

The Analyst variant organizes its dashboard into these panel categories:

#### Investigation Panels (New)

| Panel ID | Name | Description |
| --- | --- | --- |
| `investigation` | Active Investigation | Shows current investigation: objective, progress bar (coverage %), subtask tree with agent assignments, real-time findings stream. Includes "Start Investigation" trigger bar. |
| `fact-stream` | Verified Fact Stream | Scrolling feed of extracted facts. Each card shows: claim text, confidence badge (green/yellow/red), source name, entity chips, temporal marker. Filterable by classification. |
| `fact-inspector` | Fact Inspector | Detailed single-fact view. Shows: full claim with entity highlighting, provenance chain visualization, credibility breakdown donut chart, verification evidence (for/against), classification reasoning. Opens on fact-stream click. |
| `investigation-history` | Investigation History | List of past investigations with: objective, status, date, fact count, signal strength score. Click to reload any investigation's findings. Searchable. |
| `coverage-metrics` | Coverage Dashboard | SVG gauges for: source diversity (%), geographic coverage (%), topical completeness (%), signal strength (%). Updates in real-time during active investigations. |

#### Retained Panels (From Full Variant)

| Panel ID | Retained From | Reason |
| --- | --- | --- |
| `map` | full | Core 3D globe — essential for geographic context |
| `live-news` | full | Provides ambient awareness alongside investigations |
| `markets` | full | Market signals inform geopolitical analysis |
| `predictions` | full | Prediction markets provide forward-looking context |
| `cii` | full | CII scores serve as investigation triggers |

### Map Layer Configuration

```typescript
export const ANALYST_MAP_LAYERS: MapLayers = {
  // Inherited from full (essential context)
  conflicts: true,
  hotspots: true,
  bases: false,          // available but off by default
  nuclear: false,
  sanctions: false,
  cables: false,
  pipelines: false,
  natural: true,         // earthquakes as investigation triggers
  protests: true,        // protests as investigation triggers
  displacement: false,
  climate: false,
  outages: false,
  cyberThreats: false,

  // New analyst-specific layers
  verifiedFacts: true,   // Pinned markers for verified facts (confidence-sized rings)
  investigations: true,  // Pulsing hotspots for active investigations
  factDensity: false,    // Heatmap of fact density (off by default, toggleable)
};
```

**Verified Facts Layer Rendering**:

- Each verified fact with a `location` (lat/lon from entity resolution) gets a ScatterplotLayer marker
- Marker radius scales with confidence (0.0-1.0 → 4px-12px)
- Color encodes classification:
  - Green: CONFIRMED + CRITICAL
  - Blue: CONFIRMED + LESS_CRITICAL
  - Yellow: DUBIOUS (under investigation)
  - Red: REFUTED
- Click opens the Fact Inspector panel

**Investigation Hotspot Layer Rendering**:

- Active investigation's geographic scope rendered as a pulsing HeatmapLayer
- Intensity driven by fact density per region
- Opacity animates (0.3 → 0.6 → 0.3) to indicate "active investigation in progress"

### Investigation Lifecycle

#### Trigger Phase

```
 User/System Trigger
      │
      ├── Manual: User types objective in InvestigationTriggerBar
      │     "Investigate Chinese military buildup near Taiwan"
      │
      ├── CII Auto-trigger: CII score crosses threshold (e.g., > 7.0)
      │     Auto-generated objective: "Investigate instability in {country}
      │     — CII spike from {old_score} to {new_score}"
      │
      ├── Keyword Surge: Trending keyword detector fires
      │     Auto-generated: "Investigate surge in mentions of {keyword}"
      │
      └── Country Click: User clicks country on globe
            Auto-generated: "Generate intelligence brief for {country}"
```

#### Execution Phase (OSINT Double Backend)

```
 1. POST /api/v1/investigations
    Body: { objective, trigger_source, trigger_context }
    Response: { investigation_id, status: "pending" }

 2. PlanningOrchestrator.analyze_objective()
    → Decomposes into 3-8 subtasks
    → WS event: { type: "subtasks_created", data: subtasks[] }

 3. Crawler Cohort executes concurrently
    → NewsFeedAgent crawls 17+ RSS sources
    → RedditCrawler searches relevant subreddits
    → WebCrawler follows leads from initial findings
    → WS events: { type: "articles_found", data: { count, sources } }

 4. FactExtractionAgent processes raw articles
    → Extracts atomic facts with entity/temporal markers
    → WS events: { type: "fact_extracted", data: FactDTO }

 5. FactClassificationAgent scores each fact
    → Impact tier (CRITICAL/LESS_CRITICAL)
    → Dubious flags (PHANTOM/FOG/ANOMALY/NOISE)
    → WS events: { type: "fact_classified", data: ClassificationDTO }

 6. VerificationAgent investigates dubious facts
    → Generates search queries
    → Aggregates evidence
    → Reclassifies based on evidence
    → WS events: { type: "fact_verified", data: VerificationDTO }

 7. PlanningOrchestrator.evaluate_findings()
    → Checks coverage metrics
    → If insufficient: refine_approach() → loop back to step 3
    → If sufficient: synthesize_results()
    → WS event: { type: "completed", data: InvestigationStatus }
```

#### Rendering Phase (World Monitor Frontend)

```
 1. InvestigationPanel receives WS events → updates progress UI
 2. FactStreamPanel appends new facts as they arrive
 3. Globe renders new verified fact markers in real-time
 4. CoverageMetricsPanel updates gauges
 5. On completion: full investigation summary available in InvestigationHistoryPanel
```

### Shared Entity Ontology

To cross-reference between systems, both need a shared entity vocabulary.

#### Proposed Shared Types

```typescript
// World Monitor side (TypeScript)
interface SharedEntity {
  canonical_name: string;        // "Wagner Group", "Xi Jinping", "Taiwan Strait"
  type: EntityType;              // PERSON | ORGANIZATION | LOCATION | FACILITY | EVENT
  aliases: string[];             // ["PMC Wagner", "Wagner PMC", "Группа Вагнера"]
  wm_layer_refs?: string[];     // ["bases:wagner_hq", "conflicts:wagner_ops"]
  coordinates?: [number, number]; // [lat, lon] if geographic
}

enum EntityType {
  PERSON = 'PERSON',
  ORGANIZATION = 'ORGANIZATION',
  LOCATION = 'LOCATION',
  GEOPOLITICAL_REGION = 'GEOPOLITICAL_REGION',
  FACILITY = 'FACILITY',
  MILITARY_UNIT = 'MILITARY_UNIT',
  EVENT = 'EVENT',
}
```

```python
# OSINT Double side (Python) — extends existing EntitySchema
class SharedEntity(BaseModel):
    canonical_name: str
    type: EntityType               # Already defined in entity_schema.py
    aliases: list[str]
    wm_layer_refs: list[str] = []  # Cross-reference to WM map layers
    coordinates: Optional[tuple[float, float]] = None
```

#### Entity Resolution Bridge

World Monitor's static entity data (bases, ports, datacenters) can be exported as a shared entity catalog. OSINT Double's fact extraction can then resolve extracted entities against this catalog:

```
OSINT Double extracts: [E1:Incirlik Air Base]
    → Matches WM entity: bases-expanded.ts → { name: "Incirlik", lat: 37.00, lon: 35.43, operator: "US" }
    → Fact gets auto-located on the globe at [37.00, 35.43]
    → Cross-references: WM military layer + flights layer can show related data
```

### CSS Theming

The analyst variant uses a focused, low-distraction color palette optimized for extended analysis sessions:

```css
:root[data-variant="analyst"] {
  /* Base — dark theme biased for prolonged screen time */
  --bg: #0F1117;
  --bg-panel: #161821;
  --bg-panel-hover: #1C1F2B;
  --text: #C8CCD8;
  --text-muted: #6B7280;
  --border: #2A2D3A;

  /* Accent — muted blue-purple for investigation focus */
  --accent: #6366F1;
  --accent-hover: #818CF8;
  --accent-muted: #4338CA33;

  /* Classification colors */
  --fact-confirmed: #22C55E;       /* green — verified fact */
  --fact-critical: #EF4444;        /* red — critical impact */
  --fact-dubious: #F59E0B;         /* amber — under investigation */
  --fact-refuted: #6B7280;         /* gray — refuted/dismissed */
  --fact-less-critical: #3B82F6;   /* blue — lower impact */

  /* Coverage gauges */
  --gauge-fill: #6366F1;
  --gauge-bg: #1E2030;
  --gauge-text: #E2E8F0;

  /* Investigation progress */
  --progress-active: #6366F1;
  --progress-bg: #2A2D3A;
  --progress-complete: #22C55E;
}
```

### Deployment Architecture

```
                    ┌──────────────────────────┐
                    │       DNS / CDN          │
                    │  analyst.worldmonitor.app │
                    └─────────┬────────────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
    ┌─────────▼─────────┐   │    ┌──────────▼──────────┐
    │   Vercel           │   │    │  Railway / Fly.io    │
    │                    │   │    │                      │
    │  Static Assets     │   │    │  FastAPI Server      │
    │  (Vite build)      │   │    │  (OSINT Double)      │
    │                    │   │    │                      │
    │  Edge Functions    │   │    │  Background Workers  │
    │  /api/* (existing) │   │    │  (investigations)    │
    │                    │   │    │                      │
    │  Middleware         │   │    │  PostgreSQL          │
    │  (bot filtering)   │   │    │  (facts, verifications) │
    └─────────┬─────────┘   │    └──────────┬──────────┘
              │               │               │
              │   ┌───────────▼───────────┐   │
              │   │    Upstash Redis       │   │
              │   │   (shared cache)       │   │
              │   └───────────────────────┘   │
              │                               │
              └───────────────────────────────┘
                    Both services share Redis
                    for cache coordination
```

**Key deployment decisions**:

- **Vercel** handles the frontend build (`VITE_VARIANT=analyst`) and existing API routes
- **Railway or Fly.io** hosts the Python FastAPI server (long-running processes not suited for Vercel serverless)
- **Upstash Redis** shared between both for cache coordination and investigation status
- **PostgreSQL** (Railway-managed or Neon) for OSINT Double's persistent fact storage
- **WebSocket**: Railway/Fly support persistent WebSocket connections (Vercel does not)

**Environment variables** (new, on Vercel):

```bash
VITE_ANALYST_API_URL=https://analyst-api.worldmonitor.app
VITE_ANALYST_WS_URL=wss://analyst-api.worldmonitor.app
ANALYST_API_KEY=wm_analyst_...  # shared secret
```

**Environment variables** (new, on Railway/Fly):

```bash
WORLDMONITOR_API_KEYS=wm_analyst_...  # validates incoming WM requests
GEMINI_API_KEY=...                     # for LLM operations
DATABASE_URL=postgresql://...          # fact persistence
UPSTASH_REDIS_REST_URL=...             # shared cache
UPSTASH_REDIS_REST_TOKEN=...
```

### Cost and Complexity Estimates

#### Development Effort

| Component | Estimated Effort | Lines of Code |
| --- | --- | --- |
| **WM: Variant config** (`analyst.ts`, panels, layers, theme) | 1-2 days | ~400 LOC |
| **WM: Plumbing** (variant.ts, panels.ts, data-loader, App.ts updates) | 1 day | ~150 LOC |
| **WM: InvestigationPanel component** | 3-4 days | ~800 LOC |
| **WM: FactStreamPanel component** | 2 days | ~500 LOC |
| **WM: FactInspectorPanel component** | 2-3 days | ~600 LOC |
| **WM: Investigation services** (REST client, WS client, fact mapper) | 2 days | ~500 LOC |
| **WM: Map layers** (verified facts, investigation hotspot) | 2 days | ~400 LOC |
| **WM: CSS theme** | 1 day | ~200 LOC |
| **OD: FastAPI server + routes** | 3-4 days | ~800 LOC |
| **OD: DTOs** | 1-2 days | ~400 LOC |
| **OD: Database persistence** (SQLite MVP) | 2-3 days | ~600 LOC |
| **OD: WebSocket streaming** | 2 days | ~300 LOC |
| **OD: Auth middleware** | 1 day | ~150 LOC |
| **OD: Docker + deployment config** | 1 day | ~100 LOC |
| **Integration testing** | 3-4 days | — |
| **TOTAL** | **~4-6 weeks** | **~5,000 LOC** |

#### Ongoing Costs (Production)

| Service | Cost | Notes |
| --- | --- | --- |
| Vercel (frontend) | $0-20/mo | Hobby/Pro tier (already used by WM) |
| Railway/Fly (Python backend) | $5-25/mo | Depends on investigation frequency |
| Gemini API | $10-50/mo | Flash is cheap; Pro for verification adds up |
| PostgreSQL (Railway) | $5/mo | 1GB database included |
| Upstash Redis (shared) | $0-10/mo | Free tier may suffice; already used by WM |
| **Total** | **$20-110/mo** | Scales with investigation frequency |

### Critical Success Factors

1. **Investigation duration UX** — Investigations take 5-60 minutes. The UI must make progress *feel* continuous. WebSocket streaming of individual fact discoveries keeps the user engaged rather than staring at a progress bar.

2. **Fact geo-resolution accuracy** — OSINT Double extracts entities but doesn't always have coordinates. The entity resolution bridge (matching against WM's 220+ bases, 83 ports, etc.) determines whether facts appear on the globe or remain text-only. Invest in the entity catalog.

3. **Cost control** — Each investigation uses 50-200 Gemini API calls. Auto-triggered investigations (CII spikes, keyword surges) must have rate limits and cool-down periods to avoid runaway costs. Implement a daily investigation budget.

4. **Partial results are valuable** — If an investigation fails at the verification stage, the extracted (unverified) facts still have value. The system should surface partial results rather than showing "failed."

5. **Investigation provenance** — When a verified fact appears on the globe, clicking it should trace back through: fact → source article → original publication → author. Full provenance is the core differentiator over World Monitor's existing "AI analysis."

6. **Don't block the dashboard** — The analyst variant must remain a fast, responsive dashboard even when investigations are running. All OSINT Double communication must be async and non-blocking. Failed backend connections should degrade gracefully to the base WM experience.

### Phased Implementation Roadmap

#### Phase 1: Foundation (Week 1-2)

**Goal**: OSINT Double serves facts over HTTP; World Monitor can query them.

- Build FastAPI server with health check + investigation CRUD
- Implement SQLite persistence for FactStore
- Create DTOs for fact serialization
- Add API key authentication
- Deploy to Railway
- World Monitor: add `services/investigation/index.ts` REST client
- Integration test: WM can POST investigation → OD processes → WM can GET facts

#### Phase 2: Variant Shell (Week 2-3)

**Goal**: The analyst variant exists in World Monitor and shows investigation data.

- Create `src/config/variants/analyst.ts`
- Wire up variant detection + panel/layer config
- Build InvestigationPanel (basic: shows investigation status)
- Build FactStreamPanel (basic: renders fact cards from REST API)
- CSS theme
- Vercel deployment with `VITE_VARIANT=analyst`

#### Phase 3: Real-Time (Week 3-4)

**Goal**: Live investigation updates stream to the dashboard.

- Implement WebSocket server in FastAPI
- Build `services/investigation/ws-client.ts`
- InvestigationPanel shows live progress (subtasks, agent activity)
- FactStreamPanel receives facts as they're extracted (not just on poll)
- CoverageMetricsPanel with live gauges

#### Phase 4: Map Integration (Week 4-5)

**Goal**: Verified facts appear on the 3D globe.

- Build entity resolution bridge (OD entities → WM coordinates)
- Implement VerifiedFactsLayer (deck.gl ScatterplotLayer)
- Implement InvestigationHotspotLayer (deck.gl HeatmapLayer)
- Fact click → FactInspectorPanel with provenance visualization
- Investigation history panel

#### Phase 5: Auto-Triggers (Week 5-6)

**Goal**: World Monitor automatically dispatches investigations.

- CII threshold trigger (configurable in UnifiedSettings)
- Keyword surge trigger
- Country-click investigation shortcut
- Investigation rate limiting + daily budget
- Cool-down logic (don't re-investigate same country within 6 hours)

#### Phase 6: Polish (Week 6+)

**Goal**: Production-ready, polished experience.

- Mobile-responsive investigation panels
- Investigation sharing (URL state encoding)
- Export investigation as JSON/PDF
- Error handling + graceful degradation
- Performance optimization (lazy-load investigation components)
- Desktop app (Tauri) integration
- Documentation
