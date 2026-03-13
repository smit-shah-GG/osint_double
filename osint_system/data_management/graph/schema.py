"""Graph schema models for knowledge graph layer.

Defines Pydantic models for graph nodes, edges, query results, and the EdgeType
enum for semantic relationship types. These types form the contract between graph
adapters and all consumers (analysis, reporting, API).

Per Phase 9 CONTEXT.md decisions:
- Everything as first-class nodes: Facts, Entities, Sources, Investigations, Classifications
- Rich semantic edge set (~13 types) grouped by category
- Edges carry both computed weight (0.0-1.0) AND rich metadata properties
- Weight derived from authority score, evidence count, recency
- Cross-investigation connections flagged, not auto-trusted

All models use model_config with examples consistent with existing schemas.
"""

import math
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class EdgeType(str, Enum):
    """Semantic relationship types for graph edges.

    Grouped by category for clarity. Each type has a single, unambiguous
    semantic meaning. The graph layer enforces directionality:
    source_id -> target_id follows the natural reading direction.

    Structural relationships (how facts/entities are organized):
        MENTIONS: Fact references an entity. Fact -> Entity.
        SOURCED_FROM: Fact was obtained from a source. Fact -> Source.
        PART_OF: Node belongs to a scope (e.g., Fact -> Investigation).
        HAS_CLASSIFICATION: Fact has a classification record. Fact -> Classification.

    Semantic relationships (what the content means):
        CORROBORATES: Fact supports another fact's claim. Fact -> Fact.
        CONTRADICTS: Fact refutes or conflicts with another. Fact -> Fact.
        RELATED_TO: General semantic connection. Any -> Any.
        ATTRIBUTED_TO: Claim attributed to a source or person. Fact -> Entity|Source.
        CAUSES: Causal relationship between events/facts. Fact -> Fact.

    Temporal relationships (time-ordered connections):
        PRECEDES: Temporal ordering between events. Fact -> Fact.
        SUPERSEDES: Newer information replaces older. Fact -> Fact (new -> old).

    Spatial relationships:
        LOCATED_AT: Entity or event is geographically located. Entity|Fact -> Entity(LOCATION).

    Verification relationships:
        VERIFIED_BY: Fact was verified by evidence from a source. Fact -> Source|Evidence.
    """

    # Structural
    MENTIONS = "MENTIONS"
    SOURCED_FROM = "SOURCED_FROM"
    PART_OF = "PART_OF"
    HAS_CLASSIFICATION = "HAS_CLASSIFICATION"

    # Semantic
    CORROBORATES = "CORROBORATES"
    CONTRADICTS = "CONTRADICTS"
    RELATED_TO = "RELATED_TO"
    ATTRIBUTED_TO = "ATTRIBUTED_TO"
    CAUSES = "CAUSES"

    # Temporal
    PRECEDES = "PRECEDES"
    SUPERSEDES = "SUPERSEDES"

    # Spatial
    LOCATED_AT = "LOCATED_AT"

    # Verification
    VERIFIED_BY = "VERIFIED_BY"


class GraphNode(BaseModel):
    """Typed representation of a graph node.

    Node IDs follow the format ``{label}:{natural_key}`` for global uniqueness
    across node types. Labels correspond to node types: Fact, Entity, Source,
    Investigation, Classification.

    The ``properties`` dict contains all domain-specific attributes. Helper
    properties extract commonly accessed fields without forcing callers to
    dig into the properties dict.

    Attributes:
        id: Unique node key. Format: ``{label}:{natural_key}``
            e.g., ``Fact:fact-uuid-123``, ``Entity:inv-1:Vladimir Putin``.
        label: Node type (Fact, Entity, Source, Investigation, Classification).
        properties: All node properties as a flat dict. Contents vary by label.
    """

    id: str = Field(
        ...,
        description="Unique node key, format: {label}:{natural_key}",
    )
    label: str = Field(
        ...,
        description="Node type: Fact, Entity, Source, Investigation, Classification",
    )
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="All node properties (domain-specific, varies by label)",
    )

    @property
    def investigation_id(self) -> Optional[str]:
        """Extract investigation_id from properties if present."""
        return self.properties.get("investigation_id")

    @property
    def name_or_id(self) -> str:
        """Return a human-readable identifier.

        Prefers ``name`` or ``canonical`` from properties, falls back to the
        node ID. Useful for display and logging.
        """
        return (
            self.properties.get("name")
            or self.properties.get("canonical")
            or self.properties.get("claim_text", "")[:80]
            or self.id
        )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": "Fact:fact-uuid-123",
                    "label": "Fact",
                    "properties": {
                        "fact_id": "fact-uuid-123",
                        "investigation_id": "inv-456",
                        "claim_text": "[E1:Putin] visited [E2:Beijing]",
                        "extraction_confidence": 0.92,
                    },
                },
                {
                    "id": "Entity:inv-456:Vladimir Putin",
                    "label": "Entity",
                    "properties": {
                        "entity_id": "inv-456:Vladimir Putin",
                        "name": "Putin",
                        "canonical": "Vladimir Putin",
                        "entity_type": "PERSON",
                        "investigation_id": "inv-456",
                    },
                },
            ]
        }
    }


class GraphEdge(BaseModel):
    """Typed representation of a directed graph edge.

    Edges carry both a computed weight and rich metadata properties. The weight
    is derived from authority score, evidence count, and recency using
    ``compute_edge_weight()``. The ``cross_investigation`` flag marks edges that
    connect nodes from different investigations -- per CONTEXT.md, these are
    detected automatically but must not be auto-trusted.

    Attributes:
        source_id: Origin node ID (``{label}:{natural_key}`` format).
        target_id: Destination node ID.
        edge_type: Semantic relationship type from EdgeType enum.
        weight: Computed relationship strength (0.0-1.0). Default 0.5.
        properties: Metadata dict (timestamp, evidence_count, authority, source).
        cross_investigation: True if edge connects nodes from different
            investigations. Flagged for review, not automatically trusted.
    """

    source_id: str = Field(..., description="Origin node ID")
    target_id: str = Field(..., description="Destination node ID")
    edge_type: EdgeType = Field(..., description="Semantic relationship type")
    weight: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Relationship strength (0.0=weakest, 1.0=strongest)",
    )
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Edge metadata: timestamp, evidence_count, authority, source",
    )
    cross_investigation: bool = Field(
        default=False,
        description="True if edge connects nodes from different investigations",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "source_id": "Fact:fact-uuid-123",
                    "target_id": "Fact:fact-uuid-456",
                    "edge_type": "CORROBORATES",
                    "weight": 0.85,
                    "properties": {
                        "evidence_count": 3,
                        "authority": 0.9,
                        "source": "verification_loop",
                    },
                    "cross_investigation": False,
                },
                {
                    "source_id": "Fact:fact-uuid-123",
                    "target_id": "Entity:inv-456:Vladimir Putin",
                    "edge_type": "MENTIONS",
                    "weight": 1.0,
                    "properties": {
                        "entity_marker": "E1",
                    },
                    "cross_investigation": False,
                },
            ]
        }
    }


class QueryResult(BaseModel):
    """Typed container for graph query results.

    Returned by all high-level query methods on GraphAdapter. Wraps nodes
    and edges with query metadata (type, timing, counts). Consumers should
    use ``node_count`` and ``edge_count`` properties instead of computing
    lengths directly.

    Attributes:
        nodes: Graph nodes matching the query.
        edges: Graph edges matching the query.
        query_type: Query pattern that produced this result. One of:
            entity_network, corroboration_clusters, timeline, shortest_path, raw.
        metadata: Query parameters, execution timing, and result counts.
    """

    nodes: list[GraphNode] = Field(
        default_factory=list,
        description="Graph nodes matching the query",
    )
    edges: list[GraphEdge] = Field(
        default_factory=list,
        description="Graph edges matching the query",
    )
    query_type: str = Field(
        ...,
        description="Query pattern: entity_network, corroboration_clusters, "
        "timeline, shortest_path, raw",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Query parameters, timing, and result counts",
    )

    @property
    def node_count(self) -> int:
        """Number of nodes in the result set."""
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        """Number of edges in the result set."""
        return len(self.edges)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON/API responses.

        Returns:
            Dict with nodes, edges (as lists of dicts), query_type, metadata,
            and computed counts.
        """
        return {
            "nodes": [node.model_dump() for node in self.nodes],
            "edges": [edge.model_dump() for edge in self.edges],
            "query_type": self.query_type,
            "metadata": self.metadata,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
        }

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "nodes": [
                        {
                            "id": "Entity:inv-1:Vladimir Putin",
                            "label": "Entity",
                            "properties": {
                                "name": "Putin",
                                "canonical": "Vladimir Putin",
                            },
                        }
                    ],
                    "edges": [],
                    "query_type": "entity_network",
                    "metadata": {
                        "entity_id": "inv-1:Vladimir Putin",
                        "max_hops": 2,
                        "execution_ms": 42,
                    },
                }
            ]
        }
    }


def compute_edge_weight(
    evidence_count: int,
    authority_score: float,
    recency_days: int,
    base_weight: float = 0.5,
) -> float:
    """Compute edge weight from relationship properties.

    Formula per RESEARCH.md:
        weight = base + authority_boost + evidence_boost - recency_decay

    Where:
        - authority_boost = authority_score * 0.3 (range: 0.0 to 0.3)
        - evidence_boost = min(0.2, 0.05 * log1p(evidence_count)) (diminishing returns)
        - recency_decay = min(0.2, recency_days / 365 * 0.2) (decays over one year)

    Result is clamped to [0.0, 1.0].

    Args:
        evidence_count: Number of independent evidence items supporting the edge.
        authority_score: Source authority score (0.0-1.0) from credibility scoring.
        recency_days: Days since the most recent evidence was collected.
        base_weight: Starting weight before adjustments. Default 0.5.

    Returns:
        Computed weight clamped to [0.0, 1.0].

    Examples:
        >>> compute_edge_weight(5, 0.9, 30)  # High authority, recent, some evidence
        0.88...
        >>> compute_edge_weight(0, 0.3, 365)  # Low authority, old, no evidence
        0.39...
        >>> compute_edge_weight(100, 1.0, 0)  # Max authority, today, lots of evidence
        1.0
    """
    authority_boost = authority_score * 0.3
    evidence_boost = min(0.2, 0.05 * math.log1p(evidence_count))
    recency_decay = min(0.2, recency_days / 365 * 0.2)
    weight = base_weight + authority_boost + evidence_boost - recency_decay
    return max(0.0, min(1.0, weight))
