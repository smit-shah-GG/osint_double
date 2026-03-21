---
phase: 13-postgresql-memgraph-migration
plan: 02
subsystem: database
tags: [sqlalchemy, orm, pgvector, tsvector, alembic, postgresql]

# Dependency graph
requires:
  - phase: 13-01
    provides: async SQLAlchemy engine, DeclarativeBase, Alembic scaffold, Docker Compose
provides:
  - 6 SQLAlchemy ORM models with hybrid column+JSONB schemas
  - pgvector Vector(1024) columns on facts, articles, entities, reports
  - tsvector computed columns with GIN indexes on facts and articles
  - HNSW index on facts.embedding for semantic search
  - from_dict/to_dict round-trip methods preserving store data formats
  - Initial Alembic migration applied to PostgreSQL
affects: [13-03-store-migration, 13-04-memgraph-adapter, 13-05-embedding-layer, 13-06-json-migration]

# Tech tracking
tech-stack:
  added: []
  patterns: [hybrid column+JSONB schema, from_dict/to_dict contract preservation, tsvector computed columns, HNSW index on pgvector]

key-files:
  created:
    - osint_system/data_management/models/article.py
    - osint_system/data_management/models/fact.py
    - osint_system/data_management/models/entity.py
    - osint_system/data_management/models/classification.py
    - osint_system/data_management/models/verification.py
    - osint_system/data_management/models/report.py
    - migrations/versions/c753fe39a0fb_initial_schema.py
  modified:
    - osint_system/data_management/models/base.py
    - osint_system/data_management/models/__init__.py
    - migrations/env.py

key-decisions:
  - "D13-02-01: Hybrid column+JSONB pattern -- queryable fields as columns, nested Pydantic objects as JSONB"
  - "D13-02-02: claim_data JSONB stores full claim sub-object for fields not promoted to columns (e.g. claim_type)"
  - "D13-02-03: verification_data and classification_data JSONB store full record for zero-loss round-trip"
  - "D13-02-04: env.py imports from models package (not base) to trigger all model registration for autogenerate"

patterns-established:
  - "from_dict/to_dict contract on every ORM model for store interface preservation"
  - "JSONB fallback column (xxx_data) storing full Pydantic dict for fields not promoted to columns"
  - "TimestampMixin with server_default=func.now() and onupdate=func.now()"

# Metrics
duration: 8min
completed: 2026-03-22
---

# Phase 13 Plan 02: ORM Models + Alembic Migration Summary

**6 SQLAlchemy ORM models with hybrid column+JSONB, pgvector Vector(1024), tsvector+GIN, HNSW index; initial Alembic migration applied to PostgreSQL**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-21T23:03:31Z
- **Completed:** 2026-03-21T23:11:20Z
- **Tasks:** 2/2
- **Files created:** 7
- **Files modified:** 3

## Accomplishments

- All 6 ORM models (Article, Fact, Entity, Classification, Verification, Report) with hybrid column+JSONB schemas
- pgvector Vector(1024) embedding columns on facts, articles, entities, reports tables
- tsvector computed columns on facts (claim_text) and articles (title+content) with GIN indexes
- HNSW index on facts.embedding with m=16, ef_construction=64, vector_cosine_ops
- from_dict/to_dict methods on all 6 models preserving exact store data formats
- Initial Alembic migration generated via autogenerate and applied to live PostgreSQL
- All tables verified via psql with correct column types, indexes, and constraints

## Task Commits

1. **Task 1: Base + Article + Fact + Entity models** - `f5947ca` (feat)
2. **Task 2: Classification + Verification + Report models + Alembic migration** - `60140c1` (feat)

## Files Created/Modified

- `osint_system/data_management/models/base.py` - Enhanced with TimestampMixin (server_default, onupdate)
- `osint_system/data_management/models/article.py` - ArticleModel: url/title/content columns, JSONB source/metadata, Vector(1024), tsvector
- `osint_system/data_management/models/fact.py` - FactModel: claim_text/assertion_type columns, JSONB entities/provenance/quality/temporal/numeric/relationships/variants/claim_data, Vector(1024) with HNSW, tsvector with GIN
- `osint_system/data_management/models/entity.py` - EntityModel: name/entity_type/canonical columns, JSONB metadata, Vector(1024)
- `osint_system/data_management/models/classification.py` - ClassificationModel: tier/priority/credibility columns, JSONB flags/reasoning/history/classification_data, UniqueConstraint(inv, fact)
- `osint_system/data_management/models/verification.py` - VerificationModel: status/confidence columns, JSONB evidence/queries/verification_data, UniqueConstraint(inv, fact)
- `osint_system/data_management/models/report.py` - ReportModel: version/content_hash/markdown columns, JSONB synthesis_summary, Vector(1024), UniqueConstraint(inv, version)
- `osint_system/data_management/models/__init__.py` - All 6 model imports for Alembic autogenerate
- `migrations/env.py` - Import from models package instead of models.base (Pitfall 6 fix)
- `migrations/versions/c753fe39a0fb_initial_schema.py` - Initial migration with all 6 tables, indexes, constraints

## Decisions Made

- [D13-02-01] **Hybrid column+JSONB pattern**: Top-level queryable fields (fact_id, claim_text, status, tier) as proper columns with B-tree indexes. Nested Pydantic objects (entities[], provenance, quality_metrics, credibility_breakdown) as JSONB. Avoids normalization into 20+ tables while enabling SQL WHERE/ORDER BY on important fields.
- [D13-02-02] **claim_data JSONB fallback**: The FactModel stores claim.claim_type in claim_data JSONB rather than a dedicated column since it's not used in WHERE clauses. to_dict() merges claim_data back into the claim sub-object for perfect round-trip.
- [D13-02-03] **Full record JSONB columns**: verification_data and classification_data store the complete VerificationResultRecord/FactClassification dict. This ensures zero-loss round-trip even if new fields are added to Pydantic schemas before the next migration.
- [D13-02-04] **env.py import fix**: Changed `from osint_system.data_management.models.base import Base` to `from osint_system.data_management.models import Base`. The base-only import does NOT trigger model registration because individual model modules are not loaded. The package __init__.py import triggers all model imports.

## Deviations from Plan

None -- plan executed exactly as written.

## Issues Encountered

- Alembic autogenerate emits `pgvector.sqlalchemy.vector.VECTOR` references in migration files but does not auto-add the `import pgvector.sqlalchemy.vector` statement. Fixed by manually adding the import to the generated migration file before running `alembic upgrade head`.

## Next Phase Readiness

- All 6 ORM models defined with correct schemas
- Initial migration applied (c753fe39a0fb at head)
- PostgreSQL has all tables with pgvector, tsvector, HNSW, GIN
- from_dict/to_dict methods ready for Plan 03 store migration
- No blockers

---
*Phase: 13-postgresql-memgraph-migration*
*Completed: 2026-03-22*
