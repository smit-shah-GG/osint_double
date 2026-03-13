"""Unit tests for RelationshipExtractor hybrid rule-based and LLM extraction.

Tests cover:
- Rule-based CORROBORATES extraction from verification evidence
- Rule-based CONTRADICTS extraction from refuted verification
- Rule-based SUPERSEDES extraction from temporal contradiction
- Rule-based LOCATED_AT from entity co-occurrence
- Rule-based RELATED_TO from fact relationships
- LLM extraction disabled (config gate)
- LLM extraction enabled (mocked Gemini response)
- LLM extraction failure (graceful degradation)
- Edge deduplication (higher weight wins)
- Cross-investigation detection

All tests mock LLM calls (no actual API calls).
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from osint_system.agents.sifters.graph.relationship_extractor import (
    RelationshipExtractor,
)
from osint_system.config.graph_config import GraphConfig
from osint_system.data_management.graph.schema import EdgeType, GraphEdge
from osint_system.data_management.schemas.entity_schema import Entity, EntityType
from osint_system.data_management.schemas.fact_schema import (
    Claim,
    ExtractedFact,
    FactRelationship,
    QualityMetrics,
)
from osint_system.data_management.schemas.provenance_schema import (
    Provenance,
    SourceType,
)
from osint_system.data_management.schemas.verification_schema import (
    EvidenceItem,
    VerificationResult,
    VerificationStatus,
)


# --- Fixtures ---


def _make_fact(
    fact_id: str = "fact-001",
    claim_text: str = "[E1:Putin] visited [E2:Beijing]",
    entities: list[Entity] | None = None,
    relationships: list[FactRelationship] | None = None,
    claim_type: str = "event",
) -> ExtractedFact:
    """Build a minimal ExtractedFact for testing."""
    if entities is None:
        entities = [
            Entity(id="E1", text="Putin", type=EntityType.PERSON, canonical="Vladimir Putin"),
            Entity(id="E2", text="Beijing", type=EntityType.LOCATION, canonical="Beijing"),
        ]
    return ExtractedFact(
        fact_id=fact_id,
        claim=Claim(text=claim_text, assertion_type="statement", claim_type=claim_type),
        entities=entities,
        relationships=relationships or [],
        quality=QualityMetrics(extraction_confidence=0.9, claim_clarity=0.85),
    )


def _make_evidence(
    supports: bool = True,
    authority: float = 0.9,
    domain: str = "apnews.com",
) -> EvidenceItem:
    """Build a minimal EvidenceItem."""
    return EvidenceItem(
        source_url=f"https://{domain}/article/test",
        source_domain=domain,
        source_type="wire_service",
        authority_score=authority,
        snippet="Test evidence snippet",
        supports_claim=supports,
        relevance_score=0.95,
    )


def _make_verification(
    fact_id: str = "fact-001",
    status: VerificationStatus = VerificationStatus.CONFIRMED,
    supporting_evidence: list[EvidenceItem] | None = None,
    refuting_evidence: list[EvidenceItem] | None = None,
    related_fact_id: str | None = None,
    contradiction_type: str | None = None,
) -> VerificationResult:
    """Build a minimal VerificationResult."""
    return VerificationResult(
        fact_id=fact_id,
        investigation_id="inv-test",
        status=status,
        original_confidence=0.5,
        confidence_boost=0.3,
        final_confidence=0.8,
        supporting_evidence=supporting_evidence or [],
        refuting_evidence=refuting_evidence or [],
        reasoning="Test verification",
        related_fact_id=related_fact_id,
        contradiction_type=contradiction_type,
    )


# --- Tests ---


class TestRuleBasedCorroborates:
    """Test CORROBORATES edge extraction from verification evidence."""

    def test_confirmed_with_multiple_evidence_creates_corroborates(self) -> None:
        """Fact with CONFIRMED verification + 2+ supporting evidence -> CORROBORATES edges."""
        config = GraphConfig(llm_relationship_extraction=False)
        extractor = RelationshipExtractor(config=config)

        fact = _make_fact(fact_id="fact-001")
        other_fact = _make_fact(
            fact_id="fact-002",
            claim_text="[E1:Putin] visited [E2:Beijing]",  # Same claim text
        )
        verification = _make_verification(
            fact_id="fact-001",
            status=VerificationStatus.CONFIRMED,
            supporting_evidence=[
                _make_evidence(supports=True, authority=0.9),
                _make_evidence(supports=True, authority=0.85, domain="reuters.com"),
            ],
        )

        edges = extractor.extract_relationships(
            fact, verification, [fact, other_fact], "inv-test"
        )
        corr_edges = [e for e in edges if e.edge_type == EdgeType.CORROBORATES]
        assert len(corr_edges) == 1
        assert corr_edges[0].target_id == "Fact:fact-002"
        assert corr_edges[0].weight > 0.5

    def test_no_corroborates_without_matching_facts(self) -> None:
        """No CORROBORATES if no existing facts share claim text or hash."""
        config = GraphConfig(llm_relationship_extraction=False)
        extractor = RelationshipExtractor(config=config)

        fact = _make_fact(fact_id="fact-001")
        other_fact = _make_fact(fact_id="fact-002", claim_text="Completely different claim")
        verification = _make_verification(
            fact_id="fact-001",
            status=VerificationStatus.CONFIRMED,
            supporting_evidence=[
                _make_evidence(supports=True),
                _make_evidence(supports=True, domain="reuters.com"),
            ],
        )

        edges = extractor.extract_relationships(
            fact, verification, [fact, other_fact], "inv-test"
        )
        corr_edges = [e for e in edges if e.edge_type == EdgeType.CORROBORATES]
        assert len(corr_edges) == 0


class TestRuleBasedContradicts:
    """Test CONTRADICTS edge extraction from refuted verification."""

    def test_refuted_with_related_fact_creates_contradicts(self) -> None:
        """Fact with REFUTED verification + related_fact_id -> CONTRADICTS edge."""
        config = GraphConfig(llm_relationship_extraction=False)
        extractor = RelationshipExtractor(config=config)

        fact = _make_fact(fact_id="fact-001")
        verification = _make_verification(
            fact_id="fact-001",
            status=VerificationStatus.REFUTED,
            refuting_evidence=[_make_evidence(supports=False, authority=0.9)],
            related_fact_id="fact-002",
            contradiction_type="negation",
        )

        edges = extractor.extract_relationships(fact, verification, [], "inv-test")
        contra_edges = [e for e in edges if e.edge_type == EdgeType.CONTRADICTS]
        assert len(contra_edges) == 1
        assert contra_edges[0].target_id == "Fact:fact-002"
        assert contra_edges[0].properties["contradiction_type"] == "negation"

    def test_contradicts_from_fact_relationships(self) -> None:
        """FactRelationship with type='contradicts' -> CONTRADICTS edge."""
        config = GraphConfig(llm_relationship_extraction=False)
        extractor = RelationshipExtractor(config=config)

        fact = _make_fact(
            fact_id="fact-001",
            relationships=[
                FactRelationship(type="contradicts", target_fact_id="fact-003", confidence=0.7),
            ],
        )

        edges = extractor.extract_relationships(fact, None, [], "inv-test")
        contra_edges = [e for e in edges if e.edge_type == EdgeType.CONTRADICTS]
        assert len(contra_edges) == 1
        assert contra_edges[0].target_id == "Fact:fact-003"
        assert contra_edges[0].weight == 0.7


class TestRuleBasedSupersedes:
    """Test SUPERSEDES edge extraction from temporal contradiction."""

    def test_superseded_temporal_creates_supersedes(self) -> None:
        """SUPERSEDED status + temporal contradiction_type -> SUPERSEDES edge."""
        config = GraphConfig(llm_relationship_extraction=False)
        extractor = RelationshipExtractor(config=config)

        fact = _make_fact(fact_id="fact-001")
        verification = _make_verification(
            fact_id="fact-001",
            status=VerificationStatus.SUPERSEDED,
            related_fact_id="fact-old",
            contradiction_type="temporal",
        )

        edges = extractor.extract_relationships(fact, verification, [], "inv-test")
        supersedes = [e for e in edges if e.edge_type == EdgeType.SUPERSEDES]
        assert len(supersedes) == 1
        assert supersedes[0].source_id == "Fact:fact-001"
        assert supersedes[0].target_id == "Fact:fact-old"
        assert supersedes[0].properties["contradiction_type"] == "temporal"

    def test_no_supersedes_without_temporal_type(self) -> None:
        """SUPERSEDED status but non-temporal contradiction -> no SUPERSEDES edge."""
        config = GraphConfig(llm_relationship_extraction=False)
        extractor = RelationshipExtractor(config=config)

        fact = _make_fact(fact_id="fact-001")
        verification = _make_verification(
            fact_id="fact-001",
            status=VerificationStatus.SUPERSEDED,
            related_fact_id="fact-old",
            contradiction_type="negation",
        )

        edges = extractor.extract_relationships(fact, verification, [], "inv-test")
        supersedes = [e for e in edges if e.edge_type == EdgeType.SUPERSEDES]
        assert len(supersedes) == 0


class TestRuleBasedLocatedAt:
    """Test LOCATED_AT edge from entity co-occurrence."""

    def test_person_and_location_creates_located_at(self) -> None:
        """Fact with PERSON + LOCATION entities -> LOCATED_AT edge."""
        config = GraphConfig(llm_relationship_extraction=False)
        extractor = RelationshipExtractor(config=config)

        fact = _make_fact(
            fact_id="fact-001",
            entities=[
                Entity(id="E1", text="Putin", type=EntityType.PERSON, canonical="Vladimir Putin"),
                Entity(id="E2", text="Moscow", type=EntityType.LOCATION, canonical="Moscow"),
            ],
        )

        edges = extractor.extract_relationships(fact, None, [], "inv-test")
        located = [e for e in edges if e.edge_type == EdgeType.LOCATED_AT]
        assert len(located) == 1
        assert located[0].source_id == "Entity:inv-test:Vladimir Putin"
        assert located[0].target_id == "Entity:inv-test:Moscow"
        # Default claim_type is "event" -> weight 0.7
        assert located[0].weight == 0.7

    def test_state_claim_type_higher_weight(self) -> None:
        """LOCATED_AT from state claim_type -> weight 0.8."""
        config = GraphConfig(llm_relationship_extraction=False)
        extractor = RelationshipExtractor(config=config)

        fact = _make_fact(
            fact_id="fact-001",
            entities=[
                Entity(id="E1", text="UN", type=EntityType.ORGANIZATION, canonical="United Nations"),
                Entity(id="E2", text="Geneva", type=EntityType.LOCATION, canonical="Geneva"),
            ],
            claim_type="state",
        )

        edges = extractor.extract_relationships(fact, None, [], "inv-test")
        located = [e for e in edges if e.edge_type == EdgeType.LOCATED_AT]
        assert len(located) == 1
        assert located[0].weight == 0.8


class TestRuleBasedRelatedTo:
    """Test RELATED_TO edge from fact.relationships."""

    def test_supports_creates_related_to(self) -> None:
        """FactRelationship with type='supports' -> RELATED_TO edge."""
        config = GraphConfig(llm_relationship_extraction=False)
        extractor = RelationshipExtractor(config=config)

        fact = _make_fact(
            fact_id="fact-001",
            relationships=[
                FactRelationship(type="supports", target_fact_id="fact-005", confidence=0.8),
            ],
        )

        edges = extractor.extract_relationships(fact, None, [], "inv-test")
        related = [e for e in edges if e.edge_type == EdgeType.RELATED_TO]
        assert len(related) == 1
        assert related[0].target_id == "Fact:fact-005"
        assert related[0].properties["relationship_type"] == "supports"

    def test_elaborates_creates_related_to(self) -> None:
        """FactRelationship with type='elaborates' -> RELATED_TO edge."""
        config = GraphConfig(llm_relationship_extraction=False)
        extractor = RelationshipExtractor(config=config)

        fact = _make_fact(
            fact_id="fact-001",
            relationships=[
                FactRelationship(type="elaborates", target_fact_id="fact-010", confidence=0.6),
            ],
        )

        edges = extractor.extract_relationships(fact, None, [], "inv-test")
        related = [e for e in edges if e.edge_type == EdgeType.RELATED_TO]
        assert len(related) == 1
        assert related[0].properties["relationship_type"] == "elaborates"


class TestLLMExtractionDisabled:
    """Test that LLM extraction is gated by config."""

    def test_llm_disabled_returns_only_rule_based(self) -> None:
        """config.llm_relationship_extraction=False -> only rule-based edges."""
        config = GraphConfig(llm_relationship_extraction=False)
        extractor = RelationshipExtractor(config=config)

        fact = _make_fact(fact_id="fact-001")
        edges = extractor.extract_relationships(fact, None, [], "inv-test")

        # Only rule-based edges (LOCATED_AT from Putin+Beijing co-occurrence)
        for edge in edges:
            source = edge.properties.get("source", "")
            assert source != "llm_extraction"


class TestLLMExtractionEnabled:
    """Test LLM extraction with mocked Gemini response."""

    def test_llm_enabled_creates_causes_edges(self) -> None:
        """Mocked LLM response with CAUSES relationship -> CAUSES edge."""
        config = GraphConfig(llm_relationship_extraction=True)
        extractor = RelationshipExtractor(config=config)

        fact = _make_fact(
            fact_id="fact-001",
            entities=[Entity(id="E1", text="Putin", type=EntityType.PERSON, canonical="Vladimir Putin")],
        )
        other_fact = _make_fact(
            fact_id="fact-002",
            claim_text="Sanctions imposed on Russia",
            entities=[Entity(id="E1", text="Russia", type=EntityType.ORGANIZATION, canonical="Vladimir Putin")],
        )

        # Mock the google.genai module at the import level
        mock_genai = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "relationships": [
                {
                    "type": "CAUSES",
                    "source_fact_id": "fact-001",
                    "target_fact_id": "fact-002",
                    "reasoning": "Putin's visit led to sanctions",
                }
            ]
        })
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_genai.Client.return_value = mock_client

        # Create a mock google package with genai attribute
        mock_google = MagicMock()
        mock_google.genai = mock_genai

        with patch.dict("sys.modules", {"google": mock_google, "google.genai": mock_genai}):
            edges = extractor._extract_llm_based(fact, [fact, other_fact], "inv-test")

        assert len(edges) == 1
        assert edges[0].edge_type == EdgeType.CAUSES
        assert edges[0].source_id == "Fact:fact-001"
        assert edges[0].target_id == "Fact:fact-002"
        assert edges[0].weight == 0.4  # Lower weight for LLM-inferred
        assert edges[0].properties["source"] == "llm_extraction"


class TestLLMExtractionFailure:
    """Test graceful degradation on LLM failure."""

    def test_llm_failure_returns_empty_list(self) -> None:
        """LLM error -> graceful empty return, no exception."""
        config = GraphConfig(llm_relationship_extraction=True)
        extractor = RelationshipExtractor(config=config)

        fact = _make_fact(
            fact_id="fact-001",
            entities=[Entity(id="E1", text="Putin", type=EntityType.PERSON, canonical="Vladimir Putin")],
        )
        other_fact = _make_fact(
            fact_id="fact-002",
            claim_text="Related event",
            entities=[Entity(id="E1", text="Putin", type=EntityType.PERSON, canonical="Vladimir Putin")],
        )

        # Patch to raise ImportError (simulates google.genai not installed)
        with patch.dict(
            "sys.modules",
            {"google": None, "google.genai": None},
        ):
            edges = extractor._extract_llm_based(fact, [fact, other_fact], "inv-test")

        assert edges == []


class TestEdgeDeduplication:
    """Test edge deduplication logic."""

    def test_same_edge_from_rule_and_llm_keeps_higher_weight(self) -> None:
        """Duplicate edges (same source+target+type) -> keep higher weight."""
        edges = [
            GraphEdge(
                source_id="Fact:f1",
                target_id="Fact:f2",
                edge_type=EdgeType.CAUSES,
                weight=0.3,
                properties={"source": "rule_based"},
            ),
            GraphEdge(
                source_id="Fact:f1",
                target_id="Fact:f2",
                edge_type=EdgeType.CAUSES,
                weight=0.7,
                properties={"source": "llm_extraction"},
            ),
        ]

        deduped = RelationshipExtractor._deduplicate_edges(edges)
        assert len(deduped) == 1
        assert deduped[0].weight == 0.7

    def test_different_edge_types_not_deduped(self) -> None:
        """Edges with different types between same nodes are NOT deduped."""
        edges = [
            GraphEdge(
                source_id="Fact:f1",
                target_id="Fact:f2",
                edge_type=EdgeType.CAUSES,
                weight=0.5,
                properties={},
            ),
            GraphEdge(
                source_id="Fact:f1",
                target_id="Fact:f2",
                edge_type=EdgeType.PRECEDES,
                weight=0.5,
                properties={},
            ),
        ]

        deduped = RelationshipExtractor._deduplicate_edges(edges)
        assert len(deduped) == 2


class TestCrossInvestigation:
    """Test cross-investigation entity detection."""

    def test_matching_canonical_creates_cross_investigation_edge(self) -> None:
        """Entity matching canonical in another investigation -> RELATED_TO with cross_investigation=True."""
        config = GraphConfig(llm_relationship_extraction=False)
        extractor = RelationshipExtractor(config=config)

        fact = _make_fact(
            fact_id="fact-001",
            entities=[Entity(id="E1", text="Putin", type=EntityType.PERSON, canonical="Vladimir Putin")],
        )

        other_entities = {
            "Vladimir Putin": ["inv-other-1", "inv-other-2"],
        }

        edges = extractor.extract_cross_investigation(
            fact, "inv-test", other_entities
        )

        assert len(edges) == 2
        for edge in edges:
            assert edge.edge_type == EdgeType.RELATED_TO
            assert edge.cross_investigation is True
            assert edge.properties["match_type"] == "exact_canonical"
            assert edge.properties["resolution_confidence"] == 1.0
            assert edge.source_id == "Entity:inv-test:Vladimir Putin"

        target_ids = {e.target_id for e in edges}
        assert "Entity:inv-other-1:Vladimir Putin" in target_ids
        assert "Entity:inv-other-2:Vladimir Putin" in target_ids

    def test_no_cross_investigation_for_same_investigation(self) -> None:
        """Entity matching in same investigation -> no cross-investigation edge."""
        config = GraphConfig(llm_relationship_extraction=False)
        extractor = RelationshipExtractor(config=config)

        fact = _make_fact(
            fact_id="fact-001",
            entities=[Entity(id="E1", text="Putin", type=EntityType.PERSON, canonical="Vladimir Putin")],
        )

        other_entities = {
            "Vladimir Putin": ["inv-test"],  # Same investigation
        }

        edges = extractor.extract_cross_investigation(
            fact, "inv-test", other_entities
        )
        assert len(edges) == 0

    def test_no_cross_investigation_for_non_matching_entity(self) -> None:
        """Entity not found in other investigations -> no edges."""
        config = GraphConfig(llm_relationship_extraction=False)
        extractor = RelationshipExtractor(config=config)

        fact = _make_fact(
            fact_id="fact-001",
            entities=[Entity(id="E1", text="Putin", type=EntityType.PERSON, canonical="Vladimir Putin")],
        )

        other_entities = {
            "Xi Jinping": ["inv-other"],  # Different entity
        }

        edges = extractor.extract_cross_investigation(
            fact, "inv-test", other_entities
        )
        assert len(edges) == 0


class TestImportability:
    """Test that RelationshipExtractor is importable from the package."""

    def test_import_from_package(self) -> None:
        """RelationshipExtractor importable from osint_system.agents.sifters.graph."""
        from osint_system.agents.sifters.graph import RelationshipExtractor as RE

        assert RE is RelationshipExtractor
