"""Centralized Cypher query templates for Memgraph graph operations.

All Cypher queries used by MemgraphAdapter are defined here as named constants.
Adapted from cypher_queries.py (Neo4j) with the following syntax changes:

    1. Constraints: ``CREATE CONSTRAINT ON (n:Label) ASSERT n.prop IS UNIQUE;``
       (not Neo4j's FOR/REQUIRE syntax). No ``IF NOT EXISTS`` -- Memgraph does
       not support it; caller must wrap in try/except.
    2. Indexes: ``CREATE INDEX ON :Label(prop);`` (not Neo4j's named index syntax).
       Explicit indexes for ALL constrained properties (Memgraph does NOT
       auto-create backing indexes for constraints -- Pitfall 4 from RESEARCH.md).
    3. No TEXT INDEX (Memgraph doesn't support it) -- use label-property index.
    4. No relationship property indexes (Memgraph doesn't support it).
    5. ``datetime()`` replaced with ``localDateTime()`` in all MERGE queries.
    6. ``shortestPath()`` replaced with BFS traversal syntax (Pitfall 9).

Values always use ``$param`` parameterization for injection safety and query
plan caching. Labels must be injected via validated f-string since Cypher
does not support parameterized labels.

Usage:
    from osint_system.data_management.graph.memgraph_queries import (
        SCHEMA_INIT_QUERIES, MERGE_NODE, BATCH_MERGE_NODES,
    )
"""

# ---------------------------------------------------------------------------
# Schema initialization
# ---------------------------------------------------------------------------
# Memgraph does NOT support IF NOT EXISTS for constraints/indexes.
# The caller (MemgraphAdapter.initialize) must wrap each statement in
# try/except to handle already-exists errors gracefully.

SCHEMA_INIT_QUERIES: list[str] = [
    # Uniqueness constraints (Memgraph ASSERT syntax)
    "CREATE CONSTRAINT ON (f:Fact) ASSERT f.fact_id IS UNIQUE;",
    "CREATE CONSTRAINT ON (e:Entity) ASSERT e.entity_id IS UNIQUE;",
    "CREATE CONSTRAINT ON (s:Source) ASSERT s.source_id IS UNIQUE;",
    "CREATE CONSTRAINT ON (i:Investigation) ASSERT i.investigation_id IS UNIQUE;",
    # Label-property indexes for constrained properties
    # (Memgraph does NOT auto-create backing indexes for constraints)
    "CREATE INDEX ON :Fact(fact_id);",
    "CREATE INDEX ON :Entity(entity_id);",
    "CREATE INDEX ON :Source(source_id);",
    "CREATE INDEX ON :Investigation(investigation_id);",
    # Additional indexes for common query filters
    "CREATE INDEX ON :Fact(investigation_id);",
    "CREATE INDEX ON :Entity(entity_type);",
    "CREATE INDEX ON :Entity(canonical);",
    "CREATE INDEX ON :Entity(name);",
    "CREATE INDEX ON :Fact(temporal_value);",
    # Note: Memgraph does NOT support relationship property indexes.
    # The Neo4j rel_weight index on CORROBORATES.weight is dropped.
    # Note: Memgraph does NOT support TEXT indexes.
    # Entity name search uses standard label-property index above.
]

# ---------------------------------------------------------------------------
# Single node MERGE
# ---------------------------------------------------------------------------

# Label is injected via validated f-string; all values use $params.
# Caller must substitute {label} and {key_property} before execution.
# datetime() -> localDateTime() for Memgraph compatibility.
MERGE_NODE: str = (
    "MERGE (n:{label} {{{key_property}: $key_value}}) "
    "ON CREATE SET n += $props, n.created_at = localDateTime() "
    "ON MATCH SET n += $props, n.updated_at = localDateTime() "
    "RETURN n.{key_property} AS node_key"
)

# ---------------------------------------------------------------------------
# Batch MERGE nodes (UNWIND pattern for performance)
# ---------------------------------------------------------------------------

# Label and key_property are injected via validated f-string.
# $nodes is the parameterized list of property dicts.
BATCH_MERGE_NODES: str = (
    "UNWIND $nodes AS props "
    "MERGE (n:{label} {{{key_property}: props.{key_property}}}) "
    "ON CREATE SET n += props, n.created_at = localDateTime() "
    "ON MATCH SET n += props, n.updated_at = localDateTime() "
    "RETURN count(n) AS count"
)

# ---------------------------------------------------------------------------
# Relationship MERGE (nodes first, then relationship -- Pitfall 1)
# ---------------------------------------------------------------------------

# from_label, from_key, to_label, to_key, rel_type are injected via
# validated f-string. Values use $params.
MERGE_RELATIONSHIP: str = (
    "MERGE (a:{from_label} {{{from_key}: $from_id}}) "
    "MERGE (b:{to_label} {{{to_key}: $to_id}}) "
    "MERGE (a)-[r:{rel_type}]->(b) "
    "ON CREATE SET r += $props, r.created_at = localDateTime() "
    "ON MATCH SET r += $props, r.updated_at = localDateTime()"
)

# ---------------------------------------------------------------------------
# Batch MERGE relationships (UNWIND pattern)
# ---------------------------------------------------------------------------

# from_label, from_key, to_label, to_key, rel_type are injected via
# validated f-string. $rels is the parameterized list of relationship dicts.
BATCH_MERGE_RELATIONSHIPS: str = (
    "UNWIND $rels AS rel "
    "MERGE (a:{from_label} {{{from_key}: rel.from_id}}) "
    "MERGE (b:{to_label} {{{to_key}: rel.to_id}}) "
    "MERGE (a)-[r:{rel_type}]->(b) "
    "ON CREATE SET r += rel.props, r.created_at = localDateTime() "
    "ON MATCH SET r += rel.props, r.updated_at = localDateTime() "
    "RETURN count(r) AS count"
)

# ---------------------------------------------------------------------------
# Delete node (DETACH DELETE)
# ---------------------------------------------------------------------------

# Label and key_property are injected via validated f-string.
DELETE_NODE: str = (
    "MATCH (n:{label} {{{key_property}: $key_value}}) "
    "DETACH DELETE n "
    "RETURN count(n) AS deleted"
)

# ---------------------------------------------------------------------------
# Query templates for four essential patterns
# ---------------------------------------------------------------------------

# 1. Entity network: N-hop neighborhood around an entity.
# max_hops is injected via .format(max_hops=N) since Cypher cannot
# parameterize variable-length path bounds.
# All other values use $params.
QUERY_ENTITY_NETWORK: str = (
    "MATCH path = (e:Entity {{entity_id: $entity_id}})-[*1..{max_hops}]-(connected) "
    "WHERE $investigation_id IS NULL OR connected.investigation_id = $investigation_id "
    "RETURN path"
)

# 2. Corroboration/contradiction clusters within an investigation.
QUERY_CORROBORATION_CLUSTERS: str = (
    "MATCH (f1:Fact)-[r:CORROBORATES|CONTRADICTS]->(f2:Fact) "
    "WHERE f1.investigation_id = $investigation_id "
    "RETURN f1, r, f2 "
    "ORDER BY r.weight DESC"
)

# 3. Temporal timeline for an entity's associated facts.
QUERY_TIMELINE: str = (
    "MATCH (e:Entity {entity_id: $entity_id})<-[:MENTIONS]-(f:Fact) "
    "WHERE f.temporal_value IS NOT NULL "
    "AND ($investigation_id IS NULL OR f.investigation_id = $investigation_id) "
    "RETURN f "
    "ORDER BY f.temporal_value ASC"
)

# 4. Shortest path between two entities (bounded to 10 hops max).
# Memgraph BFS syntax replaces Neo4j's shortestPath() function.
# Per RESEARCH.md Pitfall 9: Memgraph uses built-in BFS traversal.
QUERY_SHORTEST_PATH: str = (
    "MATCH path = "
    "(a:Entity {entity_id: $from_id})"
    "-[*BFS ..10]-"
    "(b:Entity {entity_id: $to_id}) "
    "RETURN path"
)
