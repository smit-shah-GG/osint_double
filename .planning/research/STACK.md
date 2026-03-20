# Technology Stack: OSINT System v2.0 Additions

**Project:** OSINT Intelligence System v2.0
**Researched:** 2026-03-20
**Scope:** NEW capabilities only (existing stack validated, not re-researched)

---

## 1. Frontend: Next.js + shadcn/ui Dashboard

### Core Framework

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Next.js | 16.1.x (current LTS) | Frontend framework | Current LTS. Turbopack stable by default. App Router for SSR/RSC. Massive ecosystem. FastAPI integration patterns are well-documented with multiple production templates. |
| TypeScript | 5.x (bundled with Next.js 16) | Type safety | Non-negotiable for a data-dense dashboard. Catches schema drift between Python backend and TS frontend at compile time. |
| shadcn/ui | latest (copy-paste, not versioned) | Component library | Not a dependency — components are copied into your codebase. Full control, no version lock-in. Tailwind 4 + Radix primitives. |
| Tailwind CSS | 4.x (bundled with Next.js 16) | Styling | shadcn/ui requires it. Zero-runtime CSS. Dark mode automatic with shadcn theming. |

### shadcn/ui Components for Intelligence Dashboard

These are the specific components relevant to an OSINT data-dense dashboard. Not all 50+ shadcn components matter — these do:

**Critical (install immediately):**

| Component | Intelligence Dashboard Use Case |
|-----------|-------------------------------|
| `data-table` | Fact tables with sorting, filtering, pagination. Wraps TanStack Table v8 — handles 10K+ rows with virtualization. This is the single most important component. |
| `card` | KPI containers: fact counts, classification breakdowns, credibility scores, investigation status. |
| `chart` | Area/Bar/Line charts for temporal fact distribution, source credibility trends, classification breakdowns. Wraps Recharts — no additional dependency. |
| `tabs` | Switch between investigation views: Facts / Graph / Timeline / Sources / Report. |
| `badge` | Fact classification labels (Critical, Less-Critical, Dubious, Verified). Color-coded status indicators. |
| `dialog` | Fact detail modal with full provenance chain, source links, verification status. |
| `sheet` | Slide-out panel for entity detail views — relationships, mentions, timeline. |
| `command` | Command palette (Cmd+K) for searching facts, entities, sources across investigations. |
| `sidebar` | Investigation navigation + investigation selector. |
| `tooltip` | Hover details on graph nodes, credibility scores, confidence values. |

**Important (install in phase 2):**

| Component | Use Case |
|-----------|----------|
| `accordion` | Collapsible fact groups by source, by entity, by classification. |
| `progress` | Investigation pipeline progress (Crawl -> Extract -> Classify -> Verify -> Analyze). |
| `select` | Filter dropdowns: classification type, source, date range, credibility threshold. |
| `skeleton` | Loading states while investigation data streams in via SSE. |
| `sonner` (toast) | Notifications: "3 new facts verified", "Crawl complete", "Analysis ready". |
| `context-menu` | Right-click on facts/entities for quick actions (verify, reclassify, view source). |

**Skip (not relevant):**
- `calendar`, `date-picker` — Not a scheduling app.
- `carousel` — No image galleries.
- `form`, `input` — Minimal user input beyond investigation objectives.
- `avatar` — Single user, no profile system.

### Graph Visualization Library

**Recommendation: `@react-sigma/core` v5.x + `graphology`**

| Library | Rendering | Max Nodes (smooth) | React Integration | 3D | Verdict |
|---------|-----------|--------------------|----|-----|---------|
| @react-sigma/core | WebGL | 50K+ | Native React components, v5.0.6 (3 months old) | No | **RECOMMENDED** |
| Cytoscape.js | SVG/Canvas | ~5-10K | Wrapper needed, not React-native | No | Good layouts, poor perf at scale |
| react-force-graph | WebGL/Canvas | 10K+ | React component, maintained | Yes (3D mode) | Overkill — 3D adds complexity for no OSINT value |
| D3.js | SVG | ~2-5K | Manual integration, not React-native | No | Too low-level. Build-everything-yourself energy. |
| vis-network | Canvas | ~10K | Wrapper needed | No | Decent but stale ecosystem |

**Why Sigma.js wins for this project:**

1. **WebGL rendering** — The knowledge graph has Facts, Entities, Sources, Classifications as nodes with ~13 edge types. An investigation with 200 facts and 50 entities produces 500-2000 edges. WebGL handles this without breaking a sweat. Cytoscape's SVG chokes above 5K nodes.

2. **Graphology data model** — Sigma.js uses `graphology` as its data layer, which is a standalone graph library with algorithms (PageRank, community detection, shortest path). This maps perfectly to the existing NetworkX graph — export NetworkX to JSON, import into graphology on the frontend. Same mental model.

3. **React-native API** — `@react-sigma/core` v5 provides `<SigmaContainer>`, `<ControlsContainer>`, event hooks (`useRegisterEvents`, `useCamera`). No imperative DOM manipulation.

4. **Layout algorithms** — ForceAtlas2 (built-in), circular, random. ForceAtlas2 is the gold standard for knowledge graph layouts.

**Integration pattern:**
```
Python (NetworkX) → JSON export (node/edge lists) → REST API → graphology.import() → Sigma renders
```

**Install:**
```bash
npm install @react-sigma/core sigma graphology graphology-layout-forceatlas2
```

**Confidence:** HIGH — verified versions on npm, active maintenance, WebGL performance validated by multiple comparison articles.

### Real-Time Progress Updates

**Recommendation: Server-Sent Events (SSE), not WebSockets**

| Criterion | SSE | WebSocket |
|-----------|-----|-----------|
| Direction | Server -> Client (one-way) | Bidirectional |
| Protocol | HTTP/1.1+ | Separate WS protocol |
| Reconnection | Automatic (built into EventSource API) | Manual implementation |
| Proxy compatibility | Works through all HTTP proxies | Requires proxy WS support |
| FastAPI support | Native (`fastapi.sse.EventSourceResponse` in recent FastAPI, or `sse-starlette`) | Requires `websockets` library + separate endpoint |
| Complexity | Low | Medium |
| Your use case fit | Investigation runs 4-8 min, dashboard shows progress. Server pushes updates. Client never sends mid-investigation. | Overkill. Dashboard doesn't need to send data TO the server during a run. |

**Why SSE wins:**

The OSINT pipeline is a linear server-driven process: Crawl -> Extract -> Classify -> Verify -> Graph -> Analyze. The dashboard needs to display progress updates as each stage completes. This is textbook one-way server-to-client streaming. WebSocket's bidirectional capability is wasted complexity.

FastAPI has first-class SSE support. Recent versions include `fastapi.sse.EventSourceResponse` natively. For older versions, `sse-starlette` (actively maintained) provides the same. The existing `requirements.txt` already has `fastapi>=0.115.0`.

**Backend (Python):**
```bash
uv pip install sse-starlette  # If fastapi.sse not available in your version
```

**Frontend (Next.js):**
```typescript
// Built-in EventSource API — no library needed
const source = new EventSource('/api/investigations/inv-123/progress');
source.onmessage = (event) => { /* update React state */ };
```

**Confidence:** HIGH — SSE is the consensus recommendation for dashboards in 2025-2026 literature. FastAPI supports it natively.

---

## 2. Crawler Hardening

### Playwright Integration

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| playwright | 1.58.0 (current) | JS-heavy site crawling | Already in `requirements.txt` at `>=1.40.0`. Pin to `>=1.58.0`. Async API via `playwright.async_api.async_playwright`. Chromium, Firefox, WebKit in one package. |

**Already present in the codebase.** The `requirements.txt` lists `playwright>=1.40.0` and the `web_scraper.py` tool exists. No new dependency needed — just update the version pin.

**Async integration pattern (verified from official docs):**
```python
from playwright.async_api import async_playwright

async def scrape_js_page(url: str) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle")
        content = await page.content()
        await browser.close()
        return content
```

**Critical caveat:** Playwright's API is NOT thread-safe. Create one playwright instance per thread. In an asyncio context (which this project uses), a single instance per event loop is fine.

**Confidence:** HIGH — verified from official Playwright Python docs.

### User-Agent Rotation

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| fake-useragent | 2.2.0 | UA string rotation | Maintained, safe (no vulnerabilities per Snyk), real-world UA database. Supports filtering by browser type and popularity percentage. |

**Install:**
```bash
uv pip install fake-useragent==2.2.0
```

**Integration with Playwright:**
```python
from fake_useragent import UserAgent

ua = UserAgent(min_percentage=1.0)  # Only popular browsers
context = await browser.new_context(user_agent=ua.random)
```

**Integration with aiohttp (existing):**
```python
headers = {"User-Agent": ua.random}
async with session.get(url, headers=headers) as resp: ...
```

**Confidence:** HIGH — verified on PyPI, active maintenance.

### Proxy Rotation

**Recommendation: DO NOT add proxy rotation yet.**

Rationale:
- This is a personal-use tool, not a commercial scraper.
- The crawlers hit public RSS feeds (feedparser), public news sites (trafilatura), and DuckDuckGo search (ddgs). None of these require proxy rotation for single-user volume.
- Proxy services (Bright Data, SmartProxy, residential proxies) cost $10-100+/month — disproportionate for a personal tool.
- User-Agent rotation + respectful rate limiting (already implemented via `aiometer`) is sufficient.

**If needed later:** The `aiohttp` session already supports proxy via `proxy=` parameter. Playwright supports `proxy={"server": "..."}` in `browser.launch()`. No architectural changes needed to add proxies — it's a configuration change, not a code change.

**Confidence:** HIGH — based on project context (personal use, public sources).

---

## 3. Persistent Storage

### Database Choice

**Recommendation: SQLite with aiosqlite (already a dependency), NOT PostgreSQL**

| Criterion | SQLite | PostgreSQL |
|-----------|--------|------------|
| Setup complexity | Zero (file-based, no server) | Docker container, port management, credentials |
| Deployment | Single `.db` file ships with the app | Separate service in Docker Compose |
| Concurrent writers | One at a time (sufficient for single-user) | Full MVCC (overkill for single-user) |
| Performance at your scale | Faster than PG for single-user reads (no network overhead) | Unnecessary overhead |
| Backup | Copy the file | pg_dump or volume management |
| Already in your deps | `aiosqlite>=0.22.1` already in requirements.txt | Would add asyncpg, pg container, connection management |
| Full-text search | Built-in FTS5 extension | Requires pg_trgm or tsquery setup |
| Migration path | SQLAlchemy abstracts the dialect — swap to PG later with one connection string change | N/A |

**Why not PostgreSQL:** This is a single-user personal tool. Investigations run sequentially. There is no concurrent write contention. Adding PostgreSQL means adding a Docker dependency for development, managing a persistent volume, handling connection lifecycle, and debugging container networking — all for zero benefit at this scale.

**When to upgrade to PostgreSQL:** If the system ever supports multiple concurrent investigations or multiple users. SQLAlchemy's dialect abstraction makes this a connection-string swap, not a rewrite.

**Confidence:** HIGH — architecture decision based on project constraints.

### ORM Choice

**Recommendation: SQLAlchemy 2.0 (async mode) + Alembic**

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| SQLAlchemy | 2.0.48 (current stable) | ORM + query builder | Industry standard. First-class async support via `create_async_engine`. Works with aiosqlite (already a dep). Pydantic v2 integration. FastAPI's de facto ORM. |
| Alembic | 1.18.4 (current) | Schema migrations | Only real migration tool for SQLAlchemy. Auto-generates migrations from model diffs. |
| aiosqlite | >=0.22.1 (already in deps) | Async SQLite driver | Already a dependency. Bridges sqlite3 to asyncio. |

**Why not Tortoise ORM:** Despite Tortoise's async-first design being appealing, SQLAlchemy wins on:
1. **Ecosystem dominance** — Every FastAPI tutorial, template, and production app uses SQLAlchemy. More Stack Overflow answers, more maintained examples.
2. **Migration maturity** — Alembic is battle-tested. Tortoise's `aerich` is functional but has fewer edge-case solutions documented.
3. **Dialect portability** — If you ever move to PostgreSQL, SQLAlchemy swaps the connection string. Tortoise requires different driver imports and config changes.
4. **Your existing Pydantic models** — SQLAlchemy 2.0's `mapped_column()` syntax + Pydantic v2 integration means your existing Pydantic schemas (FactStore data, ClassificationStore data) can be directly mapped to SQLAlchemy models with minimal rewrite.

**Why not raw SQL:** The stores already have 5+ entity types (Articles, Facts, Classifications, Verifications, Reports, Graph nodes). Managing raw SQL for schema evolution across all of these is a maintenance nightmare. An ORM pays for itself immediately.

**Migration from in-memory JSON stores:**

The existing stores (FactStore, ArticleStore, ClassificationStore, VerificationStore, ReportStore) all follow the same pattern:
- In-memory dict with asyncio lock
- Optional JSON file persistence via `save_to_file()` / `load_from_file()`
- Comments explicitly say "For production: Would be replaced with database backend"

Migration strategy:
1. Define SQLAlchemy models mirroring existing Pydantic schemas
2. Create an `AbstractStore` protocol that both JSON and SQL backends implement
3. Swap backend by configuration flag
4. Write Alembic migration for initial schema
5. Write a one-time JSON-to-SQLite importer for existing investigation data

**Install:**
```bash
uv pip install "SQLAlchemy[asyncio]==2.0.48" alembic==1.18.4
```

Note: The `[asyncio]` extra installs the greenlet dependency needed for async support. In SQLAlchemy 2.1+, greenlet is no longer auto-installed.

**Confidence:** HIGH — versions verified on PyPI, integration with existing aiosqlite confirmed.

---

## 4. API Layer: FastAPI to Next.js Communication

### Protocol

**Recommendation: REST with OpenAPI-generated TypeScript client, NOT tRPC**

| Approach | Pros | Cons | Verdict |
|----------|------|------|---------|
| REST + OpenAPI client gen | FastAPI auto-generates OpenAPI spec. `@hey-api/openapi-ts` generates typed TS client from it. Zero manual type duplication. | Two codegen steps (FastAPI->OpenAPI->TS). | **RECOMMENDED** |
| tRPC | End-to-end type safety with zero codegen. | Requires Node.js backend. FastAPI is Python. Would need a Node BFF (Backend-for-Frontend) proxy. Absurd complexity for personal tool. | REJECT |
| Manual fetch + hand-typed interfaces | No tooling needed. | Types drift. Every API change requires manual TS update. Guaranteed bugs. | REJECT |
| GraphQL | Flexible queries, schema introspection. | Massive over-engineering for a single-consumer API. FastAPI+Strawberry adds complexity. | REJECT |

**Why OpenAPI client generation is the right answer:**

FastAPI already generates an OpenAPI 3.x schema at `/openapi.json`. This is free — it's automatic from your Pydantic response models. `@hey-api/openapi-ts` reads this schema and generates:
- TypeScript interfaces for every request/response model
- A fully typed fetch client with method signatures matching your FastAPI routes
- Zod schemas for runtime validation (optional)

When you change a FastAPI endpoint, re-run the generator and TypeScript compilation catches any frontend breakage.

**Tooling:**

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| @hey-api/openapi-ts | 0.94.x (current) | OpenAPI -> TypeScript codegen | Used by Vercel and PayPal. Generates typed clients, Zod schemas, TanStack Query hooks. Active development (released yesterday). Superior to openapi-generator (bloated) and orval (less maintained). |

**Install (frontend):**
```bash
npm install -D @hey-api/openapi-ts
```

**Usage:**
```bash
# Generate client from running FastAPI server
npx @hey-api/openapi-ts -i http://localhost:8000/openapi.json -o src/lib/api
```

**FastAPI side — add CORS middleware:**
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Next.js dev server
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Confidence:** HIGH — FastAPI's OpenAPI generation is automatic, @hey-api/openapi-ts verified on npm.

### Authentication

**Recommendation: DO NOT add authentication for v2.0**

Rationale:
- Single user, personal tool, running on localhost or private network.
- Adding NextAuth + JWT + session management is 2-3 days of work for zero security benefit on a personal tool.
- If remote access is needed later, put it behind Tailscale/WireGuard VPN or Cloudflare Tunnel — network-level auth, not app-level.

**If needed later:** FastAPI supports `HTTPBearer` token validation trivially. NextAuth.js handles the frontend session. But don't build it until there's a reason.

**Confidence:** HIGH — based on project context.

---

## 5. Deployment: Docker Compose

### Container Strategy

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Docker Compose | v2 (current) | Multi-container orchestration | Two containers: Python backend + Next.js frontend. Shared network. Environment variable management. |

**Architecture:**
```
docker-compose.yml
  backend:
    - Python 3.11+ (FastAPI + uvicorn)
    - Mounts ./data for SQLite persistence
    - Exposes :8000
  frontend:
    - Node.js 22 LTS (Next.js)
    - Connects to backend:8000
    - Exposes :3000
```

**Why not Kubernetes:** Single user, two containers. Kubernetes is absurd at this scale.

**Why not single container:** Separating Python and Node.js runtimes avoids a 2GB+ monolith image and lets you rebuild frontend without touching backend (and vice versa).

**Backend Dockerfile pattern:**
```dockerfile
FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY requirements.txt .
RUN uv pip install --system -r requirements.txt
RUN playwright install chromium --with-deps  # For JS-heavy crawling
COPY osint_system/ osint_system/
CMD ["uvicorn", "osint_system.dashboard.app:create_app", "--host", "0.0.0.0", "--port", "8000", "--factory"]
```

**Frontend Dockerfile pattern:**
```dockerfile
FROM node:22-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
CMD ["node", "server.js"]
```

### Process Management

**Recommendation: No extra process manager needed.**

- **Backend:** `uvicorn` handles the ASGI lifecycle. For production, use `--workers 1` (single user, single writer to SQLite).
- **Frontend:** Next.js standalone output (`output: 'standalone'` in `next.config.js`) produces a self-contained `server.js`. Node runs it directly.
- **Docker Compose** handles restart policies (`restart: unless-stopped`), health checks, and log aggregation.

Do NOT add supervisor, pm2, or circus. They solve multi-process problems you don't have.

### Environment Configuration

```
.env (git-ignored, local development)
  GEMINI_API_KEY=...
  OPENROUTER_API_KEY=...
  REDDIT_CLIENT_ID=...
  REDDIT_CLIENT_SECRET=...
  NEXT_PUBLIC_API_URL=http://localhost:8000

.env.production (Docker Compose)
  Same keys, production values
  NEXT_PUBLIC_API_URL=http://backend:8000  # Docker network name
```

**Confidence:** HIGH — standard Docker Compose patterns, verified with existing codebase structure.

---

## Complete New Dependencies Summary

### Python (backend) — add to requirements.txt

```bash
# Database (persistent storage)
SQLAlchemy[asyncio]==2.0.48    # ORM with async support
alembic==1.18.4                # Schema migrations

# Crawler hardening
fake-useragent==2.2.0          # User-Agent rotation

# Real-time updates (check if fastapi.sse exists in your version first)
sse-starlette>=2.0.0           # SSE for progress streaming (fallback if fastapi.sse unavailable)

# CORS (already part of fastapi/starlette, just needs middleware config)
# No additional package needed
```

**Already present, update version pin:**
```
playwright>=1.58.0             # Was >=1.40.0, update to current
```

### Node.js (frontend) — new package.json

```bash
# Core
npx create-next-app@latest frontend --typescript --tailwind --app --src-dir

# shadcn/ui (run inside frontend/)
npx shadcn@latest init
npx shadcn@latest add data-table card chart tabs badge dialog sheet command sidebar tooltip

# Graph visualization
npm install @react-sigma/core sigma graphology graphology-layout-forceatlas2

# Type-safe API client generation (dev dependency)
npm install -D @hey-api/openapi-ts
```

---

## What NOT to Add (and Why)

| Technology | Why Not |
|------------|---------|
| PostgreSQL | Single-user tool. SQLite is faster at this scale, zero-config, already a dependency. |
| tRPC | Requires Node.js backend. FastAPI is Python. |
| WebSocket libraries | SSE covers the use case with less complexity. |
| NextAuth.js / Auth | Personal tool. Network-level auth (VPN) if needed. |
| Kubernetes / k8s | Two containers. Docker Compose is the ceiling. |
| Redis | No caching layer needed. LLM responses are unique per investigation. SQLite handles persistence. |
| Proxy rotation services | Personal-use volume doesn't trigger rate limits on public sources. |
| GraphQL / Strawberry | Single API consumer (the Next.js frontend). REST is simpler. |
| pm2 / supervisor | Docker Compose handles process lifecycle. |
| Prisma | Node.js ORM. Backend is Python. |
| D3.js (raw) | Too low-level for React. Sigma.js provides WebGL graph rendering with React bindings. |
| Cytoscape.js | SVG rendering degrades at scale. WebGL (Sigma) is the right choice for graph data. |
| react-force-graph | 3D capability is wasted complexity for an intelligence dashboard. Sigma.js has better React integration for 2D graphs. |
| Tortoise ORM | Less ecosystem support than SQLAlchemy. Alembic > aerich for migrations. |

---

## Integration Architecture

```
                    +------------------+
                    |   Next.js 16     |
                    |  (Port 3000)     |
                    |                  |
                    |  shadcn/ui       |
                    |  @react-sigma    |
                    |  TanStack Table  |
                    |  Recharts        |
                    +--------+---------+
                             |
                    HTTP REST + SSE
                    (OpenAPI typed client)
                             |
                    +--------+---------+
                    |   FastAPI        |
                    |  (Port 8000)     |
                    |                  |
                    |  SQLAlchemy      |
                    |  SSE streaming   |
                    |  CORS middleware |
                    +--------+---------+
                             |
                    +--------+---------+
                    |   SQLite         |
                    |  (data/*.db)     |
                    |                  |
                    |  aiosqlite       |
                    |  Alembic mgmt   |
                    +------------------+
```

---

## Sources

### Frontend
- [shadcn/ui Dashboard Examples](https://ui.shadcn.com/examples/dashboard) — Official component gallery
- [shadcn/ui Data Table](https://ui.shadcn.com/docs/components/radix/data-table) — TanStack Table integration
- [shadcn/ui Charts](https://ui.shadcn.com/docs/components/radix/chart) — Recharts wrapper
- [Next.js 16.1 Release](https://nextjs.org/blog/next-16-1) — Current LTS features
- [Build a Dashboard with shadcn/ui (2026)](https://designrevision.com/blog/shadcn-dashboard-tutorial) — Component recommendations

### Graph Visualization
- [@react-sigma/core on npm](https://www.npmjs.com/package/@react-sigma/core) — v5.0.6, 3 months old
- [sigma.js on npm](https://www.npmjs.com/package/sigma) — v3.0.2
- [React Sigma.js Practical Guide](https://www.menudo.com/react-sigma-js-the-practical-guide-to-interactive-graph-visualization-in-react/) — Production patterns
- [Graph Visualization Library Comparison](https://www.cylynx.io/blog/a-comparison-of-javascript-graph-network-visualisation-libraries/) — Performance benchmarks
- [Memgraph Graph Visualization Tool Comparison](https://memgraph.com/blog/you-want-a-fast-easy-to-use-and-popular-graph-visualization-tool) — Sigma vs Cytoscape analysis

### Real-Time Updates
- [SSE vs WebSockets (2026)](https://www.nimbleway.com/blog/server-sent-events-vs-websockets-what-is-the-difference-2026-guide) — Protocol comparison
- [SSE Beat WebSockets for 95% of Apps](https://dev.to/polliog/server-sent-events-beat-websockets-for-95-of-real-time-apps-heres-why-a4l) — Use case analysis
- [Streaming in Next.js 15: WS vs SSE](https://hackernoon.com/streaming-in-nextjs-15-websockets-vs-server-sent-events) — Next.js integration
- [FastAPI SSE Tutorial](https://fastapi.tiangolo.com/tutorial/server-sent-events/) — Official docs
- [sse-starlette on PyPI](https://pypi.org/project/sse-starlette/) — Fallback library

### Crawler Hardening
- [Playwright Python on PyPI](https://pypi.org/project/playwright/) — v1.58.0 current
- [Playwright async API docs](https://playwright.dev/python/docs/library) — Official async patterns
- [fake-useragent on PyPI](https://pypi.org/project/fake-useragent/) — v2.2.0 current

### Database & ORM
- [SQLAlchemy on PyPI](https://pypi.org/project/SQLAlchemy) — v2.0.48 current stable
- [Alembic on PyPI](https://pypi.org/project/alembic/) — v1.18.4 current
- [SQLAlchemy 2.0 Async FastAPI Patterns](https://leapcell.io/blog/building-high-performance-async-apis-with-fastapi-sqlalchemy-2-0-and-asyncpg) — Integration guide
- [TortoiseORM vs SQLAlchemy](https://betterstack.com/community/guides/scaling-python/tortoiseorm-vs-sqlalchemy/) — ORM comparison
- [SQLite vs PostgreSQL (2026)](https://medium.com/pythonic-af/sqlite-vs-postgresql-performance-comparison-46ba1d39c9c8) — Performance comparison
- [aiosqlite on PyPI](https://pypi.org/project/aiosqlite/) — Async SQLite driver

### API Layer
- [@hey-api/openapi-ts on npm](https://www.npmjs.com/package/@hey-api/openapi-ts) — v0.94.x current
- [Hey API Documentation](https://heyapi.dev/openapi-ts/get-started) — Getting started
- [Full-Stack Type Safety with FastAPI + Next.js](https://abhayramesh.com/blog/type-safe-fullstack) — Integration pattern
- [Next.js FastAPI Template](https://github.com/vintasoftware/nextjs-fastapi-template) — Production reference

### Deployment
- [FastAPI Docker Official Docs](https://fastapi.tiangolo.com/deployment/docker/) — Container patterns
- [FastAPI + Next.js + Docker Compose](https://github.com/Nneji123/fastapi-nextjs) — Multi-container reference
