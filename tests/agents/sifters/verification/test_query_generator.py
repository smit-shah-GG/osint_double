"""Comprehensive tests for QueryGenerator species-specialized query generation.

Tests cover:
- Initialization (max_queries, custom values)
- PHANTOM queries (source-chain: entity_focused, exact_phrase, broader_context)
- FOG queries (clarity-seeking: vague quantity, vague temporal, wire service fallback)
- ANOMALY queries (compound: temporal_context, authority_arbitration, clarity_enhancement)
- Edge cases (no flags, NOISE-only, multi-flag limit, missing entities/claims)
- Query variant type validation (all queries have valid fields)
"""

import asyncio

import pytest

from osint_system.agents.sifters.verification.query_generator import QueryGenerator
from osint_system.data_management.schemas.classification_schema import (
    ClassificationReasoning,
    DubiousFlag,
    FactClassification,
)
from osint_system.data_management.schemas.verification_schema import (
    VerificationQuery,
)

VALID_VARIANT_TYPES = {
    "entity_focused",
    "exact_phrase",
    "broader_context",
    "temporal_context",
    "authority_arbitration",
    "clarity_enhancement",
}


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def generator() -> QueryGenerator:
    return QueryGenerator()


@pytest.fixture
def fact_with_entities() -> dict:
    return {
        "entities": [
            {"canonical_name": "Putin", "text": "Vladimir Putin"},
            {"canonical_name": "Ukraine", "text": "Ukraine"},
        ],
        "claim": {"text": "Putin ordered a new deployment to eastern Ukraine"},
        "temporal_markers": [{"value": "2024-03-15"}],
    }


@pytest.fixture
def fact_with_vague_quantity() -> dict:
    return {
        "entities": [{"text": "Russia"}],
        "claim": {"text": "Several officials confirmed the deployment of dozens of troops"},
    }


@pytest.fixture
def fact_with_vague_temporal() -> dict:
    return {
        "entities": [{"text": "NATO"}],
        "claim": {"text": "NATO will soon announce a new defense pact"},
    }


@pytest.fixture
def fact_no_entities() -> dict:
    return {
        "entities": [],
        "claim": {"text": "A significant military development was reported"},
    }


@pytest.fixture
def fact_no_claim() -> dict:
    return {
        "entities": [{"text": "China"}],
        "claim": {},
    }


@pytest.fixture
def fact_string_claim() -> dict:
    return {
        "entities": ["Russia", "China"],
        "claim": "Leaders met to discuss trade agreements",
    }


@pytest.fixture
def phantom_classification() -> FactClassification:
    return FactClassification(
        fact_id="fact-phantom",
        investigation_id="inv-1",
        dubious_flags=[DubiousFlag.PHANTOM],
        classification_reasoning=[
            ClassificationReasoning(
                flag=DubiousFlag.PHANTOM,
                reason="hop_count=4, no primary source",
                trigger_values={"hop_count": 4},
            )
        ],
    )


@pytest.fixture
def fog_classification() -> FactClassification:
    return FactClassification(
        fact_id="fact-fog",
        investigation_id="inv-1",
        dubious_flags=[DubiousFlag.FOG],
        classification_reasoning=[
            ClassificationReasoning(
                flag=DubiousFlag.FOG,
                reason="attribution contains 'reportedly'",
                trigger_values={"claim_clarity": 0.35},
            )
        ],
    )


@pytest.fixture
def anomaly_classification() -> FactClassification:
    return FactClassification(
        fact_id="fact-anomaly",
        investigation_id="inv-1",
        dubious_flags=[DubiousFlag.ANOMALY],
        classification_reasoning=[
            ClassificationReasoning(
                flag=DubiousFlag.ANOMALY,
                reason="contradicts fact-002",
                trigger_values={"contradicting_fact_ids": ["fact-002"]},
            )
        ],
    )


@pytest.fixture
def noise_only_classification() -> FactClassification:
    return FactClassification(
        fact_id="fact-noise",
        investigation_id="inv-1",
        dubious_flags=[DubiousFlag.NOISE],
    )


@pytest.fixture
def multi_flag_classification() -> FactClassification:
    return FactClassification(
        fact_id="fact-multi",
        investigation_id="inv-1",
        dubious_flags=[DubiousFlag.PHANTOM, DubiousFlag.FOG],
    )


@pytest.fixture
def no_flags_classification() -> FactClassification:
    return FactClassification(
        fact_id="fact-clean",
        investigation_id="inv-1",
        dubious_flags=[],
    )


# ── Initialization Tests ─────────────────────────────────────────────────


class TestQueryGeneratorInit:
    def test_default_max_queries(self) -> None:
        gen = QueryGenerator()
        assert gen.max_queries == 3

    def test_custom_max_queries(self) -> None:
        gen = QueryGenerator(max_queries=5)
        assert gen.max_queries == 5


# ── PHANTOM Query Tests ──────────────────────────────────────────────────


class TestPhantomQueries:
    @pytest.mark.asyncio
    async def test_generates_three_queries(
        self,
        generator: QueryGenerator,
        fact_with_entities: dict,
        phantom_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_with_entities, phantom_classification)
        assert len(queries) == 3

    @pytest.mark.asyncio
    async def test_entity_focused_variant(
        self,
        generator: QueryGenerator,
        fact_with_entities: dict,
        phantom_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_with_entities, phantom_classification)
        entity_focused = [q for q in queries if q.variant_type == "entity_focused"]
        assert len(entity_focused) == 1
        assert "Putin" in entity_focused[0].query
        assert "official statement" in entity_focused[0].query
        assert "wire_service" in entity_focused[0].target_sources

    @pytest.mark.asyncio
    async def test_exact_phrase_variant(
        self,
        generator: QueryGenerator,
        fact_with_entities: dict,
        phantom_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_with_entities, phantom_classification)
        exact = [q for q in queries if q.variant_type == "exact_phrase"]
        assert len(exact) == 1
        # Exact phrase queries use quoted claim text
        assert '"' in exact[0].query
        assert "news_outlet" in exact[0].target_sources

    @pytest.mark.asyncio
    async def test_broader_context_variant(
        self,
        generator: QueryGenerator,
        fact_with_entities: dict,
        phantom_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_with_entities, phantom_classification)
        broader = [q for q in queries if q.variant_type == "broader_context"]
        assert len(broader) == 1
        assert "transcript" in broader[0].query or "interview" in broader[0].query
        assert "official_statement" in broader[0].target_sources

    @pytest.mark.asyncio
    async def test_all_queries_tagged_phantom(
        self,
        generator: QueryGenerator,
        fact_with_entities: dict,
        phantom_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_with_entities, phantom_classification)
        for q in queries:
            assert q.dubious_flag == DubiousFlag.PHANTOM

    @pytest.mark.asyncio
    async def test_no_entities_produces_fewer_queries(
        self,
        generator: QueryGenerator,
        fact_no_entities: dict,
        phantom_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_no_entities, phantom_classification)
        # entity_focused and broader_context require entities; only exact_phrase remains
        assert len(queries) == 1
        assert queries[0].variant_type == "exact_phrase"


# ── FOG Query Tests ──────────────────────────────────────────────────────


class TestFogQueries:
    @pytest.mark.asyncio
    async def test_generates_three_queries(
        self,
        generator: QueryGenerator,
        fact_with_entities: dict,
        fog_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_with_entities, fog_classification)
        assert len(queries) == 3

    @pytest.mark.asyncio
    async def test_detects_vague_quantity(
        self,
        generator: QueryGenerator,
        fact_with_vague_quantity: dict,
        fog_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_with_vague_quantity, fog_classification)
        clarity = [q for q in queries if q.variant_type == "clarity_enhancement"]
        assert len(clarity) == 1
        assert "exact number" in clarity[0].query or "confirmed figure" in clarity[0].query

    @pytest.mark.asyncio
    async def test_detects_vague_temporal(
        self,
        generator: QueryGenerator,
        fact_with_vague_temporal: dict,
        fog_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_with_vague_temporal, fog_classification)
        clarity = [q for q in queries if q.variant_type == "clarity_enhancement"]
        assert len(clarity) == 1
        assert "date" in clarity[0].query or "when" in clarity[0].query

    @pytest.mark.asyncio
    async def test_wire_service_fallback_no_vague_terms(
        self,
        generator: QueryGenerator,
        fact_with_entities: dict,
        fog_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_with_entities, fog_classification)
        clarity = [q for q in queries if q.variant_type == "clarity_enhancement"]
        assert len(clarity) == 1
        assert "reuters.com" in clarity[0].query or "apnews.com" in clarity[0].query

    @pytest.mark.asyncio
    async def test_entity_focused_targets_confirmed(
        self,
        generator: QueryGenerator,
        fact_with_entities: dict,
        fog_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_with_entities, fog_classification)
        entity_focused = [q for q in queries if q.variant_type == "entity_focused"]
        assert len(entity_focused) == 1
        assert "confirmed" in entity_focused[0].query

    @pytest.mark.asyncio
    async def test_all_queries_tagged_fog(
        self,
        generator: QueryGenerator,
        fact_with_entities: dict,
        fog_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_with_entities, fog_classification)
        for q in queries:
            assert q.dubious_flag == DubiousFlag.FOG


# ── ANOMALY Query Tests ──────────────────────────────────────────────────


class TestAnomalyQueries:
    @pytest.mark.asyncio
    async def test_generates_three_queries(
        self,
        generator: QueryGenerator,
        fact_with_entities: dict,
        anomaly_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_with_entities, anomaly_classification)
        assert len(queries) == 3

    @pytest.mark.asyncio
    async def test_temporal_context_with_temporal_value(
        self,
        generator: QueryGenerator,
        fact_with_entities: dict,
        anomaly_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_with_entities, anomaly_classification)
        temporal = [q for q in queries if q.variant_type == "temporal_context"]
        assert len(temporal) == 1
        assert "2024-03-15" in temporal[0].query
        assert "timeline" in temporal[0].query or "chronology" in temporal[0].query

    @pytest.mark.asyncio
    async def test_temporal_context_without_temporal_value(
        self,
        generator: QueryGenerator,
        anomaly_classification: FactClassification,
    ) -> None:
        fact = {
            "entities": [{"text": "Russia"}],
            "claim": {"text": "Military forces were deployed"},
            "temporal_markers": [],
        }
        queries = await generator.generate_queries(fact, anomaly_classification)
        temporal = [q for q in queries if q.variant_type == "temporal_context"]
        assert len(temporal) == 1
        assert "latest" in temporal[0].query or "current status" in temporal[0].query

    @pytest.mark.asyncio
    async def test_authority_arbitration_variant(
        self,
        generator: QueryGenerator,
        fact_with_entities: dict,
        anomaly_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_with_entities, anomaly_classification)
        authority = [q for q in queries if q.variant_type == "authority_arbitration"]
        assert len(authority) == 1
        assert ".gov" in authority[0].query
        assert "official_statement" in authority[0].target_sources

    @pytest.mark.asyncio
    async def test_clarity_enhancement_variant(
        self,
        generator: QueryGenerator,
        fact_with_entities: dict,
        anomaly_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_with_entities, anomaly_classification)
        clarity = [q for q in queries if q.variant_type == "clarity_enhancement"]
        assert len(clarity) == 1

    @pytest.mark.asyncio
    async def test_all_queries_tagged_anomaly(
        self,
        generator: QueryGenerator,
        fact_with_entities: dict,
        anomaly_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_with_entities, anomaly_classification)
        for q in queries:
            assert q.dubious_flag == DubiousFlag.ANOMALY


# ── Edge Case Tests ──────────────────────────────────────────────────────


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_no_flags_returns_empty(
        self,
        generator: QueryGenerator,
        fact_with_entities: dict,
        no_flags_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_with_entities, no_flags_classification)
        assert queries == []

    @pytest.mark.asyncio
    async def test_noise_only_returns_empty(
        self,
        generator: QueryGenerator,
        fact_with_entities: dict,
        noise_only_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_with_entities, noise_only_classification)
        assert queries == []

    @pytest.mark.asyncio
    async def test_multi_flag_limited_to_max_queries(
        self,
        generator: QueryGenerator,
        fact_with_entities: dict,
        multi_flag_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_with_entities, multi_flag_classification)
        # PHANTOM produces 3, FOG produces 3, but limited to max_queries=3
        assert len(queries) <= 3

    @pytest.mark.asyncio
    async def test_multi_flag_includes_both_flag_types(
        self,
        generator: QueryGenerator,
        fact_with_entities: dict,
        multi_flag_classification: FactClassification,
    ) -> None:
        gen = QueryGenerator(max_queries=6)
        queries = await gen.generate_queries(fact_with_entities, multi_flag_classification)
        flags_present = {q.dubious_flag for q in queries}
        assert DubiousFlag.PHANTOM in flags_present
        assert DubiousFlag.FOG in flags_present

    @pytest.mark.asyncio
    async def test_missing_entities_handled(
        self,
        generator: QueryGenerator,
        fog_classification: FactClassification,
    ) -> None:
        fact = {"claim": {"text": "Something happened"}}
        queries = await generator.generate_queries(fact, fog_classification)
        # Should not raise; fewer queries without entities
        assert isinstance(queries, list)

    @pytest.mark.asyncio
    async def test_missing_claim_text_handled(
        self,
        generator: QueryGenerator,
        fact_no_claim: dict,
        phantom_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_no_claim, phantom_classification)
        # Should not raise; entity-based queries still generated
        assert isinstance(queries, list)

    @pytest.mark.asyncio
    async def test_string_entities_handled(
        self,
        generator: QueryGenerator,
        fact_string_claim: dict,
        phantom_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_string_claim, phantom_classification)
        entity_focused = [q for q in queries if q.variant_type == "entity_focused"]
        assert len(entity_focused) == 1
        assert "Russia" in entity_focused[0].query

    @pytest.mark.asyncio
    async def test_string_claim_handled(
        self,
        generator: QueryGenerator,
        fact_string_claim: dict,
        fog_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_string_claim, fog_classification)
        exact = [q for q in queries if q.variant_type == "exact_phrase"]
        assert len(exact) == 1
        assert "trade agreements" in exact[0].query

    @pytest.mark.asyncio
    async def test_noise_flag_skipped_in_multi_flag(
        self, generator: QueryGenerator, fact_with_entities: dict
    ) -> None:
        classification = FactClassification(
            fact_id="fact-mixed",
            investigation_id="inv-1",
            dubious_flags=[DubiousFlag.PHANTOM, DubiousFlag.NOISE],
        )
        queries = await generator.generate_queries(fact_with_entities, classification)
        # NOISE flag is skipped, only PHANTOM queries generated
        for q in queries:
            assert q.dubious_flag == DubiousFlag.PHANTOM

    @pytest.mark.asyncio
    async def test_custom_max_queries_respected(
        self, fact_with_entities: dict, phantom_classification: FactClassification
    ) -> None:
        gen = QueryGenerator(max_queries=1)
        queries = await gen.generate_queries(fact_with_entities, phantom_classification)
        assert len(queries) == 1


# ── Query Variant Validation Tests ───────────────────────────────────────


class TestQueryVariantValidation:
    @pytest.mark.asyncio
    async def test_all_queries_have_valid_variant_type(
        self,
        generator: QueryGenerator,
        fact_with_entities: dict,
        phantom_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_with_entities, phantom_classification)
        for q in queries:
            assert q.variant_type in VALID_VARIANT_TYPES

    @pytest.mark.asyncio
    async def test_all_queries_have_purpose(
        self,
        generator: QueryGenerator,
        fact_with_entities: dict,
        fog_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_with_entities, fog_classification)
        for q in queries:
            assert q.purpose != ""

    @pytest.mark.asyncio
    async def test_all_queries_have_dubious_flag(
        self,
        generator: QueryGenerator,
        fact_with_entities: dict,
        anomaly_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_with_entities, anomaly_classification)
        for q in queries:
            assert q.dubious_flag is not None
            assert isinstance(q.dubious_flag, DubiousFlag)

    @pytest.mark.asyncio
    async def test_all_queries_have_nonempty_target_sources(
        self,
        generator: QueryGenerator,
        fact_with_entities: dict,
        phantom_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_with_entities, phantom_classification)
        for q in queries:
            assert len(q.target_sources) > 0

    @pytest.mark.asyncio
    async def test_all_queries_are_verification_query_instances(
        self,
        generator: QueryGenerator,
        fact_with_entities: dict,
        fog_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_with_entities, fog_classification)
        for q in queries:
            assert isinstance(q, VerificationQuery)

    @pytest.mark.asyncio
    async def test_all_queries_have_nonempty_query_string(
        self,
        generator: QueryGenerator,
        fact_with_entities: dict,
        anomaly_classification: FactClassification,
    ) -> None:
        queries = await generator.generate_queries(fact_with_entities, anomaly_classification)
        for q in queries:
            assert q.query.strip() != ""
