"""Comprehensive tests for VerificationStore.

Tests cover:
- Save and retrieve (by fact_id, all results, by status)
- Human review tracking (pending review, mark reviewed)
- Edge cases (empty store, wrong investigation)
- Stats calculation
"""

import pytest

from osint_system.data_management.schemas import DubiousFlag
from osint_system.data_management.schemas.verification_schema import (
    EvidenceItem,
    VerificationResult,
    VerificationResultRecord,
    VerificationStatus,
)
from osint_system.data_management.verification_store import VerificationStore


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def store() -> VerificationStore:
    return VerificationStore()


@pytest.fixture
def confirmed_result() -> VerificationResult:
    return VerificationResult(
        fact_id="fact-001",
        investigation_id="inv-1",
        status=VerificationStatus.CONFIRMED,
        original_confidence=0.4,
        confidence_boost=0.3,
        final_confidence=0.7,
        supporting_evidence=[
            EvidenceItem(
                source_url="https://reuters.com/article",
                source_domain="reuters.com",
                source_type="wire_service",
                authority_score=0.9,
                snippet="Confirmed.",
                supports_claim=True,
                relevance_score=0.95,
            )
        ],
        origin_dubious_flags=[DubiousFlag.PHANTOM],
        reasoning="Wire service confirms",
    )


@pytest.fixture
def refuted_result() -> VerificationResult:
    return VerificationResult(
        fact_id="fact-002",
        investigation_id="inv-1",
        status=VerificationStatus.REFUTED,
        original_confidence=0.5,
        confidence_boost=0.0,
        final_confidence=0.5,
        reasoning="Refuted by official denial",
    )


@pytest.fixture
def critical_review_result() -> VerificationResult:
    result = VerificationResult(
        fact_id="fact-003",
        investigation_id="inv-1",
        status=VerificationStatus.CONFIRMED,
        original_confidence=0.6,
        confidence_boost=0.3,
        reasoning="Critical fact confirmed",
    )
    result.requires_human_review = True
    return result


# ── Save and Retrieve Tests ──────────────────────────────────────────────


class TestSaveAndRetrieve:
    @pytest.mark.asyncio
    async def test_save_and_get_result(
        self, store: VerificationStore, confirmed_result: VerificationResult
    ) -> None:
        await store.save_result(confirmed_result)
        retrieved = await store.get_result("inv-1", "fact-001")
        assert retrieved is not None
        assert retrieved.fact_id == "fact-001"
        assert retrieved.status == VerificationStatus.CONFIRMED

    @pytest.mark.asyncio
    async def test_get_all_results(
        self,
        store: VerificationStore,
        confirmed_result: VerificationResult,
        refuted_result: VerificationResult,
    ) -> None:
        await store.save_result(confirmed_result)
        await store.save_result(refuted_result)
        all_results = await store.get_all_results("inv-1")
        assert len(all_results) == 2

    @pytest.mark.asyncio
    async def test_get_by_status(
        self,
        store: VerificationStore,
        confirmed_result: VerificationResult,
        refuted_result: VerificationResult,
    ) -> None:
        await store.save_result(confirmed_result)
        await store.save_result(refuted_result)

        confirmed = await store.get_by_status("inv-1", VerificationStatus.CONFIRMED)
        assert len(confirmed) == 1
        assert confirmed[0].fact_id == "fact-001"

        refuted = await store.get_by_status("inv-1", VerificationStatus.REFUTED)
        assert len(refuted) == 1
        assert refuted[0].fact_id == "fact-002"

    @pytest.mark.asyncio
    async def test_result_is_record_type(
        self, store: VerificationStore, confirmed_result: VerificationResult
    ) -> None:
        await store.save_result(confirmed_result)
        retrieved = await store.get_result("inv-1", "fact-001")
        assert isinstance(retrieved, VerificationResultRecord)

    @pytest.mark.asyncio
    async def test_overwrite_existing_result(
        self, store: VerificationStore, confirmed_result: VerificationResult
    ) -> None:
        await store.save_result(confirmed_result)
        # Save same fact_id with different status
        updated = VerificationResult(
            fact_id="fact-001",
            investigation_id="inv-1",
            status=VerificationStatus.UNVERIFIABLE,
            original_confidence=0.4,
            reasoning="Updated to unverifiable",
        )
        await store.save_result(updated)
        retrieved = await store.get_result("inv-1", "fact-001")
        assert retrieved is not None
        assert retrieved.status == VerificationStatus.UNVERIFIABLE


# ── Human Review Tests ───────────────────────────────────────────────────


class TestHumanReview:
    @pytest.mark.asyncio
    async def test_get_pending_review(
        self,
        store: VerificationStore,
        critical_review_result: VerificationResult,
        confirmed_result: VerificationResult,
    ) -> None:
        await store.save_result(critical_review_result)
        await store.save_result(confirmed_result)

        pending = await store.get_pending_review("inv-1")
        assert len(pending) == 1
        assert pending[0].fact_id == "fact-003"

    @pytest.mark.asyncio
    async def test_mark_reviewed(
        self,
        store: VerificationStore,
        critical_review_result: VerificationResult,
    ) -> None:
        await store.save_result(critical_review_result)
        success = await store.mark_reviewed("inv-1", "fact-003", notes="Approved by analyst")
        assert success is True

        retrieved = await store.get_result("inv-1", "fact-003")
        assert retrieved is not None
        assert retrieved.human_review_completed is True
        assert retrieved.human_reviewer_notes == "Approved by analyst"

    @pytest.mark.asyncio
    async def test_mark_reviewed_clears_pending(
        self,
        store: VerificationStore,
        critical_review_result: VerificationResult,
    ) -> None:
        await store.save_result(critical_review_result)
        await store.mark_reviewed("inv-1", "fact-003")

        pending = await store.get_pending_review("inv-1")
        assert len(pending) == 0

    @pytest.mark.asyncio
    async def test_mark_reviewed_not_found(self, store: VerificationStore) -> None:
        result = await store.mark_reviewed("inv-1", "nonexistent")
        assert result is False


# ── Edge Case Tests ──────────────────────────────────────────────────────


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_get_from_empty_store(self, store: VerificationStore) -> None:
        result = await store.get_result("inv-1", "fact-001")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_from_wrong_investigation(
        self, store: VerificationStore, confirmed_result: VerificationResult
    ) -> None:
        await store.save_result(confirmed_result)
        result = await store.get_result("inv-999", "fact-001")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_from_empty_investigation(
        self, store: VerificationStore
    ) -> None:
        results = await store.get_all_results("inv-nonexistent")
        assert results == []

    @pytest.mark.asyncio
    async def test_get_by_status_empty(self, store: VerificationStore) -> None:
        results = await store.get_by_status("inv-1", VerificationStatus.CONFIRMED)
        assert results == []


# ── Stats Tests ──────────────────────────────────────────────────────────


class TestStats:
    @pytest.mark.asyncio
    async def test_stats_with_results(
        self,
        store: VerificationStore,
        confirmed_result: VerificationResult,
        refuted_result: VerificationResult,
    ) -> None:
        await store.save_result(confirmed_result)
        await store.save_result(refuted_result)

        stats = await store.get_stats("inv-1")
        assert stats["total"] == 2
        assert "confirmed" in stats["status_counts"]
        assert "refuted" in stats["status_counts"]

    @pytest.mark.asyncio
    async def test_stats_empty_investigation(self, store: VerificationStore) -> None:
        stats = await store.get_stats("inv-empty")
        assert stats["total"] == 0

    @pytest.mark.asyncio
    async def test_stats_pending_review_count(
        self,
        store: VerificationStore,
        critical_review_result: VerificationResult,
    ) -> None:
        await store.save_result(critical_review_result)
        stats = await store.get_stats("inv-1")
        assert stats["pending_review"] == 1
