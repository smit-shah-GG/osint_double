"""Fact-to-graph node/edge mapping with entity resolution.

Transforms the existing Pydantic data models (ExtractedFact, VerificationResult,
FactClassification) into GraphNode/GraphEdge objects ready for adapter ingestion.

Entity resolution within a mapping session deduplicates entities by canonical name,
producing a single node per resolved entity with alias tracking. Resolution uses
exact canonical match only (per RESEARCH.md open question 3).

Usage:
    mapper = FactMapper(investigation_id="inv-123")
    nodes, edges = mapper.map_fact(fact, verification, classification)

    # Entity resolution works across multiple map_fact calls:
    nodes2, edges2 = mapper.map_fact(another_fact_sharing_entities)

    # Or batch:
    all_nodes, all_edges = mapper.map_facts_batch([(f1, v1, c1), (f2, v2, c2)])
"""

from datetime import datetime, timezone
from typing import Optional

import structlog

from osint_system.data_management.graph.schema import (
    EdgeType,
    GraphEdge,
    GraphNode,
)
from osint_system.data_management.schemas.classification_schema import (
    FactClassification,
)
from osint_system.data_management.schemas.fact_schema import ExtractedFact
from osint_system.data_management.schemas.verification_schema import (
    VerificationResult,
)

logger = structlog.get_logger().bind(component="FactMapper")


class FactMapper:
    """Maps ExtractedFact + optional verification/classification into graph nodes and edges.

    Maintains internal state for entity resolution within a mapping session:
    - ``_entity_canonical_map``: canonical_name -> entity_node_id for cross-fact dedup
    - ``_entity_aliases``: entity_node_id -> set of all text variants seen
    - ``_seen_sources``: source_id set for source node dedup
    - ``_investigation_node_created``: flag to avoid duplicate Investigation nodes

    Entity resolution uses exact canonical name match with resolution_confidence=1.0.
    A single GraphNode is produced per resolved entity; the ``aliases`` property
    preserves all name variants observed across facts.

    Attributes:
        investigation_id: Investigation scope for all produced nodes.
    """

    def __init__(self, investigation_id: str) -> None:
        """Initialize FactMapper for a single investigation.

        Args:
            investigation_id: Investigation scope. All produced nodes carry this.
        """
        self.investigation_id = investigation_id

        # Entity resolution state
        self._entity_canonical_map: dict[str, str] = {}  # canonical -> entity_node_id
        self._entity_aliases: dict[str, set[str]] = {}  # entity_node_id -> text variants
        self._entity_nodes: dict[str, GraphNode] = {}  # entity_node_id -> latest node

        # Source dedup
        self._seen_sources: set[str] = set()

        # Investigation node dedup
        self._investigation_node_created = False

    def map_fact(
        self,
        fact: ExtractedFact,
        verification: Optional[VerificationResult] = None,
        classification: Optional[FactClassification] = None,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Convert a single fact into graph nodes and edges.

        Creates Fact, Entity, Source, and Investigation nodes plus structural
        edges (MENTIONS, SOURCED_FROM, PART_OF). Entity resolution deduplicates
        entities by canonical name across calls on the same FactMapper instance.

        If verification is provided, verification properties are added to the
        Fact node and a VERIFIED_BY edge is created.

        If classification is provided, classification properties are added to
        the Fact node.

        Args:
            fact: The extracted fact to map.
            verification: Optional verification result for this fact.
            classification: Optional classification for this fact.

        Returns:
            Tuple of (nodes, edges) produced for this fact.
        """
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        # --- Fact node ---
        fact_node_id = f"Fact:{fact.fact_id}"
        fact_props: dict = {
            "fact_id": fact.fact_id,
            "investigation_id": self.investigation_id,
            "claim_text": fact.claim.text,
            "assertion_type": fact.claim.assertion_type,
            "claim_type": fact.claim.claim_type,
            "content_hash": fact.content_hash,
            "schema_version": fact.schema_version,
        }

        # Quality metrics
        if fact.quality is not None:
            fact_props["extraction_confidence"] = fact.quality.extraction_confidence
            fact_props["claim_clarity"] = fact.quality.claim_clarity

        # Temporal data
        if fact.temporal is not None:
            fact_props["temporal_value"] = fact.temporal.value
            fact_props["temporal_precision"] = fact.temporal.precision

        # Verification properties
        if verification is not None:
            fact_props["verification_status"] = verification.status.value
            fact_props["final_confidence"] = verification.final_confidence
            fact_props["confidence_boost"] = verification.confidence_boost
            fact_props["verified_at"] = verification.verified_at.isoformat()

        # Classification properties
        if classification is not None:
            fact_props["impact_tier"] = classification.impact_tier.value
            fact_props["dubious_flags"] = [f.value for f in classification.dubious_flags]

        nodes.append(GraphNode(id=fact_node_id, label="Fact", properties=fact_props))

        # --- Entity nodes ---
        for entity in fact.entities:
            canonical = entity.canonical or entity.text
            entity_node_id = self._resolve_entity_id(canonical)
            entity_full_id = f"Entity:{entity_node_id}"

            # Track alias
            if entity_node_id not in self._entity_aliases:
                self._entity_aliases[entity_node_id] = set()
            self._entity_aliases[entity_node_id].add(entity.text)
            if entity.canonical:
                self._entity_aliases[entity_node_id].add(entity.canonical)

            # Only create node if not previously created (or update aliases)
            entity_props: dict = {
                "entity_id": entity_node_id,
                "name": entity.text,
                "canonical": canonical,
                "entity_type": entity.type.value,
                "investigation_id": self.investigation_id,
                "aliases": sorted(self._entity_aliases[entity_node_id]),
                "resolution_confidence": 1.0,  # Exact canonical match
            }
            if entity.cluster_id is not None:
                entity_props["cluster_id"] = entity.cluster_id

            entity_node = GraphNode(
                id=entity_full_id, label="Entity", properties=entity_props
            )
            self._entity_nodes[entity_node_id] = entity_node
            nodes.append(entity_node)

            # MENTIONS edge: Fact -> Entity
            edges.append(
                GraphEdge(
                    source_id=fact_node_id,
                    target_id=entity_full_id,
                    edge_type=EdgeType.MENTIONS,
                    weight=1.0,
                    properties={"entity_marker": entity.id},
                )
            )

        # --- Source node ---
        if fact.provenance is not None:
            source_id = fact.provenance.source_id
            source_full_id = f"Source:{source_id}"

            if source_id not in self._seen_sources:
                self._seen_sources.add(source_id)
                source_props: dict = {
                    "source_id": source_id,
                    "source_type": fact.provenance.source_type.value,
                    "investigation_id": self.investigation_id,
                }
                nodes.append(
                    GraphNode(
                        id=source_full_id, label="Source", properties=source_props
                    )
                )

            # SOURCED_FROM edge: Fact -> Source
            sourced_props: dict = {
                "hop_count": fact.provenance.hop_count,
            }
            if fact.provenance.attribution_phrase:
                sourced_props["attribution_phrase"] = (
                    fact.provenance.attribution_phrase
                )
            edges.append(
                GraphEdge(
                    source_id=fact_node_id,
                    target_id=source_full_id,
                    edge_type=EdgeType.SOURCED_FROM,
                    weight=0.8,
                    properties=sourced_props,
                )
            )

        # --- Investigation node ---
        inv_node_id = f"Investigation:{self.investigation_id}"
        if not self._investigation_node_created:
            self._investigation_node_created = True
            inv_props: dict = {
                "investigation_id": self.investigation_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            nodes.append(
                GraphNode(
                    id=inv_node_id, label="Investigation", properties=inv_props
                )
            )

        # PART_OF edge: Fact -> Investigation
        edges.append(
            GraphEdge(
                source_id=fact_node_id,
                target_id=inv_node_id,
                edge_type=EdgeType.PART_OF,
                weight=1.0,
                properties={},
            )
        )

        # --- VERIFIED_BY edge ---
        if verification is not None:
            edges.append(
                GraphEdge(
                    source_id=fact_node_id,
                    target_id=inv_node_id,
                    edge_type=EdgeType.VERIFIED_BY,
                    weight=0.9,
                    properties={
                        "status": verification.status.value,
                        "final_confidence": verification.final_confidence,
                        "query_attempts": verification.query_attempts,
                    },
                )
            )

        logger.debug(
            "fact_mapped",
            fact_id=fact.fact_id,
            nodes=len(nodes),
            edges=len(edges),
        )
        return nodes, edges

    def map_facts_batch(
        self,
        facts: list[
            tuple[
                ExtractedFact,
                Optional[VerificationResult],
                Optional[FactClassification],
            ]
        ],
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Map multiple facts, aggregating results with shared entity resolution.

        Entity resolution operates across the entire batch since all calls share
        the same ``_entity_canonical_map``.

        Args:
            facts: List of (fact, verification_or_none, classification_or_none) tuples.

        Returns:
            Aggregated (nodes, edges) for the entire batch.
        """
        all_nodes: list[GraphNode] = []
        all_edges: list[GraphEdge] = []

        for fact, verification, classification in facts:
            nodes, edges = self.map_fact(fact, verification, classification)
            all_nodes.extend(nodes)
            all_edges.extend(edges)

        logger.info(
            "batch_mapped",
            fact_count=len(facts),
            total_nodes=len(all_nodes),
            total_edges=len(all_edges),
        )
        return all_nodes, all_edges

    def _resolve_entity_id(self, canonical: str) -> str:
        """Resolve an entity canonical name to a unique entity ID.

        If the canonical name has been seen before in this mapper session,
        returns the existing entity node ID (entity resolution). Otherwise,
        creates a new ID with format ``{investigation_id}:{canonical}``.

        Args:
            canonical: The canonical name for the entity.

        Returns:
            Entity node ID string (without the ``Entity:`` label prefix).
        """
        if canonical in self._entity_canonical_map:
            return self._entity_canonical_map[canonical]

        entity_node_id = f"{self.investigation_id}:{canonical}"
        self._entity_canonical_map[canonical] = entity_node_id
        return entity_node_id
