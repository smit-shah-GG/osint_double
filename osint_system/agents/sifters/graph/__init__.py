"""Graph mapping and ingestion layer for knowledge graph integration.

Transforms extracted facts, entities, verification results, and classifications
into typed graph nodes and edges. Provides hybrid rule-based and LLM-based
relationship extraction. Event-driven ingestion via MessageBus subscription.

Primary exports:
- GraphIngestor: Event-driven graph ingestion handler. Subscribes to
    verification.complete events and auto-ingests verified facts.
- FactMapper: Converts ExtractedFact + VerificationResult + FactClassification
    into GraphNode/GraphEdge objects with entity resolution.
- RelationshipExtractor: Derives semantic edges from existing metadata (rule-based)
    and LLM analysis (config-gated).

Usage:
    from osint_system.agents.sifters.graph import GraphIngestor, FactMapper, RelationshipExtractor

    # Event-driven ingestion
    ingestor = GraphIngestor(adapter=adapter, fact_store=fs, ...)
    ingestor.register(bus)

    # Manual mapping
    mapper = FactMapper(investigation_id="inv-123")
    nodes, edges = mapper.map_fact(fact, verification, classification)

    extractor = RelationshipExtractor(config=graph_config)
    edges = extractor.extract_relationships(fact, verification, existing_facts, "inv-123")
"""

from osint_system.agents.sifters.graph.fact_mapper import FactMapper
from osint_system.agents.sifters.graph.graph_ingestor import GraphIngestor
from osint_system.agents.sifters.graph.relationship_extractor import (
    RelationshipExtractor,
)

__all__ = [
    "GraphIngestor",
    "FactMapper",
    "RelationshipExtractor",
]
