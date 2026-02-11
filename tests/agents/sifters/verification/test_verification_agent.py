"""Comprehensive tests for VerificationAgent orchestration.

Tests cover:
- Initialization (defaults, custom components)
- Single fact verification (query generation, search, evaluation)
- Batch processing (concurrency, error handling, progress callbacks)
- Status transitions (CONFIRMED, REFUTED, UNVERIFIABLE)
- Human review (CRITICAL tier flagging)
- Full investigation flow (with mock stores)
- Query limit enforcement
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from osint_system.agents.sifters.verification.schemas import (
    EvidenceEvaluation,
    EvidenceItem,
    VerificationQuery,
    VerificationResult,
    VerificationStatus,
)
from osint_system.agents.sifters.verification.verification_agent import (
    VerificationAgent,
)
from osint_system.data_management.schemas import (
    DubiousFlag,
    FactClassification,
    ImpactTier,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_classification(
    fact_id: str,
    flags: list[DubiousFlag] | None = None,
    tier: ImpactTier = ImpactTier.LESS_CRITICAL,
) -> dict:
    """Create a classification dict as returned by ClassificationStore."""
    return FactClassification(
        fact_id=fact_id,
        investigation_id="inv-1",
        dubious_flags=flags or [DubiousFlag.PHANTOM],
        impact_tier=tier,
        credibility_score=0.4,
        priority_score=0.6,
    ).model_dump(mode="json")


def _make_evidence(
    domain: str = "reuters.com",
    supports: bool = True,
    authority: float = 0.9,
) -> EvidenceItem:
    return EvidenceItem(
        source_url=f"https://{domain}/article",
        source_domain=domain,
        source_type="wire_service" if authority >= 0.85 else "news_outlet",
        authority_score=authority,
        snippet="Evidence text.",
        supports_claim=supports,
        relevance_score=0.9,
    )


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def mock_classification_store() -> AsyncMock:
    store = AsyncMock()
    store.get_priority_queue = AsyncMock(
        return_value=[_make_classification("fact-001")]
    )
    store.get_classification = AsyncMock(
        return_value=_make_classification("fact-001")
    )
    store.save_classification = AsyncMock()
    return store


@pytest.fixture
def mock_fact_store() -> AsyncMock:
    store = AsyncMock()
    store.get_fact = AsyncMock(
        return_value={
            "fact_id": "fact-001",
            "claim": {"text": "Putin ordered deployment"},
            "entities": [{"text": "Putin"}],
        }
    )
    return store


@pytest.fixture
def mock_verification_store() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_search_executor() -> AsyncMock:
    executor = AsyncMock()
    executor.execute_query = AsyncMock(
        return_value=[_make_evidence()]
    )
    return executor


@pytest.fixture
def mock_search_executor_empty() -> AsyncMock:
    executor = AsyncMock()
    executor.execute_query = AsyncMock(return_value=[])
    return executor


@pytest.fixture
def agent(
    mock_classification_store: AsyncMock,
    mock_fact_store: AsyncMock,
    mock_verification_store: AsyncMock,
    mock_search_executor: AsyncMock,
) -> VerificationAgent:
    return VerificationAgent(
        classification_store=mock_classification_store,
        fact_store=mock_fact_store,
        verification_store=mock_verification_store,
        search_executor=mock_search_executor,
    )


# ── Initialization Tests ─────────────────────────────────────────────────


class TestVerificationAgentInit:
    def test_default_batch_size(self) -> None:
        agent = VerificationAgent()
        assert agent.batch_size == 10

    def test_default_max_query_attempts(self) -> None:
        agent = VerificationAgent()
        assert agent.max_query_attempts == 3

    def test_custom_batch_size(self) -> None:
        agent = VerificationAgent(batch_size=5)
        assert agent.batch_size == 5

    def test_components_initialized(self, agent: VerificationAgent) -> None:
        assert agent.query_generator is not None
        assert agent.search_executor is not None
        assert agent.evidence_aggregator is not None
        assert agent.reclassifier is not None


# ── Single Fact Verification Tests ───────────────────────────────────────


class TestSingleFactVerification:
    @pytest.mark.asyncio
    async def test_confirmed_on_high_authority_evidence(
        self, agent: VerificationAgent
    ) -> None:
        classification = FactClassification(**_make_classification("fact-001"))
        result = await agent._verify_fact("fact-001", classification, "inv-1")
        assert result.status == VerificationStatus.CONFIRMED
        assert result.fact_id == "fact-001"

    @pytest.mark.asyncio
    async def test_unverifiable_on_no_evidence(
        self,
        mock_classification_store: AsyncMock,
        mock_fact_store: AsyncMock,
        mock_verification_store: AsyncMock,
        mock_search_executor_empty: AsyncMock,
    ) -> None:
        agent = VerificationAgent(
            classification_store=mock_classification_store,
            fact_store=mock_fact_store,
            verification_store=mock_verification_store,
            search_executor=mock_search_executor_empty,
        )
        classification = FactClassification(**_make_classification("fact-001"))
        result = await agent._verify_fact("fact-001", classification, "inv-1")
        assert result.status == VerificationStatus.UNVERIFIABLE

    @pytest.mark.asyncio
    async def test_origin_flags_preserved(
        self, agent: VerificationAgent
    ) -> None:
        classification = FactClassification(**_make_classification("fact-001"))
        result = await agent._verify_fact("fact-001", classification, "inv-1")
        assert DubiousFlag.PHANTOM in result.origin_dubious_flags

    @pytest.mark.asyncio
    async def test_queries_used_tracked(
        self, agent: VerificationAgent
    ) -> None:
        classification = FactClassification(**_make_classification("fact-001"))
        result = await agent._verify_fact("fact-001", classification, "inv-1")
        assert len(result.queries_used) >= 1

    @pytest.mark.asyncio
    async def test_result_stored(
        self, agent: VerificationAgent, mock_verification_store: AsyncMock
    ) -> None:
        classification = FactClassification(**_make_classification("fact-001"))
        await agent._verify_fact("fact-001", classification, "inv-1")
        mock_verification_store.save_result.assert_called_once()


# ── Batch Processing Tests ───────────────────────────────────────────────


class TestBatchProcessing:
    @pytest.mark.asyncio
    async def test_batch_processes_all(
        self,
        mock_fact_store: AsyncMock,
        mock_verification_store: AsyncMock,
        mock_search_executor: AsyncMock,
    ) -> None:
        queue = [
            _make_classification(f"fact-{i:03d}")
            for i in range(5)
        ]
        store = AsyncMock()
        store.get_priority_queue = AsyncMock(return_value=queue)
        store.get_classification = AsyncMock(side_effect=lambda inv, fid: queue[0])
        store.save_classification = AsyncMock()

        agent = VerificationAgent(
            classification_store=store,
            fact_store=mock_fact_store,
            verification_store=mock_verification_store,
            search_executor=mock_search_executor,
            batch_size=10,
        )
        stats = await agent.verify_investigation("inv-1")
        assert stats["total_verified"] == 5

    @pytest.mark.asyncio
    async def test_empty_queue_returns_empty_stats(
        self,
        mock_fact_store: AsyncMock,
        mock_verification_store: AsyncMock,
        mock_search_executor: AsyncMock,
    ) -> None:
        store = AsyncMock()
        store.get_priority_queue = AsyncMock(return_value=[])

        agent = VerificationAgent(
            classification_store=store,
            fact_store=mock_fact_store,
            verification_store=mock_verification_store,
            search_executor=mock_search_executor,
        )
        stats = await agent.verify_investigation("inv-1")
        assert stats["total_verified"] == 0

    @pytest.mark.asyncio
    async def test_progress_callback_called(
        self, agent: VerificationAgent
    ) -> None:
        callback = AsyncMock()
        stats = await agent.verify_investigation("inv-1", progress_callback=callback)
        assert callback.call_count == stats["total_verified"]

    @pytest.mark.asyncio
    async def test_exception_in_batch_handled(
        self,
        mock_fact_store: AsyncMock,
        mock_verification_store: AsyncMock,
    ) -> None:
        queue = [_make_classification("fact-001"), _make_classification("fact-002")]
        store = AsyncMock()
        store.get_priority_queue = AsyncMock(return_value=queue)
        store.get_classification = AsyncMock(return_value=queue[0])
        store.save_classification = AsyncMock()

        # Search that raises on second call
        call_count = 0

        async def flaky_search(query):
            nonlocal call_count
            call_count += 1
            if call_count > 3:
                raise RuntimeError("Search API error")
            return [_make_evidence()]

        executor = AsyncMock()
        executor.execute_query = AsyncMock(side_effect=flaky_search)

        agent = VerificationAgent(
            classification_store=store,
            fact_store=mock_fact_store,
            verification_store=mock_verification_store,
            search_executor=executor,
        )
        # Should not raise
        stats = await agent.verify_investigation("inv-1")
        assert stats["total_verified"] >= 1


# ── Status Transition Tests ──────────────────────────────────────────────


class TestStatusTransitions:
    @pytest.mark.asyncio
    async def test_confirmed_status_counted(
        self, agent: VerificationAgent
    ) -> None:
        stats = await agent.verify_investigation("inv-1")
        assert stats["confirmed"] >= 1

    @pytest.mark.asyncio
    async def test_unverifiable_after_no_evidence(
        self,
        mock_classification_store: AsyncMock,
        mock_fact_store: AsyncMock,
        mock_verification_store: AsyncMock,
        mock_search_executor_empty: AsyncMock,
    ) -> None:
        agent = VerificationAgent(
            classification_store=mock_classification_store,
            fact_store=mock_fact_store,
            verification_store=mock_verification_store,
            search_executor=mock_search_executor_empty,
        )
        stats = await agent.verify_investigation("inv-1")
        assert stats["unverifiable"] >= 1


# ── Human Review Tests ───────────────────────────────────────────────────


class TestHumanReview:
    @pytest.mark.asyncio
    async def test_critical_tier_requires_review(
        self,
        mock_fact_store: AsyncMock,
        mock_verification_store: AsyncMock,
        mock_search_executor: AsyncMock,
    ) -> None:
        critical_class = _make_classification(
            "fact-001", tier=ImpactTier.CRITICAL
        )
        store = AsyncMock()
        store.get_priority_queue = AsyncMock(return_value=[critical_class])
        store.get_classification = AsyncMock(return_value=critical_class)
        store.save_classification = AsyncMock()

        agent = VerificationAgent(
            classification_store=store,
            fact_store=mock_fact_store,
            verification_store=mock_verification_store,
            search_executor=mock_search_executor,
        )
        stats = await agent.verify_investigation("inv-1")
        assert stats["pending_review"] == 1

    @pytest.mark.asyncio
    async def test_less_critical_no_review(
        self, agent: VerificationAgent
    ) -> None:
        stats = await agent.verify_investigation("inv-1")
        assert stats["pending_review"] == 0


# ── Query Limit Tests ────────────────────────────────────────────────────


class TestQueryLimit:
    @pytest.mark.asyncio
    async def test_max_three_query_attempts(
        self,
        mock_classification_store: AsyncMock,
        mock_fact_store: AsyncMock,
        mock_verification_store: AsyncMock,
        mock_search_executor_empty: AsyncMock,
    ) -> None:
        agent = VerificationAgent(
            classification_store=mock_classification_store,
            fact_store=mock_fact_store,
            verification_store=mock_verification_store,
            search_executor=mock_search_executor_empty,
            max_query_attempts=3,
        )
        classification = FactClassification(**_make_classification("fact-001"))
        result = await agent._verify_fact("fact-001", classification, "inv-1")
        assert result.query_attempts <= 3

    @pytest.mark.asyncio
    async def test_short_circuits_on_confirmed(
        self, agent: VerificationAgent, mock_search_executor: AsyncMock
    ) -> None:
        classification = FactClassification(**_make_classification("fact-001"))
        result = await agent._verify_fact("fact-001", classification, "inv-1")
        # Should short-circuit after first successful query
        assert result.status == VerificationStatus.CONFIRMED
        assert result.query_attempts == 1


# ── Integration Flow Tests ───────────────────────────────────────────────


class TestIntegrationFlow:
    @pytest.mark.asyncio
    async def test_full_investigation_returns_stats(
        self, agent: VerificationAgent
    ) -> None:
        stats = await agent.verify_investigation("inv-1")
        assert "investigation_id" in stats
        assert "total_verified" in stats
        assert "confirmed" in stats
        assert "refuted" in stats
        assert "unverifiable" in stats
        assert "pending_review" in stats

    @pytest.mark.asyncio
    async def test_stats_sum_consistent(
        self,
        mock_fact_store: AsyncMock,
        mock_verification_store: AsyncMock,
        mock_search_executor: AsyncMock,
    ) -> None:
        queue = [_make_classification(f"fact-{i:03d}") for i in range(3)]
        store = AsyncMock()
        store.get_priority_queue = AsyncMock(return_value=queue)
        store.get_classification = AsyncMock(return_value=queue[0])
        store.save_classification = AsyncMock()

        agent = VerificationAgent(
            classification_store=store,
            fact_store=mock_fact_store,
            verification_store=mock_verification_store,
            search_executor=mock_search_executor,
        )
        stats = await agent.verify_investigation("inv-1")
        status_sum = (
            stats["confirmed"]
            + stats["refuted"]
            + stats["unverifiable"]
            + stats["superseded"]
        )
        assert status_sum == stats["total_verified"]
