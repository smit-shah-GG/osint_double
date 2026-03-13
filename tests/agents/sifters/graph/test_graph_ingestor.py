"""Unit tests for GraphIngestor event-driven graph ingestion.

Tests cover:
- Single fact ingestion (nodes, edges, stats)
- Investigation node creation
- Verification metadata propagation to fact nodes
- Bulk investigation ingestion with status filtering
- Bulk all-statuses ingestion
- Entity resolution across facts sharing entities
- MessageBus event handler parsing
- Registration subscription to verification.complete
- Missing fact_id error handling
- Stats return format validation
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from osint_system.agents.sifters.graph.graph_ingestor import GraphIngestor
from osint_system.config.graph_config import GraphConfig
from osint_system.data_management.classification_store import ClassificationStore
from osint_system.data_management.fact_store import FactStore
from osint_system.data_management.graph.networkx_adapter import NetworkXAdapter
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


# --- Constants ---

INV_ID = "inv-graph-test"


# --- Helpers ---


def _make_fact(
    fact_id: str = "fact-001",
    claim_text: str = "[E1:Putin] visited [E2:Beijing]",
    entities: list[Entity] | None = None,
    provenance: Provenance | None = None,
    quality: QualityMetrics | None = None,
) -> ExtractedFact:
    """Build a minimal ExtractedFact for testing."""
    if entities is None:
        entities = [
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
        claim=Claim(
            text=claim_text, assertion_type="statement", claim_type="event"
        ),
        entities=entities,
        provenance=provenance,
        quality=quality,
    )


def _make_verification(
    fact_id: str = "fact-001",
    status: VerificationStatus = VerificationStatus.CONFIRMED,
    original_confidence: float = 0.5,
    confidence_boost: float = 0.3,
) -> VerificationResult:
    """Build a minimal VerificationResult."""
    return VerificationResult(
        fact_id=fact_id,
        investigation_id=INV_ID,
        status=status,
        original_confidence=original_confidence,
        confidence_boost=confidence_boost,
        final_confidence=min(1.0, original_confidence + confidence_boost),
        reasoning="Test verification",
        query_attempts=1,
        queries_used=["test query"],
    )


def _make_classification(
    fact_id: str = "fact-001",
    impact_tier: ImpactTier = ImpactTier.CRITICAL,
    dubious_flags: list[DubiousFlag] | None = None,
) -> FactClassification:
    """Build a minimal FactClassification."""
    if dubious_flags is None:
        dubious_flags = [DubiousFlag.PHANTOM]
    return FactClassification(
        fact_id=fact_id,
        investigation_id=INV_ID,
        impact_tier=impact_tier,
        dubious_flags=dubious_flags,
    )


# --- Fixtures ---


@pytest_asyncio.fixture
async def networkx_adapter() -> NetworkXAdapter:
    """Fresh NetworkXAdapter, initialized."""
    adapter = NetworkXAdapter()
    await adapter.initialize()
    return adapter


@pytest_asyncio.fixture
async def fact_store() -> FactStore:
    """FactStore populated with 3 test facts."""
    store = FactStore()

    facts = [
        _make_fact("fact-001").model_dump(mode="json"),
        _make_fact(
            "fact-002",
            claim_text="[E1:Putin] met [E2:Xi Jinping] in [E3:Moscow]",
            entities=[
                Entity(
                    id="E1",
                    text="Putin",
                    type=EntityType.PERSON,
                    canonical="Vladimir Putin",
                ),
                Entity(
                    id="E2",
                    text="Xi Jinping",
                    type=EntityType.PERSON,
                    canonical="Xi Jinping",
                ),
                Entity(
                    id="E3",
                    text="Moscow",
                    type=EntityType.LOCATION,
                    canonical="Moscow",
                ),
            ],
            provenance=Provenance(
                source_id="src-ap-001",
                quote="Putin met Xi Jinping in Moscow",
                offsets={"start": 0, "end": 30},
                source_type=SourceType.WIRE_SERVICE,
                hop_count=1,
            ),
        ).model_dump(mode="json"),
        _make_fact(
            "fact-003",
            claim_text="[E1:EU] sanctions target [E2:Russia]",
            entities=[
                Entity(
                    id="E1",
                    text="EU",
                    type=EntityType.ORGANIZATION,
                    canonical="European Union",
                ),
                Entity(
                    id="E2",
                    text="Russia",
                    type=EntityType.LOCATION,
                    canonical="Russia",
                ),
            ],
            provenance=Provenance(
                source_id="src-bbc-001",
                quote="EU sanctions target Russia",
                offsets={"start": 0, "end": 25},
                source_type=SourceType.NEWS_OUTLET,
                hop_count=2,
            ),
        ).model_dump(mode="json"),
    ]

    await store.save_facts(INV_ID, facts)
    return store


@pytest_asyncio.fixture
async def verification_store() -> VerificationStore:
    """VerificationStore with results: 1 CONFIRMED, 1 REFUTED, 1 SUPERSEDED."""
    store = VerificationStore()
    await store.save_result(
        _make_verification("fact-001", VerificationStatus.CONFIRMED)
    )
    await store.save_result(
        _make_verification("fact-002", VerificationStatus.REFUTED)
    )
    await store.save_result(
        _make_verification("fact-003", VerificationStatus.SUPERSEDED)
    )
    return store


@pytest_asyncio.fixture
async def classification_store() -> ClassificationStore:
    """ClassificationStore with classifications for 3 facts."""
    store = ClassificationStore()
    await store.save_classification(
        _make_classification("fact-001", ImpactTier.CRITICAL, [DubiousFlag.PHANTOM])
    )
    await store.save_classification(
        _make_classification("fact-002", ImpactTier.LESS_CRITICAL, [DubiousFlag.FOG])
    )
    await store.save_classification(
        _make_classification("fact-003", ImpactTier.CRITICAL, [DubiousFlag.ANOMALY])
    )
    return store


@pytest.fixture()
def graph_config() -> GraphConfig:
    """GraphConfig with LLM extraction disabled."""
    return GraphConfig(
        llm_relationship_extraction=False,
        use_networkx_fallback=True,
    )


@pytest_asyncio.fixture
async def ingestor(
    networkx_adapter: NetworkXAdapter,
    fact_store: FactStore,
    verification_store: VerificationStore,
    classification_store: ClassificationStore,
    graph_config: GraphConfig,
) -> GraphIngestor:
    """Fully wired GraphIngestor with initialized adapter."""
    return GraphIngestor(
        adapter=networkx_adapter,
        fact_store=fact_store,
        verification_store=verification_store,
        classification_store=classification_store,
        config=graph_config,
    )


# --- Tests ---


class TestIngestSingleFact:
    """Test single fact ingestion."""

    @pytest.mark.asyncio
    async def test_ingest_single_fact(
        self,
        ingestor: GraphIngestor,
        networkx_adapter: NetworkXAdapter,
    ) -> None:
        """Ingesting one confirmed fact produces correct nodes and edges."""
        stats = await ingestor.ingest_fact(INV_ID, "fact-001")

        assert stats["nodes_merged"] > 0
        assert stats["edges_merged"] > 0

        # Should have Fact, Entity (x2), Source, Investigation nodes at minimum
        assert len(networkx_adapter._node_index) >= 5

        # Fact node must exist
        assert "Fact:fact-001" in networkx_adapter._node_index

    @pytest.mark.asyncio
    async def test_ingest_single_fact_creates_investigation_node(
        self,
        ingestor: GraphIngestor,
        networkx_adapter: NetworkXAdapter,
    ) -> None:
        """Investigation node exists after ingestion."""
        await ingestor.ingest_fact(INV_ID, "fact-001")
        assert f"Investigation:{INV_ID}" in networkx_adapter._node_index

    @pytest.mark.asyncio
    async def test_ingest_single_fact_with_verification_metadata(
        self,
        ingestor: GraphIngestor,
        networkx_adapter: NetworkXAdapter,
    ) -> None:
        """Fact node has verification_status property after ingestion."""
        await ingestor.ingest_fact(INV_ID, "fact-001")

        fact_props = networkx_adapter._node_index.get("Fact:fact-001", {})
        assert fact_props.get("verification_status") == "confirmed"
        assert "final_confidence" in fact_props

    @pytest.mark.asyncio
    async def test_ingest_fact_returns_stats(
        self,
        ingestor: GraphIngestor,
    ) -> None:
        """Returns dict with nodes_merged and edges_merged counts."""
        stats = await ingestor.ingest_fact(INV_ID, "fact-001")
        assert "nodes_merged" in stats
        assert "edges_merged" in stats
        assert isinstance(stats["nodes_merged"], int)
        assert isinstance(stats["edges_merged"], int)


class TestIngestInvestigation:
    """Test bulk investigation ingestion with status filtering."""

    @pytest.mark.asyncio
    async def test_ingest_investigation_filters_status(
        self,
        ingestor: GraphIngestor,
        networkx_adapter: NetworkXAdapter,
    ) -> None:
        """Only CONFIRMED and SUPERSEDED facts ingested; REFUTED skipped."""
        stats = await ingestor.ingest_investigation(INV_ID)

        # fact-001 (CONFIRMED) and fact-003 (SUPERSEDED) ingested; fact-002 (REFUTED) skipped
        assert stats["facts_ingested"] == 2

        # Fact nodes for confirmed/superseded must exist
        assert "Fact:fact-001" in networkx_adapter._node_index
        assert "Fact:fact-003" in networkx_adapter._node_index

        # Fact-002 (REFUTED) must NOT exist
        assert "Fact:fact-002" not in networkx_adapter._node_index

    @pytest.mark.asyncio
    async def test_ingest_investigation_all_includes_everything(
        self,
        ingestor: GraphIngestor,
        networkx_adapter: NetworkXAdapter,
    ) -> None:
        """All 3 facts ingested regardless of verification status."""
        stats = await ingestor.ingest_investigation_all(INV_ID)

        assert stats["facts_ingested"] == 3

        # All three fact nodes must exist
        assert "Fact:fact-001" in networkx_adapter._node_index
        assert "Fact:fact-002" in networkx_adapter._node_index
        assert "Fact:fact-003" in networkx_adapter._node_index


class TestEntityResolution:
    """Test entity resolution across multiple facts."""

    @pytest.mark.asyncio
    async def test_entity_resolution_across_facts(
        self,
        ingestor: GraphIngestor,
        networkx_adapter: NetworkXAdapter,
    ) -> None:
        """Two facts mentioning 'Vladimir Putin' produce a single entity node."""
        # fact-001 and fact-002 both reference "Vladimir Putin"
        # ingest_investigation_all uses shared mapper so entity resolution works
        await ingestor.ingest_investigation_all(INV_ID)

        # Count Entity nodes with canonical "Vladimir Putin"
        putin_nodes = [
            k
            for k in networkx_adapter._node_index
            if k.startswith("Entity:") and "Vladimir Putin" in k
        ]

        # Entity resolution via batch mapper: single node for Putin
        assert len(putin_nodes) == 1


class TestEventHandler:
    """Test MessageBus event handling."""

    @pytest.mark.asyncio
    async def test_event_handler_parses_message(
        self,
        ingestor: GraphIngestor,
    ) -> None:
        """Calling _on_verification_complete with mock message invokes ingest_fact."""
        message = {
            "id": "msg-001",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "key": "verification.complete",
            "payload": {
                "fact_id": "fact-001",
                "investigation_id": INV_ID,
            },
        }

        with patch.object(
            ingestor, "ingest_fact", new_callable=AsyncMock
        ) as mock_ingest:
            mock_ingest.return_value = {"nodes_merged": 5, "edges_merged": 3}
            await ingestor._on_verification_complete(message)
            mock_ingest.assert_called_once_with(INV_ID, "fact-001")

    def test_register_subscribes_to_bus(
        self,
        ingestor: GraphIngestor,
    ) -> None:
        """Registering with a mock MessageBus calls subscribe_to_pattern."""
        mock_bus = MagicMock()
        ingestor.register(bus=mock_bus)

        mock_bus.subscribe_to_pattern.assert_called_once_with(
            "graph_ingestor",
            "verification.complete",
            ingestor._on_verification_complete,
        )


class TestErrorHandling:
    """Test error scenarios."""

    @pytest.mark.asyncio
    async def test_ingest_fact_missing_fact_id(
        self,
        ingestor: GraphIngestor,
    ) -> None:
        """fact_id not found in store returns zero counts."""
        stats = await ingestor.ingest_fact(INV_ID, "nonexistent-fact")
        assert stats["nodes_merged"] == 0
        assert stats["edges_merged"] == 0

    @pytest.mark.asyncio
    async def test_event_handler_incomplete_payload(
        self,
        ingestor: GraphIngestor,
    ) -> None:
        """Event with missing fact_id in payload does not crash."""
        message = {
            "id": "msg-bad",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "key": "verification.complete",
            "payload": {"investigation_id": INV_ID},
        }

        # Should log warning but not raise
        await ingestor._on_verification_complete(message)

    def test_register_without_bus_logs_warning(
        self,
        ingestor: GraphIngestor,
    ) -> None:
        """Registering without any bus does not raise; logs warning."""
        # ingestor has no bus by default
        ingestor.register()  # Should not raise
