"""Graph mapping layer for knowledge graph integration.

Transforms extracted facts, entities, verification results, and classifications
into typed graph nodes and edges. Provides hybrid rule-based and LLM-based
relationship extraction.

Primary exports:
- FactMapper: Converts ExtractedFact + VerificationResult + FactClassification
    into GraphNode/GraphEdge objects with entity resolution.
- RelationshipExtractor: Derives semantic edges from existing metadata (rule-based)
    and LLM analysis (config-gated).

Usage:
    from osint_system.agents.sifters.graph import FactMapper, RelationshipExtractor

    mapper = FactMapper(investigation_id="inv-123")
    nodes, edges = mapper.map_fact(fact, verification, classification)

    extractor = RelationshipExtractor(config=graph_config)
    edges = extractor.extract_relationships(fact, verification, existing_facts, "inv-123")
"""

from osint_system.agents.sifters.graph.fact_mapper import FactMapper

__all__ = [
    "FactMapper",
]
