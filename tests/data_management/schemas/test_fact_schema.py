"""Tests for fact extraction schemas.

Tests comprehensive schema validation per Phase 6 CONTEXT.md requirements:
- Minimal valid fact (only claim.text required)
- Full fact with all optional fields
- Content hash auto-computation
- Entity linking validation
- Provenance chain serialization
- Quality metrics separate dimensions
- Schema version in output
- Denial assertion type handling
- Anonymous source entity
"""

import pytest
from pydantic import ValidationError

from osint_system.data_management.schemas import (
    ExtractedFact,
    Claim,
    Entity,
    EntityType,
    AnonymousSource,
    EntityCluster,
    Provenance,
    AttributionHop,
    SourceType,
    SourceClassification,
    TemporalMarker,
    NumericValue,
    QualityMetrics,
    ExtractionTrace,
    ExtractionMetadata,
    FactRelationship,
    SCHEMA_VERSION,
)


class TestMinimalValidFact:
    """Test that only claim.text is required."""

    def test_minimal_fact_with_claim_text_only(self):
        """Minimal valid fact has only claim text."""
        fact = ExtractedFact(claim=Claim(text="Putin visited Beijing"))

        assert fact.fact_id  # UUID auto-generated
        assert fact.content_hash  # Hash auto-computed
        assert fact.claim.text == "Putin visited Beijing"
        assert fact.schema_version == SCHEMA_VERSION

    def test_fact_without_claim_fails(self):
        """Fact without claim should fail validation."""
        with pytest.raises(ValidationError):
            ExtractedFact()  # type: ignore

    def test_claim_with_empty_text_passes(self):
        """Empty claim text is technically valid (warn but don't fail)."""
        # Per CONTEXT.md: lenient schema, only warn on missing fields
        fact = ExtractedFact(claim=Claim(text=""))
        assert fact.claim.text == ""
        assert fact.content_hash  # Still computes hash of empty string


class TestContentHashComputation:
    """Test automatic content hash computation."""

    def test_content_hash_auto_computed(self):
        """Content hash should be computed from claim text."""
        fact = ExtractedFact(claim=Claim(text="Test claim for hashing"))

        assert fact.content_hash
        assert len(fact.content_hash) == 64  # SHA256 hex

    def test_same_claim_produces_same_hash(self):
        """Same claim text should produce identical hash."""
        text = "Identical claim text"
        fact1 = ExtractedFact(claim=Claim(text=text))
        fact2 = ExtractedFact(claim=Claim(text=text))

        assert fact1.content_hash == fact2.content_hash
        # But UUIDs should differ
        assert fact1.fact_id != fact2.fact_id

    def test_different_claim_produces_different_hash(self):
        """Different claim text should produce different hash."""
        fact1 = ExtractedFact(claim=Claim(text="First claim"))
        fact2 = ExtractedFact(claim=Claim(text="Second claim"))

        assert fact1.content_hash != fact2.content_hash

    def test_explicit_hash_not_overwritten(self):
        """If hash is provided explicitly, should not be overwritten."""
        explicit_hash = "a" * 64
        fact = ExtractedFact(
            claim=Claim(text="Test"),
            content_hash=explicit_hash,
        )

        assert fact.content_hash == explicit_hash


class TestFullFactWithAllFields:
    """Test fact with all optional fields populated."""

    def test_full_fact_serialization(self):
        """Full fact with all fields should serialize correctly."""
        fact = ExtractedFact(
            claim=Claim(
                text="[E1:Putin] visited [E2:Beijing] in [T1:March 2024]",
                assertion_type="statement",
                claim_type="event",
            ),
            entities=[
                Entity(
                    id="E1",
                    text="Putin",
                    type=EntityType.PERSON,
                    canonical="Vladimir Putin",
                    cluster_id="cluster-putin-001",
                ),
                Entity(
                    id="E2",
                    text="Beijing",
                    type=EntityType.LOCATION,
                    canonical="Beijing, China",
                ),
            ],
            temporal=TemporalMarker(
                id="T1",
                value="2024-03",
                precision="month",
                temporal_precision="explicit",
            ),
            provenance=Provenance(
                source_id="article-uuid-123",
                quote="Russian President Vladimir Putin visited Beijing in March 2024",
                offsets={"start": 1542, "end": 1601},
                attribution_chain=[
                    AttributionHop(
                        entity="Kremlin spokesperson",
                        type=SourceType.OFFICIAL_STATEMENT,
                        hop=0,
                    ),
                    AttributionHop(entity="TASS", type=SourceType.WIRE_SERVICE, hop=1),
                    AttributionHop(
                        entity="Reuters", type=SourceType.WIRE_SERVICE, hop=2
                    ),
                ],
                attribution_phrase="according to Reuters citing TASS",
                hop_count=2,
                source_type=SourceType.WIRE_SERVICE,
                source_classification=SourceClassification.SECONDARY,
            ),
            quality=QualityMetrics(
                extraction_confidence=0.92,
                claim_clarity=0.88,
                extraction_trace=ExtractionTrace(
                    parsing_notes="Direct statement, clear structure",
                    clarity_factors=[],
                    entity_resolution="Putin identified from proper noun",
                ),
            ),
            relationships=[
                FactRelationship(
                    type="supports",
                    target_fact_id="other-uuid",
                    confidence=0.7,
                )
            ],
            variants=["variant-uuid-1", "variant-uuid-2"],
        )

        # Verify all fields present
        assert len(fact.entities) == 2
        assert fact.temporal.precision == "month"
        assert fact.provenance.hop_count == 2
        assert len(fact.provenance.attribution_chain) == 3
        assert fact.quality.extraction_confidence == 0.92
        assert fact.quality.claim_clarity == 0.88
        assert len(fact.relationships) == 1
        assert len(fact.variants) == 2

    def test_full_fact_json_roundtrip(self):
        """Full fact should serialize and deserialize correctly."""
        fact = ExtractedFact(
            claim=Claim(text="Test roundtrip"),
            entities=[
                Entity(id="E1", text="Test", type=EntityType.ORGANIZATION)
            ],
            provenance=Provenance(
                source_id="test-source",
                quote="Test quote",
                offsets={"start": 0, "end": 10},
            ),
            quality=QualityMetrics(
                extraction_confidence=0.9,
                claim_clarity=0.8,
            ),
        )

        json_data = fact.model_dump_json()
        restored = ExtractedFact.model_validate_json(json_data)

        assert restored.claim.text == fact.claim.text
        assert restored.content_hash == fact.content_hash
        assert len(restored.entities) == len(fact.entities)


class TestEntityLinking:
    """Test entity markers link to entity objects by ID."""

    def test_entity_id_pattern(self):
        """Entity IDs should follow E1, E2, etc pattern."""
        entity = Entity(id="E1", text="Putin", type=EntityType.PERSON)
        assert entity.id == "E1"

    def test_claim_text_with_entity_markers(self):
        """Claim text should contain entity markers matching entity IDs."""
        fact = ExtractedFact(
            claim=Claim(text="[E1:Putin] met [E2:Xi Jinping]"),
            entities=[
                Entity(id="E1", text="Putin", type=EntityType.PERSON),
                Entity(id="E2", text="Xi Jinping", type=EntityType.PERSON),
            ],
        )

        # Verify markers in text correspond to entities
        for entity in fact.entities:
            assert f"[{entity.id}:" in fact.claim.text

    def test_entity_clustering_without_resolution(self):
        """Entity clusters group without forcing resolution."""
        cluster = EntityCluster(
            cluster_id="cluster-putin-001",
            entities=["E1", "E5", "E12"],
            canonical_suggestion="Vladimir Putin",
        )

        assert len(cluster.entities) == 3
        # canonical_suggestion is a hint, not enforced
        assert cluster.canonical_suggestion is not None


class TestProvenanceChain:
    """Test provenance chain serialization."""

    def test_attribution_chain_ordering(self):
        """Attribution chain should preserve hop order."""
        chain = [
            AttributionHop(entity="Eyewitness", type=SourceType.EYEWITNESS, hop=0),
            AttributionHop(entity="Local Paper", type=SourceType.NEWS_OUTLET, hop=1),
            AttributionHop(entity="Reuters", type=SourceType.WIRE_SERVICE, hop=2),
        ]

        provenance = Provenance(
            source_id="test",
            quote="Test",
            offsets={"start": 0, "end": 4},
            attribution_chain=chain,
            hop_count=2,
        )

        assert provenance.attribution_chain[0].hop == 0
        assert provenance.attribution_chain[2].hop == 2
        assert len(provenance.attribution_chain) == provenance.hop_count + 1

    def test_source_type_and_hop_count_orthogonal(self):
        """Source type and hop count are separate dimensions."""
        provenance = Provenance(
            source_id="test",
            quote="Test",
            offsets={"start": 0, "end": 4},
            hop_count=2,
            source_type=SourceType.WIRE_SERVICE,
            source_classification=SourceClassification.SECONDARY,
        )

        # All three are independent fields
        assert provenance.hop_count == 2
        assert provenance.source_type == SourceType.WIRE_SERVICE
        assert provenance.source_classification == SourceClassification.SECONDARY

    def test_provenance_offsets_format(self):
        """Offsets should have start and end."""
        provenance = Provenance(
            source_id="test",
            quote="Test quote",
            offsets={"start": 100, "end": 110},
        )

        assert provenance.offsets["start"] == 100
        assert provenance.offsets["end"] == 110


class TestQualityMetricsSeparation:
    """Test quality metrics separate extraction_confidence from claim_clarity."""

    def test_separate_confidence_dimensions(self):
        """extraction_confidence and claim_clarity are separate fields."""
        quality = QualityMetrics(
            extraction_confidence=0.95,  # High: LLM parsed correctly
            claim_clarity=0.3,  # Low: Source text is vague
        )

        assert quality.extraction_confidence == 0.95
        assert quality.claim_clarity == 0.3
        # Different values allowed - they measure different things

    def test_quality_with_trace(self):
        """Quality metrics can include full extraction trace."""
        quality = QualityMetrics(
            extraction_confidence=0.8,
            claim_clarity=0.6,
            extraction_trace=ExtractionTrace(
                parsing_notes="Complex nested clause",
                clarity_factors=["hedged with 'reportedly'", "anonymous source"],
                entity_resolution="Coreference resolution applied",
            ),
        )

        assert len(quality.extraction_trace.clarity_factors) == 2
        assert "anonymous source" in quality.extraction_trace.clarity_factors

    def test_confidence_bounds(self):
        """Confidence values must be 0.0-1.0."""
        # Valid
        QualityMetrics(extraction_confidence=0.0, claim_clarity=1.0)
        QualityMetrics(extraction_confidence=1.0, claim_clarity=0.0)

        # Invalid: out of bounds
        with pytest.raises(ValidationError):
            QualityMetrics(extraction_confidence=1.5, claim_clarity=0.5)

        with pytest.raises(ValidationError):
            QualityMetrics(extraction_confidence=0.5, claim_clarity=-0.1)


class TestSchemaVersion:
    """Test schema version is explicit and tracked."""

    def test_schema_version_present(self):
        """All facts should have schema_version."""
        fact = ExtractedFact(claim=Claim(text="Test"))
        assert fact.schema_version == "1.0"
        assert fact.schema_version == SCHEMA_VERSION

    def test_schema_version_in_json(self):
        """Schema version should be serialized to JSON."""
        fact = ExtractedFact(claim=Claim(text="Test"))
        json_data = fact.model_dump()

        assert "schema_version" in json_data
        assert json_data["schema_version"] == "1.0"


class TestDenialAssertionType:
    """Test denial assertion type handling per CONTEXT.md."""

    def test_denial_assertion_type(self):
        """Denials represented as underlying claim with assertion_type='denial'."""
        fact = ExtractedFact(
            claim=Claim(
                text="[E1:Russia] involvement in [E2:the incident]",
                assertion_type="denial",
                claim_type="event",
            ),
            entities=[
                Entity(id="E1", text="Russia", type=EntityType.ORGANIZATION),
            ],
        )

        assert fact.claim.assertion_type == "denial"
        # The claim text is the underlying claim, not "Russia denied..."
        assert "involvement" in fact.claim.text

    def test_all_assertion_types(self):
        """All assertion types should be valid."""
        for assertion_type in ["statement", "denial", "claim", "prediction", "quote"]:
            claim = Claim(text="Test", assertion_type=assertion_type)
            assert claim.assertion_type == assertion_type


class TestAnonymousSource:
    """Test anonymous source entity handling."""

    def test_anonymous_source_with_descriptors(self):
        """Anonymous source captures available metadata."""
        anon = AnonymousSource(
            descriptors={
                "role": "official",
                "affiliation": "US_government",
                "department": "State Department",
                "seniority": "senior",
            },
            anonymity_granted_by="source-doc-uuid",
        )

        assert anon.entity_type == "anonymous_source"
        assert anon.descriptors["seniority"] == "senior"
        assert anon.anonymity_granted_by == "source-doc-uuid"

    def test_anonymous_source_minimal(self):
        """Anonymous source can have minimal descriptors."""
        anon = AnonymousSource()
        assert anon.entity_type == "anonymous_source"
        assert anon.descriptors == {}

    def test_anonymous_source_entity_type(self):
        """Entity can be ANONYMOUS_SOURCE type."""
        entity = Entity(
            id="E1",
            text="senior US official",
            type=EntityType.ANONYMOUS_SOURCE,
        )

        assert entity.type == EntityType.ANONYMOUS_SOURCE


class TestTemporalMarker:
    """Test temporal marker extraction."""

    def test_explicit_temporal_precision(self):
        """Explicit temporal precision from stated text."""
        temporal = TemporalMarker(
            id="T1",
            value="2024-03-15",
            precision="day",
            temporal_precision="explicit",
        )

        assert temporal.temporal_precision == "explicit"

    def test_inferred_temporal_precision(self):
        """Inferred temporal precision from article date."""
        temporal = TemporalMarker(
            id="T1",
            value="2024-03",
            precision="month",
            temporal_precision="inferred",
        )

        assert temporal.temporal_precision == "inferred"

    def test_unknown_temporal_precision(self):
        """Unknown temporal precision for ambiguous cases."""
        temporal = TemporalMarker(
            id="T1",
            value="2024",
            precision="year",
            temporal_precision="unknown",
        )

        assert temporal.temporal_precision == "unknown"


class TestNumericValue:
    """Test numeric value extraction with precision preservation."""

    def test_numeric_exact(self):
        """Exact numeric values."""
        num = NumericValue(
            value_original="42",
            value_normalized=[42, 42],
            numeric_precision="exact",
        )

        assert num.numeric_precision == "exact"

    def test_numeric_approximate(self):
        """Approximate numeric values."""
        num = NumericValue(
            value_original="~50",
            value_normalized=[45, 55],
            numeric_precision="approximate",
        )

        assert num.numeric_precision == "approximate"
        assert num.value_normalized[0] == 45

    def test_numeric_order_of_magnitude(self):
        """Order of magnitude numeric values."""
        num = NumericValue(
            value_original="thousands",
            value_normalized=[1000, 9999],
            numeric_precision="order_of_magnitude",
        )

        assert num.numeric_precision == "order_of_magnitude"
        assert num.value_original == "thousands"


class TestFactRelationships:
    """Test fact relationship hints."""

    def test_supports_relationship(self):
        """Facts can support each other."""
        rel = FactRelationship(
            type="supports",
            target_fact_id="uuid-other",
            confidence=0.8,
        )

        assert rel.type == "supports"

    def test_contradicts_relationship(self):
        """Facts can contradict each other."""
        rel = FactRelationship(
            type="contradicts",
            target_fact_id="uuid-other",
            confidence=0.9,
        )

        assert rel.type == "contradicts"

    def test_all_relationship_types(self):
        """All relationship types should be valid."""
        for rel_type in ["supports", "contradicts", "temporal_sequence", "elaborates"]:
            rel = FactRelationship(
                type=rel_type,
                target_fact_id="test-uuid",
            )
            assert rel.type == rel_type


class TestInferredExtractionType:
    """Test extraction type for implicit facts."""

    def test_explicit_extraction(self):
        """Explicit extraction from stated text."""
        meta = ExtractionMetadata(extraction_type="explicit")
        assert meta.extraction_type == "explicit"

    def test_inferred_extraction(self):
        """Inferred extraction from obvious implication."""
        meta = ExtractionMetadata(extraction_type="inferred")
        assert meta.extraction_type == "inferred"


class TestSourceTypes:
    """Test all source types and classifications."""

    def test_all_source_types(self):
        """All source types should be valid."""
        source_types = [
            SourceType.WIRE_SERVICE,
            SourceType.OFFICIAL_STATEMENT,
            SourceType.NEWS_OUTLET,
            SourceType.SOCIAL_MEDIA,
            SourceType.ACADEMIC,
            SourceType.DOCUMENT,
            SourceType.EYEWITNESS,
            SourceType.UNKNOWN,
        ]

        for source_type in source_types:
            hop = AttributionHop(entity="Test", type=source_type, hop=0)
            assert hop.type == source_type

    def test_all_source_classifications(self):
        """All source classifications should be valid."""
        classifications = [
            SourceClassification.PRIMARY,
            SourceClassification.SECONDARY,
            SourceClassification.TERTIARY,
        ]

        for classification in classifications:
            provenance = Provenance(
                source_id="test",
                quote="test",
                offsets={"start": 0, "end": 4},
                source_classification=classification,
            )
            assert provenance.source_classification == classification


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
