# Phase 9: Knowledge Graph Integration - Research

**Researched:** 2026-03-13
**Domain:** Graph database (Neo4j), knowledge graph construction, relationship extraction, Python async graph adapter patterns
**Confidence:** HIGH

## Summary

Phase 9 transforms verified facts, entities, and relationships from the existing stores (FactStore, ClassificationStore, VerificationStore) into a queryable Neo4j graph. The decision to use Neo4j from day one is well-supported: the official Python driver (`neo4j` 6.1.0) has native async support (`AsyncGraphDatabase`, `AsyncSession`), the Cypher query language has first-class support for the four required query patterns (entity network, corroboration clusters, timelines, shortest path), and Docker Compose provides trivial local setup.

The primary technical challenges are: (1) designing a graph adapter abstraction (`GraphAdapter` protocol) that cleanly wraps both Neo4j and NetworkX backends for test/CI without Docker, (2) mapping the existing Pydantic-heavy data schemas (ExtractedFact, FactClassification, VerificationResult, Entity, EntityCluster) into graph nodes/edges without data loss, and (3) implementing hybrid rule-based + LLM relationship extraction that triggers at ingestion time without blocking the pipeline.

**Primary recommendation:** Build a `GraphAdapter` Python Protocol with `Neo4jAdapter` and `NetworkXAdapter` implementations. Use UNWIND-based batch MERGE for ingestion performance. Define indexes/constraints at schema init time with IF NOT EXISTS for idempotency. Subscribe to `verification.complete` events on the MessageBus to auto-ingest verified facts.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `neo4j` | 6.1.0 | Official Neo4j Python driver with async support | Official driver, native AsyncGraphDatabase, connection pooling, retry logic |
| `networkx` | 3.x | In-memory graph for tests/CI (no Docker needed) | De facto Python graph library, same node/edge semantics, zero infra dependency |
| `docker` (runtime) | neo4j:2025.x image | Graph database server | Decision locked in CONTEXT.md |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `neo4j-rust-ext` | 6.1.x | Rust-accelerated PackStream encoding/decoding | Optional: 3-10x speedup on heavy read/write, drop-in replacement |
| `pydantic` | 2.x (already installed) | Typed query result models (GraphNode, GraphEdge, QueryResult) | All query returns |
| `structlog` | (already installed) | Structured logging for graph operations | All graph adapter logging |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Raw `neo4j` driver | `neomodel` (OGM) | Neomodel adds ORM overhead, locks schema in Python classes, less control over Cypher. Raw driver is better for knowledge graph with dynamic edge types |
| Raw `neo4j` driver | `py2neo` | py2neo is community-maintained, less active. Official driver is the clear choice |
| NetworkX for tests | Docker neo4j in CI | Adds CI Docker dependency, slower test runs. NetworkX adapter is faster and simpler |

**Installation:**
```bash
uv pip install neo4j>=6.1.0 networkx>=3.0
# Optional performance boost (drop-in, no code changes):
uv pip install neo4j-rust-ext>=6.1.0
```

## Architecture Patterns

### Recommended Project Structure
```
osint_system/
  data_management/
    graph/
      __init__.py              # Exports GraphAdapter, Neo4jAdapter, NetworkXAdapter
      adapter.py               # GraphAdapter Protocol definition
      neo4j_adapter.py         # Neo4j implementation
      networkx_adapter.py      # NetworkX fallback for tests/CI
      schema.py                # Pydantic models: GraphNode, GraphEdge, QueryResult
      cypher_queries.py        # Named Cypher query templates (constants)
  agents/
    sifters/
      graph/
        __init__.py
        fact_mapper.py          # Fact-to-graph mapping logic
        relationship_extractor.py  # Hybrid rule-based + LLM extraction
        graph_ingestor.py       # Event-driven ingestion handler
  config/
    graph_config.py             # Neo4j connection config, edge type registry
docker-compose.yml              # Neo4j service definition (dev)
```

### Pattern 1: GraphAdapter Protocol (Core Abstraction)

**What:** A Python Protocol that defines the graph interface. Both Neo4j and NetworkX implement it. All consumers depend only on the Protocol, never on a concrete backend.

**When to use:** Always. This is the foundational abstraction.

```python
# Source: Verified against neo4j 6.1.0 async API docs
from typing import Protocol, runtime_checkable

@runtime_checkable
class GraphAdapter(Protocol):
    """Graph storage abstraction. Neo4j or NetworkX backends."""

    async def initialize(self) -> None:
        """Create indexes, constraints, schema setup."""
        ...

    async def close(self) -> None:
        """Clean shutdown."""
        ...

    async def merge_node(
        self, label: str, properties: dict, key_property: str = "id"
    ) -> str:
        """MERGE a node by key property. Returns node ID."""
        ...

    async def merge_relationship(
        self, from_id: str, to_id: str, rel_type: str, properties: dict
    ) -> None:
        """MERGE a relationship between two nodes."""
        ...

    async def batch_merge_nodes(
        self, label: str, nodes: list[dict], key_property: str = "id"
    ) -> int:
        """Batch MERGE nodes via UNWIND. Returns count."""
        ...

    async def batch_merge_relationships(
        self, relationships: list[dict]
    ) -> int:
        """Batch MERGE relationships. Returns count."""
        ...

    async def query_entity_network(
        self, entity_id: str, max_hops: int = 2,
        investigation_id: str | None = None
    ) -> "QueryResult":
        """Find connected entities/facts within N hops."""
        ...

    async def query_corroboration_clusters(
        self, investigation_id: str
    ) -> "QueryResult":
        """Find groups of corroborating/contradicting facts."""
        ...

    async def query_timeline(
        self, entity_id: str, investigation_id: str | None = None
    ) -> "QueryResult":
        """Facts ordered by time for an entity."""
        ...

    async def query_shortest_path(
        self, from_entity_id: str, to_entity_id: str,
        investigation_id: str | None = None
    ) -> "QueryResult":
        """Shortest connection path between two entities."""
        ...

    async def execute_cypher(
        self, query: str, parameters: dict | None = None
    ) -> list[dict]:
        """Raw Cypher escape hatch (Neo4j only; NetworkX raises)."""
        ...
```

### Pattern 2: Neo4j Async Driver Lifecycle

**What:** Single AsyncDriver instance, session-per-operation, transaction functions for retry safety.

**When to use:** All Neo4j interactions.

```python
# Source: neo4j.com/docs/api/python-driver/current/async_api.html
from neo4j import AsyncGraphDatabase

class Neo4jAdapter:
    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j"):
        self._driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
        self._database = database

    async def initialize(self) -> None:
        """Create constraints and indexes. Idempotent with IF NOT EXISTS."""
        await self._driver.verify_connectivity()
        async with self._driver.session(database=self._database) as session:
            for query in SCHEMA_INIT_QUERIES:
                await session.run(query)

    async def close(self) -> None:
        await self._driver.close()

    async def batch_merge_nodes(self, label: str, nodes: list[dict], key_property: str = "id") -> int:
        """UNWIND batch MERGE for performance."""
        query = f"""
        UNWIND $nodes AS props
        MERGE (n:{label} {{{key_property}: props.{key_property}}})
        ON CREATE SET n += props, n.created_at = datetime()
        ON MATCH SET n += props, n.updated_at = datetime()
        RETURN count(n) AS count
        """
        records, _, _ = await self._driver.execute_query(
            query, nodes=nodes, database_=self._database
        )
        return records[0]["count"]
```

### Pattern 3: UNWIND Batch Ingestion

**What:** Use UNWIND with parameterized MERGE for bulk node/edge creation. Up to 900x faster than individual transactions.

**When to use:** All multi-record inserts. Batch size 1000-10000 per transaction.

```python
# Source: neo4j.com/docs/python-manual/current/performance/
# Batch facts into graph nodes
async def ingest_facts(self, facts: list[dict]) -> int:
    """Ingest verified facts as graph nodes."""
    BATCH_SIZE = 5000
    total = 0
    for i in range(0, len(facts), BATCH_SIZE):
        batch = facts[i:i + BATCH_SIZE]
        count = await self.adapter.batch_merge_nodes("Fact", batch, key_property="fact_id")
        total += count
    return total
```

### Pattern 4: Schema Initialization (Idempotent)

**What:** CREATE CONSTRAINT/INDEX with IF NOT EXISTS on adapter startup.

**When to use:** Once on adapter initialization, safe to re-run.

```cypher
-- Uniqueness constraints (auto-create backing indexes)
CREATE CONSTRAINT fact_id_unique IF NOT EXISTS
  FOR (f:Fact) REQUIRE f.fact_id IS UNIQUE;

CREATE CONSTRAINT entity_id_unique IF NOT EXISTS
  FOR (e:Entity) REQUIRE e.entity_id IS UNIQUE;

CREATE CONSTRAINT source_id_unique IF NOT EXISTS
  FOR (s:Source) REQUIRE s.source_id IS UNIQUE;

CREATE CONSTRAINT investigation_id_unique IF NOT EXISTS
  FOR (i:Investigation) REQUIRE i.investigation_id IS UNIQUE;

-- Range indexes for common queries
CREATE INDEX fact_investigation IF NOT EXISTS
  FOR (f:Fact) ON (f.investigation_id);

CREATE INDEX entity_type IF NOT EXISTS
  FOR (e:Entity) ON (e.entity_type);

CREATE INDEX entity_canonical IF NOT EXISTS
  FOR (e:Entity) ON (e.canonical);

-- Text index for entity name search
CREATE TEXT INDEX entity_text_search IF NOT EXISTS
  FOR (e:Entity) ON (e.name);

-- Temporal index for timeline queries
CREATE INDEX fact_temporal IF NOT EXISTS
  FOR (f:Fact) ON (f.temporal_value);

-- Relationship index for weight-based queries
CREATE INDEX rel_weight IF NOT EXISTS
  FOR ()-[r:CORROBORATES]-() ON (r.weight);
```

### Pattern 5: Event-Driven Ingestion via MessageBus

**What:** Subscribe to `verification.complete` on the existing MessageBus singleton. When verification completes, auto-ingest the verified fact and its entities/relationships into the graph.

**When to use:** Production pipeline integration.

```python
# Source: Existing MessageBus pattern from osint_system/agents/communication/bus.py
class GraphIngestor:
    def __init__(self, adapter: GraphAdapter, fact_store: FactStore,
                 verification_store: VerificationStore, bus: MessageBus):
        self._adapter = adapter
        self._fact_store = fact_store
        self._verification_store = verification_store
        self._bus = bus

    def register(self) -> None:
        """Subscribe to verification.complete events."""
        self._bus.subscribe_to_pattern(
            "graph_ingestor", "verification.complete",
            self._on_verification_complete
        )

    async def _on_verification_complete(self, message: dict) -> None:
        """Handle verification complete events."""
        payload = message.get("payload", {})
        fact_id = payload.get("fact_id")
        investigation_id = payload.get("investigation_id")
        # Fetch full fact + verification result, map to graph, ingest
        ...
```

### Anti-Patterns to Avoid

- **Individual MERGE per fact:** Use UNWIND batch MERGE. Individual transactions are 900x slower.
- **Creating driver per request:** Driver contains connection pool; create once, reuse forever.
- **Concurrent AsyncSession sharing:** AsyncSession is NOT thread/task-safe. Create one per operation.
- **MERGE on full patterns:** MERGE nodes first, then MERGE relationships separately. Full-pattern MERGE creates duplicates when partial matches exist.
- **Hardcoded Cypher strings everywhere:** Centralize in `cypher_queries.py` as named constants.
- **Missing IF NOT EXISTS on constraints:** Without it, re-running schema init throws errors.
- **Using `neo4j-driver` package:** Deprecated since 6.0. Use `neo4j` package.
- **Skipping database parameter:** Always specify `database_` in `execute_query()` or `database` in `session()` to avoid extra server roundtrip.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Connection pooling | Custom connection manager | `neo4j.AsyncGraphDatabase.driver()` built-in pool | Handles reconnection, load balancing, connection reuse |
| Retry on transient failure | Try/except loops | `session.execute_write()` / `execute_read()` transaction functions | Driver auto-retries on classified retryable errors with backoff |
| Graph traversal algorithms | BFS/DFS in Python | Cypher `shortestPath()`, variable-length patterns `[*1..N]` | Database-native execution, index-aware, orders of magnitude faster |
| Entity deduplication in graph | Python string matching | Cypher `MERGE` with key property + `ON CREATE SET` / `ON MATCH SET` | Atomic, constraint-backed, handles concurrent writes |
| Result serialization | Manual dict building | `neo4j` driver record objects + Pydantic `model_validate()` | Type-safe, handles Neo4j temporal/spatial types |
| Schema migration | Manual Cypher scripts | IF NOT EXISTS on all constraints/indexes | Idempotent, safe to re-run on every startup |
| PackStream encoding | N/A | `neo4j-rust-ext` (optional) | 3-10x speedup, zero code changes, drop-in |

**Key insight:** Neo4j's Cypher language is Turing-complete for graph operations. Any traversal, path-finding, or pattern-matching logic you would write in Python is better expressed as a Cypher query executed server-side where indexes and native storage are leveraged.

## Common Pitfalls

### Pitfall 1: MERGE on Full Patterns Creates Duplicates
**What goes wrong:** `MERGE (a:Entity)-[:MENTIONS]->(b:Fact)` creates duplicate nodes if only one side exists. MERGE treats the entire pattern atomically -- it either matches ALL of it or creates ALL of it.
**Why it happens:** Misunderstanding MERGE semantics. It is not "find or create each piece."
**How to avoid:** Always MERGE nodes independently first, then MERGE the relationship between bound variables.
**Warning signs:** Duplicate nodes appearing in the graph despite using MERGE.

```cypher
-- WRONG: creates duplicate Entity if Fact already exists
MERGE (e:Entity {entity_id: $eid})-[:MENTIONS]->(f:Fact {fact_id: $fid})

-- CORRECT: MERGE nodes separately, then relationship
MERGE (e:Entity {entity_id: $eid})
MERGE (f:Fact {fact_id: $fid})
MERGE (e)-[:MENTIONS]->(f)
```

### Pitfall 2: AsyncSession Sharing Across Tasks
**What goes wrong:** Multiple `asyncio.Task`s share one `AsyncSession`, causing race conditions and protocol errors.
**Why it happens:** Unlike the sync driver (thread-safe), async sessions are NOT task-safe.
**How to avoid:** Create a new `AsyncSession` per concurrent operation. Sessions are cheap.
**Warning signs:** `BrokenPipeError`, `IncompleteRead`, or `SessionError` under concurrent load.

### Pitfall 3: Missing Database Parameter
**What goes wrong:** Every query triggers an extra server roundtrip to resolve the default database.
**Why it happens:** The driver doesn't cache the default database resolution.
**How to avoid:** Always pass `database_="neo4j"` to `execute_query()` or `database="neo4j"` to `session()`.
**Warning signs:** Unexplained latency on every query, visible in network traces.

### Pitfall 4: Unbounded Variable-Length Paths
**What goes wrong:** `MATCH p=(a)-[*]->(b)` without bounds explores the entire graph, causing OOM or timeouts.
**Why it happens:** Default max hops is infinity.
**How to avoid:** Always bound variable-length patterns: `[*1..5]`. For entity networks, cap at 2-3 hops.
**Warning signs:** Queries that worked on small test data fail catastrophically on real data.

### Pitfall 5: Not Parameterizing Cypher Queries
**What goes wrong:** String interpolation in Cypher queries bypasses query cache and enables injection.
**Why it happens:** Habit from Python string formatting.
**How to avoid:** Always use `$parameter` syntax. The driver handles escaping and type conversion.
**Warning signs:** Query plan cache misses (visible via EXPLAIN), potential injection vectors.

### Pitfall 6: NetworkX Adapter Semantic Mismatch
**What goes wrong:** NetworkX `MultiDiGraph` does not enforce uniqueness constraints or support Cypher. Tests pass on NetworkX but fail on Neo4j due to duplicate nodes or missing indexes.
**Why it happens:** The adapter is a behavioral subset, not a full semantic equivalent.
**How to avoid:** The NetworkX adapter must manually enforce key-property uniqueness in its MERGE emulation. Integration tests MUST run against real Neo4j (gated behind env var).
**Warning signs:** Tests pass, production fails. Duplicate entities in graph.

### Pitfall 7: Entity Resolution Creating Orphan Relationships
**What goes wrong:** When merging entity aliases into canonical nodes, existing relationships pointing to the old node ID become orphaned.
**Why it happens:** Relationships reference node IDs, not logical keys.
**How to avoid:** Use Cypher to transfer relationships before deleting the merged node:
```cypher
MATCH (old:Entity {entity_id: $old_id})-[r]->(target)
MATCH (canonical:Entity {entity_id: $canonical_id})
CREATE (canonical)-[r2:SAME_TYPE_AS_R]->(target)
SET r2 = properties(r)
DELETE r
```
**Warning signs:** Disconnected subgraphs after entity resolution runs.

## Code Examples

### Complete Node Schema Mapping (Fact -> Graph)
```python
# Source: Mapping from existing ExtractedFact schema to graph nodes
def fact_to_graph_nodes(fact: dict, investigation_id: str) -> tuple[list[dict], list[dict]]:
    """Convert ExtractedFact dict to graph nodes and relationships.

    Returns:
        (nodes, relationships) where each is a list of dicts ready for batch MERGE.
    """
    nodes = []
    relationships = []

    # Fact node
    fact_node = {
        "fact_id": fact["fact_id"],
        "investigation_id": investigation_id,
        "claim_text": fact["claim"]["text"],
        "assertion_type": fact["claim"].get("assertion_type", "statement"),
        "claim_type": fact["claim"].get("claim_type", "event"),
        "content_hash": fact.get("content_hash", ""),
        "extraction_confidence": fact.get("quality", {}).get("extraction_confidence", 0.0),
        "claim_clarity": fact.get("quality", {}).get("claim_clarity", 0.0),
    }
    # Add temporal data if present
    temporal = fact.get("temporal")
    if temporal:
        fact_node["temporal_value"] = temporal.get("value", "")
        fact_node["temporal_precision"] = temporal.get("precision", "")
    nodes.append(("Fact", fact_node))

    # Entity nodes
    for entity in fact.get("entities", []):
        entity_node = {
            "entity_id": f"{investigation_id}:{entity.get('canonical', entity['text'])}",
            "name": entity["text"],
            "canonical": entity.get("canonical", entity["text"]),
            "entity_type": entity["type"],
            "investigation_id": investigation_id,
            "cluster_id": entity.get("cluster_id"),
        }
        nodes.append(("Entity", entity_node))
        # MENTIONS relationship: Fact -> Entity
        relationships.append({
            "from_label": "Fact", "from_key": "fact_id", "from_id": fact["fact_id"],
            "to_label": "Entity", "to_key": "entity_id", "to_id": entity_node["entity_id"],
            "rel_type": "MENTIONS",
            "properties": {"entity_marker": entity["id"]},  # E1, E2, etc.
        })

    # Source node + SOURCED_FROM relationship
    provenance = fact.get("provenance")
    if provenance and isinstance(provenance, dict):
        source_node = {
            "source_id": provenance["source_id"],
            "source_type": provenance.get("source_type", "unknown"),
            "investigation_id": investigation_id,
        }
        nodes.append(("Source", source_node))
        relationships.append({
            "from_label": "Fact", "from_key": "fact_id", "from_id": fact["fact_id"],
            "to_label": "Source", "to_key": "source_id", "to_id": provenance["source_id"],
            "rel_type": "SOURCED_FROM",
            "properties": {
                "hop_count": provenance.get("hop_count", 0),
                "attribution_phrase": provenance.get("attribution_phrase", ""),
            },
        })

    return nodes, relationships
```

### Investigation Node Pattern
```cypher
-- Every ingestion ensures Investigation node exists
MERGE (inv:Investigation {investigation_id: $investigation_id})
ON CREATE SET inv.created_at = datetime()
ON MATCH SET inv.updated_at = datetime()

-- Link facts to investigation
MERGE (f:Fact {fact_id: $fact_id})
MERGE (f)-[:PART_OF]->(inv)
```

### Four Essential Query Patterns

```cypher
-- 1. Entity Network (N-hop neighborhood)
MATCH path = (e:Entity {entity_id: $entity_id})-[*1..2]-(connected)
WHERE $investigation_id IS NULL OR connected.investigation_id = $investigation_id
RETURN path

-- 2. Corroboration/Contradiction Clusters
MATCH (f1:Fact)-[r:CORROBORATES|CONTRADICTS]->(f2:Fact)
WHERE f1.investigation_id = $investigation_id
RETURN f1, r, f2
ORDER BY r.weight DESC

-- 3. Temporal Timeline
MATCH (e:Entity {entity_id: $entity_id})<-[:MENTIONS]-(f:Fact)
WHERE f.temporal_value IS NOT NULL
RETURN f
ORDER BY f.temporal_value ASC

-- 4. Shortest Path
MATCH path = shortestPath(
  (a:Entity {entity_id: $from_id})-[*..10]-(b:Entity {entity_id: $to_id})
)
RETURN path
```

### NetworkX Adapter MERGE Emulation
```python
# Source: Pattern for emulating MERGE semantics in NetworkX
import networkx as nx

class NetworkXAdapter:
    def __init__(self):
        self._graph = nx.MultiDiGraph()
        self._node_index: dict[str, dict] = {}  # key -> node attrs

    async def merge_node(self, label: str, properties: dict, key_property: str = "id") -> str:
        key = f"{label}:{properties[key_property]}"
        if key in self._node_index:
            # ON MATCH: update properties
            self._graph.nodes[key].update(properties)
        else:
            # ON CREATE: add new node
            self._graph.add_node(key, label=label, **properties)
        self._node_index[key] = properties
        return key

    async def merge_relationship(self, from_id: str, to_id: str,
                                  rel_type: str, properties: dict) -> None:
        # Check if relationship already exists
        if self._graph.has_edge(from_id, to_id):
            for key, data in self._graph[from_id][to_id].items():
                if data.get("rel_type") == rel_type:
                    data.update(properties)
                    return
        self._graph.add_edge(from_id, to_id, rel_type=rel_type, **properties)

    async def execute_cypher(self, query: str, parameters: dict | None = None) -> list[dict]:
        raise NotImplementedError(
            "Raw Cypher is not supported by NetworkX adapter. "
            "Use high-level query methods instead."
        )
```

### Docker Compose for Development
```yaml
# docker-compose.yml
services:
  neo4j:
    image: neo4j:2025-community
    ports:
      - "${NEO4J_HTTP_PORT:-7474}:7474"
      - "${NEO4J_BOLT_PORT:-7687}:7687"
    environment:
      - NEO4J_AUTH=${NEO4J_USER:-neo4j}/${NEO4J_PASSWORD:-osint_dev_password}
      - NEO4J_PLUGINS=["apoc"]
      - NEO4J_server_memory_heap_initial__size=256m
      - NEO4J_server_memory_heap_max__size=512m
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
    healthcheck:
      test: ["CMD", "neo4j", "status"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

volumes:
  neo4j_data:
  neo4j_logs:
```

### Weight Computation Formula
```python
def compute_edge_weight(
    evidence_count: int,
    authority_score: float,
    recency_days: int,
    base_weight: float = 0.5
) -> float:
    """Compute edge weight from properties.

    Formula: base + authority_boost + evidence_boost - recency_decay
    Capped at [0.0, 1.0].
    """
    import math
    authority_boost = authority_score * 0.3  # 0.0 to 0.3
    evidence_boost = min(0.2, 0.05 * math.log1p(evidence_count))  # diminishing returns
    recency_decay = min(0.2, recency_days / 365 * 0.2)  # decays over a year
    weight = base_weight + authority_boost + evidence_boost - recency_decay
    return max(0.0, min(1.0, weight))
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `neo4j-driver` package | `neo4j` package (6.x) | 2024 (v6.0) | `neo4j-driver` is deprecated, receives no updates |
| Sync-only driver | Native AsyncGraphDatabase | v5.0+ (2023) | Full asyncio support, no wrapper hacks needed |
| `py2neo` community driver | Official `neo4j` driver | 2022+ | py2neo is largely abandoned, official driver is actively maintained |
| Manual connection management | `execute_query()` convenience method | v5.x+ | Single-line query execution with auto-session/transaction management |
| Pure Python PackStream | `neo4j-rust-ext` optional | v5.14+ | 3-10x encoding/decoding speedup, zero code changes |
| Node key constraints (Enterprise) | Uniqueness constraints (Community) | Always | Community Edition supports uniqueness but not node key (multi-property) constraints |

**Deprecated/outdated:**
- `neo4j-driver` PyPI package: Replaced by `neo4j`. No updates since 6.0.
- `py2neo`: Community driver, largely unmaintained. Use official driver.
- `neomodel` for dynamic schemas: OGM pattern fights knowledge graph flexibility.

## Open Questions

1. **Community vs Enterprise Edition for Constraints**
   - What we know: Community Edition supports uniqueness constraints. Enterprise adds node key constraints (multi-property uniqueness + existence).
   - What's unclear: Whether the project needs multi-property node keys for entity resolution.
   - Recommendation: Start with Community Edition uniqueness constraints. If multi-property keys are needed, the `MERGE` key-property pattern achieves the same behavioral result in application code. Enterprise constraint enforcement is a nice-to-have, not a blocker.

2. **APOC Plugin Availability in Docker**
   - What we know: APOC provides useful procedures (graph refactoring, batch operations, NLP integration). Docker image supports `NEO4J_PLUGINS=["apoc"]` for auto-install.
   - What's unclear: Whether any Phase 9 operations strictly require APOC or if native Cypher suffices.
   - Recommendation: Include APOC in docker-compose for flexibility. Do not depend on it for core operations. Use native Cypher for all essential queries so NetworkX adapter parity is maintained.

3. **Cross-Investigation Entity Matching**
   - What we know: CONTEXT.md specifies cross-investigation connections are detected automatically but flagged as `cross_investigation`.
   - What's unclear: The matching algorithm for identifying the same entity across investigations when canonical names differ.
   - Recommendation: Start with exact canonical name match. Flag as `cross_investigation` with `resolution_confidence` based on string similarity. Defer fuzzy matching to Phase 10 or later.

4. **LLM Cost for Relationship Extraction**
   - What we know: Hybrid approach (rule-based first, LLM for semantic relationships like CAUSES). Gemini Flash is the designated model for high-volume tasks.
   - What's unclear: Cost per fact for LLM-based relationship extraction at scale.
   - Recommendation: Rule-based extraction handles CORROBORATES, CONTRADICTS, SUPERSEDES, MENTIONS, SOURCED_FROM, PART_OF from existing metadata. Only invoke LLM for CAUSES, PRECEDES (temporal), ATTRIBUTED_TO (complex attribution). Gate LLM calls behind a config flag.

## Sources

### Primary (HIGH confidence)
- [Neo4j Python Driver 6.1 Async API](https://neo4j.com/docs/api/python-driver/current/async_api.html) - AsyncGraphDatabase, AsyncSession, AsyncTransaction API
- [Neo4j Python Driver Manual](https://neo4j.com/docs/python-manual/current/) - Driver patterns, concurrency, performance
- [Neo4j Performance Recommendations](https://neo4j.com/docs/python-manual/current/performance/) - UNWIND batching, MERGE vs CREATE, connection pooling
- [Neo4j Concurrency Guide](https://neo4j.com/docs/python-manual/current/concurrency/) - Async patterns, session safety
- [Cypher Index Creation](https://neo4j.com/docs/cypher-manual/current/indexes/search-performance-indexes/create-indexes/) - Range, text, relationship index syntax
- [Cypher MERGE](https://neo4j.com/docs/cypher-manual/current/clauses/merge/) - ON CREATE SET, ON MATCH SET, pattern MERGE pitfalls
- [Neo4j Docker Compose](https://neo4j.com/docs/operations-manual/current/docker/docker-compose-standalone/) - Service configuration, volumes, auth
- [neo4j PyPI](https://pypi.org/project/neo4j/) - v6.1.0, Python >=3.10, async support confirmed

### Secondary (MEDIUM confidence)
- [Neo4j Driver Best Practices Blog](https://neo4j.com/blog/developer/neo4j-driver-best-practices/) - Connection pool sizing, session patterns
- [neo4j-rust-ext](https://pypi.org/project/neo4j-rust-ext/) - Drop-in performance extension, 3-10x measured speedup
- [Neo4j GraphRAG Python](https://neo4j.com/docs/neo4j-graphrag-python/current/) - Entity extraction patterns (reference, not dependency)

### Tertiary (LOW confidence)
- [NetworkX-Neo4j adapter library](https://github.com/neo4j-graph-analytics/networkx-neo4j) - Concept validation for adapter pattern (library itself not needed)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Official Neo4j driver docs verified, version confirmed on PyPI
- Architecture: HIGH - Adapter pattern well-established, async API documented
- Schema/Cypher: HIGH - All Cypher syntax verified against current manual
- Pitfalls: HIGH - Documented in official performance guide and community knowledge base
- Weight formula: MEDIUM - Custom formula, reasonable but needs empirical tuning
- Cross-investigation matching: LOW - No established pattern; application-specific

**Research date:** 2026-03-13
**Valid until:** 2026-04-13 (neo4j driver is stable, monthly releases but API is backward-compatible)
