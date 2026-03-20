"""Hybrid rule-based and LLM relationship extraction.

Derives semantic edges from existing metadata (cheap, rule-based) and optional
LLM analysis (expensive, config-gated). Rule-based extraction handles ~8 edge
types from verification, classification, and fact relationship data. LLM-based
extraction handles CAUSES, PRECEDES, ATTRIBUTED_TO edges that can't be derived
from metadata alone.

Rule-based extraction is always performed. LLM extraction only runs when
``config.llm_relationship_extraction`` is True.

Cross-investigation entity detection finds entities with matching canonical names
in other investigations and flags them as ``cross_investigation=True`` edges.

Usage:
    from osint_system.agents.sifters.graph import RelationshipExtractor
    from osint_system.config.graph_config import GraphConfig

    config = GraphConfig(llm_relationship_extraction=False)
    extractor = RelationshipExtractor(config=config)

    edges = extractor.extract_relationships(
        fact, verification, existing_facts, "inv-123"
    )
"""

import json
from typing import Any, Optional

import structlog

from osint_system.config.graph_config import GraphConfig
from osint_system.data_management.graph.schema import (
    EdgeType,
    GraphEdge,
    compute_edge_weight,
)
from osint_system.data_management.schemas.entity_schema import EntityType
from osint_system.data_management.schemas.fact_schema import ExtractedFact
from osint_system.data_management.schemas.verification_schema import (
    VerificationResult,
    VerificationStatus,
)

logger = structlog.get_logger().bind(component="RelationshipExtractor")


class RelationshipExtractor:
    """Hybrid rule-based and LLM relationship extractor.

    Rule-based extraction derives edges from existing metadata (verification
    results, fact relationships, entity co-occurrence). LLM-based extraction
    derives CAUSES, PRECEDES, ATTRIBUTED_TO edges from claim text analysis.

    LLM extraction is gated behind ``config.llm_relationship_extraction``.
    When disabled, only rule-based edges are produced. When the LLM call fails
    (rate limit, unavailable), graceful degradation returns an empty list.

    Attributes:
        config: GraphConfig controlling LLM extraction gate.
    """

    def __init__(self, config: GraphConfig) -> None:
        """Initialize RelationshipExtractor.

        Args:
            config: Graph configuration. Controls llm_relationship_extraction gate.
        """
        self.config = config

    def extract_relationships(
        self,
        fact: ExtractedFact,
        verification: Optional[VerificationResult],
        existing_facts: list[ExtractedFact],
        investigation_id: str,
    ) -> list[GraphEdge]:
        """Extract all relationships for a fact.

        Calls rule-based extraction first (always). If LLM extraction is enabled,
        calls LLM extraction second. Deduplicates edges where same source+target+type
        appear from both methods, keeping the edge with higher weight.

        Args:
            fact: The fact to extract relationships for.
            verification: Optional verification result for this fact.
            existing_facts: Other facts in the investigation for relationship detection.
            investigation_id: Investigation scope.

        Returns:
            Deduplicated list of GraphEdge objects.
        """
        edges = self._extract_rule_based(
            fact, verification, existing_facts, investigation_id
        )

        if self.config.llm_relationship_extraction:
            llm_edges = self._extract_llm_based(
                fact, existing_facts, investigation_id
            )
            edges.extend(llm_edges)

        deduped = self._deduplicate_edges(edges)
        logger.debug(
            "relationships_extracted",
            fact_id=fact.fact_id,
            rule_based=len(edges) - (len(edges) - len(deduped)),
            total=len(deduped),
            llm_enabled=self.config.llm_relationship_extraction,
        )
        return deduped

    def _extract_rule_based(
        self,
        fact: ExtractedFact,
        verification: Optional[VerificationResult],
        existing_facts: list[ExtractedFact],
        investigation_id: str,
    ) -> list[GraphEdge]:
        """Extract edges from existing metadata without LLM calls.

        Handles:
        - CORROBORATES: From verification supporting evidence
        - CONTRADICTS: From verification refuting evidence or fact relationships
        - SUPERSEDES: From SUPERSEDED verification with temporal contradiction
        - RELATED_TO: From fact.relationships (supports, elaborates)
        - LOCATED_AT: From entity co-occurrence (PERSON/ORG + LOCATION)

        MENTIONS, SOURCED_FROM, PART_OF are handled by FactMapper (not here).

        Args:
            fact: The fact to extract relationships for.
            verification: Optional verification result.
            existing_facts: Other facts for cross-referencing.
            investigation_id: Investigation scope.

        Returns:
            List of rule-based GraphEdge objects.
        """
        edges: list[GraphEdge] = []
        fact_node_id = f"Fact:{fact.fact_id}"

        # --- CORROBORATES ---
        if verification is not None and verification.status == VerificationStatus.CONFIRMED:
            if len(verification.supporting_evidence) >= 2:
                # Find existing facts with same content_hash or matching claim text
                for other in existing_facts:
                    if other.fact_id == fact.fact_id:
                        continue
                    if (
                        other.content_hash == fact.content_hash
                        or other.claim.text == fact.claim.text
                    ):
                        # Weight from authority score of supporting evidence
                        avg_authority = sum(
                            e.authority_score
                            for e in verification.supporting_evidence
                        ) / len(verification.supporting_evidence)
                        weight = compute_edge_weight(
                            evidence_count=len(verification.supporting_evidence),
                            authority_score=avg_authority,
                            recency_days=0,
                        )
                        edges.append(
                            GraphEdge(
                                source_id=fact_node_id,
                                target_id=f"Fact:{other.fact_id}",
                                edge_type=EdgeType.CORROBORATES,
                                weight=weight,
                                properties={
                                    "evidence_count": len(
                                        verification.supporting_evidence
                                    ),
                                    "source": "rule_based",
                                },
                            )
                        )

        # --- CONTRADICTS ---
        if verification is not None and verification.status == VerificationStatus.REFUTED:
            if verification.refuting_evidence:
                # If related_fact_id is set, link directly
                if verification.related_fact_id:
                    avg_authority = sum(
                        e.authority_score for e in verification.refuting_evidence
                    ) / len(verification.refuting_evidence)
                    weight = compute_edge_weight(
                        evidence_count=len(verification.refuting_evidence),
                        authority_score=avg_authority,
                        recency_days=0,
                    )
                    edges.append(
                        GraphEdge(
                            source_id=fact_node_id,
                            target_id=f"Fact:{verification.related_fact_id}",
                            edge_type=EdgeType.CONTRADICTS,
                            weight=weight,
                            properties={
                                "evidence_count": len(
                                    verification.refuting_evidence
                                ),
                                "source": "rule_based",
                                "contradiction_type": verification.contradiction_type
                                or "unknown",
                            },
                        )
                    )

        # Also handle explicit contradicts relationships from fact schema
        for rel in fact.relationships:
            if rel.type == "contradicts":
                edges.append(
                    GraphEdge(
                        source_id=fact_node_id,
                        target_id=f"Fact:{rel.target_fact_id}",
                        edge_type=EdgeType.CONTRADICTS,
                        weight=rel.confidence,
                        properties={"source": "fact_relationship"},
                    )
                )

        # --- SUPERSEDES ---
        if (
            verification is not None
            and verification.status == VerificationStatus.SUPERSEDED
            and verification.contradiction_type == "temporal"
            and verification.related_fact_id
        ):
            edges.append(
                GraphEdge(
                    source_id=fact_node_id,
                    target_id=f"Fact:{verification.related_fact_id}",
                    edge_type=EdgeType.SUPERSEDES,
                    weight=0.9,
                    properties={
                        "contradiction_type": "temporal",
                        "source": "rule_based",
                    },
                )
            )

        # --- RELATED_TO from fact.relationships (supports, elaborates) ---
        for rel in fact.relationships:
            if rel.type in ("supports", "elaborates"):
                edges.append(
                    GraphEdge(
                        source_id=fact_node_id,
                        target_id=f"Fact:{rel.target_fact_id}",
                        edge_type=EdgeType.RELATED_TO,
                        weight=rel.confidence,
                        properties={
                            "relationship_type": rel.type,
                            "source": "fact_relationship",
                        },
                    )
                )

        # --- LOCATED_AT from entity co-occurrence ---
        locations = [
            e for e in fact.entities if e.type == EntityType.LOCATION
        ]
        actors = [
            e
            for e in fact.entities
            if e.type in (EntityType.PERSON, EntityType.ORGANIZATION)
        ]

        if locations and actors:
            # Weight based on claim_type
            weight = 0.8 if fact.claim.claim_type == "state" else 0.7
            for actor in actors:
                actor_canonical = actor.canonical or actor.text
                actor_id = f"Entity:{investigation_id}:{actor_canonical}"
                for location in locations:
                    loc_canonical = location.canonical or location.text
                    loc_id = f"Entity:{investigation_id}:{loc_canonical}"
                    edges.append(
                        GraphEdge(
                            source_id=actor_id,
                            target_id=loc_id,
                            edge_type=EdgeType.LOCATED_AT,
                            weight=weight,
                            properties={
                                "claim_type": fact.claim.claim_type,
                                "fact_id": fact.fact_id,
                                "source": "entity_cooccurrence",
                            },
                        )
                    )

        return edges

    def _extract_llm_based(
        self,
        fact: ExtractedFact,
        existing_facts: list[ExtractedFact],
        investigation_id: str,
    ) -> list[GraphEdge]:
        """Extract CAUSES, PRECEDES, ATTRIBUTED_TO edges via LLM analysis.

        Builds a prompt with the fact's claim text and nearby facts (those sharing
        entities or in the same investigation), then asks Gemini Flash to identify
        causal, temporal, and complex attribution relationships.

        LLM-inferred edges use a lower base weight (0.4) since they are less
        certain than metadata-derived edges.

        If the LLM call fails (rate limit, unavailable), logs a warning and
        returns an empty list (graceful degradation).

        Args:
            fact: The fact to analyze.
            existing_facts: Nearby facts for context.
            investigation_id: Investigation scope.

        Returns:
            List of LLM-derived GraphEdge objects, or empty list on failure.
        """
        # Find nearby facts (those sharing entities with this fact)
        fact_entity_canonicals = {
            (e.canonical or e.text) for e in fact.entities
        }
        nearby_facts = []
        for other in existing_facts:
            if other.fact_id == fact.fact_id:
                continue
            other_canonicals = {
                (e.canonical or e.text) for e in other.entities
            }
            if fact_entity_canonicals & other_canonicals:
                nearby_facts.append(other)

        if not nearby_facts:
            return []

        # Build prompt
        nearby_texts = "\n".join(
            f"- [{other.fact_id}]: {other.claim.text}"
            for other in nearby_facts[:10]  # Cap at 10 to limit tokens
        )

        prompt = (
            "Analyze the following facts and identify relationships between them.\n\n"
            f"Current fact [{fact.fact_id}]: {fact.claim.text}\n\n"
            f"Related facts:\n{nearby_texts}\n\n"
            "Identify any of these relationships:\n"
            "1. CAUSES: Event A led to/caused Event B\n"
            "2. PRECEDES: Event A happened before Event B (temporal ordering)\n"
            "3. ATTRIBUTED_TO: A claim was attributed to an entity\n\n"
            "Respond in JSON format:\n"
            '{"relationships": [\n'
            '  {"type": "CAUSES|PRECEDES|ATTRIBUTED_TO", '
            '"source_fact_id": "...", "target_fact_id": "...", '
            '"reasoning": "..."}\n'
            "]}\n\n"
            "Only include relationships you are confident about. "
            "Return empty list if none found."
        )

        try:
            # Import lazily to avoid circular imports and hard dependency on Gemini
            from google import genai

            from osint_system.config.settings import settings
            client = genai.Client(api_key=settings.gemini_api_key)
            response = client.models.generate_content(
                model="gemini-3-pro-preview",
                contents=prompt,
                config={
                    "temperature": 0.1,
                    "response_mime_type": "application/json",
                },
            )

            # Parse response
            response_text = response.text.strip()
            data = json.loads(response_text)
            relationships = data.get("relationships", [])

            edges: list[GraphEdge] = []
            valid_fact_ids = {fact.fact_id} | {f.fact_id for f in nearby_facts}

            for rel in relationships:
                rel_type_str = rel.get("type", "")
                source_fid = rel.get("source_fact_id", "")
                target_fid = rel.get("target_fact_id", "")

                # Validate
                if source_fid not in valid_fact_ids or target_fid not in valid_fact_ids:
                    continue

                edge_type_map = {
                    "CAUSES": EdgeType.CAUSES,
                    "PRECEDES": EdgeType.PRECEDES,
                    "ATTRIBUTED_TO": EdgeType.ATTRIBUTED_TO,
                }
                edge_type = edge_type_map.get(rel_type_str)
                if edge_type is None:
                    continue

                edges.append(
                    GraphEdge(
                        source_id=f"Fact:{source_fid}",
                        target_id=f"Fact:{target_fid}",
                        edge_type=edge_type,
                        weight=0.4,  # Lower weight for LLM-inferred
                        properties={
                            "source": "llm_extraction",
                            "reasoning": rel.get("reasoning", ""),
                        },
                    )
                )

            logger.info(
                "llm_extraction_complete",
                fact_id=fact.fact_id,
                edges_found=len(edges),
            )
            return edges

        except Exception as exc:
            logger.warning(
                "llm_extraction_failed",
                fact_id=fact.fact_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return []

    def extract_cross_investigation(
        self,
        fact: ExtractedFact,
        investigation_id: str,
        other_investigation_entities: dict[str, list[str]],
    ) -> list[GraphEdge]:
        """Detect cross-investigation entity matches.

        Searches for entities in the fact that have matching canonical names in
        other investigations. Creates RELATED_TO edges with ``cross_investigation=True``.

        Uses exact canonical name match only (per RESEARCH.md open question 3).
        Edges are flagged, not auto-trusted (per CONTEXT.md).

        Args:
            fact: The fact whose entities to check.
            investigation_id: This fact's investigation scope.
            other_investigation_entities: Mapping of canonical_name -> list of
                investigation_ids where that entity appears. Typically obtained
                from adapter queries.

        Returns:
            List of cross-investigation RELATED_TO edges.
        """
        edges: list[GraphEdge] = []

        for entity in fact.entities:
            canonical = entity.canonical or entity.text
            if canonical in other_investigation_entities:
                other_inv_ids = other_investigation_entities[canonical]
                for other_inv_id in other_inv_ids:
                    if other_inv_id == investigation_id:
                        continue
                    edges.append(
                        GraphEdge(
                            source_id=f"Entity:{investigation_id}:{canonical}",
                            target_id=f"Entity:{other_inv_id}:{canonical}",
                            edge_type=EdgeType.RELATED_TO,
                            weight=0.6,
                            properties={
                                "match_type": "exact_canonical",
                                "resolution_confidence": 1.0,
                                "source": "cross_investigation_detection",
                            },
                            cross_investigation=True,
                        )
                    )

        if edges:
            logger.info(
                "cross_investigation_detected",
                fact_id=fact.fact_id,
                investigation_id=investigation_id,
                cross_edges=len(edges),
            )
        return edges

    @staticmethod
    def _deduplicate_edges(edges: list[GraphEdge]) -> list[GraphEdge]:
        """Deduplicate edges by (source_id, target_id, edge_type).

        When duplicates exist (e.g., same edge from both rule-based and LLM),
        the edge with the higher weight is kept.

        Args:
            edges: List of edges potentially containing duplicates.

        Returns:
            Deduplicated list, keeping highest-weight edge per key.
        """
        best: dict[tuple[str, str, str], GraphEdge] = {}
        for edge in edges:
            key = (edge.source_id, edge.target_id, edge.edge_type.value)
            if key not in best or edge.weight > best[key].weight:
                best[key] = edge
        return list(best.values())
