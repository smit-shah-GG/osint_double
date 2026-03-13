"""Unit tests for FactMapper graph node/edge mapping.

Tests cover:
- Single fact mapping (nodes, edges, counts)
- Entity resolution (canonical dedup, alias accumulation)
- Missing provenance handling
- Verification property propagation
- Classification property propagation
- Batch mapping with shared entity resolution
- Temporal marker mapping
"""

from datetime import datetime, timezone

import pytest

from osint_system.agents.sifters.graph.fact_mapper import FactMapper
from osint_system.data_management.graph.schema import EdgeType
from osint_system.data_management.schemas.classification_schema import (
    DubiousFlag,
    FactClassification,
    ImpactTier,
)
from osint_system.data_management.schemas.entity_schema import Entity, EntityType
from osint_system.data_management.schemas.fact_schema import (
    Claim,
    ExtractedFact,
    QualityMetrics,
    TemporalMarker,
)
from osint_system.data_management.schemas.provenance_schema import (
    Provenance,
    SourceType,
)
from osint_system.data_management.schemas.verification_schema import (
    VerificationResult,
    VerificationStatus,
)


# --- Fixtures ---


def _make_fact(
    fact_id: str = "fact-001",
    claim_text: str = "[E1:Putin] visited [E2:Beijing]",
    entities: list[Entity] | None = None,
    provenance: Provenance | None = None,
    temporal: TemporalMarker | None = None,
    quality: QualityMetrics | None = None,
) -> ExtractedFact:
    """Build a minimal ExtractedFact for testing."""
    if entities is None:
        entities = [
            Entity(id="E1", text="Putin", type=EntityType.PERSON, canonical="Vladimir Putin"),
            Entity(id="E2", text="Beijing", type=EntityType.LOCATION, canonical="Beijing"),
        ]
    if provenance is None:
        provenance = Provenance(
            source_id="src-reuters-001",
            quote="Putin visited Beijing",
            offsets={"start": 0, "end": 20},
            source_type=SourceType.WIRE_SERVICE,
            hop_count=1,
            attribution_phrase="according to Reuters",
        )
    if quality is None:
        quality = QualityMetrics(extraction_confidence=0.92, claim_clarity=0.88)

    return ExtractedFact(
        fact_id=fact_id,
        claim=Claim(text=claim_text, assertion_type="statement", claim_type="event"),
        entities=entities,
        provenance=provenance,
        temporal=temporal,
        quality=quality,
    )


def _make_verification(
    fact_id: str = "fact-001",
    status: VerificationStatus = VerificationStatus.CONFIRMED,
    original_confidence: float = 0.5,
    confidence_boost: float = 0.3,
) -> VerificationResult:
    """Build a minimal VerificationResult for testing."""
    return VerificationResult(
        fact_id=fact_id,
        investigation_id="inv-test",
        status=status,
        original_confidence=original_confidence,
        confidence_boost=confidence_boost,
        final_confidence=min(1.0, original_confidence + confidence_boost),
        reasoning="Test verification",
    )


def _make_classification(
    fact_id: str = "fact-001",
    impact_tier: ImpactTier = ImpactTier.CRITICAL,
    dubious_flags: list[DubiousFlag] | None = None,
) -> FactClassification:
    """Build a minimal FactClassification for testing."""
    if dubious_flags is None:
        dubious_flags = [DubiousFlag.PHANTOM]
    return FactClassification(
        fact_id=fact_id,
        investigation_id="inv-test",
        impact_tier=impact_tier,
        dubious_flags=dubious_flags,
    )


# --- Tests ---


class TestFactMapperSingleFact:
    """Test mapping a single fact with two entities."""

    def test_single_fact_produces_correct_node_counts(self) -> None:
        """Single fact with 2 entities -> 1 Fact + 2 Entity + 1 Source + 1 Investigation = 5 nodes."""
        mapper = FactMapper(investigation_id="inv-test")
        fact = _make_fact()
        nodes, edges = mapper.map_fact(fact)

        labels = [n.label for n in nodes]
        assert labels.count("Fact") == 1
        assert labels.count("Entity") == 2
        assert labels.count("Source") == 1
        assert labels.count("Investigation") == 1
        assert len(nodes) == 5

    def test_single_fact_produces_correct_edge_counts(self) -> None:
        """2 MENTIONS + 1 SOURCED_FROM + 1 PART_OF = 4 edges."""
        mapper = FactMapper(investigation_id="inv-test")
        fact = _make_fact()
        _, edges = mapper.map_fact(fact)

        edge_types = [e.edge_type for e in edges]
        assert edge_types.count(EdgeType.MENTIONS) == 2
        assert edge_types.count(EdgeType.SOURCED_FROM) == 1
        assert edge_types.count(EdgeType.PART_OF) == 1
        assert len(edges) == 4

    def test_fact_node_properties(self) -> None:
        """Fact node carries all expected properties."""
        mapper = FactMapper(investigation_id="inv-test")
        fact = _make_fact()
        nodes, _ = mapper.map_fact(fact)

        fact_node = next(n for n in nodes if n.label == "Fact")
        props = fact_node.properties
        assert props["fact_id"] == "fact-001"
        assert props["investigation_id"] == "inv-test"
        assert props["claim_text"] == "[E1:Putin] visited [E2:Beijing]"
        assert props["assertion_type"] == "statement"
        assert props["claim_type"] == "event"
        assert props["extraction_confidence"] == 0.92
        assert props["claim_clarity"] == 0.88

    def test_entity_node_properties(self) -> None:
        """Entity nodes carry canonical name, type, and investigation_id."""
        mapper = FactMapper(investigation_id="inv-test")
        fact = _make_fact()
        nodes, _ = mapper.map_fact(fact)

        entity_nodes = [n for n in nodes if n.label == "Entity"]
        canonicals = {n.properties["canonical"] for n in entity_nodes}
        assert "Vladimir Putin" in canonicals
        assert "Beijing" in canonicals

        putin_node = next(n for n in entity_nodes if n.properties["canonical"] == "Vladimir Putin")
        assert putin_node.properties["entity_type"] == "PERSON"
        assert putin_node.properties["investigation_id"] == "inv-test"
        assert putin_node.id == "Entity:inv-test:Vladimir Putin"

    def test_mentions_edge_carries_entity_marker(self) -> None:
        """MENTIONS edges carry the entity marker (E1, E2, etc.)."""
        mapper = FactMapper(investigation_id="inv-test")
        fact = _make_fact()
        _, edges = mapper.map_fact(fact)

        mentions = [e for e in edges if e.edge_type == EdgeType.MENTIONS]
        markers = {e.properties["entity_marker"] for e in mentions}
        assert markers == {"E1", "E2"}

    def test_sourced_from_edge_properties(self) -> None:
        """SOURCED_FROM edge carries hop_count and attribution_phrase."""
        mapper = FactMapper(investigation_id="inv-test")
        fact = _make_fact()
        _, edges = mapper.map_fact(fact)

        sourced = next(e for e in edges if e.edge_type == EdgeType.SOURCED_FROM)
        assert sourced.properties["hop_count"] == 1
        assert sourced.properties["attribution_phrase"] == "according to Reuters"


class TestEntityResolution:
    """Test entity resolution across multiple facts."""

    def test_shared_canonical_resolves_to_single_node_id(self) -> None:
        """Two facts sharing the same entity canonical -> same entity node ID."""
        mapper = FactMapper(investigation_id="inv-test")

        fact1 = _make_fact(
            fact_id="fact-001",
            entities=[Entity(id="E1", text="Putin", type=EntityType.PERSON, canonical="Vladimir Putin")],
        )
        fact2 = _make_fact(
            fact_id="fact-002",
            claim_text="[E1:Russian President] met with officials",
            entities=[Entity(id="E1", text="Russian President", type=EntityType.PERSON, canonical="Vladimir Putin")],
        )

        nodes1, _ = mapper.map_fact(fact1)
        nodes2, _ = mapper.map_fact(fact2)

        entity_ids_1 = {n.id for n in nodes1 if n.label == "Entity"}
        entity_ids_2 = {n.id for n in nodes2 if n.label == "Entity"}
        # Same entity node ID
        assert entity_ids_1 & entity_ids_2 == {"Entity:inv-test:Vladimir Putin"}

    def test_aliases_accumulated_across_facts(self) -> None:
        """Alias set accumulates text variants from all facts."""
        mapper = FactMapper(investigation_id="inv-test")

        fact1 = _make_fact(
            fact_id="fact-001",
            entities=[Entity(id="E1", text="Putin", type=EntityType.PERSON, canonical="Vladimir Putin")],
        )
        fact2 = _make_fact(
            fact_id="fact-002",
            claim_text="[E1:Russian President] met with officials",
            entities=[Entity(id="E1", text="Russian President", type=EntityType.PERSON, canonical="Vladimir Putin")],
        )

        mapper.map_fact(fact1)
        nodes2, _ = mapper.map_fact(fact2)

        entity_node = next(n for n in nodes2 if n.label == "Entity")
        aliases = set(entity_node.properties["aliases"])
        assert "Putin" in aliases
        assert "Russian President" in aliases
        assert "Vladimir Putin" in aliases


class TestMissingProvenance:
    """Test fact without provenance."""

    def test_no_source_node_without_provenance(self) -> None:
        """Fact without provenance -> no Source node, no SOURCED_FROM edge."""
        mapper = FactMapper(investigation_id="inv-test")
        fact = _make_fact(provenance=None)

        # Override provenance to None on the model
        fact_no_prov = fact.model_copy(update={"provenance": None})
        nodes, edges = mapper.map_fact(fact_no_prov)

        labels = [n.label for n in nodes]
        assert "Source" not in labels

        edge_types = [e.edge_type for e in edges]
        assert EdgeType.SOURCED_FROM not in edge_types


class TestVerificationProperties:
    """Test verification property propagation to Fact node."""

    def test_verification_adds_properties_to_fact_node(self) -> None:
        """Fact with verification -> verification properties on Fact node."""
        mapper = FactMapper(investigation_id="inv-test")
        fact = _make_fact()
        verification = _make_verification()
        nodes, _ = mapper.map_fact(fact, verification=verification)

        fact_node = next(n for n in nodes if n.label == "Fact")
        props = fact_node.properties
        assert props["verification_status"] == "confirmed"
        assert props["final_confidence"] == 0.8
        assert props["confidence_boost"] == 0.3

    def test_verification_creates_verified_by_edge(self) -> None:
        """Fact with verification -> VERIFIED_BY edge to Investigation."""
        mapper = FactMapper(investigation_id="inv-test")
        fact = _make_fact()
        verification = _make_verification()
        _, edges = mapper.map_fact(fact, verification=verification)

        verified_edges = [e for e in edges if e.edge_type == EdgeType.VERIFIED_BY]
        assert len(verified_edges) == 1
        assert verified_edges[0].properties["status"] == "confirmed"
        assert verified_edges[0].properties["final_confidence"] == 0.8


class TestClassificationProperties:
    """Test classification property propagation to Fact node."""

    def test_classification_adds_properties_to_fact_node(self) -> None:
        """Fact with classification -> impact_tier and dubious_flags on Fact node."""
        mapper = FactMapper(investigation_id="inv-test")
        fact = _make_fact()
        classification = _make_classification()
        nodes, _ = mapper.map_fact(fact, classification=classification)

        fact_node = next(n for n in nodes if n.label == "Fact")
        props = fact_node.properties
        assert props["impact_tier"] == "critical"
        assert props["dubious_flags"] == ["phantom"]


class TestBatchMapping:
    """Test batch mapping with shared entity resolution."""

    def test_batch_entity_resolution_works_across_facts(self) -> None:
        """Batch mapping shares entity resolution across all facts."""
        mapper = FactMapper(investigation_id="inv-test")

        facts = [
            (
                _make_fact(
                    fact_id="fact-001",
                    entities=[Entity(id="E1", text="Putin", type=EntityType.PERSON, canonical="Vladimir Putin")],
                ),
                None,
                None,
            ),
            (
                _make_fact(
                    fact_id="fact-002",
                    claim_text="[E1:V. Putin] visited Moscow",
                    entities=[
                        Entity(id="E1", text="V. Putin", type=EntityType.PERSON, canonical="Vladimir Putin"),
                        Entity(id="E2", text="Moscow", type=EntityType.LOCATION, canonical="Moscow"),
                    ],
                ),
                None,
                None,
            ),
        ]

        all_nodes, all_edges = mapper.map_facts_batch(facts)

        # Both facts share "Vladimir Putin" -> same entity_id
        putin_nodes = [
            n for n in all_nodes
            if n.label == "Entity" and n.properties["canonical"] == "Vladimir Putin"
        ]
        # Multiple GraphNode objects emitted (one per fact reference), but all share the same ID
        putin_ids = {n.id for n in putin_nodes}
        assert len(putin_ids) == 1
        assert putin_ids == {"Entity:inv-test:Vladimir Putin"}

        # Aliases should include both text variants
        last_putin = putin_nodes[-1]
        aliases = set(last_putin.properties["aliases"])
        assert "Putin" in aliases
        assert "V. Putin" in aliases

    def test_batch_aggregates_nodes_and_edges(self) -> None:
        """Batch returns combined nodes and edges from all facts."""
        mapper = FactMapper(investigation_id="inv-test")

        facts = [
            (_make_fact(fact_id="f1"), None, None),
            (
                _make_fact(
                    fact_id="f2",
                    claim_text="Another claim",
                    entities=[Entity(id="E1", text="Macron", type=EntityType.PERSON, canonical="Emmanuel Macron")],
                ),
                None,
                None,
            ),
        ]

        all_nodes, all_edges = mapper.map_facts_batch(facts)
        # Should have nodes and edges from both facts
        fact_nodes = [n for n in all_nodes if n.label == "Fact"]
        assert len(fact_nodes) == 2
        assert len(all_edges) > 0


class TestTemporalMarker:
    """Test temporal marker property propagation."""

    def test_temporal_value_on_fact_node(self) -> None:
        """Fact with temporal marker -> temporal_value and temporal_precision on Fact node."""
        mapper = FactMapper(investigation_id="inv-test")
        temporal = TemporalMarker(
            id="T1", value="2024-03", precision="month", temporal_precision="explicit"
        )
        fact = _make_fact(temporal=temporal)
        nodes, _ = mapper.map_fact(fact)

        fact_node = next(n for n in nodes if n.label == "Fact")
        assert fact_node.properties["temporal_value"] == "2024-03"
        assert fact_node.properties["temporal_precision"] == "month"

    def test_no_temporal_properties_without_marker(self) -> None:
        """Fact without temporal marker -> no temporal properties on Fact node."""
        mapper = FactMapper(investigation_id="inv-test")
        fact = _make_fact(temporal=None)
        nodes, _ = mapper.map_fact(fact)

        fact_node = next(n for n in nodes if n.label == "Fact")
        assert "temporal_value" not in fact_node.properties
        assert "temporal_precision" not in fact_node.properties


class TestInvestigationNodeDedup:
    """Test that Investigation node is created only once per mapper."""

    def test_investigation_node_created_once(self) -> None:
        """Multiple map_fact calls produce only one Investigation node."""
        mapper = FactMapper(investigation_id="inv-test")
        nodes1, _ = mapper.map_fact(_make_fact(fact_id="f1"))
        nodes2, _ = mapper.map_fact(_make_fact(fact_id="f2"))

        inv_nodes_1 = [n for n in nodes1 if n.label == "Investigation"]
        inv_nodes_2 = [n for n in nodes2 if n.label == "Investigation"]
        assert len(inv_nodes_1) == 1
        assert len(inv_nodes_2) == 0


class TestSourceNodeDedup:
    """Test that Source nodes are deduplicated by source_id."""

    def test_same_source_not_duplicated(self) -> None:
        """Two facts from same source -> Source node created only once."""
        mapper = FactMapper(investigation_id="inv-test")
        nodes1, _ = mapper.map_fact(_make_fact(fact_id="f1"))
        nodes2, _ = mapper.map_fact(_make_fact(fact_id="f2"))

        source_nodes_1 = [n for n in nodes1 if n.label == "Source"]
        source_nodes_2 = [n for n in nodes2 if n.label == "Source"]
        assert len(source_nodes_1) == 1
        assert len(source_nodes_2) == 0  # Deduped

    def test_sourced_from_edge_still_created_for_deduped_source(self) -> None:
        """SOURCED_FROM edge is created for each fact even if Source node is deduped."""
        mapper = FactMapper(investigation_id="inv-test")
        _, edges1 = mapper.map_fact(_make_fact(fact_id="f1"))
        _, edges2 = mapper.map_fact(_make_fact(fact_id="f2"))

        sourced1 = [e for e in edges1 if e.edge_type == EdgeType.SOURCED_FROM]
        sourced2 = [e for e in edges2 if e.edge_type == EdgeType.SOURCED_FROM]
        assert len(sourced1) == 1
        assert len(sourced2) == 1


class TestImportability:
    """Test that FactMapper is importable from the package."""

    def test_import_from_package(self) -> None:
        """FactMapper importable from osint_system.agents.sifters.graph."""
        from osint_system.agents.sifters.graph import FactMapper as FM

        assert FM is FactMapper
