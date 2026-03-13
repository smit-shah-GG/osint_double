# Phase 9: Knowledge Graph Integration - Context

**Gathered:** 2026-03-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Transform verified facts, entities, and their relationships into a queryable Neo4j graph structure. Includes graph persistence, node/edge schema, relationship extraction, and a query interface for Phase 10's Analysis & Reporting Engine. Does NOT include analysis logic, report generation, or dashboard — those are Phase 10.

</domain>

<decisions>
## Implementation Decisions

### Graph technology & persistence
- Neo4j from day one — real graph database, not in-memory
- Docker-compose for dev convenience, with .env override for external instances (NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
- Unified graph across all investigations, every node carries `investigation_id` label — enables cross-investigation queries
- NetworkX fallback adapter for tests/CI — same interface, no Docker dependency in test suite
- Production hard-requires Neo4j

### Node/edge schema
- Everything as first-class nodes: Facts, Entities, Sources, Events, Investigations, Classifications
- Rich semantic edge set (~12-15 types): CORROBORATES, CONTRADICTS, SUPERSEDES, MENTIONS, SOURCED_FROM, PART_OF, CAUSES, PRECEDES, LOCATED_AT, ATTRIBUTED_TO, RELATED_TO, and more as needed
- Edges carry both computed weight (0.0-1.0) AND rich metadata properties (timestamp, evidence_count, source, authority)
- Weight derived from properties (authority score, evidence count, recency)
- Entity resolution: merge into canonical nodes with alias tracking — single node per resolved entity, `aliases` property preserves all name variants, `resolution_confidence` score for merge quality
- Consistent with existing FactConsolidator's entity clustering output

### Relationship extraction
- Hybrid approach: rule-based from existing metadata first (cheap), LLM (Gemini) for semantic relationships rules can't capture (CAUSES, causal chains)
- Relationships extracted at ingestion time — each new fact triggers extraction against nearby nodes
- Direct pairwise relationships only — no multi-hop causal chain inference; chains emerge from graph traversal
- Cross-investigation connections detected automatically but flagged as `cross_investigation` requiring confirmation before influencing analysis

### Query interface & consumers
- Python abstraction layer with escape hatch for raw Cypher queries
- High-level methods for four essential query patterns:
  1. Entity network — connected entities/facts within N hops
  2. Corroboration/contradiction clusters — groups of agreeing/disagreeing facts
  3. Temporal timeline — facts ordered by time for entity/event
  4. Shortest path — connection chain between two entities
- Query results returned as typed Pydantic models (GraphNode, GraphEdge, QueryResult) — consistent with FactStore/VerificationStore
- Event-driven integration via message bus — listen for `verification.complete` events, auto-ingest verified facts

### Claude's Discretion
- Neo4j index strategy and constraint definitions
- Exact Cypher query optimization
- NetworkX adapter implementation details
- Batch ingestion vs single-fact ingestion performance tuning
- Docker-compose configuration specifics
- Weight computation formula from edge properties

</decisions>

<specifics>
## Specific Ideas

- Investigation labels on all nodes enables "zoom out" queries across investigations without restructuring
- Entity `resolution_confidence` mirrors the dubious fact pattern — low confidence merges can be flagged like dubious facts
- Rule-based relationship extraction should leverage existing verification results (CORROBORATES/CONTRADICTS edges from VerificationStore data)
- The `cross_investigation` flag on edges is a first step toward the cross-investigation analysis Phase 10 will build on

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope

</deferred>

---

*Phase: 09-knowledge-graph-integration*
*Context gathered: 2026-03-13*
