"""Tests for InvestigationExporter SQLite database export.

Verifies that InvestigationExporter creates queryable SQLite databases
with normalized tables, proper foreign keys, and indexes from
FactStore, ClassificationStore, and VerificationStore data.
"""

import json
import sqlite3
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
from osint_system.database.exporter import InvestigationExporter

INVESTIGATION_ID = "inv-export-test"


def _make_test_facts() -> list[dict]:
    """Create 3 test facts with varying provenance and entities."""
    return [
        {
            "fact_id": "fact-001",
            "content_hash": "hash001",
            "claim": {
                "text": "[E1:Putin] visited [E2:Beijing] in March 2024",
                "assertion_type": "statement",
                "claim_type": "event",
            },
            "entities": [
                {
                    "id": "E1",
                    "text": "Putin",
                    "type": "PERSON",
                    "canonical": "Vladimir Putin",
                },
                {
                    "id": "E2",
                    "text": "Beijing",
                    "type": "LOCATION",
                    "canonical": "Beijing, China",
                },
            ],
            "temporal": {
                "id": "T1",
                "value": "2024-03",
                "precision": "month",
                "temporal_precision": "explicit",
            },
            "quality": {
                "extraction_confidence": 0.95,
                "claim_clarity": 0.9,
            },
            "provenance": {
                "source_id": "src-reuters-001",
                "source_type": "wire_service",
                "source_domain": "reuters.com",
                "quote": "Putin visited Beijing in March 2024",
                "offsets": {"start": 0, "end": 35},
                "hop_count": 1,
            },
        },
        {
            "fact_id": "fact-002",
            "content_hash": "hash002",
            "claim": {
                "text": "[E1:Russia] deployed troops to [E2:Crimea]",
                "assertion_type": "statement",
                "claim_type": "event",
            },
            "entities": [
                {
                    "id": "E1",
                    "text": "Russia",
                    "type": "ORGANIZATION",
                    "canonical": "Russian Federation",
                },
                {
                    "id": "E2",
                    "text": "Crimea",
                    "type": "LOCATION",
                    "canonical": "Crimea",
                },
            ],
            "quality": {
                "extraction_confidence": 0.8,
                "claim_clarity": 0.7,
            },
            "provenance": {
                "source_id": "src-reuters-001",
                "source_type": "wire_service",
                "source_domain": "reuters.com",
                "quote": "Russia deployed troops to Crimea",
                "offsets": {"start": 100, "end": 131},
                "hop_count": 2,
            },
        },
        {
            "fact_id": "fact-003",
            "content_hash": "hash003",
            "claim": {
                "text": "[E1:NATO] held emergency meeting",
                "assertion_type": "statement",
                "claim_type": "event",
            },
            "entities": [
                {
                    "id": "E1",
                    "text": "NATO",
                    "type": "ORGANIZATION",
                    "canonical": "NATO",
                },
            ],
            "quality": {
                "extraction_confidence": 0.92,
                "claim_clarity": 0.85,
            },
            "provenance": {
                "source_id": "src-bbc-001",
                "source_type": "news_outlet",
                "source_domain": "bbc.co.uk",
                "quote": "NATO held emergency meeting",
                "offsets": {"start": 200, "end": 227},
                "hop_count": 1,
            },
        },
    ]


def _make_test_classifications() -> list[FactClassification]:
    """Create classifications for the 3 test facts."""
    return [
        FactClassification(
            fact_id="fact-001",
            investigation_id=INVESTIGATION_ID,
            impact_tier=ImpactTier.CRITICAL,
            dubious_flags=[],
            priority_score=0.9,
            credibility_score=0.85,
        ),
        FactClassification(
            fact_id="fact-002",
            investigation_id=INVESTIGATION_ID,
            impact_tier=ImpactTier.CRITICAL,
            dubious_flags=[DubiousFlag.FOG],
            priority_score=0.7,
            credibility_score=0.5,
        ),
        FactClassification(
            fact_id="fact-003",
            investigation_id=INVESTIGATION_ID,
            impact_tier=ImpactTier.LESS_CRITICAL,
            dubious_flags=[],
            priority_score=0.4,
            credibility_score=0.75,
        ),
    ]


def _make_test_verification_results() -> list[VerificationResult]:
    """Create verification results for the test facts."""
    return [
        VerificationResult(
            fact_id="fact-001",
            investigation_id=INVESTIGATION_ID,
            status=VerificationStatus.CONFIRMED,
            original_confidence=0.85,
            confidence_boost=0.1,
            final_confidence=0.95,
            query_attempts=1,
            queries_used=["Putin Beijing visit March 2024"],
            reasoning="High-authority wire service confirms visit",
        ),
        VerificationResult(
            fact_id="fact-002",
            investigation_id=INVESTIGATION_ID,
            status=VerificationStatus.UNVERIFIABLE,
            original_confidence=0.5,
            confidence_boost=0.0,
            final_confidence=0.5,
            query_attempts=3,
            queries_used=[
                "Russia troops Crimea deployment",
                "Russian military Crimea",
                "Crimea troop buildup",
            ],
            origin_dubious_flags=[DubiousFlag.FOG],
            reasoning="Exhausted query attempts without sufficient evidence",
            requires_human_review=True,
        ),
    ]


@pytest_asyncio.fixture
async def populated_stores():
    """Create and populate all three stores with test data."""
    fact_store = FactStore()
    classification_store = ClassificationStore()
    verification_store = VerificationStore()

    # Save facts
    await fact_store.save_facts(
        INVESTIGATION_ID,
        _make_test_facts(),
        investigation_metadata={"objective": "Test geopolitical analysis"},
    )

    # Save classifications
    for classification in _make_test_classifications():
        await classification_store.save_classification(classification)

    # Save verification results
    for result in _make_test_verification_results():
        await verification_store.save_result(result)

    return fact_store, classification_store, verification_store


@pytest_asyncio.fixture
async def exporter(populated_stores, tmp_path):
    """Create InvestigationExporter with populated stores."""
    fact_store, classification_store, verification_store = populated_stores
    return InvestigationExporter(
        fact_store=fact_store,
        classification_store=classification_store,
        verification_store=verification_store,
        output_dir=str(tmp_path),
    )


@pytest.mark.asyncio
async def test_export_creates_file(exporter, tmp_path):
    """Export produces a .db file at the expected path."""
    db_path = await exporter.export(INVESTIGATION_ID)

    assert db_path.exists()
    assert db_path.suffix == ".db"
    assert db_path.name == f"{INVESTIGATION_ID}.db"
    assert db_path.parent == tmp_path


@pytest.mark.asyncio
async def test_export_facts_table(exporter):
    """Exported database contains all 3 facts in the facts table."""
    db_path = await exporter.export(INVESTIGATION_ID)

    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("SELECT COUNT(*) FROM facts")
    count = cursor.fetchone()[0]
    conn.close()

    assert count == 3


@pytest.mark.asyncio
async def test_export_classifications_table(exporter):
    """Exported database contains all 3 classifications."""
    db_path = await exporter.export(INVESTIGATION_ID)

    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("SELECT COUNT(*) FROM classifications")
    count = cursor.fetchone()[0]
    conn.close()

    assert count == 3


@pytest.mark.asyncio
async def test_export_verification_table(exporter):
    """Exported database contains the 2 verification results."""
    db_path = await exporter.export(INVESTIGATION_ID)

    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("SELECT COUNT(*) FROM verification_results")
    count = cursor.fetchone()[0]
    conn.close()

    assert count == 2


@pytest.mark.asyncio
async def test_export_metadata_table(exporter):
    """investigation_metadata row exists with correct investigation_id."""
    db_path = await exporter.export(INVESTIGATION_ID)

    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute(
        "SELECT investigation_id, objective FROM investigation_metadata"
    )
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    assert row[0] == INVESTIGATION_ID
    assert row[1] == "Test geopolitical analysis"


@pytest.mark.asyncio
async def test_export_sources_table(exporter):
    """Sources table is populated from fact provenance data."""
    db_path = await exporter.export(INVESTIGATION_ID)

    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("SELECT COUNT(*) FROM sources")
    count = cursor.fetchone()[0]

    # We have 2 unique sources: reuters and bbc
    cursor2 = conn.execute(
        "SELECT source_id, fact_count FROM sources ORDER BY source_id"
    )
    rows = cursor2.fetchall()
    conn.close()

    assert count == 2
    source_dict = {row[0]: row[1] for row in rows}
    assert source_dict["src-reuters-001"] == 2  # fact-001 and fact-002
    assert source_dict["src-bbc-001"] == 1  # fact-003


@pytest.mark.asyncio
async def test_export_entities_table(exporter):
    """Entities table is populated from fact entity lists."""
    db_path = await exporter.export(INVESTIGATION_ID)

    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("SELECT COUNT(*) FROM entities")
    count = cursor.fetchone()[0]
    conn.close()

    # 5 unique entities: Putin, Beijing, Russia, Crimea, NATO
    assert count == 5


@pytest.mark.asyncio
async def test_export_queryable(exporter):
    """JOIN query across facts and classifications returns expected results."""
    db_path = await exporter.export(INVESTIGATION_ID)

    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute(
        """SELECT f.fact_id, f.claim_text, c.impact_tier
           FROM facts f
           JOIN classifications c ON f.fact_id = c.fact_id
           WHERE c.impact_tier = 'critical'
           ORDER BY f.fact_id"""
    )
    rows = cursor.fetchall()
    conn.close()

    assert len(rows) == 2
    assert rows[0][0] == "fact-001"
    assert rows[1][0] == "fact-002"
    # Both should have impact_tier = 'critical'
    assert all(row[2] == "critical" for row in rows)


@pytest.mark.asyncio
async def test_export_custom_path(exporter, tmp_path):
    """Export to custom output_path works correctly."""
    custom_path = str(tmp_path / "custom" / "my_investigation.db")
    db_path = await exporter.export(INVESTIGATION_ID, output_path=custom_path)

    assert db_path == Path(custom_path)
    assert db_path.exists()

    # Verify it has data
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("SELECT COUNT(*) FROM facts")
    count = cursor.fetchone()[0]
    conn.close()

    assert count == 3


@pytest.mark.asyncio
async def test_export_empty_investigation(exporter):
    """Exporting nonexistent investigation creates db with schema but empty tables."""
    db_path = await exporter.export("nonexistent-investigation")

    assert db_path.exists()

    conn = sqlite3.connect(str(db_path))

    # All tables should exist but be empty (except metadata which gets a row)
    cursor = conn.execute("SELECT COUNT(*) FROM facts")
    assert cursor.fetchone()[0] == 0

    cursor = conn.execute("SELECT COUNT(*) FROM classifications")
    assert cursor.fetchone()[0] == 0

    cursor = conn.execute("SELECT COUNT(*) FROM verification_results")
    assert cursor.fetchone()[0] == 0

    cursor = conn.execute("SELECT COUNT(*) FROM sources")
    assert cursor.fetchone()[0] == 0

    cursor = conn.execute("SELECT COUNT(*) FROM entities")
    assert cursor.fetchone()[0] == 0

    # Metadata row should exist
    cursor = conn.execute("SELECT COUNT(*) FROM investigation_metadata")
    assert cursor.fetchone()[0] == 1

    conn.close()
