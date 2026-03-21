# Phase 13: PostgreSQL + Memgraph Migration - Research

**Researched:** 2026-03-22
**Domain:** Database migration (PostgreSQL/pgvector + Memgraph), SQLAlchemy ORM, Alembic, local embeddings
**Confidence:** HIGH

## Summary

This phase replaces 5 in-memory+JSON stores with PostgreSQL (via SQLAlchemy 2.0 async + asyncpg), adds pgvector for semantic search, replaces Neo4j with Memgraph for the knowledge graph, and introduces Alembic for schema versioning. The technology choices are all mature and well-documented.

The existing codebase has 5 store classes (ArticleStore, FactStore, ClassificationStore, VerificationStore, ReportStore) with identical patterns: `Dict[str, Dict]` in-memory storage, asyncio.Lock for concurrency, optional JSON persistence via `_save_to_file`/`_load_from_file`. All expose async methods that callers depend on. The migration preserves these method signatures while swapping the backend to SQLAlchemy async sessions. The graph layer already has a `GraphAdapter` Protocol with `Neo4jAdapter` and `NetworkXAdapter` implementations -- `MemgraphAdapter` forks `Neo4jAdapter`, fixes 9 Cypher syntax differences, and adds MAGE algorithm calls.

**Primary recommendation:** Use SQLAlchemy 2.0 async with asyncpg driver for all PostgreSQL stores, psycopg for pgvector type registration, Alembic with `-t async` template, `pgvector/pgvector:pg17` Docker image, `memgraph/memgraph-mage` Docker image, and `sentence-transformers` for local gte-large-en-v1.5 embeddings.

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | >=2.0 | Async ORM for PostgreSQL stores | Industry standard Python ORM; 2.0 has native async support with `AsyncSession` |
| asyncpg | >=0.29.0 | Async PostgreSQL driver | 5x faster than psycopg3 async in benchmarks; native async, zero libpq dependency |
| psycopg[binary] | >=3.1 | pgvector type registration | Required by pgvector-python for `register_vector_async`; asyncpg does not support custom types |
| pgvector | >=0.3.0 | pgvector SQLAlchemy integration | Official pgvector Python library; provides `Vector` type, distance operators, index helpers |
| alembic | >=1.12 | Schema migration management | The only production-grade SQLAlchemy migration tool |
| sentence-transformers | >=2.7.0 | Local embedding generation | Required for gte-large-en-v1.5; wraps transformers/torch |
| neo4j | >=5.0 (already installed >=6.1) | Bolt driver for Memgraph | Memgraph uses same Bolt protocol; existing driver works unchanged |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| torch | >=2.0 | PyTorch backend for sentence-transformers | Dependency of sentence-transformers; CUDA 12.x for RTX 3060 |
| transformers | >=4.36.0 | Model loading for gte-large-en-v1.5 | Dependency of sentence-transformers |

### Docker Images

| Image | Tag | Purpose |
|-------|-----|---------|
| pgvector/pgvector | pg17 | PostgreSQL 17 with pgvector extension pre-installed |
| memgraph/memgraph-mage | latest (3.7.1+) | Memgraph with MAGE algorithms (PageRank, Louvain, betweenness) |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| asyncpg | psycopg3 async | psycopg3 is slower (28% lower QPS) but has LISTEN/NOTIFY and pgvector type registration built-in |
| pgvector/pgvector Docker | Custom Dockerfile with `CREATE EXTENSION` | Official image is simpler; custom only if needing non-standard PG extensions |
| sentence-transformers | Raw transformers + manual pooling | sentence-transformers handles batching, normalization, GPU offload automatically |

**Dual driver note:** The project needs BOTH asyncpg (fast queries via SQLAlchemy) AND psycopg (pgvector type registration). This is a well-known pattern. pgvector-python requires psycopg to call `register_vector_async` on the raw connection. SQLAlchemy uses asyncpg for actual query execution. The registration happens via SQLAlchemy's `event.listens_for(engine.sync_engine, "connect")` hook.

**Installation:**
```bash
uv pip install "sqlalchemy[asyncio]>=2.0" asyncpg "psycopg[binary]>=3.1" pgvector alembic sentence-transformers
```

## Architecture Patterns

### Recommended Project Structure

```
osint_system/
├── data_management/
│   ├── database.py              # AsyncEngine, async_sessionmaker, pgvector registration
│   ├── models/                  # SQLAlchemy ORM models (declarative)
│   │   ├── __init__.py
│   │   ├── base.py              # DeclarativeBase, common mixins
│   │   ├── article.py           # ArticleModel
│   │   ├── fact.py              # FactModel (+ pgvector + tsvector)
│   │   ├── classification.py    # ClassificationModel
│   │   ├── verification.py      # VerificationModel
│   │   ├── report.py            # ReportModel (+ pgvector)
│   │   └── entity.py            # EntityModel (+ pgvector)
│   ├── article_store.py         # MODIFIED: SQLAlchemy backend, same interface
│   ├── fact_store.py            # MODIFIED: SQLAlchemy backend, same interface
│   ├── classification_store.py  # MODIFIED: SQLAlchemy backend, same interface
│   ├── verification_store.py    # MODIFIED: SQLAlchemy backend, same interface
│   ├── graph/
│   │   ├── memgraph_adapter.py  # NEW: replaces neo4j_adapter.py
│   │   ├── memgraph_queries.py  # NEW: replaces cypher_queries.py (Memgraph syntax)
│   │   ├── mage_algorithms.py   # NEW: PageRank, Louvain, betweenness calls
│   │   ├── networkx_adapter.py  # PRESERVED: dev/test backend
│   │   ├── adapter.py           # PRESERVED: GraphAdapter Protocol
│   │   └── schema.py            # PRESERVED: GraphNode, GraphEdge, QueryResult
│   └── embeddings.py            # NEW: EmbeddingService wrapping gte-large-en-v1.5
├── reporting/
│   └── report_store.py          # MODIFIED: SQLAlchemy backend, same interface
├── config/
│   ├── graph_config.py          # MODIFIED: renamed fields from neo4j_ to memgraph_
│   └── database_config.py       # NEW: PostgreSQL connection config
├── migrations/                  # Alembic migration directory
│   ├── env.py
│   ├── versions/
│   │   └── 001_initial_schema.py
│   └── script.py.mako
├── scripts/
│   └── migrate_json_to_postgres.py  # One-time JSON data migration
└── docker-compose.yml           # PostgreSQL + Memgraph + backend
```

### Pattern 1: AsyncSession per Unit of Work (Store Method)

**What:** Each store method creates a short-lived AsyncSession, performs its work, commits, and closes.
**When to use:** Every store method that accesses the database.

```python
# Source: SQLAlchemy 2.0 async documentation
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Module-level: one engine, one session factory
engine = create_async_engine(
    "postgresql+asyncpg://user:pass@localhost:5432/osint",
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)

# In each store method:
async def get_fact(self, investigation_id: str, fact_id: str) -> Optional[dict]:
    async with self._session_factory() as session:
        stmt = select(FactModel).where(
            FactModel.investigation_id == investigation_id,
            FactModel.fact_id == fact_id,
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return row.to_dict() if row else None
```

### Pattern 2: Hybrid Schema (Columns + JSONB)

**What:** Top-level queryable fields as proper columns; nested Pydantic objects as JSONB.
**When to use:** All 5 store tables.

```python
# Source: SQLAlchemy 2.0 + PostgreSQL JSONB docs
from sqlalchemy import String, Float, DateTime, Text, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

class FactModel(Base):
    __tablename__ = "facts"

    # Primary key and queryable columns
    id: Mapped[int] = mapped_column(primary_key=True)
    fact_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    investigation_id: Mapped[str] = mapped_column(String(64), index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    claim_text: Mapped[str] = mapped_column(Text)
    assertion_type: Mapped[str] = mapped_column(String(20), default="statement")
    extraction_confidence: Mapped[float] = mapped_column(Float, nullable=True)
    claim_clarity: Mapped[float] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    # Nested objects as JSONB
    entities: Mapped[dict] = mapped_column(JSONB, default=list)
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=True)
    quality_metrics: Mapped[dict] = mapped_column(JSONB, nullable=True)
    temporal: Mapped[dict] = mapped_column(JSONB, nullable=True)
    numeric: Mapped[dict] = mapped_column(JSONB, nullable=True)
    relationships: Mapped[dict] = mapped_column(JSONB, default=list)
    variants: Mapped[list] = mapped_column(JSONB, default=list)

    # pgvector embedding (1024 dims for gte-large-en-v1.5)
    embedding: Mapped[list] = mapped_column(Vector(1024), nullable=True)

    # tsvector for full-text search (generated column)
    claim_tsvector = mapped_column(
        TSVector(),
        Computed("to_tsvector('english', claim_text)", persisted=True),
    )

    __table_args__ = (
        Index("ix_facts_claim_fts", "claim_tsvector", postgresql_using="gin"),
        Index(
            "ix_facts_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
```

### Pattern 3: pgvector Registration with Dual Drivers

**What:** Register pgvector types via psycopg event hook while using asyncpg for queries.
**When to use:** Database initialization in `database.py`.

```python
# Source: pgvector-python README
from pgvector.psycopg import register_vector_async
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine

engine = create_async_engine("postgresql+asyncpg://...")

@event.listens_for(engine.sync_engine, "connect")
def connect(dbapi_connection, connection_record):
    dbapi_connection.run_async(register_vector_async)
```

**IMPORTANT CORRECTION (HIGH confidence):** The above pattern from pgvector-python README only works with psycopg as the driver, NOT asyncpg. asyncpg has its own type registration system. For asyncpg, the Vector column type from `pgvector.sqlalchemy` handles serialization/deserialization transparently via SQLAlchemy's type system -- no manual registration needed. The `Vector` mapped column type handles encoding/decoding Python lists to PostgreSQL vector format at the SQLAlchemy layer, not the driver layer.

**Verified approach for asyncpg:**
```python
from pgvector.sqlalchemy import Vector
# Just use Vector(1024) in your model definition
# asyncpg handles the binary protocol; pgvector.sqlalchemy handles type mapping
# No event hooks needed when using asyncpg
```

### Pattern 4: Memgraph Cypher Syntax Adaptation

**What:** Rewrite 9 Neo4j schema init queries for Memgraph's Cypher dialect.
**When to use:** `memgraph_queries.py` replacing `cypher_queries.py`.

```python
# Neo4j syntax (current):
"CREATE CONSTRAINT fact_id_unique IF NOT EXISTS "
"FOR (f:Fact) REQUIRE f.fact_id IS UNIQUE"

# Memgraph syntax (new):
"CREATE CONSTRAINT ON (f:Fact) ASSERT f.fact_id IS UNIQUE;"

# Neo4j index syntax (current):
"CREATE INDEX fact_investigation IF NOT EXISTS "
"FOR (f:Fact) ON (f.investigation_id)"

# Memgraph index syntax (new):
"CREATE INDEX ON :Fact(investigation_id);"

# Neo4j TEXT INDEX (current):
"CREATE TEXT INDEX entity_text_search IF NOT EXISTS "
"FOR (e:Entity) ON (e.name)"

# Memgraph: No TEXT INDEX equivalent. Use label-property index instead:
"CREATE INDEX ON :Entity(name);"

# Neo4j relationship index (current):
"CREATE INDEX rel_weight IF NOT EXISTS "
"FOR ()-[r:CORROBORATES]-() ON (r.weight)"

# Memgraph: No relationship property indexes. Remove this.
# Memgraph does not support indexing relationship properties.

# datetime() -> localDateTime() in MERGE queries:
# Neo4j: n.created_at = datetime()
# Memgraph: n.created_at = localDateTime()
```

### Pattern 5: MAGE Algorithm Invocation

**What:** Call MAGE graph algorithms post-pipeline via raw Cypher.
**When to use:** After graph ingestion completes, via `mage_algorithms.py`.

```python
# Source: Memgraph MAGE documentation

# PageRank on full graph
PAGERANK_QUERY = (
    "CALL pagerank.get() "
    "YIELD node, rank "
    "SET node.rank = rank "
    "RETURN count(node) AS nodes_ranked"
)

# PageRank on investigation subgraph
PAGERANK_SUBGRAPH_QUERY = (
    "MATCH p=(n)-[r]-(m) "
    "WHERE n.investigation_id = $investigation_id "
    "WITH project(p) AS subgraph "
    "CALL pagerank.get(subgraph) "
    "YIELD node, rank "
    "SET node.rank = rank "
    "RETURN count(node) AS nodes_ranked"
)

# Community detection (Louvain)
COMMUNITY_DETECTION_QUERY = (
    "CALL community_detection.get() "
    "YIELD node, community_id "
    "SET node.community = community_id "
    "RETURN count(node) AS nodes_assigned"
)

# Betweenness centrality
BETWEENNESS_QUERY = (
    "CALL betweenness_centrality.get(TRUE, TRUE) "
    "YIELD node, betweenness_centrality "
    "SET node.betweenness = betweenness_centrality "
    "RETURN count(node) AS nodes_scored"
)
```

### Pattern 6: Alembic Async Configuration

**What:** Initialize Alembic with async template for asyncpg driver.
**When to use:** One-time setup in `migrations/env.py`.

```bash
# Initialize Alembic with async template
alembic init -t async migrations
```

```python
# migrations/env.py
from sqlalchemy.ext.asyncio import create_async_engine
from osint_system.data_management.models.base import Base

target_metadata = Base.metadata

def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

async def run_async_migrations():
    connectable = create_async_engine(config.get_main_option("sqlalchemy.url"))
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()

def run_migrations_online():
    asyncio.run(run_async_migrations())
```

### Anti-Patterns to Avoid

- **Sharing AsyncSession across tasks:** Each `asyncio.gather()` task MUST have its own session. The stores already use `async with self._lock` -- replace the lock with per-method session creation.
- **Using `expire_on_commit=True` (default):** With async, expired attributes trigger lazy loads which fail outside session scope. Always set `expire_on_commit=False`.
- **MERGE on full patterns in Memgraph:** Same as Neo4j -- MERGE nodes first, then relationships. This is already correct in the existing code.
- **Storing embeddings as Python lists in JSONB:** Use proper `Vector(1024)` column type. JSONB vectors cannot be indexed or searched.
- **Running Alembic autogenerate without all models imported:** The `env.py` must import `Base` from a module that has all models imported, or autogenerate misses tables.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| PostgreSQL connection pooling | Custom pool | SQLAlchemy's built-in pool via `create_async_engine(pool_size=10)` | Handles health checks, reconnection, overflow automatically |
| Vector similarity search | Manual cosine distance SQL | `pgvector.sqlalchemy.Vector` + `.cosine_distance()` operator | Handles index selection, operator class, distance functions |
| Full-text search | LIKE queries or Python string matching | `tsvector` + GIN index + `to_tsquery()` | Orders of magnitude faster; handles stemming, ranking |
| Schema migrations | Raw `ALTER TABLE` scripts | Alembic with `--autogenerate` | Tracks version history, supports rollback, detects drift |
| Embedding generation | Manual tokenization + model inference | `sentence_transformers.SentenceTransformer.encode()` | Handles batching, GPU offload, normalization, truncation |
| Graph algorithm implementation | Custom PageRank/Louvain in Python | MAGE `CALL pagerank.get()` / `community_detection.get()` | C++ implementations orders of magnitude faster; runs in-database |
| JSON-to-Postgres migration | Manual SQL INSERT scripts | SQLAlchemy ORM bulk insert with existing store read methods | Type validation, Pydantic parsing, error handling for free |
| Memgraph driver | Custom Bolt implementation | `neo4j` async driver (already installed) | Same Bolt protocol; works unchanged against Memgraph |

**Key insight:** The existing stores are pure dict-based backends with well-defined async interfaces. The migration is a backend swap, not an API redesign. Every existing test and consumer should work without modification if the method signatures and return types are preserved.

## Common Pitfalls

### Pitfall 1: asyncpg and pgvector Type Registration
**What goes wrong:** Developers try to use the psycopg `register_vector_async` hook with asyncpg and get runtime errors or silently broken vector queries.
**Why it happens:** pgvector-python's README shows psycopg-specific registration. asyncpg uses a different type system.
**How to avoid:** When using asyncpg as the SQLAlchemy driver, rely on `pgvector.sqlalchemy.Vector` column type exclusively. It handles serialization at the SQLAlchemy layer, not the driver layer. Do NOT add psycopg-specific event hooks.
**Warning signs:** `UndefinedFunctionError` or vectors stored as text strings instead of binary.

### Pitfall 2: Memgraph Constraint Syntax
**What goes wrong:** Copy-pasting Neo4j constraint queries causes `SyntaxError` in Memgraph.
**Why it happens:** Neo4j uses `CREATE CONSTRAINT name IF NOT EXISTS FOR (n:Label) REQUIRE n.prop IS UNIQUE`. Memgraph uses `CREATE CONSTRAINT ON (n:Label) ASSERT n.prop IS UNIQUE;`.
**How to avoid:** Rewrite all 9 SCHEMA_INIT_QUERIES using Memgraph syntax. Note: Memgraph has no `IF NOT EXISTS` for constraints -- use try/except to handle already-exists errors. Memgraph also has NO relationship property indexes and NO text indexes.
**Warning signs:** `SyntaxError` on startup; missing `;` at end of Memgraph queries.

### Pitfall 3: Memgraph datetime() vs localDateTime()
**What goes wrong:** Using `datetime()` in MERGE queries works but returns UTC ZonedDateTime which may not match expected format.
**Why it happens:** Memgraph supports `datetime()` (returns ZonedDateTime) and `localDateTime()` (returns LocalDateTime). Neo4j's `datetime()` semantics differ.
**How to avoid:** Use `localDateTime()` consistently in all Cypher queries for Memgraph. The CONTEXT.md already flagged this.
**Warning signs:** Timezone-aware datetime objects where naive datetimes were expected.

### Pitfall 4: Memgraph Index/Constraint Independence
**What goes wrong:** Creating a uniqueness constraint in Memgraph does NOT create an index. Queries remain slow.
**Why it happens:** Neo4j auto-creates backing indexes for constraints. Memgraph does not.
**How to avoid:** Explicitly create label-property indexes for EVERY property that has a constraint AND for every property used in WHERE/ORDER BY clauses. Two statements: one constraint + one index.
**Warning signs:** Full graph scans on MERGE operations; slow `MATCH ... WHERE n.fact_id = $id` queries.

### Pitfall 5: Store Interface Contract Violations
**What goes wrong:** New PostgreSQL-backed stores return SQLAlchemy model objects instead of plain dicts, breaking callers.
**Why it happens:** Laziness -- returning ORM objects instead of converting to the dict format callers expect.
**How to avoid:** Every store method must return the EXACT same dict/list structure as the current in-memory implementation. Add `to_dict()` methods on models. Write interface compliance tests that assert return shapes.
**Warning signs:** `AttributeError` or `KeyError` in pipeline/API code that worked before.

### Pitfall 6: Alembic env.py Missing Model Imports
**What goes wrong:** `alembic revision --autogenerate` generates an empty migration.
**Why it happens:** Alembic only sees models that are imported and registered with `Base.metadata`. If `env.py` imports `Base` but not the individual model modules, their tables are invisible.
**How to avoid:** In `models/__init__.py`, explicitly import all model classes. In `env.py`, import from `models` to trigger registration.
**Warning signs:** Empty `upgrade()` function in generated migrations.

### Pitfall 7: Embedding Model First-Load Latency
**What goes wrong:** First API request after server start takes 10-15 seconds because gte-large-en-v1.5 (1.2GB) loads on demand.
**Why it happens:** sentence-transformers downloads/loads the model on first `encode()` call.
**How to avoid:** Load the model at application startup (in `create_api_app()` lifespan or runner `__init__`). Pre-download the model to a local cache directory.
**Warning signs:** First investigation after restart is dramatically slower than subsequent ones.

### Pitfall 8: tsvector Column + JSONB Interaction
**What goes wrong:** Computed tsvector column references a column that contains JSONB, or the column is nullable, causing `NULL` tsvector values.
**Why it happens:** `to_tsvector('english', claim_text)` fails silently if claim_text is NULL.
**How to avoid:** Use `COALESCE`: `to_tsvector('english', COALESCE(claim_text, ''))`. Ensure the source column is `NOT NULL` or use `COALESCE` in the computed expression.
**Warning signs:** Empty full-text search results despite matching data existing.

### Pitfall 9: Memgraph shortestPath Syntax
**What goes wrong:** Neo4j's `shortestPath()` function call syntax does not work in Memgraph.
**Why it happens:** Memgraph uses built-in BFS traversal syntax instead of a function call.
**How to avoid:** Rewrite `MATCH path = shortestPath((a)-[*..10]-(b))` to use Memgraph BFS: `MATCH path = (a:Entity {entity_id: $from_id})-[*BFS ..10]-(b:Entity {entity_id: $to_id})`.
**Warning signs:** `SyntaxError` or `UndefinedFunction` when calling shortest_path queries.

## Code Examples

### Database Engine Setup

```python
# osint_system/data_management/database.py
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

def create_engine(database_url: str) -> AsyncEngine:
    """Create async PostgreSQL engine with connection pooling."""
    return create_async_engine(
        database_url,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        echo=False,  # Set True for SQL logging during development
    )

def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create async session factory. expire_on_commit=False is critical for async."""
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
```

### Store Migration Example (FactStore)

```python
# Migrated FactStore.save_facts -- same signature, SQLAlchemy backend
async def save_facts(
    self,
    investigation_id: str,
    facts: List[Dict[str, Any]],
    investigation_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    saved_count = 0
    updated_count = 0
    skipped_count = 0

    async with self._session_factory() as session:
        async with session.begin():
            for fact in facts:
                fact_id = fact.get("fact_id")
                if not fact_id:
                    skipped_count += 1
                    continue

                existing = await session.execute(
                    select(FactModel).where(FactModel.fact_id == fact_id)
                )
                if existing.scalar_one_or_none():
                    skipped_count += 1
                    continue

                model = FactModel.from_dict(fact, investigation_id)

                # Generate embedding at extraction time
                if self._embedding_service:
                    model.embedding = await self._embedding_service.embed(
                        fact.get("claim", {}).get("text", "")
                    )

                session.add(model)
                saved_count += 1

        # Commit happens automatically when exiting session.begin()

    return {
        "saved": saved_count,
        "updated": updated_count,
        "skipped": skipped_count,
        "total": saved_count,  # Query count if needed
    }
```

### Embedding Service

```python
# osint_system/data_management/embeddings.py
import asyncio
from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer

class EmbeddingService:
    """Local embedding generation using gte-large-en-v1.5 on GPU."""

    def __init__(self, model_name: str = "Alibaba-NLP/gte-large-en-v1.5"):
        self._model = SentenceTransformer(model_name, trust_remote_code=True)
        # Move to GPU if available
        self._model.to("cuda" if self._model.device.type != "cuda" else "cuda")

    async def embed(self, text: str) -> list[float]:
        """Embed a single text string. Returns 1024-dim vector."""
        loop = asyncio.get_running_loop()
        vector = await loop.run_in_executor(
            None,
            lambda: self._model.encode(
                text, normalize_embeddings=True
            ).tolist(),
        )
        return vector

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts. Batched for GPU efficiency."""
        loop = asyncio.get_running_loop()
        vectors = await loop.run_in_executor(
            None,
            lambda: self._model.encode(
                texts, normalize_embeddings=True, batch_size=32
            ).tolist(),
        )
        return vectors
```

### Docker Compose

```yaml
# docker-compose.yml
services:
  postgres:
    image: pgvector/pgvector:pg17
    environment:
      POSTGRES_USER: osint
      POSTGRES_PASSWORD: osint_dev_password
      POSTGRES_DB: osint
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./init.sql:/docker-entrypoint-initdb.d/init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U osint"]
      interval: 5s
      timeout: 5s
      retries: 5

  memgraph:
    image: memgraph/memgraph-mage
    ports:
      - "7687:7687"
      - "7444:7444"
    volumes:
      - mgdata:/var/lib/memgraph
    command: ["--bolt-server-name-for-init=Neo4j/5.2.0"]
    # Note: --bolt-server-name-for-init not needed for Memgraph >= 2.11
    # but harmless to include for compatibility with older neo4j drivers

volumes:
  pgdata:
  mgdata:
```

```sql
-- init.sql (mounted into PostgreSQL container)
CREATE EXTENSION IF NOT EXISTS vector;
```

### Memgraph Schema Init Queries (Adapted from Neo4j)

```python
# osint_system/data_management/graph/memgraph_queries.py

SCHEMA_INIT_QUERIES: list[str] = [
    # Uniqueness constraints (Memgraph syntax: ASSERT ... IS UNIQUE)
    "CREATE CONSTRAINT ON (f:Fact) ASSERT f.fact_id IS UNIQUE;",
    "CREATE CONSTRAINT ON (e:Entity) ASSERT e.entity_id IS UNIQUE;",
    "CREATE CONSTRAINT ON (s:Source) ASSERT s.source_id IS UNIQUE;",
    "CREATE CONSTRAINT ON (i:Investigation) ASSERT i.investigation_id IS UNIQUE;",
    # Label-property indexes (must be created separately -- Memgraph
    # does NOT auto-create indexes for constraints)
    "CREATE INDEX ON :Fact(fact_id);",
    "CREATE INDEX ON :Entity(entity_id);",
    "CREATE INDEX ON :Source(source_id);",
    "CREATE INDEX ON :Investigation(investigation_id);",
    # Additional indexes for common filters
    "CREATE INDEX ON :Fact(investigation_id);",
    "CREATE INDEX ON :Entity(entity_type);",
    "CREATE INDEX ON :Entity(canonical);",
    "CREATE INDEX ON :Entity(name);",
    "CREATE INDEX ON :Fact(temporal_value);",
    # Note: Memgraph does NOT support relationship property indexes.
    # The Neo4j rel_weight index on CORROBORATES.weight is dropped.
    # Note: Memgraph does NOT support TEXT indexes.
    # Entity name search uses standard label-property index.
]

# MERGE queries -- same as Neo4j but datetime() -> localDateTime()
MERGE_NODE: str = (
    "MERGE (n:{label} {{{key_property}: $key_value}}) "
    "ON CREATE SET n += $props, n.created_at = localDateTime() "
    "ON MATCH SET n += $props, n.updated_at = localDateTime() "
    "RETURN n.{key_property} AS node_key"
)

# shortestPath -- Memgraph BFS syntax
QUERY_SHORTEST_PATH: str = (
    "MATCH path = "
    "(a:Entity {{entity_id: $from_id}})"
    "-[*BFS ..10]-"
    "(b:Entity {{entity_id: $to_id}}) "
    "RETURN path"
)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| pgvector IVFFlat index | HNSW index | pgvector 0.5.0 (2023) | HNSW is default choice for <1M vectors; no rebuild on data change |
| `ankane/pgvector` Docker | `pgvector/pgvector` Docker | pgvector 0.6.0 (2024) | Official maintained image; use `pgvector/pgvector:pg17` |
| `memgraph/memgraph-platform` (all-in-one) | `memgraph/memgraph-mage` (DB+MAGE) | Memgraph 2.15 (2024) | Platform image deprecated; use memgraph-mage + separate Lab container |
| Neo4j `datetime()` | Memgraph `localDateTime()` | Memgraph 2.19 (2025) | Timezone handling changed in 2.19; `localDateTime()` uses DB timezone |
| SQLAlchemy 1.x async workarounds | SQLAlchemy 2.0 native async | SQLAlchemy 2.0 (2023) | First-class `AsyncSession`, `async_sessionmaker`, `mapped_column` |
| Manual `alembic init` + async hacks | `alembic init -t async` | Alembic 1.12 (2023) | Official async template; no custom event loop management needed |

**Deprecated/outdated:**
- `ankane/pgvector` Docker image: use `pgvector/pgvector` instead
- `memgraph/memgraph-platform`: deprecated since v2.15, use `memgraph/memgraph-mage`
- Neo4j's `datetime()` in Memgraph queries: use `localDateTime()` for Memgraph 2.19+
- IVFFlat indexes for dynamic data: use HNSW (no rebuild required on insert)

## Open Questions

1. **Memgraph `IF NOT EXISTS` for constraints**
   - What we know: Memgraph does not support `IF NOT EXISTS` on constraints. Attempting to create a duplicate constraint raises an error.
   - What's unclear: Whether the error is a specific exception type we can catch, or a generic `DatabaseError`.
   - Recommendation: Wrap each constraint creation in try/except during `initialize()`. Log and continue on already-exists errors. Test empirically on first implementation.

2. **pgvector Vector type with asyncpg binary format**
   - What we know: `pgvector.sqlalchemy.Vector` handles type mapping at the SQLAlchemy level. asyncpg uses binary protocol.
   - What's unclear: Whether asyncpg needs explicit type codec registration for `vector` type or if SQLAlchemy's type adapter handles it completely.
   - Recommendation: Test with a simple model first. If asyncpg throws `UndefinedType`, may need `await conn.set_type_codec()` for the vector OID. Fall back to psycopg3 async driver if asyncpg proves incompatible.

3. **MAGE subgraph projection syntax for investigation-scoped algorithms**
   - What we know: MAGE supports `project(p)` to create subgraph projections. PageRank accepts optional subgraph as first arg.
   - What's unclear: Whether `project(p)` works reliably with complex path patterns or only simple label matches. Documentation examples are basic.
   - Recommendation: Test with simple full-graph calls first. Add investigation-scoped `project()` calls as enhancement if needed. Full-graph PageRank is acceptable for initial implementation since investigations don't share nodes.

4. **Memgraph BFS shortest path vs Neo4j shortestPath return format**
   - What we know: Neo4j's `shortestPath()` returns a Path object with `.nodes` and `.relationships`. Memgraph's BFS also returns paths.
   - What's unclear: Whether the Memgraph path object has identical structure (`.nodes`, `.relationships`) via the neo4j Python driver.
   - Recommendation: The neo4j Python driver parses Bolt protocol path objects identically regardless of backend. The `_extract_paths()` helper should work unchanged. Validate empirically.

## Sources

### Primary (HIGH confidence)
- [SQLAlchemy 2.0 Async Documentation](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html) - AsyncSession, async_sessionmaker, engine creation
- [pgvector-python GitHub](https://github.com/pgvector/pgvector-python) - Vector type, HNSW index, SQLAlchemy integration
- [Memgraph Cypher Differences](https://memgraph.com/docs/querying/differences-in-cypher-implementations) - Constraint, index, and function syntax differences
- [Memgraph Python Client Docs](https://memgraph.com/docs/client-libraries/python) - Neo4j driver compatibility, Bolt protocol, auth
- [Memgraph Constraints](https://memgraph.com/docs/fundamentals/constraints) - CREATE CONSTRAINT ASSERT syntax
- [Memgraph Indexes](https://memgraph.com/docs/fundamentals/indexes) - CREATE INDEX ON syntax
- [Memgraph MAGE Run Algorithms](https://memgraph.com/docs/advanced-algorithms/run-algorithms) - CALL syntax, project(), YIELD/SET
- [Alembic Async Cookbook](https://alembic.sqlalchemy.org/en/latest/cookbook.html) - Async migration setup pattern
- [Alibaba-NLP/gte-large-en-v1.5 on HuggingFace](https://huggingface.co/Alibaba-NLP/gte-large-en-v1.5) - Model specs, sentence-transformers usage

### Secondary (MEDIUM confidence)
- [pgvector HNSW vs IVFFlat study](https://medium.com/@bavalpreetsinghh/pgvector-hnsw-vs-ivfflat-a-comprehensive-study-21ce0aaab931) - Index selection for dataset sizes
- [asyncpg vs psycopg3 benchmarks](https://fernandoarteaga.dev/blog/psycopg-vs-asyncpg/) - Driver performance comparison
- [Memgraph Docker Install](https://memgraph.com/docs/getting-started/install-memgraph/docker) - Docker image names, versions
- [pgvector/pgvector Docker Hub](https://hub.docker.com/r/pgvector/pgvector) - Official Docker image for PostgreSQL+pgvector

### Tertiary (LOW confidence)
- [Memgraph localDateTime forum post](https://discourse.memgraph.com/t/support-for-datetime-function-in-cypher/327) - datetime vs localDateTime behavior changes
- [SQLAlchemy tsvector blog posts](https://hamon.in/blog/sqlalchemy-and-full-text-searching-in-postgresql/) - Computed tsvector column patterns

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries are mature, well-documented, and verified against official sources
- Architecture: HIGH - Patterns are directly from official SQLAlchemy 2.0 and pgvector documentation
- Memgraph migration: HIGH - Cypher differences verified against official Memgraph docs; 9 queries are small, well-defined scope
- Pitfalls: HIGH - Drawn from official docs, community discussions, and codebase analysis
- pgvector + asyncpg integration: MEDIUM - Official examples show psycopg; asyncpg integration works via SQLAlchemy type system but needs empirical validation
- MAGE subgraph projection: MEDIUM - Documentation exists but examples are simple; complex patterns untested

**Research date:** 2026-03-22
**Valid until:** 2026-04-22 (30 days -- all components are stable releases)
