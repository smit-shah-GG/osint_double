"""Tests for GET /api/v1/investigations/{id}/facts endpoints.

Validates fact enrichment (classification + verification join), pagination,
404 handling, and internal nested structure flattening.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from osint_system.api.errors import register_error_handlers
from osint_system.api.routes.facts import router


# -- Fixtures & helpers ----------------------------------------------------


def _make_raw_fact(
    fact_id: str = "fact-001",
    claim_text: str = "Test claim",
    claim_type: str = "event",
    source_id: str = "src-001",
    source_type: str = "news_outlet",
    extraction_confidence: float = 0.85,
) -> dict[str, Any]:
    """Build an internal fact dict matching FactStore structure."""
    return {
        "fact_id": fact_id,
        "content_hash": "abc123",
        "claim": {
            "text": claim_text,
            "claim_type": claim_type,
        },
        "provenance": {
            "source_id": source_id,
            "source_type": source_type,
        },
        "extraction_confidence": extraction_confidence,
        "stored_at": "2026-03-21T12:00:00Z",
        "variants": [],
    }


def _build_app(
    facts: list[dict[str, Any]],
    classification_data: dict[str, dict[str, Any]] | None = None,
    verification_data: dict[str, Any] | None = None,
    investigation_id: str = "inv-test",
    use_direct_stores: bool = False,
) -> FastAPI:
    """Build a minimal FastAPI app with mocked stores.

    Args:
        facts: Raw fact dicts to return from fact_store.
        classification_data: fact_id -> classification dict.
        verification_data: fact_id -> mock verification record.
        investigation_id: Investigation ID for store resolution.
        use_direct_stores: If True, mount stores on app.state directly
            (serve.py fallback path).
    """
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router)

    # -- Mock FactStore
    fact_store = AsyncMock()
    fact_store.retrieve_by_investigation.return_value = {
        "investigation_id": investigation_id,
        "facts": facts,
        "total_facts": len(facts),
        "returned_facts": len(facts),
    }

    async def mock_get_fact(inv_id: str, fid: str) -> dict[str, Any] | None:
        for f in facts:
            if f["fact_id"] == fid:
                return f
        return None

    fact_store.get_fact = AsyncMock(side_effect=mock_get_fact)

    # -- Mock ClassificationStore
    classification_store = AsyncMock()

    async def mock_get_classification(inv_id: str, fid: str) -> dict | None:
        if classification_data is None:
            return None
        return classification_data.get(fid)

    classification_store.get_classification = AsyncMock(
        side_effect=mock_get_classification
    )

    # -- Mock VerificationStore
    verification_store = AsyncMock()

    async def mock_get_result(inv_id: str, fid: str) -> Any:
        if verification_data is None:
            return None
        return verification_data.get(fid)

    verification_store.get_result = AsyncMock(side_effect=mock_get_result)

    # Mount stores
    if use_direct_stores:
        app.state.fact_store = fact_store
        app.state.classification_store = classification_store
        app.state.verification_store = verification_store
    else:
        app.state.investigation_stores = {
            investigation_id: {
                "fact_store": fact_store,
                "classification_store": classification_store,
                "verification_store": verification_store,
            }
        }

    return app


# -- Tests: List facts -----------------------------------------------------


def test_list_facts_returns_paginated_enriched_response() -> None:
    """GET /facts returns paginated FactResponse list with enriched fields."""
    facts = [
        _make_raw_fact("fact-001", "Claim A", "event"),
        _make_raw_fact("fact-002", "Claim B", "statement"),
    ]
    classification_data = {
        "fact-001": {"impact_tier": "critical", "dubious_flags": []},
        "fact-002": {"impact_tier": "less_critical", "dubious_flags": ["phantom"]},
    }
    verification_data = {
        "fact-001": SimpleNamespace(status=SimpleNamespace(value="confirmed")),
    }

    app = _build_app(facts, classification_data, verification_data)
    client = TestClient(app)

    resp = client.get("/api/v1/investigations/inv-test/facts")
    assert resp.status_code == 200

    body = resp.json()
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["page_size"] == 100
    assert len(body["data"]) == 2

    # Check enrichment on fact-001
    f1 = body["data"][0]
    assert f1["fact_id"] == "fact-001"
    assert f1["claim_text"] == "Claim A"
    assert f1["claim_type"] == "event"
    assert f1["source_id"] == "src-001"
    assert f1["impact_tier"] == "critical"
    assert f1["verification_status"] == "confirmed"

    # fact-002 has classification but no verification
    f2 = body["data"][1]
    assert f2["impact_tier"] == "less_critical"
    assert f2["verification_status"] is None


def test_list_facts_pagination() -> None:
    """GET /facts?page=2&page_size=1 returns correct page slice."""
    facts = [
        _make_raw_fact("fact-001"),
        _make_raw_fact("fact-002"),
        _make_raw_fact("fact-003"),
    ]
    app = _build_app(facts)
    client = TestClient(app)

    resp = client.get(
        "/api/v1/investigations/inv-test/facts?page=2&page_size=1"
    )
    assert resp.status_code == 200

    body = resp.json()
    assert body["total"] == 3
    assert body["page"] == 2
    assert body["page_size"] == 1
    assert len(body["data"]) == 1
    assert body["data"][0]["fact_id"] == "fact-002"


def test_list_facts_empty_investigation() -> None:
    """GET /facts for investigation with no facts returns empty paginated response."""
    app = _build_app([])
    client = TestClient(app)

    resp = client.get("/api/v1/investigations/inv-test/facts")
    assert resp.status_code == 200

    body = resp.json()
    assert body["total"] == 0
    assert body["data"] == []


def test_list_facts_unknown_investigation_returns_404() -> None:
    """GET /facts for non-existent investigation returns 404."""
    app = _build_app([], investigation_id="inv-real")
    client = TestClient(app)

    resp = client.get("/api/v1/investigations/inv-unknown/facts")
    assert resp.status_code == 404
    assert resp.json()["title"] == "Not Found"


def test_list_facts_fallback_to_direct_stores() -> None:
    """GET /facts resolves stores from app.state directly (serve.py path)."""
    facts = [_make_raw_fact("fact-001")]
    app = _build_app(facts, investigation_id="inv-test", use_direct_stores=True)
    client = TestClient(app)

    resp = client.get("/api/v1/investigations/inv-test/facts")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


# -- Tests: Get single fact ------------------------------------------------


def test_get_fact_returns_enriched_response() -> None:
    """GET /facts/{fact_id} returns single enriched FactResponse."""
    facts = [_make_raw_fact("fact-001")]
    classification_data = {
        "fact-001": {"impact_tier": "critical"},
    }
    verification_data = {
        "fact-001": SimpleNamespace(status=SimpleNamespace(value="confirmed")),
    }

    app = _build_app(facts, classification_data, verification_data)
    client = TestClient(app)

    resp = client.get("/api/v1/investigations/inv-test/facts/fact-001")
    assert resp.status_code == 200

    body = resp.json()
    assert body["fact_id"] == "fact-001"
    assert body["claim_text"] == "Test claim"
    assert body["impact_tier"] == "critical"
    assert body["verification_status"] == "confirmed"
    assert body["extraction_confidence"] == 0.85


def test_get_fact_not_found_returns_404() -> None:
    """GET /facts/{bad-id} returns 404."""
    app = _build_app([_make_raw_fact("fact-001")])
    client = TestClient(app)

    resp = client.get("/api/v1/investigations/inv-test/facts/nonexistent")
    assert resp.status_code == 404
    assert "nonexistent" in resp.json()["detail"]


def test_get_fact_no_classification_no_verification() -> None:
    """GET /facts/{id} returns None for impact_tier and verification_status when no data."""
    facts = [_make_raw_fact("fact-001")]
    app = _build_app(facts)
    client = TestClient(app)

    resp = client.get("/api/v1/investigations/inv-test/facts/fact-001")
    assert resp.status_code == 200

    body = resp.json()
    assert body["impact_tier"] is None
    assert body["verification_status"] is None


def test_enrichment_handles_non_dict_claim_gracefully() -> None:
    """_enrich_fact handles a fact where claim is a plain string."""
    fact = {
        "fact_id": "fact-weird",
        "claim": "just a string claim",
        "provenance": "not a dict either",
        "extraction_confidence": 0.5,
        "stored_at": "2026-03-21T12:00:00Z",
    }
    app = _build_app([fact])
    client = TestClient(app)

    resp = client.get("/api/v1/investigations/inv-test/facts/fact-weird")
    assert resp.status_code == 200

    body = resp.json()
    assert body["claim_text"] == "just a string claim"
    assert body["claim_type"] == "unknown"
    assert body["source_id"] is None
