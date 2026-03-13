"""Centralized Cypher query templates for Neo4j graph operations.

All Cypher queries used by Neo4jAdapter are defined here as named constants.
Values always use ``$param`` parameterization for injection safety and query
plan caching (Pitfall 5 from RESEARCH.md). Labels must be injected via
validated f-string since Cypher does not support parameterized labels.

Variable-length path bounds (e.g., ``[*1..N]``) cannot be parameterized in
Cypher either, so those use ``.format(max_hops=N)`` with the integer validated
upstream. All other values use ``$param`` syntax exclusively.

Usage:
    from osint_system.data_management.graph.cypher_queries import (
        SCHEMA_INIT_QUERIES, MERGE_NODE, BATCH_MERGE_NODES,
    )
"""

# ---------------------------------------------------------------------------
# Schema initialization (idempotent with IF NOT EXISTS)
# ---------------------------------------------------------------------------

SCHEMA_INIT_QUERIES: list[str] = [
    # Uniqueness constraints (auto-create backing indexes)
    (
        "CREATE CONSTRAINT fact_id_unique IF NOT EXISTS "
        "FOR (f:Fact) REQUIRE f.fact_id IS UNIQUE"
    ),
    (
        "CREATE CONSTRAINT entity_id_unique IF NOT EXISTS "
        "FOR (e:Entity) REQUIRE e.entity_id IS UNIQUE"
    ),
    (
        "CREATE CONSTRAINT source_id_unique IF NOT EXISTS "
        "FOR (s:Source) REQUIRE s.source_id IS UNIQUE"
    ),
    (
        "CREATE CONSTRAINT investigation_id_unique IF NOT EXISTS "
        "FOR (i:Investigation) REQUIRE i.investigation_id IS UNIQUE"
    ),
    # Range indexes for common filters
    (
        "CREATE INDEX fact_investigation IF NOT EXISTS "
        "FOR (f:Fact) ON (f.investigation_id)"
    ),
    (
        "CREATE INDEX entity_type IF NOT EXISTS "
        "FOR (e:Entity) ON (e.entity_type)"
    ),
    (
        "CREATE INDEX entity_canonical IF NOT EXISTS "
        "FOR (e:Entity) ON (e.canonical)"
    ),
    # Text index for entity name search
    (
        "CREATE TEXT INDEX entity_text_search IF NOT EXISTS "
        "FOR (e:Entity) ON (e.name)"
    ),
    # Temporal index for timeline queries
    (
        "CREATE INDEX fact_temporal IF NOT EXISTS "
        "FOR (f:Fact) ON (f.temporal_value)"
    ),
    # Relationship index for weight-based queries on CORROBORATES
    (
        "CREATE INDEX rel_weight IF NOT EXISTS "
        "FOR ()-[r:CORROBORATES]-() ON (r.weight)"
    ),
]

# ---------------------------------------------------------------------------
# Single node MERGE
# ---------------------------------------------------------------------------

# Label is injected via validated f-string; all values use $params.
# Caller must substitute {label} and {key_property} before execution.
MERGE_NODE: str = (
    "MERGE (n:{label} {{{key_property}: $key_value}}) "
    "ON CREATE SET n += $props, n.created_at = datetime() "
    "ON MATCH SET n += $props, n.updated_at = datetime() "
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
    "ON CREATE SET n += props, n.created_at = datetime() "
    "ON MATCH SET n += props, n.updated_at = datetime() "
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
    "ON CREATE SET r += $props, r.created_at = datetime() "
    "ON MATCH SET r += $props, r.updated_at = datetime()"
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
    "ON CREATE SET r += rel.props, r.created_at = datetime() "
    "ON MATCH SET r += rel.props, r.updated_at = datetime() "
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
QUERY_SHORTEST_PATH: str = (
    "MATCH path = shortestPath("
    "(a:Entity {entity_id: $from_id})-[*..10]-(b:Entity {entity_id: $to_id})"
    ") "
    "RETURN path"
)
