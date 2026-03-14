"""Tests for DataAggregator - collects investigation data into InvestigationSnapshot.

Uses populated in-memory stores with realistic test data:
- 4 facts for investigation "inv-test" with provenance, temporal markers, entities
- Classifications: 2 clean, 1 phantom, 1 fog
- Verification results: 1 CONFIRMED, 1 REFUTED, 1 UNVERIFIABLE, 1 PENDING
"""

import pytest
import pytest_asyncio

from osint_system.analysis.data_aggregator import DataAggregator
from osint_system.analysis.schemas import InvestigationSnapshot
from osint_system.data_management.classification_store import ClassificationStore
from osint_system.data_management.fact_store import FactStore
from osint_system.data_management.schemas.classification_schema import (
    DubiousFlag,
    FactClassification,
    ImpactTier,
)
from osint_system.data_management.schemas.verification_schema import (
    VerificationResult,
    VerificationStatus,
)
from osint_system.data_management.verification_store import VerificationStore


INVESTIGATION_ID = "inv-test"


def _make_fact(fact_id: str, claim_text: str, **extras) -> dict:
    """Build a fact dict consistent with FactStore format."""
    fact = {
        "fact_id": fact_id,
        "content_hash": f"hash-{fact_id}",
        "claim": {"text": claim_text, "assertion_type": "statement", "claim_type": "event"},
        "entities": extras.get("entities", []),
        "provenance": extras.get("provenance", {
            "source_id": f"source-{fact_id}",
            "source_url": f"https://example.com/article-{fact_id}",
            "source_type": "news_outlet",
        }),
        "quality": extras.get("quality", {
            "extraction_confidence": 0.9,
            "claim_clarity": 0.85,
        }),
        "variants": [],
    }
    if "temporal" in extras:
        fact["temporal"] = extras["temporal"]
    return fact


@pytest_asyncio.fixture
async def fact_store() -> FactStore:
    """FactStore populated with 4 test facts."""
    store = FactStore()
    facts = [
        _make_fact(
            "fact-001",
            "[E1:Putin] visited [E2:Beijing] in [T1:March 2024]",
            temporal={"id": "T1", "value": "2024-03", "precision": "month", "temporal_precision": "explicit"},
            provenance={
                "source_id": "apnews",
                "source_url": "https://apnews.com/article/putin-beijing",
                "source_type": "wire_service",
            },
            entities=[{"id": "E1", "text": "Putin", "type": "PERSON", "canonical": "Vladimir Putin"}],
        ),
        _make_fact(
            "fact-002",
            "[E1:Russia] deployed additional troops to [E2:eastern Ukraine]",
            temporal={"id": "T1", "value": "2024-01-15", "precision": "day", "temporal_precision": "explicit"},
            provenance={
                "source_id": "reuters",
                "source_url": "https://reuters.com/article/russia-troops",
                "source_type": "wire_service",
            },
        ),
        _make_fact(
            "fact-003",
            "Sanctions impact remains limited according to [E1:unnamed officials]",
            provenance={
                "source_id": "bbc",
                "source_url": "https://bbc.com/news/sanctions",
                "source_type": "news_outlet",
            },
        ),
        _make_fact(
            "fact-004",
            "[E1:China] increased energy imports from [E2:Russia] by 30%",
            temporal={"id": "T1", "value": "2024-02", "precision": "month", "temporal_precision": "inferred"},
            provenance={
                "source_id": "social-post-1",
                "source_url": "https://twitter.com/user/status/123",
                "source_type": "social_media",
            },
        ),
    ]
    await store.save_facts(INVESTIGATION_ID, facts, {"objective": "Track Russia-Ukraine escalation"})
    return store


@pytest_asyncio.fixture
async def classification_store() -> ClassificationStore:
    """ClassificationStore with classifications for 4 facts: 2 clean, 1 phantom, 1 fog."""
    store = ClassificationStore()

    classifications = [
        FactClassification(
            fact_id="fact-001",
            investigation_id=INVESTIGATION_ID,
            impact_tier=ImpactTier.CRITICAL,
            dubious_flags=[],
            priority_score=0.0,
            credibility_score=0.9,
        ),
        FactClassification(
            fact_id="fact-002",
            investigation_id=INVESTIGATION_ID,
            impact_tier=ImpactTier.CRITICAL,
            dubious_flags=[],
            priority_score=0.0,
            credibility_score=0.85,
        ),
        FactClassification(
            fact_id="fact-003",
            investigation_id=INVESTIGATION_ID,
            impact_tier=ImpactTier.LESS_CRITICAL,
            dubious_flags=[DubiousFlag.PHANTOM],
            priority_score=0.6,
            credibility_score=0.4,
        ),
        FactClassification(
            fact_id="fact-004",
            investigation_id=INVESTIGATION_ID,
            impact_tier=ImpactTier.LESS_CRITICAL,
            dubious_flags=[DubiousFlag.FOG],
            priority_score=0.5,
            credibility_score=0.35,
        ),
    ]

    await store.save_classifications(INVESTIGATION_ID, classifications)
    return store


@pytest_asyncio.fixture
async def verification_store() -> VerificationStore:
    """VerificationStore with 4 results: CONFIRMED, REFUTED, UNVERIFIABLE, PENDING."""
    store = VerificationStore()

    results = [
        VerificationResult(
            fact_id="fact-001",
            investigation_id=INVESTIGATION_ID,
            status=VerificationStatus.CONFIRMED,
            original_confidence=0.8,
            confidence_boost=0.3,
            final_confidence=1.0,
            supporting_evidence=[{
                "source_url": "https://apnews.com/confirm",
                "source_domain": "apnews.com",
                "source_type": "wire_service",
                "authority_score": 0.9,
                "snippet": "Officials confirmed the visit",
                "supports_claim": True,
                "relevance_score": 0.95,
            }],
            query_attempts=1,
            reasoning="High-authority wire service confirms",
        ),
        VerificationResult(
            fact_id="fact-002",
            investigation_id=INVESTIGATION_ID,
            status=VerificationStatus.REFUTED,
            original_confidence=0.6,
            confidence_boost=0.0,
            final_confidence=0.2,
            refuting_evidence=[{
                "source_url": "https://reuters.com/refute",
                "source_domain": "reuters.com",
                "source_type": "wire_service",
                "authority_score": 0.9,
                "snippet": "No evidence of additional troop deployment",
                "supports_claim": False,
                "relevance_score": 0.85,
            }],
            query_attempts=2,
            reasoning="Reuters directly contradicts the claim",
        ),
        VerificationResult(
            fact_id="fact-003",
            investigation_id=INVESTIGATION_ID,
            status=VerificationStatus.UNVERIFIABLE,
            original_confidence=0.3,
            confidence_boost=0.0,
            final_confidence=0.3,
            query_attempts=3,
            reasoning="No corroborating evidence found after 3 queries",
        ),
        VerificationResult(
            fact_id="fact-004",
            investigation_id=INVESTIGATION_ID,
            status=VerificationStatus.PENDING,
            original_confidence=0.4,
            confidence_boost=0.0,
            final_confidence=0.4,
            query_attempts=0,
            reasoning="Queued for verification",
        ),
    ]

    for result in results:
        await store.save_result(result)

    return store


@pytest_asyncio.fixture
async def aggregator(
    fact_store: FactStore,
    classification_store: ClassificationStore,
    verification_store: VerificationStore,
) -> DataAggregator:
    """DataAggregator with populated stores (no graph_pipeline)."""
    return DataAggregator(
        fact_store=fact_store,
        classification_store=classification_store,
        verification_store=verification_store,
        graph_pipeline=None,
    )


@pytest.mark.asyncio
async def test_aggregate_returns_snapshot(aggregator: DataAggregator) -> None:
    """aggregate() returns an InvestigationSnapshot with correct investigation_id."""
    snapshot = await aggregator.aggregate(INVESTIGATION_ID)
    assert isinstance(snapshot, InvestigationSnapshot)
    assert snapshot.investigation_id == INVESTIGATION_ID


@pytest.mark.asyncio
async def test_aggregate_fact_count(aggregator: DataAggregator) -> None:
    """Snapshot contains 4 facts."""
    snapshot = await aggregator.aggregate(INVESTIGATION_ID)
    assert snapshot.fact_count == 4
    assert len(snapshot.facts) == 4


@pytest.mark.asyncio
async def test_aggregate_verification_counts(aggregator: DataAggregator) -> None:
    """Snapshot has correct verification status counts."""
    snapshot = await aggregator.aggregate(INVESTIGATION_ID)
    assert snapshot.confirmed_count == 1
    assert snapshot.refuted_count == 1
    assert snapshot.unverifiable_count == 1


@pytest.mark.asyncio
async def test_aggregate_dubious_count(aggregator: DataAggregator) -> None:
    """Snapshot dubious_count is 2 (phantom + fog)."""
    snapshot = await aggregator.aggregate(INVESTIGATION_ID)
    assert snapshot.dubious_count == 2


@pytest.mark.asyncio
async def test_aggregate_source_inventory(aggregator: DataAggregator) -> None:
    """Source inventory has entries with fact counts."""
    snapshot = await aggregator.aggregate(INVESTIGATION_ID)
    assert len(snapshot.source_inventory) > 0

    # Each source should have at least 1 fact
    for entry in snapshot.source_inventory:
        assert entry.fact_count >= 1
        assert entry.source_id != ""

    # Total facts across sources should equal total facts
    total_source_facts = sum(e.fact_count for e in snapshot.source_inventory)
    assert total_source_facts == 4


@pytest.mark.asyncio
async def test_aggregate_timeline(aggregator: DataAggregator) -> None:
    """Timeline entries are sorted chronologically."""
    snapshot = await aggregator.aggregate(INVESTIGATION_ID)

    # 3 facts have temporal markers (fact-001, fact-002, fact-004)
    assert len(snapshot.timeline_entries) == 3

    # Verify chronological ordering
    timestamps = [e.timestamp for e in snapshot.timeline_entries]
    assert timestamps == sorted(timestamps)

    # First entry should be January (2024-01-15), then February, then March
    assert snapshot.timeline_entries[0].timestamp == "2024-01-15"
    assert snapshot.timeline_entries[1].timestamp == "2024-02"
    assert snapshot.timeline_entries[2].timestamp == "2024-03"


@pytest.mark.asyncio
async def test_aggregate_no_graph_pipeline(aggregator: DataAggregator) -> None:
    """Works without graph_pipeline; graph_summary is empty dict."""
    snapshot = await aggregator.aggregate(INVESTIGATION_ID)
    assert snapshot.graph_summary == {}


@pytest.mark.asyncio
async def test_aggregate_empty_investigation(aggregator: DataAggregator) -> None:
    """aggregate() for nonexistent investigation returns zero counts and empty lists."""
    snapshot = await aggregator.aggregate("nonexistent-inv")
    assert snapshot.investigation_id == "nonexistent-inv"
    assert snapshot.fact_count == 0
    assert snapshot.confirmed_count == 0
    assert snapshot.refuted_count == 0
    assert snapshot.unverifiable_count == 0
    assert snapshot.dubious_count == 0
    assert snapshot.facts == []
    assert snapshot.classifications == []
    assert snapshot.verification_results == []
    assert snapshot.source_inventory == []
    assert snapshot.timeline_entries == []


@pytest.mark.asyncio
async def test_aggregate_token_estimate(aggregator: DataAggregator) -> None:
    """token_estimate() returns a positive integer for a populated snapshot."""
    snapshot = await aggregator.aggregate(INVESTIGATION_ID)
    estimate = snapshot.token_estimate()
    assert isinstance(estimate, int)
    assert estimate > 0


@pytest.mark.asyncio
async def test_aggregate_classifications_present(aggregator: DataAggregator) -> None:
    """Snapshot contains all 4 classifications."""
    snapshot = await aggregator.aggregate(INVESTIGATION_ID)
    assert len(snapshot.classifications) == 4


@pytest.mark.asyncio
async def test_aggregate_verification_results_present(aggregator: DataAggregator) -> None:
    """Snapshot contains all 4 verification result dicts."""
    snapshot = await aggregator.aggregate(INVESTIGATION_ID)
    assert len(snapshot.verification_results) == 4

    # Verify they are dicts (serialized from VerificationResultRecord)
    for vr in snapshot.verification_results:
        assert isinstance(vr, dict)
        assert "fact_id" in vr
        assert "status" in vr


@pytest.mark.asyncio
async def test_aggregate_objective_from_metadata(
    fact_store: FactStore,
    classification_store: ClassificationStore,
    verification_store: VerificationStore,
) -> None:
    """Snapshot objective is extracted from investigation metadata."""
    agg = DataAggregator(
        fact_store=fact_store,
        classification_store=classification_store,
        verification_store=verification_store,
    )
    snapshot = await agg.aggregate(INVESTIGATION_ID)
    assert snapshot.objective == "Track Russia-Ukraine escalation"


@pytest.mark.asyncio
async def test_source_inventory_authority_from_verification(aggregator: DataAggregator) -> None:
    """Source inventory picks up authority_score from verification evidence."""
    snapshot = await aggregator.aggregate(INVESTIGATION_ID)

    # Find the apnews source entry
    apnews_entries = [e for e in snapshot.source_inventory if "apnews" in e.source_domain]
    assert len(apnews_entries) >= 1
    apnews = apnews_entries[0]
    assert apnews.authority_score >= 0.9  # From verification evidence


@pytest.mark.asyncio
async def test_timeline_confidence_from_classification(aggregator: DataAggregator) -> None:
    """Timeline entries derive confidence from classification credibility scores."""
    snapshot = await aggregator.aggregate(INVESTIGATION_ID)

    # fact-001 has credibility_score 0.9 -> should be "high" confidence
    fact_001_entries = [e for e in snapshot.timeline_entries if "fact-001" in e.fact_ids]
    assert len(fact_001_entries) == 1
    assert fact_001_entries[0].confidence.level == "high"

    # fact-004 has credibility_score 0.35 -> should be "low" confidence
    fact_004_entries = [e for e in snapshot.timeline_entries if "fact-004" in e.fact_ids]
    assert len(fact_004_entries) == 1
    assert fact_004_entries[0].confidence.level == "low"
