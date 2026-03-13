"""End-to-end integration tests for GraphPipeline.

Validates the full pipeline flow: facts -> verification -> graph ingestion -> query.
Uses NetworkXAdapter as the graph backend (zero Docker dependency).

Tests cover:
- End-to-end confirmed fact ingestion with query verification
- Multiple facts with mixed verification statuses
- Entity resolution across facts
- Timeline query for temporal facts
- Shortest path query between connected entities
- Lazy initialization of pipeline components
- on_verification_complete event handler
- Query convenience method
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import pytest
import pytest_asyncio

from osint_system.agents.sifters.graph.graph_ingestor import GraphIngestor
from osint_system.config.graph_config import GraphConfig
from osint_system.data_management.classification_store import ClassificationStore
from osint_system.data_management.fact_store import FactStore
from osint_system.data_management.graph.networkx_adapter import NetworkXAdapter
from osint_system.data_management.graph.schema import QueryResult
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
from osint_system.data_management.verification_store import VerificationStore
from osint_system.pipeline.graph_pipeline import GraphPipeline


# --- Constants ---

INV_ID = "inv-pipeline-test"


# --- Helpers ---


def _make_fact(
    fact_id: str,
    claim_text: str,
    entities: list[Entity],
    provenance: Provenance | None = None,
    quality: QualityMetrics | None = None,
    temporal: TemporalMarker | None = None,
) -> ExtractedFact:
    """Build an ExtractedFact for testing."""
    if provenance is None:
        provenance = Provenance(
            source_id=f"src-{fact_id}",
            quote=claim_text[:40],
            offsets={"start": 0, "end": len(claim_text)},
            source_type=SourceType.WIRE_SERVICE,
            hop_count=1,
        )
    if quality is None:
        quality = QualityMetrics(extraction_confidence=0.9, claim_clarity=0.85)

    return ExtractedFact(
        fact_id=fact_id,
        claim=Claim(
            text=claim_text, assertion_type="statement", claim_type="event"
        ),
        entities=entities,
        provenance=provenance,
        quality=quality,
        temporal=temporal,
    )


def _make_verification(
    fact_id: str,
    status: VerificationStatus = VerificationStatus.CONFIRMED,
    confidence_boost: float = 0.3,
) -> VerificationResult:
    """Build a VerificationResult."""
    return VerificationResult(
        fact_id=fact_id,
        investigation_id=INV_ID,
        status=status,
        original_confidence=0.5,
        confidence_boost=confidence_boost,
        final_confidence=min(1.0, 0.5 + confidence_boost),
        reasoning=f"Test verification for {fact_id}",
        query_attempts=1,
        queries_used=[f"query for {fact_id}"],
    )


def _make_classification(
    fact_id: str,
    impact_tier: ImpactTier = ImpactTier.CRITICAL,
    dubious_flags: list[DubiousFlag] | None = None,
) -> FactClassification:
    """Build a FactClassification."""
    return FactClassification(
        fact_id=fact_id,
        investigation_id=INV_ID,
        impact_tier=impact_tier,
        dubious_flags=dubious_flags or [],
    )


# --- Shared fixtures ---


@pytest_asyncio.fixture
async def networkx_adapter() -> NetworkXAdapter:
    """Fresh initialized NetworkXAdapter."""
    adapter = NetworkXAdapter()
    await adapter.initialize()
    return adapter


@pytest.fixture()
def graph_config() -> GraphConfig:
    """GraphConfig for tests: NetworkX fallback, no LLM extraction."""
    return GraphConfig(
        llm_relationship_extraction=False,
        use_networkx_fallback=True,
    )


@pytest_asyncio.fixture
async def stores_single_fact() -> (
    tuple[FactStore, VerificationStore, ClassificationStore]
):
    """Stores populated with 1 confirmed fact."""
    fs = FactStore()
    vs = VerificationStore()
    cs = ClassificationStore()

    fact = _make_fact(
        "fact-e2e-1",
        "[E1:Putin] visited [E2:Beijing]",
        entities=[
            Entity(
                id="E1",
                text="Putin",
                type=EntityType.PERSON,
                canonical="Vladimir Putin",
            ),
            Entity(
                id="E2",
                text="Beijing",
                type=EntityType.LOCATION,
                canonical="Beijing",
            ),
        ],
    )
    await fs.save_facts(INV_ID, [fact.model_dump(mode="json")])
    await vs.save_result(
        _make_verification("fact-e2e-1", VerificationStatus.CONFIRMED)
    )
    await cs.save_classification(
        _make_classification("fact-e2e-1", ImpactTier.CRITICAL)
    )

    return fs, vs, cs


@pytest_asyncio.fixture
async def stores_multiple_facts() -> (
    tuple[FactStore, VerificationStore, ClassificationStore]
):
    """Stores with 5 facts: 2 CONFIRMED, 1 REFUTED, 1 SUPERSEDED, 1 UNVERIFIABLE."""
    fs = FactStore()
    vs = VerificationStore()
    cs = ClassificationStore()

    facts = [
        _make_fact(
            "fact-m1",
            "[E1:Putin] visited [E2:Beijing] for talks",
            entities=[
                Entity(id="E1", text="Putin", type=EntityType.PERSON, canonical="Vladimir Putin"),
                Entity(id="E2", text="Beijing", type=EntityType.LOCATION, canonical="Beijing"),
            ],
        ),
        _make_fact(
            "fact-m2",
            "[E1:Putin] met [E2:Xi Jinping] in [E3:Moscow]",
            entities=[
                Entity(id="E1", text="Putin", type=EntityType.PERSON, canonical="Vladimir Putin"),
                Entity(id="E2", text="Xi Jinping", type=EntityType.PERSON, canonical="Xi Jinping"),
                Entity(id="E3", text="Moscow", type=EntityType.LOCATION, canonical="Moscow"),
            ],
        ),
        _make_fact(
            "fact-m3",
            "[E1:EU] imposed sanctions on [E2:Russia]",
            entities=[
                Entity(id="E1", text="EU", type=EntityType.ORGANIZATION, canonical="European Union"),
                Entity(id="E2", text="Russia", type=EntityType.LOCATION, canonical="Russia"),
            ],
        ),
        _make_fact(
            "fact-m4",
            "[E1:NATO] held emergency meeting about [E2:Ukraine]",
            entities=[
                Entity(id="E1", text="NATO", type=EntityType.ORGANIZATION, canonical="NATO"),
                Entity(id="E2", text="Ukraine", type=EntityType.LOCATION, canonical="Ukraine"),
            ],
        ),
        _make_fact(
            "fact-m5",
            "[E1:Biden] called [E2:Zelensky] for update",
            entities=[
                Entity(id="E1", text="Biden", type=EntityType.PERSON, canonical="Joe Biden"),
                Entity(id="E2", text="Zelensky", type=EntityType.PERSON, canonical="Volodymyr Zelensky"),
            ],
        ),
    ]

    await fs.save_facts(INV_ID, [f.model_dump(mode="json") for f in facts])

    statuses = [
        VerificationStatus.CONFIRMED,
        VerificationStatus.CONFIRMED,
        VerificationStatus.REFUTED,
        VerificationStatus.SUPERSEDED,
        VerificationStatus.UNVERIFIABLE,
    ]
    for fact, status in zip(facts, statuses):
        await vs.save_result(_make_verification(fact.fact_id, status))
        await cs.save_classification(
            _make_classification(fact.fact_id, ImpactTier.CRITICAL)
        )

    return fs, vs, cs


@pytest_asyncio.fixture
async def stores_entity_resolution() -> (
    tuple[FactStore, VerificationStore, ClassificationStore]
):
    """Two facts mentioning 'Vladimir Putin' with different text forms."""
    fs = FactStore()
    vs = VerificationStore()
    cs = ClassificationStore()

    facts = [
        _make_fact(
            "fact-er1",
            "[E1:Putin] announced new policy",
            entities=[
                Entity(id="E1", text="Putin", type=EntityType.PERSON, canonical="Vladimir Putin"),
            ],
        ),
        _make_fact(
            "fact-er2",
            "[E1:Vladimir Putin] signed agreement",
            entities=[
                Entity(id="E1", text="Vladimir Putin", type=EntityType.PERSON, canonical="Vladimir Putin"),
            ],
        ),
    ]

    await fs.save_facts(INV_ID, [f.model_dump(mode="json") for f in facts])
    for fact in facts:
        await vs.save_result(
            _make_verification(fact.fact_id, VerificationStatus.CONFIRMED)
        )
        await cs.save_classification(
            _make_classification(fact.fact_id, ImpactTier.CRITICAL)
        )

    return fs, vs, cs


@pytest_asyncio.fixture
async def stores_timeline() -> (
    tuple[FactStore, VerificationStore, ClassificationStore]
):
    """Multiple facts with temporal markers for the same entity."""
    fs = FactStore()
    vs = VerificationStore()
    cs = ClassificationStore()

    facts = [
        _make_fact(
            "fact-t1",
            "[E1:Putin] visited [E2:Beijing]",
            entities=[
                Entity(id="E1", text="Putin", type=EntityType.PERSON, canonical="Vladimir Putin"),
                Entity(id="E2", text="Beijing", type=EntityType.LOCATION, canonical="Beijing"),
            ],
            temporal=TemporalMarker(
                id="T1", value="2024-03-15", precision="day", temporal_precision="explicit"
            ),
        ),
        _make_fact(
            "fact-t2",
            "[E1:Putin] met [E2:Zelensky]",
            entities=[
                Entity(id="E1", text="Putin", type=EntityType.PERSON, canonical="Vladimir Putin"),
                Entity(id="E2", text="Zelensky", type=EntityType.PERSON, canonical="Volodymyr Zelensky"),
            ],
            temporal=TemporalMarker(
                id="T2", value="2024-01-10", precision="day", temporal_precision="explicit"
            ),
        ),
        _make_fact(
            "fact-t3",
            "[E1:Putin] addressed parliament",
            entities=[
                Entity(id="E1", text="Putin", type=EntityType.PERSON, canonical="Vladimir Putin"),
            ],
            temporal=TemporalMarker(
                id="T3", value="2024-06-20", precision="day", temporal_precision="explicit"
            ),
        ),
    ]

    await fs.save_facts(INV_ID, [f.model_dump(mode="json") for f in facts])
    for fact in facts:
        await vs.save_result(
            _make_verification(fact.fact_id, VerificationStatus.CONFIRMED)
        )
        await cs.save_classification(
            _make_classification(fact.fact_id, ImpactTier.CRITICAL)
        )

    return fs, vs, cs


@pytest_asyncio.fixture
async def stores_path() -> (
    tuple[FactStore, VerificationStore, ClassificationStore]
):
    """Facts connecting entities A-B-C via shared mentions."""
    fs = FactStore()
    vs = VerificationStore()
    cs = ClassificationStore()

    facts = [
        _make_fact(
            "fact-p1",
            "[E1:Putin] met [E2:Xi Jinping]",
            entities=[
                Entity(id="E1", text="Putin", type=EntityType.PERSON, canonical="Vladimir Putin"),
                Entity(id="E2", text="Xi Jinping", type=EntityType.PERSON, canonical="Xi Jinping"),
            ],
        ),
        _make_fact(
            "fact-p2",
            "[E1:Xi Jinping] called [E2:Biden]",
            entities=[
                Entity(id="E1", text="Xi Jinping", type=EntityType.PERSON, canonical="Xi Jinping"),
                Entity(id="E2", text="Biden", type=EntityType.PERSON, canonical="Joe Biden"),
            ],
        ),
    ]

    await fs.save_facts(INV_ID, [f.model_dump(mode="json") for f in facts])
    for fact in facts:
        await vs.save_result(
            _make_verification(fact.fact_id, VerificationStatus.CONFIRMED)
        )
        await cs.save_classification(
            _make_classification(fact.fact_id, ImpactTier.CRITICAL)
        )

    return fs, vs, cs


# --- Tests ---


class TestEndToEnd:
    """Full pipeline flow: store -> verify -> ingest -> query."""

    @pytest.mark.asyncio
    async def test_pipeline_end_to_end_confirmed_fact(
        self,
        networkx_adapter: NetworkXAdapter,
        graph_config: GraphConfig,
        stores_single_fact: tuple[FactStore, VerificationStore, ClassificationStore],
    ) -> None:
        """Confirmed fact flows through pipeline and is queryable."""
        fs, vs, cs = stores_single_fact

        pipeline = GraphPipeline(
            adapter=networkx_adapter,
            fact_store=fs,
            verification_store=vs,
            classification_store=cs,
            config=graph_config,
        )

        stats = await pipeline.run_ingestion(INV_ID)

        assert stats["facts_ingested"] >= 1
        assert stats["nodes_merged"] > 0

        # Query entity network for Putin -> should find the fact
        entity_id = f"{INV_ID}:Vladimir Putin"
        result = await networkx_adapter.query_entity_network(entity_id)

        assert result.node_count > 0
        # Find the fact node in results
        fact_nodes = [n for n in result.nodes if n.label == "Fact"]
        assert len(fact_nodes) >= 1
        assert fact_nodes[0].properties.get("verification_status") == "confirmed"

    @pytest.mark.asyncio
    async def test_pipeline_end_to_end_multiple_facts(
        self,
        networkx_adapter: NetworkXAdapter,
        graph_config: GraphConfig,
        stores_multiple_facts: tuple[FactStore, VerificationStore, ClassificationStore],
    ) -> None:
        """5 facts with mixed statuses: only CONFIRMED+SUPERSEDED ingested."""
        fs, vs, cs = stores_multiple_facts

        pipeline = GraphPipeline(
            adapter=networkx_adapter,
            fact_store=fs,
            verification_store=vs,
            classification_store=cs,
            config=graph_config,
        )

        stats = await pipeline.run_ingestion(INV_ID)

        # 2 CONFIRMED + 1 SUPERSEDED = 3 facts ingested
        assert stats["facts_ingested"] == 3

        # Fact-m3 (REFUTED) and fact-m5 (UNVERIFIABLE) should not be in graph
        assert "Fact:fact-m3" not in networkx_adapter._node_index
        assert "Fact:fact-m5" not in networkx_adapter._node_index

        # Fact-m1, m2 (CONFIRMED), m4 (SUPERSEDED) should be in graph
        assert "Fact:fact-m1" in networkx_adapter._node_index
        assert "Fact:fact-m2" in networkx_adapter._node_index
        assert "Fact:fact-m4" in networkx_adapter._node_index


class TestEntityResolutionPipeline:
    """Entity resolution through the pipeline."""

    @pytest.mark.asyncio
    async def test_pipeline_entity_resolution(
        self,
        networkx_adapter: NetworkXAdapter,
        graph_config: GraphConfig,
        stores_entity_resolution: tuple[FactStore, VerificationStore, ClassificationStore],
    ) -> None:
        """Two facts with 'Putin' and 'Vladimir Putin' resolve to one entity node."""
        fs, vs, cs = stores_entity_resolution

        pipeline = GraphPipeline(
            adapter=networkx_adapter,
            fact_store=fs,
            verification_store=vs,
            classification_store=cs,
            config=graph_config,
        )

        await pipeline.run_ingestion(INV_ID)

        # Find Entity nodes containing "Vladimir Putin"
        putin_nodes = [
            k
            for k in networkx_adapter._node_index
            if k.startswith("Entity:") and "Vladimir Putin" in k
        ]

        # Entity resolution: single node regardless of text form
        assert len(putin_nodes) == 1

        # Check aliases include both text forms
        putin_key = putin_nodes[0]
        putin_props = networkx_adapter._node_index[putin_key]
        aliases = putin_props.get("aliases", [])
        assert "Putin" in aliases
        assert "Vladimir Putin" in aliases


class TestTimelineQuery:
    """Timeline query through the pipeline."""

    @pytest.mark.asyncio
    async def test_pipeline_timeline_query(
        self,
        networkx_adapter: NetworkXAdapter,
        graph_config: GraphConfig,
        stores_timeline: tuple[FactStore, VerificationStore, ClassificationStore],
    ) -> None:
        """Facts with temporal markers are returned in chronological order."""
        fs, vs, cs = stores_timeline

        pipeline = GraphPipeline(
            adapter=networkx_adapter,
            fact_store=fs,
            verification_store=vs,
            classification_store=cs,
            config=graph_config,
        )

        await pipeline.run_ingestion(INV_ID)

        # Query timeline for Putin
        entity_id = f"{INV_ID}:Vladimir Putin"
        result = await networkx_adapter.query_timeline(entity_id)

        assert result.query_type == "timeline"
        assert result.metadata["fact_count"] == 3

        # Verify chronological order: 2024-01-10 < 2024-03-15 < 2024-06-20
        temporal_values = [
            n.properties.get("temporal_value") for n in result.nodes
        ]
        assert temporal_values == sorted(temporal_values)
        assert temporal_values[0] == "2024-01-10"
        assert temporal_values[-1] == "2024-06-20"


class TestShortestPath:
    """Shortest path query through the pipeline."""

    @pytest.mark.asyncio
    async def test_pipeline_shortest_path(
        self,
        networkx_adapter: NetworkXAdapter,
        graph_config: GraphConfig,
        stores_path: tuple[FactStore, VerificationStore, ClassificationStore],
    ) -> None:
        """Facts connecting A-B-C produce a valid shortest path."""
        fs, vs, cs = stores_path

        pipeline = GraphPipeline(
            adapter=networkx_adapter,
            fact_store=fs,
            verification_store=vs,
            classification_store=cs,
            config=graph_config,
        )

        await pipeline.run_ingestion(INV_ID)

        # Putin -> Xi Jinping -> Biden: path should exist
        from_entity = f"{INV_ID}:Vladimir Putin"
        to_entity = f"{INV_ID}:Joe Biden"

        result = await networkx_adapter.query_shortest_path(from_entity, to_entity)

        assert result.query_type == "shortest_path"
        assert result.node_count > 0
        assert result.metadata["path_length"] > 0

        # Path endpoints must be the queried entities
        node_ids = [n.id for n in result.nodes]
        assert any("Vladimir Putin" in nid for nid in node_ids)
        assert any("Joe Biden" in nid for nid in node_ids)

        # Path must traverse intermediate nodes (not direct connection)
        assert result.metadata["path_length"] >= 2


class TestPipelineLazyInit:
    """Test lazy initialization of pipeline components."""

    @pytest.mark.asyncio
    async def test_pipeline_lazy_init(
        self,
    ) -> None:
        """Pipeline with no args + NetworkX config lazy-inits without error."""
        # Create pipeline with only config (all stores lazy-created)
        config = GraphConfig(
            use_networkx_fallback=True,
            llm_relationship_extraction=False,
        )
        pipeline = GraphPipeline(config=config)

        # Call run_ingestion with a non-existent investigation
        # This should lazy-init adapter, stores, ingestor without error
        stats = await pipeline.run_ingestion("nonexistent-inv")

        # No facts to ingest, but no errors
        assert stats["nodes_merged"] == 0
        assert stats["edges_merged"] == 0


class TestEventHandler:
    """Test event handler wiring."""

    @pytest.mark.asyncio
    async def test_pipeline_on_verification_complete_handler(
        self,
        networkx_adapter: NetworkXAdapter,
        graph_config: GraphConfig,
        stores_single_fact: tuple[FactStore, VerificationStore, ClassificationStore],
    ) -> None:
        """on_verification_complete populates graph from verification summary."""
        fs, vs, cs = stores_single_fact

        pipeline = GraphPipeline(
            adapter=networkx_adapter,
            fact_store=fs,
            verification_store=vs,
            classification_store=cs,
            config=graph_config,
        )

        summary = {"total_verified": 1, "confirmed": 1}
        stats = await pipeline.on_verification_complete(INV_ID, summary)

        assert stats["facts_ingested"] >= 1
        assert "Fact:fact-e2e-1" in networkx_adapter._node_index


class TestQueryConvenience:
    """Test pipeline.query() convenience method."""

    @pytest.mark.asyncio
    async def test_pipeline_query_convenience(
        self,
        networkx_adapter: NetworkXAdapter,
        graph_config: GraphConfig,
        stores_single_fact: tuple[FactStore, VerificationStore, ClassificationStore],
    ) -> None:
        """pipeline.query('entity_network') returns a QueryResult."""
        fs, vs, cs = stores_single_fact

        pipeline = GraphPipeline(
            adapter=networkx_adapter,
            fact_store=fs,
            verification_store=vs,
            classification_store=cs,
            config=graph_config,
        )

        await pipeline.run_ingestion(INV_ID)

        entity_id = f"{INV_ID}:Vladimir Putin"
        result = await pipeline.query("entity_network", entity_id=entity_id)

        assert isinstance(result, QueryResult)
        assert result.query_type == "entity_network"
        assert result.node_count > 0

    @pytest.mark.asyncio
    async def test_pipeline_query_unknown_type_raises(
        self,
        networkx_adapter: NetworkXAdapter,
        graph_config: GraphConfig,
        stores_single_fact: tuple[FactStore, VerificationStore, ClassificationStore],
    ) -> None:
        """Unknown query type raises ValueError."""
        fs, vs, cs = stores_single_fact

        pipeline = GraphPipeline(
            adapter=networkx_adapter,
            fact_store=fs,
            verification_store=vs,
            classification_store=cs,
            config=graph_config,
        )

        with pytest.raises(ValueError, match="Unknown query_type"):
            await pipeline.query("nonexistent_query_type")
