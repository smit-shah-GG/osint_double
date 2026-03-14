"""Route response tests with populated stores and TestClient.

Tests cover all 5 route modules: investigations, facts, reports,
monitoring, and API. Uses real store instances populated with test
data for "inv-dash-test" investigation.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from osint_system.dashboard import create_app
from osint_system.data_management.classification_store import ClassificationStore
from osint_system.data_management.fact_store import FactStore
from osint_system.data_management.schemas import (
    DubiousFlag,
    FactClassification,
    ImpactTier,
)
from osint_system.data_management.schemas.verification_schema import (
    VerificationResult,
    VerificationStatus,
)
from osint_system.data_management.verification_store import VerificationStore
from osint_system.reporting.report_store import ReportStore

INV_ID = "inv-dash-test"


def _run(coro: Any) -> Any:
    """Run an async coroutine synchronously for test setup."""
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture()
def populated_stores() -> (
    tuple[FactStore, ClassificationStore, VerificationStore, ReportStore]
):
    """Create stores populated with test data for INV_ID."""
    loop = asyncio.new_event_loop()

    fact_store = FactStore()
    classification_store = ClassificationStore()
    verification_store = VerificationStore()
    report_store = ReportStore()

    # Save test facts
    facts = [
        {
            "fact_id": "fact-001",
            "content_hash": "hash001",
            "claim_text": "President signed executive order on trade tariffs",
            "extraction_confidence": 0.92,
            "provenance": {"source_id": "reuters", "source_url": "https://reuters.com/article1"},
        },
        {
            "fact_id": "fact-002",
            "content_hash": "hash002",
            "claim_text": "Opposition party rejected the proposed budget amendment",
            "extraction_confidence": 0.87,
            "provenance": {"source_id": "apnews", "source_url": "https://apnews.com/article2"},
        },
        {
            "fact_id": "fact-003",
            "content_hash": "hash003",
            "claim_text": "Unconfirmed reports of military movements near border",
            "extraction_confidence": 0.45,
            "provenance": {"source_id": "twitter", "source_url": "https://twitter.com/user/status/123"},
        },
    ]
    loop.run_until_complete(fact_store.save_facts(INV_ID, facts))

    # Save classifications
    classifications = [
        FactClassification(
            fact_id="fact-001",
            investigation_id=INV_ID,
            impact_tier=ImpactTier.CRITICAL,
            credibility_score=0.9,
            dubious_flags=[],
            priority_score=0.85,
        ),
        FactClassification(
            fact_id="fact-002",
            investigation_id=INV_ID,
            impact_tier=ImpactTier.LESS_CRITICAL,
            credibility_score=0.75,
            dubious_flags=[],
            priority_score=0.6,
        ),
        FactClassification(
            fact_id="fact-003",
            investigation_id=INV_ID,
            impact_tier=ImpactTier.CRITICAL,
            credibility_score=0.3,
            dubious_flags=[DubiousFlag.PHANTOM],
            priority_score=0.9,
        ),
    ]
    loop.run_until_complete(
        classification_store.save_classifications(INV_ID, classifications)
    )

    # Save verification results
    ver_result = VerificationResult(
        fact_id="fact-001",
        investigation_id=INV_ID,
        status=VerificationStatus.CONFIRMED,
        original_confidence=0.65,
        confidence_boost=0.3,
        final_confidence=0.95,
        reasoning="High-authority wire service (Reuters, 0.90) confirms claim",
        queries_used=["trade tariffs executive order"],
        query_attempts=1,
    )
    loop.run_until_complete(verification_store.save_result(ver_result))

    ver_result_2 = VerificationResult(
        fact_id="fact-003",
        investigation_id=INV_ID,
        status=VerificationStatus.UNVERIFIABLE,
        original_confidence=0.3,
        confidence_boost=0.0,
        final_confidence=0.3,
        reasoning="3 query variants exhausted, no sufficient evidence either way",
        queries_used=["military movements border"],
        query_attempts=3,
    )
    loop.run_until_complete(verification_store.save_result(ver_result_2))

    loop.close()

    return fact_store, classification_store, verification_store, report_store


@pytest.fixture()
def client(
    populated_stores: tuple[FactStore, ClassificationStore, VerificationStore, ReportStore],
) -> TestClient:
    """Create TestClient with populated stores."""
    fact_store, classification_store, verification_store, report_store = populated_stores
    app = create_app(
        fact_store=fact_store,
        classification_store=classification_store,
        verification_store=verification_store,
        report_store=report_store,
    )
    return TestClient(app)


def test_investigation_list(client: TestClient) -> None:
    """GET / returns 200 with HTML containing the test investigation ID."""
    response = client.get("/")
    assert response.status_code == 200
    assert INV_ID in response.text
    assert "text/html" in response.headers.get("content-type", "")


def test_investigation_detail(client: TestClient) -> None:
    """GET /investigation/{id} returns 200 with fact count and stats."""
    response = client.get(f"/investigation/{INV_ID}")
    assert response.status_code == 200
    assert INV_ID in response.text
    # Should show total facts count of 3
    assert "3" in response.text


def test_facts_list(client: TestClient) -> None:
    """GET /facts/{id} returns 200 with fact table HTML."""
    response = client.get(f"/facts/{INV_ID}")
    assert response.status_code == 200
    assert "fact-001" in response.text
    assert "fact-002" in response.text
    assert "fact-003" in response.text
    assert "data-table" in response.text


def test_facts_filter_by_tier(client: TestClient) -> None:
    """GET /facts/{id}?tier=critical returns only critical-tier facts."""
    response = client.get(f"/facts/{INV_ID}?tier=critical")
    assert response.status_code == 200
    # fact-001 and fact-003 are critical
    assert "fact-001" in response.text
    assert "fact-003" in response.text
    # fact-002 is less_critical, should be filtered out
    assert "fact-002" not in response.text


def test_reports_no_report(client: TestClient) -> None:
    """GET /reports/{id} returns 200 with 'No report generated' message."""
    response = client.get(f"/reports/{INV_ID}")
    assert response.status_code == 200
    assert "No report generated" in response.text


def test_monitoring_status(client: TestClient) -> None:
    """GET /monitoring/status returns 200 with aggregated system stats."""
    response = client.get("/monitoring/status")
    assert response.status_code == 200
    # Should show total facts (3), verifications (2)
    assert "3" in response.text
    assert "2" in response.text
    assert INV_ID in response.text


def test_api_stats(client: TestClient) -> None:
    """GET /api/investigation/{id}/stats returns JSON with stats."""
    response = client.get(f"/api/investigation/{INV_ID}/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["investigation_id"] == INV_ID
    assert data["fact_count"] == 3
    assert "classification" in data
    assert "verification" in data
    assert data["classification"]["critical"] == 2
    assert data["verification"]["total"] == 2


def test_nonexistent_investigation(client: TestClient) -> None:
    """GET /investigation/nonexistent returns 200 with empty data (graceful)."""
    response = client.get("/investigation/nonexistent")
    assert response.status_code == 200
    assert "nonexistent" in response.text
    # Total facts should be 0
    assert "0" in response.text


def test_api_facts_partial(client: TestClient) -> None:
    """GET /api/investigation/{id}/facts returns HTML partial."""
    response = client.get(f"/api/investigation/{INV_ID}/facts")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "fact-001" in response.text


def test_report_generate_redirect(client: TestClient) -> None:
    """POST /reports/{id}/generate redirects to report view."""
    response = client.post(
        f"/reports/{INV_ID}/generate",
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert f"/reports/{INV_ID}" in response.headers.get("location", "")
