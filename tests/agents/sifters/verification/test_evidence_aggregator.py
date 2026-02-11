"""Comprehensive tests for EvidenceAggregator authority-weighted evaluation.

Tests cover:
- Initialization (default/custom thresholds, scorer injection)
- High-authority confirmation (wire service, .gov, boundary values)
- Multi-source confirmation (2+ independent, same-domain dedup)
- Refutation (authority >= 0.7, low-authority ignored)
- Confidence boost calculation (graduated by source type, cumulative, capped)
- Edge cases (empty evidence, mixed evidence, all irrelevant)
"""

import pytest

from osint_system.agents.sifters.verification.evidence_aggregator import (
    CONFIDENCE_BOOSTS,
    EvidenceAggregator,
)
from osint_system.data_management.schemas.verification_schema import (
    EvidenceEvaluation,
    EvidenceItem,
    VerificationStatus,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def aggregator() -> EvidenceAggregator:
    return EvidenceAggregator()


@pytest.fixture
def wire_service_evidence() -> EvidenceItem:
    return EvidenceItem(
        source_url="https://www.reuters.com/article/test",
        source_domain="reuters.com",
        source_type="wire_service",
        authority_score=0.9,
        snippet="Officials confirmed the deployment.",
        supports_claim=True,
        relevance_score=0.95,
    )


@pytest.fixture
def gov_evidence() -> EvidenceItem:
    return EvidenceItem(
        source_url="https://www.state.gov/press-release",
        source_domain="state.gov",
        source_type="official_statement",
        authority_score=0.85,
        snippet="The department confirmed the report.",
        supports_claim=True,
        relevance_score=0.9,
    )


@pytest.fixture
def news_evidence_bbc() -> EvidenceItem:
    return EvidenceItem(
        source_url="https://www.bbc.com/news/world-12345",
        source_domain="bbc.com",
        source_type="news_outlet",
        authority_score=0.85,
        snippet="BBC reports the event occurred.",
        supports_claim=True,
        relevance_score=0.8,
    )


@pytest.fixture
def news_evidence_nyt() -> EvidenceItem:
    return EvidenceItem(
        source_url="https://www.nytimes.com/article/test",
        source_domain="nytimes.com",
        source_type="news_outlet",
        authority_score=0.85,
        snippet="NYT confirms the report.",
        supports_claim=True,
        relevance_score=0.85,
    )


@pytest.fixture
def social_media_evidence() -> EvidenceItem:
    return EvidenceItem(
        source_url="https://twitter.com/user/status/123",
        source_domain="twitter.com",
        source_type="social_media",
        authority_score=0.3,
        snippet="Twitter user claims event happened.",
        supports_claim=True,
        relevance_score=0.5,
    )


@pytest.fixture
def refuting_high_authority() -> EvidenceItem:
    return EvidenceItem(
        source_url="https://www.bbc.com/news/refutation",
        source_domain="bbc.com",
        source_type="news_outlet",
        authority_score=0.85,
        snippet="The ministry denied the claim categorically.",
        supports_claim=False,
        relevance_score=0.9,
    )


@pytest.fixture
def refuting_low_authority() -> EvidenceItem:
    return EvidenceItem(
        source_url="https://random-blog.com/post",
        source_domain="random-blog.com",
        source_type="news_outlet",
        authority_score=0.3,
        snippet="Blog claims this is false.",
        supports_claim=False,
        relevance_score=0.4,
    )


@pytest.fixture
def sample_fact() -> dict:
    return {"fact_id": "test-fact", "claim": {"text": "Test claim"}}


# ── Initialization Tests ─────────────────────────────────────────────────


class TestEvidenceAggregatorInit:
    def test_default_thresholds(self) -> None:
        agg = EvidenceAggregator()
        assert agg.high_authority_threshold == 0.85
        assert agg.refutation_threshold == 0.7

    def test_custom_thresholds(self) -> None:
        agg = EvidenceAggregator(high_authority_threshold=0.9, refutation_threshold=0.8)
        assert agg.high_authority_threshold == 0.9
        assert agg.refutation_threshold == 0.8

    def test_scorer_lazy_initialized(self) -> None:
        agg = EvidenceAggregator()
        assert agg._source_scorer is None
        # Triggers lazy init
        scorer = agg._get_source_scorer()
        assert scorer is not None
        assert agg._source_scorer is not None


# ── High-Authority Confirmation Tests ────────────────────────────────────


class TestHighAuthorityConfirmation:
    @pytest.mark.asyncio
    async def test_wire_service_confirms_alone(
        self,
        aggregator: EvidenceAggregator,
        sample_fact: dict,
        wire_service_evidence: EvidenceItem,
    ) -> None:
        result = await aggregator.evaluate_evidence(sample_fact, [wire_service_evidence])
        assert result.status == VerificationStatus.CONFIRMED
        assert result.confidence_boost > 0

    @pytest.mark.asyncio
    async def test_gov_domain_confirms_alone(
        self,
        aggregator: EvidenceAggregator,
        sample_fact: dict,
        gov_evidence: EvidenceItem,
    ) -> None:
        result = await aggregator.evaluate_evidence(sample_fact, [gov_evidence])
        assert result.status == VerificationStatus.CONFIRMED

    @pytest.mark.asyncio
    async def test_authority_below_threshold_does_not_confirm_alone(
        self,
        aggregator: EvidenceAggregator,
        sample_fact: dict,
    ) -> None:
        low_auth = EvidenceItem(
            source_url="https://medium.com/article",
            source_domain="medium.com",
            source_type="news_outlet",
            authority_score=0.5,
            snippet="Medium post supports claim.",
            supports_claim=True,
            relevance_score=0.7,
        )
        result = await aggregator.evaluate_evidence(sample_fact, [low_auth])
        # Single low-authority source → PENDING (not enough for confirmation)
        assert result.status == VerificationStatus.PENDING

    @pytest.mark.asyncio
    async def test_confirmation_includes_supporting_evidence(
        self,
        aggregator: EvidenceAggregator,
        sample_fact: dict,
        wire_service_evidence: EvidenceItem,
    ) -> None:
        result = await aggregator.evaluate_evidence(sample_fact, [wire_service_evidence])
        assert len(result.supporting_evidence) == 1
        assert result.supporting_evidence[0].source_domain == "reuters.com"


# ── Multi-Source Confirmation Tests ──────────────────────────────────────


class TestMultiSourceConfirmation:
    @pytest.mark.asyncio
    async def test_two_independent_sources_confirm(
        self,
        aggregator: EvidenceAggregator,
        sample_fact: dict,
    ) -> None:
        source_a = EvidenceItem(
            source_url="https://cnn.com/article",
            source_domain="cnn.com",
            source_type="news_outlet",
            authority_score=0.6,
            snippet="CNN confirms event.",
            supports_claim=True,
            relevance_score=0.8,
        )
        source_b = EvidenceItem(
            source_url="https://foxnews.com/article",
            source_domain="foxnews.com",
            source_type="news_outlet",
            authority_score=0.6,
            snippet="Fox confirms event.",
            supports_claim=True,
            relevance_score=0.8,
        )
        result = await aggregator.evaluate_evidence(sample_fact, [source_a, source_b])
        assert result.status == VerificationStatus.CONFIRMED

    @pytest.mark.asyncio
    async def test_same_domain_not_independent(
        self,
        aggregator: EvidenceAggregator,
        sample_fact: dict,
    ) -> None:
        # Two articles from same domain don't count as independent
        source_a = EvidenceItem(
            source_url="https://cnn.com/article/1",
            source_domain="cnn.com",
            source_type="news_outlet",
            authority_score=0.6,
            snippet="CNN article 1.",
            supports_claim=True,
            relevance_score=0.8,
        )
        source_b = EvidenceItem(
            source_url="https://cnn.com/article/2",
            source_domain="cnn.com",
            source_type="news_outlet",
            authority_score=0.6,
            snippet="CNN article 2.",
            supports_claim=True,
            relevance_score=0.8,
        )
        result = await aggregator.evaluate_evidence(sample_fact, [source_a, source_b])
        # Same domain → only 1 independent source → PENDING
        assert result.status == VerificationStatus.PENDING

    @pytest.mark.asyncio
    async def test_three_social_media_confirm(
        self,
        aggregator: EvidenceAggregator,
        sample_fact: dict,
    ) -> None:
        sources = [
            EvidenceItem(
                source_url=f"https://{domain}/post",
                source_domain=domain,
                source_type="social_media",
                authority_score=0.3,
                snippet="Social media post.",
                supports_claim=True,
                relevance_score=0.6,
            )
            for domain in ["twitter.com", "reddit.com", "facebook.com"]
        ]
        result = await aggregator.evaluate_evidence(sample_fact, sources)
        assert result.status == VerificationStatus.CONFIRMED


# ── Refutation Tests ─────────────────────────────────────────────────────


class TestRefutation:
    @pytest.mark.asyncio
    async def test_high_authority_refutation(
        self,
        aggregator: EvidenceAggregator,
        sample_fact: dict,
        refuting_high_authority: EvidenceItem,
    ) -> None:
        result = await aggregator.evaluate_evidence(
            sample_fact, [refuting_high_authority]
        )
        assert result.status == VerificationStatus.REFUTED
        assert len(result.refuting_evidence) == 1

    @pytest.mark.asyncio
    async def test_low_authority_refutation_ignored(
        self,
        aggregator: EvidenceAggregator,
        sample_fact: dict,
        refuting_low_authority: EvidenceItem,
    ) -> None:
        result = await aggregator.evaluate_evidence(
            sample_fact, [refuting_low_authority]
        )
        # Low authority AND low relevance → not counted as refutation
        assert result.status == VerificationStatus.PENDING

    @pytest.mark.asyncio
    async def test_refutation_zero_confidence_boost(
        self,
        aggregator: EvidenceAggregator,
        sample_fact: dict,
        refuting_high_authority: EvidenceItem,
    ) -> None:
        result = await aggregator.evaluate_evidence(
            sample_fact, [refuting_high_authority]
        )
        assert result.confidence_boost == 0.0

    @pytest.mark.asyncio
    async def test_supporting_overrides_refuting_when_high_authority(
        self,
        aggregator: EvidenceAggregator,
        sample_fact: dict,
        wire_service_evidence: EvidenceItem,
        refuting_high_authority: EvidenceItem,
    ) -> None:
        # High-authority supporting checked before refuting
        result = await aggregator.evaluate_evidence(
            sample_fact, [wire_service_evidence, refuting_high_authority]
        )
        assert result.status == VerificationStatus.CONFIRMED


# ── Confidence Boost Tests ───────────────────────────────────────────────


class TestConfidenceBoost:
    @pytest.mark.asyncio
    async def test_wire_service_boost(
        self,
        aggregator: EvidenceAggregator,
        sample_fact: dict,
        wire_service_evidence: EvidenceItem,
    ) -> None:
        result = await aggregator.evaluate_evidence(sample_fact, [wire_service_evidence])
        assert result.confidence_boost == pytest.approx(0.3)

    @pytest.mark.asyncio
    async def test_cumulative_boosts(
        self,
        aggregator: EvidenceAggregator,
        sample_fact: dict,
        news_evidence_bbc: EvidenceItem,
        news_evidence_nyt: EvidenceItem,
    ) -> None:
        result = await aggregator.evaluate_evidence(
            sample_fact, [news_evidence_bbc, news_evidence_nyt]
        )
        assert result.status == VerificationStatus.CONFIRMED
        # Two news outlets: 0.2 + 0.2 = 0.4
        assert result.confidence_boost == pytest.approx(0.4)

    @pytest.mark.asyncio
    async def test_boost_capped_at_one(
        self,
        aggregator: EvidenceAggregator,
        sample_fact: dict,
    ) -> None:
        # Create many sources to exceed 1.0
        sources = [
            EvidenceItem(
                source_url=f"https://source{i}.com/article",
                source_domain=f"source{i}.com",
                source_type="wire_service",
                authority_score=0.9,
                snippet=f"Source {i} confirms.",
                supports_claim=True,
                relevance_score=0.9,
            )
            for i in range(5)
        ]
        result = await aggregator.evaluate_evidence(sample_fact, sources)
        assert result.confidence_boost <= 1.0


# ── Edge Case Tests ──────────────────────────────────────────────────────


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_evidence_returns_pending(
        self, aggregator: EvidenceAggregator, sample_fact: dict
    ) -> None:
        result = await aggregator.evaluate_evidence(sample_fact, [])
        assert result.status == VerificationStatus.PENDING
        assert "No evidence" in result.reasoning

    @pytest.mark.asyncio
    async def test_result_is_evidence_evaluation(
        self,
        aggregator: EvidenceAggregator,
        sample_fact: dict,
        wire_service_evidence: EvidenceItem,
    ) -> None:
        result = await aggregator.evaluate_evidence(sample_fact, [wire_service_evidence])
        assert isinstance(result, EvidenceEvaluation)

    @pytest.mark.asyncio
    async def test_reasoning_always_set(
        self,
        aggregator: EvidenceAggregator,
        sample_fact: dict,
    ) -> None:
        result = await aggregator.evaluate_evidence(sample_fact, [])
        assert result.reasoning != ""

    @pytest.mark.asyncio
    async def test_mixed_supporting_refuting(
        self,
        aggregator: EvidenceAggregator,
        sample_fact: dict,
        social_media_evidence: EvidenceItem,
    ) -> None:
        refuting = EvidenceItem(
            source_url="https://blog.example.com/post",
            source_domain="blog.example.com",
            source_type="news_outlet",
            authority_score=0.4,
            snippet="Blog denies.",
            supports_claim=False,
            relevance_score=0.5,
        )
        result = await aggregator.evaluate_evidence(
            sample_fact, [social_media_evidence, refuting]
        )
        # 1 social media supporting, 1 low-authority refuting with low relevance
        assert result.status == VerificationStatus.PENDING
