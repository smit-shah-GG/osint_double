---
phase: 13-postgresql-memgraph-migration
verified: 2026-03-22T12:00:00Z
status: gaps_found
score: 6/7 must-haves verified
gaps:
  - truth: "Memgraph runs MAGE algorithms (PageRank, community detection, betweenness centrality) on ingested graph data post-pipeline"
    status: failed
    reason: "run_mage_analysis() is defined in mage_algorithms.py but is never called from graph_pipeline.py, runner.py, serve.py, or any other call site. The function is an orphan."
    artifacts:
      - path: "osint_system/data_management/graph/mage_algorithms.py"
        issue: "run_mage_analysis() exists (118 lines, substantive) but is not imported or invoked by any pipeline code"
      - path: "osint_system/pipeline/graph_pipeline.py"
        issue: "on_verification_complete() and run_ingestion() complete successfully but neither calls run_mage_analysis post-ingestion"
    missing:
      - "Import run_mage_analysis in graph_pipeline.py"
      - "Call run_mage_analysis(self._adapter, investigation_id) after ingestor.ingest_investigation() in on_verification_complete()"
      - "Return MAGE stats in ingestion result dict"
---

# Phase 13: PostgreSQL + Memgraph Storage Migration — Verification Report

**Phase Goal:** All investigation data persists durably in PostgreSQL with pgvector embeddings, knowledge graph persists in Memgraph with MAGE algorithms, surviving process restarts with no behavioral changes to pipeline or API code

**Verified:** 2026-03-22T12:00:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Investigation data survives process restarts | VERIFIED | All 5 stores use PostgreSQL async sessions via SQLAlchemy. No in-memory state; every write commits to DB. `async_sessionmaker` with `expire_on_commit=False`, `pool_pre_ping=True`. Docker volume `pgdata` named in compose. |
| 2 | Concurrent API reads during active pipeline do not block or produce stale data | VERIFIED | PostgreSQL default READ COMMITTED isolation. Each store method opens its own `async with session_factory() as session` — no shared session state, no asyncio.Lock. Multiple readers never contend. |
| 3 | Pipeline and agent code runs without modification against new store implementations | VERIFIED | All 5 stores preserve original method signatures and return types. `runner.py` injects session_factory via constructor; `serve.py` does the same. ExtractionPipeline, VerificationPipeline, GraphPipeline, AnalysisPipeline all receive store objects — no import changes needed. |
| 4 | Migration script + Alembic schema versioning + JSON-to-PostgreSQL migration | VERIFIED | `alembic.ini` configured with asyncpg URL. Single initial migration `c753fe39a0fb_initial_schema.py` covers all 6 tables. `scripts/migrate_json_to_postgres.py` handles all 5 data types with ON CONFLICT DO NOTHING idempotency. |
| 5 | pgvector embedding columns populated by gte-large-en-v1.5 | VERIFIED | `EmbeddingService` wraps sentence-transformers with async offload. Vector(1024) columns on articles, facts, entities, reports. HNSW index on facts.embedding with cosine ops. Graceful zero-vector fallback on CUDA errors (per known issue). EmbeddingService injected in runner.py constructor. |
| 6 | Full-text search via tsvector + GIN indexes on fact claim_text and article content | VERIFIED | `claim_tsvector` computed column + GIN index on facts. `content_tsvector` computed column + GIN index on articles. Both are `Computed(..., persisted=True)` — auto-populated by PostgreSQL on insert/update. Infrastructure is wired; no application-level FTS queries yet (acceptable — columns are queryable infrastructure, not a behavioral requirement). |
| 7 | Memgraph runs MAGE algorithms post-pipeline | FAILED | `run_mage_analysis()` defined but never called. See gaps section. |

**Score: 6/7 truths verified**

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `osint_system/data_management/article_store.py` | ArticleStore → PostgreSQL + pgvector | VERIFIED | 413 lines, async sessions, upsert via pg_insert ON CONFLICT, embedding injection, no JSON auto-persistence |
| `osint_system/data_management/fact_store.py` | FactStore → PostgreSQL + pgvector + FTS | VERIFIED | 712 lines, content-hash dedup, variant linking, entity extraction to entities table, embedding injection |
| `osint_system/data_management/classification_store.py` | ClassificationStore → PostgreSQL | VERIFIED | 661 lines, JSONB dubious_flags with `@>` containment queries, tier filtering, upsert pattern |
| `osint_system/data_management/verification_store.py` | VerificationStore → PostgreSQL | VERIFIED | 350 lines, VerificationResultRecord round-trip, broken _load_from_file structurally eliminated |
| `osint_system/reporting/report_store.py` | ReportStore → PostgreSQL + pgvector | VERIFIED | 477 lines, SHA256 content dedup, versioned immutable records, embedding on executive summary |
| `osint_system/data_management/database.py` | Async SQLAlchemy engine + session factory | VERIFIED | `init_db()` idempotent, `pool_pre_ping=True`, `expire_on_commit=False` (critical for async) |
| `osint_system/data_management/embeddings.py` | EmbeddingService (gte-large-en-v1.5) | VERIFIED | 159 lines, async offload via `run_in_executor`, CUDA→CPU fallback, zero-vector on error |
| `osint_system/data_management/graph/memgraph_adapter.py` | MemgraphAdapter with all query patterns | VERIFIED | 653 lines, 4 query patterns, batch UNWIND MERGE, label/rel-type allowlists, Bolt driver |
| `osint_system/data_management/graph/mage_algorithms.py` | MAGE algorithm runner | PARTIAL | 118 lines, 3 algorithms defined (PageRank, Louvain, betweenness), graceful degradation — BUT not called from any pipeline |
| `migrations/versions/c753fe39a0fb_initial_schema.py` | Alembic initial migration | VERIFIED | All 6 tables, pgvector VECTOR(1024) columns, HNSW index, GIN tsvector indexes, JSONB columns |
| `scripts/migrate_json_to_postgres.py` | JSON → PostgreSQL migration | VERIFIED | 559 lines, all 5 data types, ON CONFLICT DO NOTHING, embedding service integration |
| `docker-compose.yml` | PostgreSQL + Memgraph services | VERIFIED | `pgvector/pgvector:pg17` image, `memgraph/memgraph-mage` image (MAGE included), named volumes `pgdata`/`mgdata`, healthcheck on postgres |
| `init.sql` | pgvector extension initialization | VERIFIED | `CREATE EXTENSION IF NOT EXISTS vector;` — runs once on container first start |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `runner.py` | `ArticleStore` | `session_factory` injection at line 208 | WIRED | `init_db()` called at line 195, factory injected |
| `runner.py` | `FactStore` | `session_factory` injection at line 212 | WIRED | Factory + EmbeddingService injected |
| `runner.py` | `ClassificationStore` | `session_factory` injection at line 216 | WIRED | Factory injected |
| `runner.py` | `VerificationStore` | `session_factory` injection at line 219 | WIRED | Factory injected |
| `runner.py` | `ReportStore` | `session_factory` injection at line 226 | WIRED | Factory + EmbeddingService injected |
| `serve.py` | All stores | `init_db()` + constructor injection | WIRED | Lines 85-90, all 4 dashboard-relevant stores wired |
| `ArticleStore.save_articles()` | `EmbeddingService.embed()` | Conditional at line 106-108 | WIRED | Generates embedding if service present |
| `FactStore.save_facts()` | `EmbeddingService.embed()` | Conditional at line 126-129 | WIRED | Per-fact embedding at save time |
| `ReportStore.save_report()` | `EmbeddingService.embed()` | Conditional at line 277-281 | WIRED | Embeds executive summary |
| `GraphPipeline` | `MemgraphAdapter` | `_get_adapter()` lazy init at line 119-123 | WIRED | Config-driven; NetworkX fallback when `GRAPH_USE_NETWORKX=true` |
| `mage_algorithms.run_mage_analysis` | `GraphPipeline` | **MISSING** | NOT WIRED | `run_mage_analysis` defined, never imported or called from graph_pipeline.py |
| `Alembic env.py` | ORM models `Base.metadata` | `from osint_system.data_management.models import Base` | WIRED | Full metadata import; autogenerate covers all tables |

---

### Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| STORE-01: ArticleStore → PostgreSQL + pgvector | SATISFIED | Async upsert, embedding column, tsvector GIN index |
| STORE-02: FactStore → PostgreSQL + pgvector + FTS | SATISFIED | HNSW index, claim_tsvector, entity side-write |
| STORE-03: ClassificationStore → PostgreSQL | SATISFIED | JSONB containment queries, tier/flag indexes |
| STORE-04: VerificationStore → PostgreSQL | SATISFIED | Broken _load_from_file eliminated, VerificationResultRecord round-trip |
| STORE-05: ReportStore → PostgreSQL + pgvector | SATISFIED | Content-hash dedup, versioned immutable, embedding on executive summary |
| STORE-06: Alembic + Docker Compose + migration script | SATISFIED | Initial migration, compose with MAGE image, migration script |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `osint_system/data_management/graph/mage_algorithms.py` | 88-89 | `investigation_id: Reserved for future... Currently unused` | Warning | Documents intentional incompleteness; acceptable per deferred scope |
| `osint_system/database/__init__.py` | 1-11 | Imports `InvestigationArchive`, `InvestigationExporter` — SQLite-era artifacts | Info | Old database package not removed; but not called by any active pipeline code |

No blocker anti-patterns in the 5 store implementations or the embedding service.

---

### Human Verification Required

None required for structural verification. The following items are environment-dependent and need a live environment test:

1. **Process restart durability**
   - Test: Run an investigation, kill process, restart, read data via API
   - Expected: Full investigation data returns from PostgreSQL
   - Why human: Requires running Docker environment with Postgres

2. **Embedding zero-vector behavior under CUDA errors**
   - Test: Trigger investigation with CUDA driver error present
   - Expected: Migration completes with zero vectors, no crash
   - Why human: Specific CUDA environment condition

3. **Memgraph MAGE algorithms execution**
   - Test: Once Truth 7 gap is fixed, run investigation and inspect node.rank, node.community, node.betweenness properties
   - Expected: Properties populated post-ingestion
   - Why human: Requires live Memgraph with MAGE image running

---

## Gaps Summary

One gap blocks full goal achievement.

**Truth 7 — MAGE algorithms run post-pipeline:** The `mage_algorithms.py` module contains a complete, substantive `run_mage_analysis()` function (PageRank, Louvain community detection, betweenness centrality with graceful MAGE-not-available degradation). However, no code in the codebase calls it. `GraphPipeline.on_verification_complete()` calls `ingestor.ingest_investigation()` and returns — it never triggers MAGE analysis. The fix is small: import `run_mage_analysis` in `graph_pipeline.py` and call it after `ingest_investigation()` completes in both `on_verification_complete()` and `run_ingestion()`.

This is an orphaned function, not a missing feature. The capability was implemented but the final wiring step was skipped.

**Observation on FTS and pgvector queries:** The infrastructure (tsvector columns, GIN indexes, HNSW index) exists and is populated correctly. However, no code path currently executes an FTS query (`@@` operator) or a vector similarity query (`<->` operator) against these columns. This is not a gap against the phase goal — the phase goal specifies these capabilities "working" and "enabled," which is satisfied by the schema and index existence. Exercising these queries is a consumer-side concern for future phases (semantic search UI, dedup pipeline). Not flagged as a gap.

**Observation on `osint_system/database/` package:** Contains `InvestigationArchive` and `InvestigationExporter` — SQLite-era artifacts from before Phase 13. Neither is imported by any active pipeline code. This is dead code but not a blocker. The note is for cleanup in a future housekeeping pass.

---

_Verified: 2026-03-22T12:00:00Z_
_Verifier: Claude (gsd-verifier)_
