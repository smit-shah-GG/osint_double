# Phase 13: PostgreSQL + Memgraph Storage Migration - Context

**Gathered:** 2026-03-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Replace all in-memory+JSON stores with PostgreSQL (+ pgvector) for relational/document data and Memgraph for knowledge graph persistence. All investigation data survives process restarts. Existing pipeline and API code runs against new store implementations via preserved interfaces. No new user-facing features — this is an infrastructure swap with capability unlocks (semantic search, full-text search, graph algorithms).

**Scope change from original ROADMAP:** Phase was originally "SQLite Storage Migration." User rejected SQLite as insufficiently production-grade for a startup product. PostgreSQL + pgvector selected for stores; Memgraph selected for graph (replacing NetworkX in-memory + optional Neo4j).

</domain>

<decisions>
## Implementation Decisions

### Database Selection (Critical Decisions)

#### PostgreSQL + pgvector over SQLite
- **Decision:** PostgreSQL replaces SQLite as the relational store.
- **Why:** SQLite is not performant, modern, or confidence-inspiring in presentations and promos. The user is evaluating this as a startup product. PostgreSQL is the industry standard — "PostgreSQL-backed" is a statement that adds credibility in every technical audience. SQLAlchemy works identically with both, so the ORM code migration effort is the same regardless.
- **Additional capability unlocks:** JSONB for flexible nested schemas, concurrent reads/writes without WAL hacks, full-text search (tsvector/tsquery + GIN), scales to multi-user when needed, runs in Docker alongside the backend.

#### pgvector for embeddings
- **Decision:** Add pgvector extension for vector similarity search.
- **Why:** Enables semantic deduplication (catch near-duplicate facts with different wording), "find similar facts" queries, entity resolution across investigations, and cross-investigation comparison. Future-proofs the system for semantic search without a separate vector DB.
- **Embedding model:** `gte-large-en-v1.5` (1.2GB, 1024 dimensions). Runs locally on user's RTX 3060 12GB. At ~500 facts per investigation, embedding takes <2 seconds. No API calls, no token costs.
- **Embedding timing:** At extraction time — each fact's claim text is embedded immediately when extracted. Available for dedup and search instantly.
- **Tables with embedding columns:** Facts (claim_text), Articles (content), Entities (canonical name), Reports (executive summary). All four get pgvector columns.

#### Memgraph over Neo4j for knowledge graph
- **Decision:** Memgraph replaces Neo4j as the graph database.
- **Why (in priority order):**
  1. **Licensing is the deciding factor.** Neo4j CE is GPLv3 + Commons Clause — litigated ($597K PureThink suit). A hostile reading could argue the OSINT product "derives primary value from" the graph DB. Memgraph's BSL 1.1 is unambiguously safe for commercial use — you can embed it, sell products using it, everything except offering Memgraph-as-a-service.
  2. **Free graph algorithms (MAGE).** PageRank for entity importance, Louvain community detection for information clusters, betweenness centrality for broker entities. All Apache 2.0. Neo4j's equivalent (GDS) requires Enterprise licensing ($36K+/year).
  3. **Native triggers + Kafka streaming** free in CE. Neo4j CE has no trigger support at all.
  4. **Docker footprint.** ~200MB image, ~50MB idle RAM, 1-5s startup vs Neo4j's ~400MB, ~300MB RAM, 10-30s. Live demos go from "wait for health check" to instant.
- **Cypher compatibility:** 90-95%. Core MERGE/UNWIND/parameterized queries work as-is via the same `neo4j` Python async driver. Schema init queries need rewriting (9 statements — constraint/index syntax differs). `datetime()` becomes `localDateTime()`.
- **Risk acknowledged:** Smaller community (10-20x less StackOverflow). Smaller company (~50-100 employees). BSL converts to Apache 2.0 if they fold. User is unconcerned with complexity.

### Store Migration Scope
- **All 5 stores migrate to PostgreSQL:** ArticleStore, FactStore, ClassificationStore, VerificationStore, ReportStore.
- **JSON persistence removed as auto-save mechanism.** Postgres is the single source of truth.
- **JSON export capability preserved.** Keep ability to export investigation data to JSON for portability (manual export, not auto-save). Delete all `_save_to_file` / `_load_from_file` auto-persistence code.
- **Store interfaces preserved.** Same method signatures, same return types. Swap in-memory dict backend for SQLAlchemy. Pipeline and API code unchanged. Safest migration path.

### Schema Design
- **Hybrid: key fields as columns + JSONB for nested objects.** Top-level queryable fields (fact_id, investigation_id, claim_text, source_url, created_at, status) as proper columns. Nested Pydantic objects (entities[], provenance, quality_metrics) as JSONB columns. Best of both: SQL-queryable keys + flexible nesting without 6+ normalized tables per concept.
- **Full-text search:** tsvector columns + GIN indexes on both facts.claim_text AND articles.content. Enables instant text search without external engine.
- **pgvector columns:** 1024-dimension vectors on facts, articles, entities, reports tables.

### Memgraph Adapter
- **Rename Neo4jAdapter to MemgraphAdapter.** Fork existing code, rename, fix Cypher syntax differences. Delete Neo4jAdapter. Clean break — no ambiguity about which DB is supported. NetworkXAdapter remains as dev/test backend.
- **MAGE algorithms integrated in this phase:** PageRank (entity importance ranking), Louvain community detection (entity clusters), betweenness centrality (broker/intermediary entities). Run post-ingestion, not on every node insertion.
- **Triggers:** Manual re-analysis, not trigger-based. Run MAGE algorithms explicitly after pipeline completes. Avoids trigger cascade complexity.

### Infrastructure & Docker
- **Single docker-compose.yml:** Postgres (+ pgvector extension), Memgraph, and Python backend all in one compose file. `docker compose up` starts everything.
- **Alembic from day one:** Initialize with initial schema as first migration. Future schema changes tracked properly from the start.
- **Data migration script:** One-time script reads existing `data/inv-*/*.json` files and inserts into Postgres tables. Preserves existing investigations.

### Claude's Discretion
- SQLAlchemy model design (declarative base, mixins, session management)
- Alembic configuration (async driver, migration file organization)
- Connection pooling parameters (pool_size, max_overflow)
- Memgraph Docker image version and configuration
- pgvector index type (IVFFlat vs HNSW) based on dataset size
- Embedding generation pipeline (sentence-transformers integration)
- JSON export format and CLI interface

</decisions>

<specifics>
## Specific Ideas

- The `GraphAdapter` Protocol from Phase 9 is the right abstraction — MemgraphAdapter implements the same interface, swapped via config
- Existing Neo4jAdapter is ~80% complete with all 4 query patterns (entity_network, corroboration, timeline, shortest_path) + Cypher escape hatch
- The `neo4j` Python async driver works unchanged against Memgraph (same Bolt protocol)
- Geopol project uses file-based serialization (GraphML + JSON) — not applicable here due to concurrent access needs
- User's machine: i9-13900K, 32GB RAM, RTX 3060 12GB — gte-large-en-v1.5 runs comfortably locally
- VerificationStore._load_from_file() was identified as broken in prior sessions — Postgres migration fixes this structurally
- Application-level joins in facts.py API route (3 sequential store calls) become SQL JOINs — dramatic speedup for paginated views
- Event bus persistence (pipeline events in Postgres table) enables SSE replay across server restarts

</specifics>

<deferred>
## Deferred Ideas

- Memgraph triggers for automatic re-analysis on fact ingestion — decided manual re-analysis for now, could add triggers later
- Kafka streaming integration with Memgraph — powerful for real-time monitoring pipelines, but no Kafka infrastructure yet
- Temporal Graph Networks (MAGE 1.2+) — temporal evolution modeling for intelligence networks, add when temporal analysis is a user requirement
- Cross-investigation entity linking via graph queries — use entity embeddings in pgvector + Memgraph entity_network to find canonical matches across investigations
- PostgreSQL + AGE extension as an alternative/fallback graph backend — valid option if Memgraph constraints arise, but adding a second graph backend is premature
- Semantic dedup during extraction — pgvector enables it but the dedup logic itself (threshold tuning, what to do with near-duplicates) needs its own design pass

</deferred>

---

*Phase: 13-postgresql-memgraph-migration*
*Context gathered: 2026-03-22*
