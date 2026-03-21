"""Tests for API response and request schema validation.

Validates Pydantic v2 model constraints, serialization, and the
``PaginatedResponse.from_items`` slicing helper.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from osint_system.api.schemas import (
    FactResponse,
    InvestigationResponse,
    LaunchRequest,
    PaginatedResponse,
)


# ── LaunchRequest ────────────────────────────────────────────────────


class TestLaunchRequest:
    """LaunchRequest validation rules."""

    def test_valid_request(self) -> None:
        req = LaunchRequest(objective="Investigate semiconductor supply chains")
        assert req.objective == "Investigate semiconductor supply chains"
        assert req.enable_verification is True
        assert req.enable_graph is True
        assert req.extraction_model is None

    def test_requires_objective(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            LaunchRequest()  # type: ignore[call-arg]
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("objective",) for e in errors)

    def test_rejects_empty_objective(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            LaunchRequest(objective="")
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("objective",) for e in errors)

    def test_rejects_too_short_objective(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            LaunchRequest(objective="ab")
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("objective",) for e in errors)

    def test_accepts_minimum_length_objective(self) -> None:
        req = LaunchRequest(objective="abc")
        assert req.objective == "abc"

    def test_optional_fields_default_none(self) -> None:
        req = LaunchRequest(objective="Test objective")
        assert req.extraction_model is None
        assert req.synthesis_model is None
        assert req.max_sources is None
        assert req.rss_feeds is None

    def test_full_request(self) -> None:
        req = LaunchRequest(
            objective="Test full",
            extraction_model="gemini-flash",
            synthesis_model="gemini-pro",
            max_sources=50,
            enable_verification=False,
            enable_graph=False,
            rss_feeds=["https://example.com/rss"],
        )
        assert req.extraction_model == "gemini-flash"
        assert req.enable_verification is False
        assert req.rss_feeds == ["https://example.com/rss"]


# ── PaginatedResponse ───────────────────────────────────────────────


class TestPaginatedResponse:
    """PaginatedResponse.from_items slicing logic."""

    def _make_items(self, n: int) -> list[str]:
        return [f"item-{i}" for i in range(n)]

    def test_page_one_of_three(self) -> None:
        items = self._make_items(25)
        resp = PaginatedResponse[str].from_items(items, page=1, page_size=10)
        assert len(resp.data) == 10
        assert resp.total == 25
        assert resp.page == 1
        assert resp.page_size == 10
        assert resp.data[0] == "item-0"
        assert resp.data[9] == "item-9"

    def test_page_two(self) -> None:
        items = self._make_items(25)
        resp = PaginatedResponse[str].from_items(items, page=2, page_size=10)
        assert len(resp.data) == 10
        assert resp.data[0] == "item-10"
        assert resp.data[9] == "item-19"

    def test_last_partial_page(self) -> None:
        items = self._make_items(25)
        resp = PaginatedResponse[str].from_items(items, page=3, page_size=10)
        assert len(resp.data) == 5
        assert resp.total == 25
        assert resp.data[0] == "item-20"

    def test_page_beyond_range(self) -> None:
        items = self._make_items(10)
        resp = PaginatedResponse[str].from_items(items, page=5, page_size=10)
        assert len(resp.data) == 0
        assert resp.total == 10

    def test_empty_items(self) -> None:
        resp = PaginatedResponse[str].from_items([], page=1, page_size=10)
        assert len(resp.data) == 0
        assert resp.total == 0

    def test_single_item(self) -> None:
        resp = PaginatedResponse[str].from_items(["only"], page=1, page_size=10)
        assert resp.data == ["only"]
        assert resp.total == 1


# ── InvestigationResponse ────────────────────────────────────────────


class TestInvestigationResponse:
    """InvestigationResponse serialization with datetime fields."""

    def test_serialization_with_datetimes(self) -> None:
        ts = datetime(2026, 3, 21, 12, 0, 0, tzinfo=timezone.utc)
        resp = InvestigationResponse(
            id="inv-abc12345",
            objective="Test investigation",
            status="running",
            params={"extraction_model": "gemini-flash"},
            created_at=ts,
            updated_at=ts,
            stream_url="/api/v1/investigations/inv-abc12345/stream",
            stats={"articles": 42, "facts": 100},
        )
        data = resp.model_dump(mode="json")
        assert data["id"] == "inv-abc12345"
        assert data["status"] == "running"
        # datetime should serialize to ISO string
        assert "2026-03-21" in data["created_at"]
        assert data["stats"]["articles"] == 42
        assert data["stream_url"] == "/api/v1/investigations/inv-abc12345/stream"

    def test_optional_fields_default_none(self) -> None:
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        resp = InvestigationResponse(
            id="inv-test",
            objective="Test",
            status="pending",
            created_at=ts,
        )
        assert resp.updated_at is None
        assert resp.stream_url is None
        assert resp.stats is None
        assert resp.error is None


# ── FactResponse ─────────────────────────────────────────────────────


class TestFactResponse:
    """FactResponse with None optional fields."""

    def test_minimal_fact(self) -> None:
        resp = FactResponse(
            fact_id="fact-001",
            claim_text="Sanctions imposed on Country X",
            claim_type="geopolitical_event",
        )
        assert resp.source_id is None
        assert resp.extraction_confidence is None
        assert resp.impact_tier is None
        assert resp.verification_status is None
        assert resp.created_at is None

    def test_full_fact(self) -> None:
        resp = FactResponse(
            fact_id="fact-002",
            claim_text="GDP fell by 3%",
            claim_type="quantitative_claim",
            source_id="src-reuters",
            source_type="wire_service",
            extraction_confidence=0.92,
            impact_tier="critical",
            verification_status="confirmed",
            created_at="2026-03-21T12:00:00Z",
        )
        assert resp.extraction_confidence == 0.92
        assert resp.impact_tier == "critical"
        data = resp.model_dump(mode="json")
        assert data["verification_status"] == "confirmed"

    def test_serialization_preserves_none(self) -> None:
        resp = FactResponse(
            fact_id="fact-003",
            claim_text="Claim text",
            claim_type="assertion",
        )
        data = resp.model_dump(mode="json")
        assert data["source_id"] is None
        assert data["impact_tier"] is None
