"""Tests for InvestigationArchive self-contained JSON bundle.

Verifies that InvestigationArchive creates valid JSON archives with
all investigation data, schema versioning, statistics, and round-trip
load/validate capability.
"""

import json
from pathlib import Path

import pytest
import pytest_asyncio

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
from osint_system.database.archive import InvestigationArchive

INVESTIGATION_ID = "inv-archive-test"


def _make_test_facts() -> list[dict]:
    """Create 3 test facts for archive testing."""
    return [
        {
            "fact_id": "fact-a1",
            "content_hash": "hash-a1",
            "claim": {
                "text": "[E1:Putin] met [E2:Xi] in Beijing",
                "assertion_type": "statement",
                "claim_type": "event",
            },
            "entities": [
                {"id": "E1", "text": "Putin", "type": "PERSON", "canonical": "Vladimir Putin"},
                {"id": "E2", "text": "Xi", "type": "PERSON", "canonical": "Xi Jinping"},
            ],
            "quality": {"extraction_confidence": 0.9, "claim_clarity": 0.85},
            "provenance": {
                "source_id": "src-ap-001",
                "source_type": "wire_service",
                "quote": "Putin met Xi in Beijing",
                "offsets": {"start": 0, "end": 23},
            },
        },
        {
            "fact_id": "fact-a2",
            "content_hash": "hash-a2",
            "claim": {
                "text": "Trade agreement signed worth $50B",
                "assertion_type": "statement",
                "claim_type": "event",
            },
            "entities": [],
            "quality": {"extraction_confidence": 0.75, "claim_clarity": 0.6},
            "provenance": {
                "source_id": "src-bbc-001",
                "source_type": "news_outlet",
                "quote": "A trade agreement was signed",
                "offsets": {"start": 100, "end": 128},
            },
        },
        {
            "fact_id": "fact-a3",
            "content_hash": "hash-a3",
            "claim": {
                "text": "Diplomatic tensions rose between NATO and Russia",
                "assertion_type": "statement",
                "claim_type": "state",
            },
            "entities": [],
            "quality": {"extraction_confidence": 0.82, "claim_clarity": 0.78},
            "provenance": {
                "source_id": "src-nyt-001",
                "source_type": "news_outlet",
                "quote": "Tensions rose between NATO and Russia",
                "offsets": {"start": 200, "end": 237},
            },
        },
    ]


def _make_test_classifications() -> list[FactClassification]:
    """Create classifications for archive test facts."""
    return [
        FactClassification(
            fact_id="fact-a1",
            investigation_id=INVESTIGATION_ID,
            impact_tier=ImpactTier.CRITICAL,
            priority_score=0.85,
            credibility_score=0.8,
        ),
        FactClassification(
            fact_id="fact-a2",
            investigation_id=INVESTIGATION_ID,
            impact_tier=ImpactTier.LESS_CRITICAL,
            dubious_flags=[DubiousFlag.FOG],
            priority_score=0.5,
            credibility_score=0.4,
        ),
    ]


def _make_test_verifications() -> list[VerificationResult]:
    """Create verification results for archive test facts."""
    return [
        VerificationResult(
            fact_id="fact-a1",
            investigation_id=INVESTIGATION_ID,
            status=VerificationStatus.CONFIRMED,
            original_confidence=0.8,
            confidence_boost=0.15,
            final_confidence=0.95,
            query_attempts=1,
            queries_used=["Putin Xi Beijing meeting"],
            reasoning="Wire service confirmed the meeting",
        ),
        VerificationResult(
            fact_id="fact-a2",
            investigation_id=INVESTIGATION_ID,
            status=VerificationStatus.UNVERIFIABLE,
            original_confidence=0.4,
            confidence_boost=0.0,
            final_confidence=0.4,
            query_attempts=3,
            queries_used=["trade agreement 50B", "bilateral trade deal", "trade pact"],
            origin_dubious_flags=[DubiousFlag.FOG],
            reasoning="Exhausted queries without confirmation",
        ),
    ]


@pytest_asyncio.fixture
async def populated_stores():
    """Create and populate stores with test data."""
    fact_store = FactStore()
    classification_store = ClassificationStore()
    verification_store = VerificationStore()

    await fact_store.save_facts(
        INVESTIGATION_ID,
        _make_test_facts(),
        investigation_metadata={"objective": "Analyze geopolitical summit"},
    )

    for classification in _make_test_classifications():
        await classification_store.save_classification(classification)

    for result in _make_test_verifications():
        await verification_store.save_result(result)

    return fact_store, classification_store, verification_store


@pytest_asyncio.fixture
async def archive(populated_stores, tmp_path):
    """Create InvestigationArchive with populated stores."""
    fact_store, classification_store, verification_store = populated_stores
    return InvestigationArchive(
        fact_store=fact_store,
        classification_store=classification_store,
        verification_store=verification_store,
        output_dir=str(tmp_path),
    )


@pytest.mark.asyncio
async def test_create_archive_file(archive, tmp_path):
    """Creates JSON file at expected path."""
    path = await archive.create_archive(INVESTIGATION_ID)

    assert path.exists()
    assert path.suffix == ".json"
    assert path.name == f"{INVESTIGATION_ID}_archive.json"
    assert path.parent == tmp_path


@pytest.mark.asyncio
async def test_archive_schema_version(archive):
    """Archive has schema_version '1.0'."""
    path = await archive.create_archive(INVESTIGATION_ID)

    with open(path) as f:
        data = json.load(f)

    assert data["schema_version"] == "1.0"
    assert data["archive_type"] == "investigation_archive"


@pytest.mark.asyncio
async def test_archive_contains_facts(archive):
    """data.facts list has correct count."""
    path = await archive.create_archive(INVESTIGATION_ID)

    with open(path) as f:
        data = json.load(f)

    assert len(data["data"]["facts"]) == 3


@pytest.mark.asyncio
async def test_archive_contains_classifications(archive):
    """data.classifications is populated."""
    path = await archive.create_archive(INVESTIGATION_ID)

    with open(path) as f:
        data = json.load(f)

    assert len(data["data"]["classifications"]) == 2


@pytest.mark.asyncio
async def test_archive_contains_verifications(archive):
    """data.verification_results is populated."""
    path = await archive.create_archive(INVESTIGATION_ID)

    with open(path) as f:
        data = json.load(f)

    assert len(data["data"]["verification_results"]) == 2


@pytest.mark.asyncio
async def test_archive_statistics(archive):
    """Statistics dict has correct counts."""
    path = await archive.create_archive(INVESTIGATION_ID)

    with open(path) as f:
        data = json.load(f)

    stats = data["statistics"]
    assert stats["fact_count"] == 3
    assert stats["classification_count"] == 2
    assert stats["verification_count"] == 2
    assert stats["confirmed_count"] == 1
    assert stats["refuted_count"] == 0
    # fact-a2 is unverifiable -> counted as dubious
    assert stats["dubious_count"] == 1


@pytest.mark.asyncio
async def test_archive_roundtrip(archive):
    """create_archive then load_archive returns same data."""
    path = await archive.create_archive(INVESTIGATION_ID)

    loaded = await InvestigationArchive.load_archive(path)

    assert loaded["schema_version"] == "1.0"
    assert loaded["investigation_id"] == INVESTIGATION_ID
    assert len(loaded["data"]["facts"]) == 3
    assert len(loaded["data"]["classifications"]) == 2
    assert len(loaded["data"]["verification_results"]) == 2
    assert loaded["statistics"]["fact_count"] == 3


@pytest.mark.asyncio
async def test_load_archive_invalid_version(archive, tmp_path):
    """load_archive with bad schema_version raises ValueError."""
    # Create a fake archive with invalid version
    bad_archive = {
        "schema_version": "99.0",
        "archive_type": "investigation_archive",
        "investigation_id": "test",
        "data": {},
    }
    bad_path = tmp_path / "bad_archive.json"
    with open(bad_path, "w") as f:
        json.dump(bad_archive, f)

    with pytest.raises(ValueError, match="Unsupported archive schema version"):
        await InvestigationArchive.load_archive(bad_path)


@pytest.mark.asyncio
async def test_archive_empty_investigation(archive):
    """Archive for nonexistent investigation creates valid JSON with zero counts."""
    path = await archive.create_archive("nonexistent-investigation")

    assert path.exists()

    with open(path) as f:
        data = json.load(f)

    assert data["schema_version"] == "1.0"
    assert data["investigation_id"] == "nonexistent-investigation"
    assert data["statistics"]["fact_count"] == 0
    assert data["statistics"]["classification_count"] == 0
    assert data["statistics"]["verification_count"] == 0
    assert data["statistics"]["confirmed_count"] == 0
    assert data["statistics"]["refuted_count"] == 0
    assert data["statistics"]["dubious_count"] == 0
