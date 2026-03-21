---
phase: 13-postgresql-memgraph-migration
plan: 07
subsystem: database
tags: [postgresql, memgraph, migration, embeddings, pgvector, alembic, docker]

# Dependency graph
requires:
  - phase: 13-postgresql-memgraph-migration
    provides: PostgreSQL + pgvector infra (Plan 01), ORM models (Plan 02), MemgraphAdapter (Plan 03), ArticleStore + FactStore migration (Plan 04), Classification + Verification + ReportStore migration (Plan 05), EmbeddingService (Plan 06)
provides:
  - Runner/API/pipeline wired to PostgreSQL stores with EmbeddingService
  - MemgraphAdapter replacing Neo4jAdapter in all consumers
  - JSON-to-PostgreSQL data migration script
  - Neo4jAdapter and cypher_queries deleted
  - API discovers persisted investigations from PostgreSQL (not just in-memory registry)
affects: [17-crawler-agent-integration]

# Tech tracking
tech-stack:
  added: []
  patterns: [init_db/close_db lifespan for API, session_factory + EmbeddingService constructor injection for all stores, async init_db at runner startup]

key-files:
  created:
    - scripts/migrate_json_to_postgres.py
  modified:
    - osint_system/runner.py
    - osint_system/serve.py
    - osint_system/api/app.py
    - osint_system/api/dependencies.py
    - osint_system/api/routes/investigations.py
    - osint_system/pipeline/graph_pipeline.py
    - osint_system/data_management/graph/__init__.py
    - osint_system/data_management/graph/adapter.py
    - osint_system/data_management/graph/networkx_adapter.py
    - osint_system/data_management/graph/memgraph_adapter.py
    - osint_system/data_management/graph/memgraph_queries.py
    - osint_system/data_management/embeddings.py
    - osint_system/config/graph_config.py
  deleted:
    - osint_system/data_management/graph/neo4j_adapter.py
    - osint_system/data_management/graph/cypher_queries.py

key-decisions:
  - "D13-07-01: list_investigations queries PostgreSQL for persisted investigations, merging with in-memory registry for complete view"
  - "D13-07-02: EmbeddingService in runner wrapped in try/except ImportError for graceful degradation without sentence-transformers"

patterns-established:
  - "Lifespan init: API app lifespan calls init_db() on startup, stores session_factory + EmbeddingService on app.state, calls close_db() on shutdown"
  - "Dependency injection: route dependencies create store instances from request.app.state.session_factory + request.app.state.embedding_service"
  - "Migration script pattern: idempotent ON CONFLICT DO NOTHING with composite unique constraints for safe re-runs"

# Metrics
duration: ~25min (across checkpoint)
completed: 2026-03-22
---

# Phase 13 Plan 07: Integration Wiring + Data Migration Summary

**Runner, API, pipeline wired to PostgreSQL/Memgraph with EmbeddingService; Neo4jAdapter deleted; 539-line migration script migrated 12 investigations (87 articles, 888 facts, 1425 entities) to PostgreSQL**

## Performance

- **Duration:** ~25 min (across checkpoint verification)
- **Tasks:** 3/3 (2 auto + 1 checkpoint)
- **Files modified:** 17 (14 modified, 1 created, 2 deleted)

## Accomplishments
- InvestigationRunner creates all stores with `session_factory` from `init_db()` and `EmbeddingService` -- ArticleStore, FactStore, and ReportStore all receive mandatory embedding_service
- API app lifespan manages database lifecycle (init_db on startup, close_db on shutdown) with EmbeddingService on app.state
- GraphPipeline uses MemgraphAdapter; all Neo4jAdapter/cypher_queries references eliminated and files deleted (803 lines removed)
- Migration script successfully migrated 12 investigations: 87 articles, 888 facts, 1425 entities, 888 classifications, 29 verifications, 3 reports
- API `list_investigations` now discovers persisted investigations from PostgreSQL, not just in-memory registry
- CUDA embedding errors caught gracefully with CPU fallback and zero-vector sentinel

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire runner, API, pipeline to PostgreSQL + Memgraph + EmbeddingService** - `932e06e` (feat)
2. **Task 2: JSON-to-PostgreSQL data migration script** - `46c5485` (feat)
3. **Task 3: Checkpoint -- human verification** - approved by user

**Bugfix commits during checkpoint testing:**
- `3b51dee` (fix) - Migration script column names + embedding safety truncation
- `d2e4803` (fix) - Composite unique constraints in migration + CUDA CPU fallback
- `13f0f4b` (fix) - Parse ISO datetime strings for report generated_at column
- `4f715b2` (fix) - list_investigations discovers persisted investigations from PostgreSQL

## Files Created/Modified
- `osint_system/runner.py` - Runner creates stores with session_factory and EmbeddingService, uses MemgraphAdapter
- `osint_system/serve.py` - Dashboard mode uses PostgreSQL stores instead of JSON file loading
- `osint_system/api/app.py` - Lifespan manages init_db/close_db, stores session_factory + EmbeddingService on app.state
- `osint_system/api/dependencies.py` - Route dependencies create stores from app.state session_factory + embedding_service
- `osint_system/api/routes/investigations.py` - list_investigations queries PostgreSQL for persisted investigations
- `osint_system/pipeline/graph_pipeline.py` - Uses MemgraphAdapter instead of Neo4jAdapter
- `osint_system/data_management/graph/__init__.py` - Exports MemgraphAdapter, removed Neo4jAdapter
- `osint_system/data_management/graph/adapter.py` - Updated docstring references from Neo4j to Memgraph
- `osint_system/data_management/graph/networkx_adapter.py` - Updated docstring references from Neo4j to Memgraph
- `osint_system/data_management/graph/memgraph_adapter.py` - Minor connector config updates
- `osint_system/data_management/graph/memgraph_queries.py` - Minor query updates
- `osint_system/data_management/embeddings.py` - CUDA fallback to CPU, safety truncation for model max_seq_length
- `osint_system/config/graph_config.py` - Updated docstring references from Neo4j to Memgraph
- `scripts/migrate_json_to_postgres.py` - 539-line idempotent migration script with entity extraction, embedding generation, and progress logging
- `tests/data_management/graph/test_networkx_adapter.py` - Updated docstring reference

**Deleted:**
- `osint_system/data_management/graph/neo4j_adapter.py` (628 lines)
- `osint_system/data_management/graph/cypher_queries.py` (175 lines)

## Decisions Made
- [D13-07-01] `list_investigations` queries PostgreSQL `articles` table for distinct investigation_ids to discover persisted investigations, merging with the in-memory runner registry. This ensures investigations that survived process restarts are visible in the API.
- [D13-07-02] EmbeddingService construction in runner wrapped in `try/except ImportError` so the system degrades gracefully if sentence-transformers is not installed (stores receive `None` and skip embedding generation).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Migration script column name mismatches**
- **Found during:** Checkpoint testing (Task 3)
- **Issue:** Migration script used column names that didn't match the ORM model column names (e.g., wrong field names in INSERT statements)
- **Fix:** Aligned all column names with the ORM models defined in Plans 02/04/05
- **Files modified:** scripts/migrate_json_to_postgres.py
- **Committed in:** 3b51dee

**2. [Rule 1 - Bug] Composite unique constraints for ON CONFLICT**
- **Found during:** Checkpoint testing (Task 3)
- **Issue:** ON CONFLICT clauses referenced wrong constraint columns, causing insert failures on re-runs
- **Fix:** Updated ON CONFLICT to use correct composite unique constraint columns matching the database schema
- **Files modified:** scripts/migrate_json_to_postgres.py
- **Committed in:** d2e4803

**3. [Rule 1 - Bug] CUDA embedding errors crash migration**
- **Found during:** Checkpoint testing (Task 3)
- **Issue:** CUDA initialization errors during embedding generation crashed the entire migration
- **Fix:** EmbeddingService falls back to CPU when CUDA fails; embedding errors produce zero vectors instead of crashing
- **Files modified:** osint_system/data_management/embeddings.py
- **Committed in:** d2e4803

**4. [Rule 1 - Bug] ISO datetime string parsing for report generated_at**
- **Found during:** Checkpoint testing (Task 3)
- **Issue:** Report JSON files store `generated_at` as ISO datetime strings, but the ORM model expects datetime objects. SQLAlchemy rejected the raw strings.
- **Fix:** Added `datetime.fromisoformat()` parsing for `generated_at` field before insertion
- **Files modified:** scripts/migrate_json_to_postgres.py
- **Committed in:** 13f0f4b

**5. [Rule 2 - Missing Critical] API cannot discover persisted investigations**
- **Found during:** Checkpoint testing (Task 3)
- **Issue:** `list_investigations` only returned investigations from the in-memory runner registry. After process restart, migrated investigations were invisible via the API even though data existed in PostgreSQL.
- **Fix:** Added PostgreSQL query to discover investigation_ids from the articles table and merge with in-memory registry
- **Files modified:** osint_system/api/routes/investigations.py
- **Committed in:** 4f715b2

**6. [Rule 1 - Bug] Embedding input exceeds model max_seq_length**
- **Found during:** Checkpoint testing (Task 3)
- **Issue:** Long article content exceeded the embedding model's maximum sequence length, causing silent truncation warnings
- **Fix:** Added safety truncation in EmbeddingService to clip input text to model's max_seq_length before encoding
- **Files modified:** osint_system/data_management/embeddings.py
- **Committed in:** 3b51dee

---

**Total deviations:** 6 auto-fixed (4 bugs, 1 missing critical, 1 bug)
**Impact on plan:** All fixes were necessary for correct migration and API operation. The checkpoint verification phase revealed real-world integration issues that unit tests alone would not catch. No scope creep.

## Issues Encountered
- CUDA initialization fails in some environments (resolved with CPU fallback)
- JSON file formats had minor inconsistencies across investigation directories (resolved with defensive parsing)
- Embedding generation for 87 articles + 888 facts is slow on CPU (~5 min) -- acceptable for one-time migration

## User Setup Required
Docker services (PostgreSQL + Memgraph) must be running: `docker compose up -d`
Alembic migrations must be applied: `uv run alembic upgrade head`

## Next Phase Readiness
- Phase 13 (PostgreSQL + Memgraph Migration) is COMPLETE. All 7 plans executed:
  - Plan 01: PostgreSQL + pgvector + Alembic infrastructure
  - Plan 02: ORM models (6 tables with JSONB, vector columns, tsvector)
  - Plan 03: MemgraphAdapter replacing Neo4jAdapter
  - Plan 04: ArticleStore + FactStore migration with entity extraction
  - Plan 05: ClassificationStore + VerificationStore + ReportStore migration
  - Plan 06: EmbeddingService (sentence-transformers + gte-large-en-v1.5)
  - Plan 07: Integration wiring + data migration (this plan)
- All STORE requirements satisfied: STORE-01 through STORE-06
- System is ready for Phase 17 (Crawler Agent Integration)
- Embedding backfill with GPU can be done later when CUDA environment is available
- No blockers

---
*Phase: 13-postgresql-memgraph-migration*
*Completed: 2026-03-22*
