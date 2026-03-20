# Domain Pitfalls

**Domain:** Production hardening + Next.js frontend for existing Python OSINT pipeline
**Researched:** 2026-03-20
**Scope:** Adding Playwright browser automation, Next.js frontend, database persistence, LLM model switching, graph visualization, and deployment to an existing async Python pipeline.

---

## Critical Pitfalls

Mistakes that cause rewrites, data loss, or multi-week delays.

---

### Pitfall C1: Playwright Browser Launch Per Request (Memory Exhaustion)

**What goes wrong:** The existing `HybridWebCrawler._playwright_fetch()` launches a *new browser process* for every single URL that needs JS rendering. Each Chromium instance consumes 150-300 MB of RAM. When processing a batch of 20 articles that all need JS rendering (news sites behind SPAs), the crawler spawns 20 concurrent Chromium processes via `asyncio.gather()` in `ExtractionPipeline.process_investigation()`, consuming 3-6 GB of RAM and triggering OOM kills.

**Why it happens:** The current code uses `async with async_playwright() as p: browser = await p.chromium.launch(headless=True)` inside each `_playwright_fetch()` call. This is correct for isolation but catastrophic for throughput. The `asyncio.Semaphore(5)` in the pipeline limits concurrent *extractions* but not concurrent *browser launches* -- a single extraction can trigger multiple fetches.

**Consequences:**
- Process killed by OOM on machines with less than 8 GB RAM
- Silent data loss -- partially-processed investigations look complete
- Docker containers crash without useful error messages (just `Killed`)

**Warning signs:**
- RSS memory climbs monotonically during crawl phases
- `js_render_count` in metrics exceeds 5 per batch
- System swap usage spikes during investigation runs

**Prevention:**
1. Maintain a **single persistent browser instance** with a **context pool**. Launch the browser once at crawler initialization, create lightweight `BrowserContext` instances per request (isolated cookies/storage, ~2 MB each vs ~200 MB per browser).
2. Add a dedicated `asyncio.Semaphore` for Playwright operations (cap at 3 concurrent contexts).
3. Implement `browser.close()` in a `finally` block and add a health-check that restarts the browser if it becomes unresponsive.
4. Track RSS memory per crawl and abort if it exceeds a configurable threshold.

**Code pattern (what to build):**
```python
class BrowserPool:
    """Persistent browser with context pool."""
    def __init__(self, max_contexts: int = 3):
        self._browser: Browser | None = None
        self._sem = asyncio.Semaphore(max_contexts)
        self._pw: Playwright | None = None

    async def acquire_context(self) -> BrowserContext:
        async with self._sem:
            if self._browser is None or not self._browser.is_connected():
                self._pw = await async_playwright().start()
                self._browser = await self._pw.chromium.launch(headless=True)
            return await self._browser.new_context(user_agent=random_ua())

    async def release_context(self, ctx: BrowserContext) -> None:
        await ctx.close()  # Frees ~2 MB, not ~200 MB
```

**Phase that should address it:** Browser automation / crawler hardening phase. This must happen *before* any batch crawling goes into production.

**Confidence:** HIGH -- verified via Playwright GitHub issues [#2511](https://github.com/microsoft/playwright-python/issues/2511), [#286](https://github.com/microsoft/playwright-python/issues/286), and [official docs](https://playwright.dev/python/docs/library).

---

### Pitfall C2: Cloudflare AI Labyrinth Traps Headless Browsers in Infinite Loops

**What goes wrong:** Cloudflare introduced "AI Labyrinth" in March 2025. When it detects automated traffic, instead of blocking with a 403, it *serves realistic-looking fake content* and links the bot deeper into an infinite maze of generated pages. The crawler follows these links, extracting "facts" from fabricated content. The LLM extraction pipeline happily processes this garbage and produces confident-sounding but entirely fictional intelligence.

**Why it happens:** `playwright-stealth` (latest v2.0.2, Feb 2026) only handles basic fingerprint masking (hiding `navigator.webdriver`, spoofing Chrome UA). It does *not* defeat Cloudflare Turnstile, Bot Management, or AI Labyrinth. The existing `HybridWebCrawler` has no validation that the content it receives is genuine vs. honeypot content.

**Consequences:**
- Intelligence product contaminated with fabricated data
- Token budget wasted on extracting facts from fake pages
- No way to retroactively identify which facts came from honeypot content without re-crawling

**Warning signs:**
- Crawled content seems plausible but doesn't match any other source
- URL paths become suspiciously deep (4+ path segments you didn't request)
- Crawl returns content for sites that previously returned 403/challenge pages
- Content length is surprisingly uniform across different "articles"

**Prevention:**
1. **Content validation layer**: Compare extracted text against the expected domain/topic. Flag articles where the URL depth exceeds 3 levels from the seed URL.
2. **Do not chase links from JS-rendered pages** -- only fetch the specific URLs the planning agent provides. The current architecture already does this, but any future "link following" feature must have depth limits.
3. **Resign yourself to some sources being inaccessible.** For high-value paywalled/Cloudflare-protected sites, use their RSS feeds (usually unprotected) or official APIs instead of scraping.
4. **Proxy rotation with residential IPs** is the only reliable bypass for Cloudflare Bot Management, but this adds cost and legal complexity. For a personal research tool, the cost-benefit is poor.
5. **Track fetch success rates per domain.** If a domain that previously returned 403 suddenly returns 200 with content, flag it -- you may be in a honeypot.

**Phase that should address it:** Crawler hardening phase. Add content validation before extraction, not after.

**Confidence:** HIGH -- Cloudflare AI Labyrinth is [well-documented](https://www.zenrows.com/blog/playwright-cloudflare-bypass) and `playwright-stealth` limitations are [acknowledged by its own maintainers](https://pypi.org/project/playwright-stealth/).

---

### Pitfall C3: Event Loop Deadlocks When Mixing Playwright Sync/Async APIs

**What goes wrong:** The existing pipeline is fully async (`asyncio`). If any code path imports or calls Playwright's *synchronous* API (`sync_playwright`), it detects the running event loop and throws `Error: It looks like you are using Playwright Sync API inside the asyncio loop`. The more insidious case: a developer uses `nest_asyncio` to "fix" this, which works for simple HTTP requests but causes non-deterministic deadlocks with Playwright because the CDP WebSocket protocol requires bidirectional message passing on the event loop.

**Why it happens:** Playwright Python has two separate APIs (`sync_api` and `async_api`). They are mutually exclusive at runtime. The sync API creates its own event loop internally. If your process already has a running loop (FastAPI, asyncio pipeline), the sync API cannot start.

**Consequences:**
- Application hangs with no error message (deadlock)
- Intermittent failures that only occur under load (when multiple coroutines compete for the loop)
- Tests pass (because pytest creates a fresh loop per test) but production fails

**Warning signs:**
- `RuntimeError: This event loop is already running` during tests
- Application hangs after Playwright operations with no log output
- `nest_asyncio.apply()` appears anywhere in the codebase

**Prevention:**
1. **Exclusive use of `async_playwright`** throughout. Grep the codebase for `sync_playwright` imports and remove them.
2. **Never use `nest_asyncio`** with Playwright. If you think you need it, the architecture is wrong.
3. **Use `pytest-asyncio` with `asyncio_mode = "auto"`** for testing async Playwright code. Do not use `pytest-playwright` (it defaults to sync API).
4. The existing `_playwright_fetch()` already uses `async_playwright` -- the danger is future contributors adding sync calls in new modules.

**Phase that should address it:** All phases. Add a lint rule or pre-commit hook that blocks `from playwright.sync_api` imports.

**Confidence:** HIGH -- verified via [Playwright Python issue #462](https://github.com/microsoft/playwright-python/issues/462), [#2705](https://github.com/microsoft/playwright-python/issues/2705), and [Python async discussion](https://discuss.python.org/t/two-sync-apis-playwright-and-procrastinate-cannot-use-asynctosync-in-the-same-thread-as-an-async-event-loop/81521).

---

### Pitfall C4: LLM Model Switching Breaks JSON Schema Compliance Silently

**What goes wrong:** The system uses OpenRouter with a fallback chain: `Qwen 3.5 Flash -> Hermes 405B (free)` for extraction and `Gemini 2.5 Pro -> DeepSeek R1 -> Hermes 405B` for synthesis. Each model handles structured output differently:
- **Gemini**: Native `response_schema` enforcement (server-side constrained decoding)
- **DeepSeek R1**: Emits `<think>...</think>` reasoning tokens *before* the JSON, contaminating the response if you parse from the start
- **Hermes 405B (free)**: No native structured output support; relies on prompt instructions only
- **OpenRouter**: Offers `response_format.type: "json_schema"` but provider-level support varies -- some providers silently ignore it

When the primary model is rate-limited and falls back, the JSON structure changes subtly: field ordering shifts, enum values use different casing, optional fields disappear, or thinking tokens appear in the output. The existing Pydantic validation then either crashes or silently drops facts (the known `claim_type: "statement"` bug is an instance of this).

**Consequences:**
- Silent fact loss when fallback model uses unexpected field values
- `ValidationError` exceptions that kill the entire extraction batch
- Thinking tokens (`<think>...`) parsed as fact content, producing garbage
- Investigation results vary depending on which model happened to respond

**Warning signs:**
- Extraction success rate drops suddenly (check correlation with OpenRouter's `model` response field)
- `claim_type` or `classification` validation errors in logs
- Fact content contains XML-like tags (`<think>`, `</think>`)
- The same article produces different fact counts on re-processing

**Prevention:**
1. **Strip thinking tokens before JSON parsing.** Add a preprocessing step: `re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL).strip()`.
2. **Validate with Pydantic `model_validate()` using `strict=False`** to allow type coercion (e.g., "CRITICAL" vs "critical").
3. **Log the actual model used** (OpenRouter returns this in the response). Correlate extraction failures with model fallbacks.
4. **Normalize enum values post-extraction.** Don't rely on the LLM to produce exact enum strings. Map common variants: `{"statement": "claim", "CRITICAL": "critical", "Critical": "critical"}`.
5. **Test the fallback chain explicitly.** Mock rate-limit responses from the primary model and verify the entire pipeline produces valid output with each fallback model.
6. **Consider using `instructor` library** with OpenRouter for structured output enforcement with automatic retries on schema violations.

**Phase that should address it:** LLM integration hardening phase, before any new model additions.

**Confidence:** HIGH -- DeepSeek R1 thinking token behavior is [documented](https://api-docs.deepseek.com/news/news250120). OpenRouter provider variance is [acknowledged officially](https://openrouter.ai/announcements/provider-variance-introducing-exacto). The `claim_type: "statement"` bug in the existing codebase is direct evidence of this pitfall.

---

### Pitfall C5: In-Memory to Database Migration Breaks Async Lock Semantics

**What goes wrong:** The current stores (`FactStore`, `ClassificationStore`, `VerificationStore`) use `asyncio.Lock()` for thread safety around in-memory dict operations. When migrating to a database (SQLite via `aiosqlite` or PostgreSQL via `asyncpg`), developers often:

1. **Keep the `asyncio.Lock()` around database calls** -- this serializes all database access through a single coroutine, eliminating the concurrency benefit of async entirely.
2. **Remove the lock entirely** -- this causes race conditions during concurrent writes (e.g., two extraction tasks storing facts for the same investigation simultaneously).
3. **Mix sync and async database access** -- `sqlite3` is synchronous. Calling it inside an async function blocks the event loop. `aiosqlite` wraps it in a thread but has its own quirks (no WAL mode by default, connection pooling limitations).

**Consequences:**
- Serialized database access creates a bottleneck worse than in-memory storage
- Race conditions cause duplicate facts or lost updates
- Event loop blocking causes the entire pipeline to stall during database writes
- Alembic migrations fail silently on async engines without the async template

**Warning signs:**
- Pipeline throughput *decreases* after database migration
- Duplicate `fact_id` entries in the database
- `asyncio` warnings about blocking calls in the event loop
- Alembic `autogenerate` produces empty migrations

**Prevention:**
1. **For a single-user personal tool, use SQLite with `aiosqlite` and WAL mode.** This is the right level of complexity. PostgreSQL is over-engineering for this use case.
2. **Use SQLAlchemy 2.0 async engine** (`create_async_engine`) with `aiosqlite` dialect. This gives you ORM benefits, Alembic migration support, and proper async connection handling.
3. **Replace `asyncio.Lock()` with database-level transactions.** The database handles concurrency natively; application-level locks are redundant and harmful.
4. **Implement a repository pattern** that wraps the database operations and can be swapped between in-memory (for tests) and database (for production) implementations. The existing stores already approximate this -- formalize it.
5. **Enable WAL mode for SQLite** (`PRAGMA journal_mode=WAL`) to allow concurrent reads during writes. Without WAL, SQLite locks the entire database on any write.
6. **Migrate incrementally**: Keep the JSON persistence as a backup. Run both in parallel for one phase, validate data consistency, then cut over.

**Phase that should address it:** Database migration phase. Must be a dedicated phase, not bundled with feature work.

**Confidence:** HIGH -- SQLAlchemy async quirks are [documented](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html). `aiosqlite` threading model is [well-documented](https://github.com/omnilib/aiosqlite).

---

## Moderate Pitfalls

Mistakes that cause multi-day delays, degraded UX, or accumulated tech debt.

---

### Pitfall M1: Next.js + FastAPI CORS Configuration Appears to Work but Fails with Credentials

**What goes wrong:** Developer adds `CORSMiddleware` to FastAPI with `allow_origins=["*"]` and it works for GET requests. Then they add authentication (cookies, Bearer tokens) using `credentials: "include"` in `fetch()`. The browser now rejects all responses because the CORS spec prohibits `Access-Control-Allow-Origin: *` when credentials are included -- it must be the exact origin string.

Additionally, `http://localhost:3000` and `http://127.0.0.1:3000` are treated as *different origins* by browsers. The developer configures CORS for `localhost` but their browser navigates to `127.0.0.1` (or vice versa), and CORS blocks everything.

**Consequences:**
- Authentication works in Postman but fails in the browser
- Intermittent failures depending on how the developer navigates to the frontend
- Hours of debugging because the error message ("CORS policy: No 'Access-Control-Allow-Origin'") is the same for both misconfigured origins and missing credentials support

**Prevention:**
1. **Use Next.js `rewrites` in `next.config.js`** to proxy `/api/*` requests to FastAPI. This eliminates CORS entirely -- the browser only talks to the Next.js server, which forwards to FastAPI server-to-server. This is the correct approach for a monorepo / single-deployment setup.
   ```javascript
   // next.config.js
   async rewrites() {
     return [{ source: '/api/:path*', destination: 'http://localhost:8000/api/:path*' }]
   }
   ```
2. If you must use direct CORS, explicitly list *both* `http://localhost:3000` and `http://127.0.0.1:3000` in `allow_origins`, and set `allow_credentials=True`.
3. Test CORS in the browser, never with `curl` or Postman (they don't enforce CORS).

**Phase that should address it:** Frontend scaffolding phase. Get the proxy configuration right in the first commit.

**Confidence:** HIGH -- [FastAPI CORS docs](https://fastapi.tiangolo.com/tutorial/cors/) explicitly document the wildcard + credentials conflict. [Next.js rewrites](https://nextjs.org/docs/app/api-reference/file-conventions/proxy) are the documented solution.

---

### Pitfall M2: API Contract Drift Between FastAPI and Next.js Frontend

**What goes wrong:** The FastAPI backend returns Pydantic models. The Next.js frontend has TypeScript interfaces. These are defined independently. When a backend developer adds a field to a Pydantic model, renames a field, or changes a type, the frontend continues using the old interface. This causes:
- Silent `undefined` values in the UI (field was renamed)
- Runtime crashes when the frontend destructures a response expecting the old shape
- Stale data displayed because the frontend ignores new fields

**Consequences:**
- UI shows "undefined" or empty values for new data
- Type errors discovered only at runtime, not at build time
- Frontend and backend get progressively out of sync

**Prevention:**
1. **Generate TypeScript types from FastAPI's OpenAPI schema.** FastAPI auto-generates OpenAPI at `/openapi.json`. Use `openapi-typescript` to generate types from it. Run this as a build step.
   ```bash
   npx openapi-typescript http://localhost:8000/openapi.json -o src/types/api.ts
   ```
2. **Alternatively, use a shared schema definition.** Define the data shapes in a format both Python and TypeScript can consume (JSON Schema files, or generate Pydantic models from TypeScript types).
3. **Add a CI check** that regenerates the types and fails if they differ from committed types.
4. For a solo developer, at minimum: put API response types in a single `src/types/api.ts` file and reference it everywhere. Never inline type assertions (`as any`, `as unknown`).

**Phase that should address it:** Frontend scaffolding phase. Set up type generation before building any UI components.

**Confidence:** MEDIUM -- [Vinta Software's monorepo guide](https://www.vintasoftware.com/blog/nextjs-fastapi-monorepo) and [type-safe fullstack patterns](https://abhayramesh.com/blog/type-safe-fullstack) document this approach. Not yet verified with Context7.

---

### Pitfall M3: SSE Connections Silently Drop Behind Reverse Proxies

**What goes wrong:** Server-Sent Events (SSE) are the natural choice for streaming investigation progress from FastAPI to the Next.js frontend (pipeline status, fact counts, etc.). SSE works perfectly in local development. In production behind nginx, Cloudflare, or any buffering reverse proxy, the connection either:
- Buffers all events and delivers them in a burst (defeating the purpose of real-time)
- Drops the connection after 60 seconds (proxy timeout)
- Fails silently with no error on the client side

**Consequences:**
- Progress indicators freeze and then jump to 100%
- Investigation appears stuck when it's actually running
- Developer adds WebSocket "to fix the problem," doubling complexity

**Prevention:**
1. **For a personal tool running locally, SSE is fine.** Just be aware it won't survive a reverse proxy without configuration.
2. **Add `X-Accel-Buffering: no` header** in FastAPI SSE responses for nginx compatibility.
3. **Implement reconnection logic** on the frontend using `EventSource` with `onclose` handler. SSE has built-in reconnection, but it needs a `Last-Event-Id` mechanism on the backend to resume from where it left off.
4. **Fallback pattern**: Use SSE for real-time, but also expose a polling endpoint (`GET /api/investigation/{id}/status`) that the frontend falls back to if SSE disconnects. This is simpler than WebSocket and more robust.
5. **Start with polling.** For a single-user tool, polling every 2 seconds is perfectly adequate. Add SSE only if the latency bothers you.

**Phase that should address it:** Frontend real-time features phase. Don't implement SSE until basic polling works end-to-end.

**Confidence:** MEDIUM -- nginx buffering of SSE is [well-documented](https://blog.greeden.me/en/2025/10/28/weaponizing-real-time-websocket-sse-notifications-with-fastapi-connection-management-rooms-reconnection-scale-out-and-observability/). Safari background tab behavior [confirmed](https://potapov.me/en/make/websocket-sse-longpolling-realtime).

---

### Pitfall M4: Graph Visualization Renders All Nodes and Crashes the Browser Tab

**What goes wrong:** Developer renders the full fact-relationship graph using D3.js force-directed layout. With 500+ facts and their relationships (source links, corroboration edges, temporal links), the graph has 1000+ nodes and 3000+ edges. D3's force simulation runs on the main thread, consuming 100% CPU. The browser tab becomes unresponsive and eventually crashes.

**Consequences:**
- Dashboard unusable for any non-trivial investigation
- User cannot interact with the graph (zoom, click, filter) because the layout simulation consumes all CPU
- Mobile browsers crash immediately

**Warning signs:**
- Frame rate drops below 10 FPS during graph rendering
- Browser DevTools shows continuous high CPU usage after graph loads
- `requestAnimationFrame` callbacks take > 100ms

**Prevention:**
1. **Use Sigma.js with graphology, not D3 force-directed.** Sigma.js uses WebGL for rendering and can handle 10k+ nodes. D3 uses SVG/Canvas on the main thread and struggles past 500 nodes.
2. **Run ForceAtlas2 layout in a Web Worker** (`graphology-layout-forceatlas2/worker`). This offloads the O(n^2) force calculation to a background thread.
3. **Implement progressive disclosure**: Show only the top-level clusters initially. Expand clusters on click. Never render the full graph at once.
4. **Cap visible nodes at 200-300.** Show a "simplified view" by default with the option to "show all" with a performance warning.
5. **Pre-compute layouts server-side** for large graphs. Store node positions in the database. The client just renders, no simulation needed.
6. **Use `react-sigma` (v4+)** for React/Next.js integration. It wraps Sigma.js with proper React lifecycle management.

**Phase that should address it:** Graph visualization phase. Make a technology choice (Sigma.js) before writing any graph UI code.

**Confidence:** HIGH -- Sigma.js performance characteristics are [documented on their site](https://www.sigmajs.org/). D3 limitations with large graphs are well-established. The [PMC study](https://pmc.ncbi.nlm.nih.gov/articles/PMC12061801/) benchmarks web graph libraries specifically.

---

### Pitfall M5: Docker Build Invalidates Entire Cache on Any Source Change

**What goes wrong:** A naive Dockerfile copies the entire project source tree, then installs dependencies:
```dockerfile
COPY . .
RUN pip install -r requirements.txt
```
Any change to *any* Python file invalidates the `COPY . .` layer, forcing a full dependency reinstall (3-5 minutes). For a Next.js + Python monorepo, this means every frontend CSS change triggers a full Python dependency install.

**Consequences:**
- 5-10 minute build times for trivial changes
- Developer stops using Docker and tests locally, where "it works on my machine" begins
- CI/CD pipeline costs increase due to long build times

**Prevention:**
1. **Copy dependency files first, install, then copy source.** This is Docker 101 but universally forgotten in practice:
   ```dockerfile
   # Python
   COPY requirements.txt .
   RUN uv pip install -r requirements.txt
   COPY osint_system/ osint_system/

   # Next.js (separate stage)
   COPY frontend/package.json frontend/pnpm-lock.yaml ./
   RUN pnpm install --frozen-lockfile
   COPY frontend/ .
   RUN pnpm build
   ```
2. **Use multi-stage builds**: Separate `builder` and `runtime` stages. The runtime image doesn't need `gcc`, `node_modules/.cache`, or build tools.
3. **Use BuildKit `--mount=type=cache`** for `uv` and `pnpm` caches:
   ```dockerfile
   RUN --mount=type=cache,target=/root/.cache/uv uv pip install -r requirements.txt
   ```
4. **Separate Dockerfiles** for backend and frontend if they deploy independently. A monorepo Dockerfile that builds both is fragile and slow.

**Phase that should address it:** Deployment / infrastructure phase.

**Confidence:** HIGH -- standard Docker best practices, confirmed via [2026 Dockerfile guide](https://devtoolbox.dedyn.io/blog/dockerfile-complete-guide) and [multi-stage build guide](https://devtoolbox.dedyn.io/blog/docker-multi-stage-builds-guide).

---

### Pitfall M6: Environment Variables Leak Between Build and Runtime in Next.js

**What goes wrong:** Next.js has *two* environment variable contexts:
- `NEXT_PUBLIC_*` variables are embedded into the JavaScript bundle at **build time**. They are visible to anyone inspecting the page source.
- Server-only variables are available at **runtime** in API routes and `getServerSideProps`.

Developer puts `NEXT_PUBLIC_API_URL=http://localhost:8000` in development. Builds the Docker image. Deploys to production. The frontend still tries to call `http://localhost:8000` because the variable was baked into the JS bundle at build time. Alternatively, developer uses `NEXT_PUBLIC_GEMINI_API_KEY` and now the API key is visible in the browser.

**Consequences:**
- API calls fail in production because the URL points to localhost
- API keys exposed in client-side JavaScript
- Environment changes require a full rebuild and redeploy

**Prevention:**
1. **Never put secrets in `NEXT_PUBLIC_*` variables.** If the frontend needs to call an authenticated API, it should go through a Next.js API route (server-side) that holds the secret.
2. **Use runtime configuration for URLs** that change between environments. Next.js `publicRuntimeConfig` or a `/api/config` endpoint that returns the current configuration.
3. **Document which variables are build-time vs runtime** in a `.env.example` file with comments.
4. **For this OSINT project**: The frontend should *never* hold any API keys. All LLM calls, crawling, and external API access must go through the FastAPI backend.

**Phase that should address it:** Frontend scaffolding phase. Establish the env var convention before any configuration code is written.

**Confidence:** HIGH -- [Next.js deployment docs](https://nextjs.org/docs/app/getting-started/deploying) document this behavior explicitly.

---

## Minor Pitfalls

Mistakes that cause hours of debugging but are fixable once identified.

---

### Pitfall L1: Playwright `networkidle` Wait Hangs on Long-Polling Sites

**What goes wrong:** The existing `_playwright_fetch()` uses `await page.wait_for_load_state("networkidle")`. This waits until there are no network requests for 500ms. Many modern news sites have analytics, ad networks, or WebSocket connections that *never* go idle. The page load hangs until the `playwright_timeout` (60 seconds) expires.

**Prevention:**
1. Replace `networkidle` with `domcontentloaded` for most sites. Add a fixed `await page.wait_for_timeout(3000)` after navigation to let JS render.
2. Better: wait for a specific selector that indicates content is loaded (e.g., `article`, `.post-content`, `main`).
3. Set a page-level timeout that's shorter than the browser timeout: `await page.goto(url, timeout=30000)`.

**Phase that should address it:** Crawler hardening phase.

**Confidence:** HIGH -- this is a [known Playwright pattern](https://playwright.dev/python/docs/library). The existing code already has this exact anti-pattern at line 236 of `web_crawler.py`.

---

### Pitfall L2: SQLite File Locking in Docker Volumes

**What goes wrong:** SQLite databases stored in Docker bind-mount volumes on macOS (with Docker Desktop) can experience file locking issues because the `flock()` syscall doesn't work correctly over the VirtioFS/gRPC-FUSE filesystem shared between the Linux VM and macOS. Writes appear to succeed but silently corrupt the database.

**Prevention:**
1. On macOS development: use a named Docker volume instead of a bind mount for the SQLite database file.
2. In production: store the SQLite file inside the container's own filesystem, not on a mounted volume.
3. Alternatively, use PostgreSQL in Docker (where the database server handles its own file access) if you need volume-mounted persistence.
4. For this project (Linux host): this is less of a concern since Docker on Linux uses native filesystem access. But document the macOS limitation for portability.

**Phase that should address it:** Deployment phase.

**Confidence:** MEDIUM -- documented in Docker community forums and SQLite FAQ, but not universally reproduced. Linux host (current environment) is unaffected.

---

### Pitfall L3: `asyncio.Lock()` Created Outside the Running Event Loop

**What goes wrong:** The current stores create `asyncio.Lock()` in `__init__()`. If the store is instantiated *before* the event loop starts (e.g., at module import time or in a global singleton), the lock is bound to a different (or no) event loop. This causes `RuntimeError: Task got Future attached to a different loop` when the lock is acquired inside an async context.

**Prevention:**
1. Use lazy lock initialization: create the lock on first `await` call, not in `__init__`.
2. Or use `asyncio.Lock()` only inside `async` methods where the loop is guaranteed to be running.
3. The `settings = Settings()` singleton pattern in `config/settings.py` is fine (no async). But any store with `asyncio.Lock()` in `__init__` is vulnerable if instantiated at import time.

**Phase that should address it:** Database migration phase (locks will be replaced with database transactions anyway).

**Confidence:** HIGH -- this is a well-documented Python asyncio footgun. The existing `FactStore.__init__` creates `self._lock = asyncio.Lock()` at line 80, which is vulnerable to this.

---

### Pitfall L4: Next.js `fetch()` Caching Serves Stale Investigation Data

**What goes wrong:** Next.js 14+ aggressively caches `fetch()` calls by default. When the frontend fetches investigation data, Next.js caches the response. The user runs a new extraction, but the dashboard still shows old data because the cached response is served. The developer adds `{ cache: 'no-store' }` to every fetch call, which works but defeats Next.js's caching benefits entirely.

**Prevention:**
1. Use `revalidatePath()` or `revalidateTag()` after mutations (investigation runs, manual fact edits).
2. For real-time data (investigation status), use `{ next: { revalidate: 0 } }` or fetch from client components with `useEffect`.
3. For the OSINT dashboard specifically: investigation data changes infrequently (only during active runs). Use ISR (Incremental Static Regeneration) with a short revalidation period (10 seconds).
4. Understand the caching model *before* building: App Router caching is fundamentally different from Pages Router. Pick one and stick with it.

**Phase that should address it:** Frontend scaffolding phase.

**Confidence:** MEDIUM -- Next.js caching behavior has changed significantly between versions. Verify against the specific Next.js version you adopt.

---

### Pitfall L5: Gemini `response_schema` Counts Against Input Token Limit

**What goes wrong:** When using Gemini's structured output feature, the JSON schema provided in `response_schema` counts toward the input token limit. For complex fact extraction schemas with nested objects, enums, and descriptions, the schema itself can consume 500-1000 tokens. Combined with the article content and system prompt, this pushes requests over the context window limit for shorter-context models.

**Prevention:**
1. Keep extraction schemas minimal. Use short field names and remove `description` fields from the schema (describe the schema in the system prompt instead).
2. Monitor total input tokens per request. Log `prompt_token_count` from the Gemini response metadata.
3. For the existing extraction prompt: measure the schema size in tokens. If it exceeds 300 tokens, simplify it.
4. When using OpenRouter, be aware that `response_format.type: "json_schema"` may or may not pass the schema to the underlying provider -- check the response's `model` field to verify.

**Phase that should address it:** LLM integration hardening phase.

**Confidence:** HIGH -- [Gemini structured output docs](https://ai.google.dev/gemini-api/docs/structured-output) explicitly state this. [Google blog](https://blog.google/innovation-and-ai/technology/developers-tools/gemini-api-structured-outputs/) confirms.

---

### Pitfall L6: Process Supervision -- Uvicorn Worker Dies Silently

**What goes wrong:** Deploying with a single `uvicorn` worker (the default). The process crashes (OOM from Playwright, unhandled exception). No supervisor restarts it. The user doesn't know the backend is down until they try to use the dashboard.

**Prevention:**
1. Use `uvicorn` with multiple workers behind a process manager: `gunicorn -k uvicorn.workers.UvicornWorker -w 2`.
2. For Docker: use a health check endpoint (`/health` already exists in the dashboard) and configure `HEALTHCHECK` in the Dockerfile:
   ```dockerfile
   HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
     CMD curl -f http://localhost:8000/health || exit 1
   ```
3. Docker Compose: use `restart: unless-stopped` policy.
4. For a personal tool: `supervisord` or `systemd` unit file is sufficient. Don't over-engineer with Kubernetes.
5. **Caveat**: Multiple uvicorn workers with in-memory stores causes data inconsistency (each worker has its own store instance). This must be solved *before* adding workers -- either via database persistence or a shared memory store.

**Phase that should address it:** Deployment phase.

**Confidence:** HIGH -- standard Python deployment practice.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Severity | Mitigation |
|-------------|---------------|----------|------------|
| Browser automation / crawlers | C1 (browser per request), C2 (Cloudflare honeypots), C3 (event loop deadlock), L1 (networkidle hang) | CRITICAL | Implement BrowserPool pattern. Add content validation. Ban sync_playwright imports. Replace networkidle with domcontentloaded. |
| Next.js frontend scaffolding | M1 (CORS with credentials), M2 (API contract drift), M6 (env var leaks), L4 (fetch caching) | MODERATE | Use Next.js rewrites to proxy API. Generate TypeScript types from OpenAPI. Establish env var convention day one. |
| Database migration | C5 (async lock semantics), L2 (SQLite Docker volumes), L3 (lock created outside loop) | CRITICAL | Use SQLAlchemy 2.0 async + aiosqlite. Replace asyncio.Lock with DB transactions. Enable WAL mode. Migrate incrementally. |
| LLM model switching | C4 (JSON schema incompatibility), L5 (schema token cost) | CRITICAL | Strip thinking tokens pre-parse. Normalize enums post-extraction. Log actual model used. Test each fallback model. |
| Graph visualization | M4 (render all nodes) | MODERATE | Use Sigma.js + WebGL. Run ForceAtlas2 in Web Worker. Cap visible nodes at 200-300. Progressive disclosure. |
| Deployment | M5 (Docker cache invalidation), M6 (env var leaks), L2 (SQLite volumes), L6 (no process supervision) | MODERATE | Multi-stage builds. Copy deps before source. Health checks. Process manager. |
| Real-time updates | M3 (SSE proxy issues) | MODERATE | Start with polling. Add SSE later. Include X-Accel-Buffering header. Implement reconnection. |

---

## Sources

**Playwright & Browser Automation:**
- [Playwright Python Library Docs](https://playwright.dev/python/docs/library) (HIGH confidence)
- [Memory leak with contexts - GitHub #2511](https://github.com/microsoft/playwright-python/issues/2511) (HIGH)
- [Context memory leak - GitHub #286](https://github.com/microsoft/playwright-python/issues/286) (HIGH)
- [Sync API in asyncio loop - GitHub #462](https://github.com/microsoft/playwright-python/issues/462) (HIGH)
- [Sync API detection - GitHub #2705](https://github.com/microsoft/playwright-python/issues/2705) (HIGH)
- [playwright-stealth PyPI](https://pypi.org/project/playwright-stealth/) (HIGH)
- [Cloudflare bypass with Playwright - ZenRows](https://www.zenrows.com/blog/playwright-cloudflare-bypass) (MEDIUM)
- [Cloudflare anti-scraping - ScrapFly](https://scrapfly.io/blog/posts/how-to-bypass-cloudflare-anti-scraping) (MEDIUM)
- [Browser pool management - playwright-pool](https://github.com/tgscan/playwright-pool) (MEDIUM)
- [Python async gap discussion](https://discuss.python.org/t/two-sync-apis-playwright-and-procrastinate-cannot-use-asynctosync-in-the-same-thread-as-an-async-event-loop/81521) (HIGH)

**Next.js + FastAPI:**
- [FastAPI CORS Docs](https://fastapi.tiangolo.com/tutorial/cors/) (HIGH)
- [Next.js Rewrites / Proxy](https://nextjs.org/docs/app/api-reference/file-conventions/proxy) (HIGH)
- [Next.js Deployment Docs](https://nextjs.org/docs/app/getting-started/deploying) (HIGH)
- [Type-safe fullstack with FastAPI + Next.js](https://abhayramesh.com/blog/type-safe-fullstack) (MEDIUM)
- [Monorepo API client generation - Vinta Software](https://www.vintasoftware.com/blog/nextjs-fastapi-monorepo) (MEDIUM)
- [SSE with FastAPI production patterns](https://blog.greeden.me/en/2025/10/28/weaponizing-real-time-websocket-sse-notifications-with-fastapi-connection-management-rooms-reconnection-scale-out-and-observability/) (MEDIUM)
- [SSE in Next.js - vercel/next.js #48427](https://github.com/vercel/next.js/discussions/48427) (MEDIUM)

**Database Migration:**
- [SQLAlchemy 2.0 SQLite Dialect](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html) (HIGH)
- [aiosqlite GitHub](https://github.com/omnilib/aiosqlite) (HIGH)
- [Async SQLAlchemy + SQLModel + Alembic](https://testdriven.io/blog/fastapi-sqlmodel/) (MEDIUM)

**LLM Structured Output:**
- [DeepSeek R1 Release Notes](https://api-docs.deepseek.com/news/news250120) (HIGH)
- [OpenRouter Provider Variance / Exacto](https://openrouter.ai/announcements/provider-variance-introducing-exacto) (HIGH)
- [OpenRouter Structured Outputs Docs](https://openrouter.ai/docs/guides/features/structured-outputs) (HIGH)
- [Gemini Structured Output Docs](https://ai.google.dev/gemini-api/docs/structured-output) (HIGH)
- [Gemini API Structured Outputs Blog](https://blog.google/innovation-and-ai/technology/developers-tools/gemini-api-structured-outputs/) (HIGH)
- [Structured output guide - agenta.ai](https://agenta.ai/blog/the-guide-to-structured-outputs-and-function-calling-with-llms) (MEDIUM)
- [Instructor with OpenRouter](https://python.useinstructor.com/integrations/openrouter/) (MEDIUM)

**Graph Visualization:**
- [Sigma.js Official](https://www.sigmajs.org/) (HIGH)
- [Graph visualization efficiency - PMC study](https://pmc.ncbi.nlm.nih.gov/articles/PMC12061801/) (HIGH)
- [React Sigma.js Guide](https://www.menudo.com/react-sigma-js-the-practical-guide-to-interactive-graph-visualization-in-react/) (MEDIUM)
- [Graph rendering comparison - Stephen Weber](https://weber-stephen.medium.com/the-best-libraries-and-methods-to-render-large-network-graphs-on-the-web-d122ece2f4dc) (MEDIUM)

**Deployment:**
- [Dockerfile Complete Guide 2026](https://devtoolbox.dedyn.io/blog/dockerfile-complete-guide) (MEDIUM)
- [Multi-stage Docker Builds for Python AI APIs](https://dasroot.net/posts/2026/02/multi-stage-docker-builds-python-ai-apis/) (MEDIUM)
- [Docker Multi-Stage Builds Guide 2026](https://devtoolbox.dedyn.io/blog/docker-multi-stage-builds-guide) (MEDIUM)
