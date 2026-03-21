---
phase: 13-postgresql-memgraph-migration
plan: 04
subsystem: database
tags: [sqlalchemy, async-session, pgvector, embedding, entity-extraction, upsert, postgresql]

# Dependency graph
requires:
  - phase: 13-02
    provides: 6 SQLAlchemy ORM models with from_dict/to_dict contracts
  - phase: 13-06
    provides: EmbeddingService with async/sync embedding API
provides:
  - PostgreSQL-backed ArticleStore with pgvector embedding on save
  - PostgreSQL-backed FactStore with pgvector embedding + entity extraction on save
  - Both stores use async_sessionmaker per method call (no shared sessions)
  - Identical public method signatures and return types as in-memory originals
affects: [13-05-store-migration, 13-07-wiring]

# Tech tracking
tech-stack:
  added: []
  patterns: [pg_insert ON CONFLICT DO UPDATE for upsert, JSONB containment query for source lookup, deterministic entity_id hashing]

key-files:
  modified:
    - osint_system/data_management/article_store.py
    - osint_system/data_management/fact_store.py

key-decisions:
  - "D13-04-01: Upsert via INSERT ON CONFLICT DO UPDATE on article_id for URL deduplication (replaces in-memory URL index)"
  - "D13-04-02: Entity extraction uses deterministic hash of (investigation_id, canonical, entity_type) for entity_id dedup"
  - "D13-04-03: Entity extraction wrapped in try/except per entity -- failure does not abort fact save"

patterns-established:
  - "async with session_factory() as session / async with session.begin() per mutation method"
  - "pg_insert().on_conflict_do_update() for idempotent upserts"
  - "JSONB containment query (provenance['source_id'].astext) for source-based lookup"

# Metrics
duration: 4min
completed: 2026-03-22
---

# Phase 13 Plan 04: ArticleStore + FactStore PostgreSQL Migration Summary

**ArticleStore and FactStore rewritten from in-memory+JSON to SQLAlchemy async sessions with pgvector embedding wiring and entity extraction on fact save**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-21T23:14:21Z
- **Completed:** 2026-03-21T23:18:07Z
- **Tasks:** 2/2
- **Files modified:** 2

## Accomplishments

- ArticleStore fully migrated to PostgreSQL: async_sessionmaker constructor, URL dedup via INSERT ON CONFLICT, optional EmbeddingService populates Vector(1024) column on save
- FactStore fully migrated to PostgreSQL: async_sessionmaker constructor, content-hash dedup via SQL, variant linking via JSONB array mutation, optional EmbeddingService embeds claim_text
- Entity extraction in FactStore: iterates fact JSONB entities array, upserts EntityModel rows with deterministic entity_id hash, optional entity name embedding
- All in-memory state eliminated: no self._storage, self._lock, self._url_index, self._fact_index, self._hash_index, self._source_index
- All JSON persistence eliminated: no _save_to_file, _load_from_file, json.dump, json.load
- All public method signatures and return dict shapes preserved exactly

## Task Commits

1. **Task 1: Migrate ArticleStore to PostgreSQL with embedding support** - `0ce8ff1` (feat)
2. **Task 2: Migrate FactStore to PostgreSQL with embedding + entity extraction** - `4aee42d` (feat)

## Files Modified

- `osint_system/data_management/article_store.py` - Complete rewrite: 300 lines of SQLAlchemy async session code replacing 313 lines of in-memory+JSON. Constructor takes session_factory + optional EmbeddingService. 7 public methods preserved: save_articles, retrieve_by_investigation, retrieve_recent_articles, check_url_exists, get_investigation_stats, list_investigations, delete_investigation, get_storage_stats.
- `osint_system/data_management/fact_store.py` - Complete rewrite: 526 lines of SQLAlchemy async session code replacing 507 lines of in-memory+JSON. Constructor takes session_factory + optional EmbeddingService. 11 public methods preserved: save_facts, get_fact, get_fact_by_id, get_facts_by_hash, get_facts_by_source, retrieve_by_investigation, check_hash_exists, get_stats, list_investigations, delete_investigation, link_variants, get_storage_stats. Entity extraction added to save_facts.

## Decisions Made

- [D13-04-01] **Upsert via INSERT ON CONFLICT**: ArticleStore uses `pg_insert().on_conflict_do_update(index_elements=["article_id"])` for URL deduplication. This replaces the in-memory `_url_index` dict. The article_id is SHA256(url) computed in ArticleModel.from_dict().
- [D13-04-02] **Deterministic entity_id**: Entity extraction in FactStore hashes `(investigation_id, canonical_name, entity_type)` to produce a deterministic entity_id. This enables natural dedup via ON CONFLICT without requiring a lookup query before each insert.
- [D13-04-03] **Entity extraction isolation**: Each entity upsert is wrapped in try/except. If a single entity fails to extract (bad data, missing name, etc.), the fact save proceeds normally. Logged at WARNING level via stdlib logging.

## Deviations from Plan

None -- plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- Both stores accept session_factory from database.init_db() or create_session_factory()
- Both stores accept optional EmbeddingService for pgvector population
- Plan 13-07 (wiring) will update all callers to pass session_factory instead of persistence_path
- No blockers

---
*Phase: 13-postgresql-memgraph-migration*
*Completed: 2026-03-22*
