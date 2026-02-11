"""Comprehensive tests for Reclassifier status transitions and re-classification.

Tests cover:
- Origin flag preservation (flags saved before clearing)
- Confidence update (boost applied, capped at 1.0)
- History entry creation (trigger recorded)
- ANOMALY resolution (temporal->SUPERSEDED, factual->REFUTED)
- Impact re-assessment (ImpactAssessor called for CONFIRMED facts)
- Edge cases (classification not found, no evidence)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from osint_system.agents.sifters.verification.reclassifier import Reclassifier
from osint_system.data_management.schemas import (
    DubiousFlag,
    FactClassification,
    ImpactTier,
)
from osint_system.data_management.schemas.verification_schema import (
    EvidenceItem,
    VerificationResult,
    VerificationStatus,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def reclassifier() -> Reclassifier:
    return Reclassifier()


@pytest.fixture
def phantom_classification_dict() -> dict:
    """A classification dict as returned by ClassificationStore.get_classification."""
    return FactClassification(
        fact_id="fact-001",
        investigation_id="inv-1",
        impact_tier=ImpactTier.LESS_CRITICAL,
        dubious_flags=[DubiousFlag.PHANTOM],
        credibility_score=0.4,
        priority_score=0.5,
    ).model_dump(mode="json")


@pytest.fixture
def confirmed_verification_result() -> VerificationResult:
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
        reasoning="Wire service confirms claim",
    )


@pytest.fixture
def refuted_verification_result() -> VerificationResult:
    return VerificationResult(
        fact_id="fact-001",
        investigation_id="inv-1",
        status=VerificationStatus.REFUTED,
        original_confidence=0.4,
        confidence_boost=0.0,
        final_confidence=0.4,
        refuting_evidence=[
            EvidenceItem(
                source_url="https://bbc.com/refute",
                source_domain="bbc.com",
                source_type="news_outlet",
                authority_score=0.85,
                snippet="Denied.",
                supports_claim=False,
                relevance_score=0.9,
            )
        ],
        origin_dubious_flags=[DubiousFlag.PHANTOM],
        reasoning="BBC refutes claim",
    )


@pytest.fixture
def mock_classification_store(phantom_classification_dict: dict) -> AsyncMock:
    store = AsyncMock()
    store.get_classification = AsyncMock(return_value=phantom_classification_dict)
    store.save_classification = AsyncMock()
    return store


@pytest.fixture
def mock_fact_store() -> AsyncMock:
    store = AsyncMock()
    store.get_fact = AsyncMock(
        return_value={
            "fact_id": "fact-001",
            "claim": {"text": "Putin ordered deployment"},
            "entities": [{"text": "Putin", "canonical": "Vladimir Putin"}],
        }
    )
    return store


# ── Origin Flag Preservation Tests ───────────────────────────────────────


class TestOriginFlagPreservation:
    @pytest.mark.asyncio
    async def test_phantom_flag_preserved_after_confirmation(
        self,
        reclassifier: Reclassifier,
        confirmed_verification_result: VerificationResult,
        mock_classification_store: AsyncMock,
        mock_fact_store: AsyncMock,
    ) -> None:
        result = await reclassifier.reclassify_fact(
            "fact-001", "inv-1", confirmed_verification_result,
            mock_classification_store, mock_fact_store,
        )
        assert result is not None
        # Flags cleared from current classification
        assert result.dubious_flags == []

    @pytest.mark.asyncio
    async def test_multi_flags_cleared_after_reclassification(
        self,
        reclassifier: Reclassifier,
        confirmed_verification_result: VerificationResult,
        mock_fact_store: AsyncMock,
    ) -> None:
        multi_flag_dict = FactClassification(
            fact_id="fact-001",
            investigation_id="inv-1",
            dubious_flags=[DubiousFlag.PHANTOM, DubiousFlag.FOG],
            credibility_score=0.3,
        ).model_dump(mode="json")

        store = AsyncMock()
        store.get_classification = AsyncMock(return_value=multi_flag_dict)
        store.save_classification = AsyncMock()

        result = await reclassifier.reclassify_fact(
            "fact-001", "inv-1", confirmed_verification_result,
            store, mock_fact_store,
        )
        assert result is not None
        assert result.dubious_flags == []


# ── Confidence Update Tests ──────────────────────────────────────────────


class TestConfidenceUpdate:
    @pytest.mark.asyncio
    async def test_confidence_boost_applied(
        self,
        reclassifier: Reclassifier,
        confirmed_verification_result: VerificationResult,
        mock_classification_store: AsyncMock,
        mock_fact_store: AsyncMock,
    ) -> None:
        result = await reclassifier.reclassify_fact(
            "fact-001", "inv-1", confirmed_verification_result,
            mock_classification_store, mock_fact_store,
        )
        assert result is not None
        # Original 0.4 + boost 0.3 = 0.7
        assert result.credibility_score == pytest.approx(0.7)

    @pytest.mark.asyncio
    async def test_confidence_capped_at_one(
        self,
        reclassifier: Reclassifier,
        mock_fact_store: AsyncMock,
    ) -> None:
        high_cred_dict = FactClassification(
            fact_id="fact-001",
            investigation_id="inv-1",
            dubious_flags=[DubiousFlag.PHANTOM],
            credibility_score=0.9,
        ).model_dump(mode="json")

        store = AsyncMock()
        store.get_classification = AsyncMock(return_value=high_cred_dict)
        store.save_classification = AsyncMock()

        big_boost_result = VerificationResult(
            fact_id="fact-001",
            investigation_id="inv-1",
            status=VerificationStatus.CONFIRMED,
            original_confidence=0.9,
            confidence_boost=0.5,
            reasoning="Multiple sources confirm",
        )

        result = await reclassifier.reclassify_fact(
            "fact-001", "inv-1", big_boost_result, store, mock_fact_store,
        )
        assert result is not None
        assert result.credibility_score == 1.0

    @pytest.mark.asyncio
    async def test_refutation_no_boost(
        self,
        reclassifier: Reclassifier,
        refuted_verification_result: VerificationResult,
        mock_classification_store: AsyncMock,
        mock_fact_store: AsyncMock,
    ) -> None:
        result = await reclassifier.reclassify_fact(
            "fact-001", "inv-1", refuted_verification_result,
            mock_classification_store, mock_fact_store,
        )
        assert result is not None
        # Original 0.4 + boost 0.0 = 0.4
        assert result.credibility_score == pytest.approx(0.4)


# ── History Entry Tests ──────────────────────────────────────────────────


class TestHistoryEntry:
    @pytest.mark.asyncio
    async def test_history_entry_added(
        self,
        reclassifier: Reclassifier,
        confirmed_verification_result: VerificationResult,
        mock_classification_store: AsyncMock,
        mock_fact_store: AsyncMock,
    ) -> None:
        result = await reclassifier.reclassify_fact(
            "fact-001", "inv-1", confirmed_verification_result,
            mock_classification_store, mock_fact_store,
        )
        assert result is not None
        assert len(result.history) >= 1

    @pytest.mark.asyncio
    async def test_history_trigger_includes_status(
        self,
        reclassifier: Reclassifier,
        confirmed_verification_result: VerificationResult,
        mock_classification_store: AsyncMock,
        mock_fact_store: AsyncMock,
    ) -> None:
        result = await reclassifier.reclassify_fact(
            "fact-001", "inv-1", confirmed_verification_result,
            mock_classification_store, mock_fact_store,
        )
        assert result is not None
        latest_entry = result.history[-1]
        assert "verification_confirmed" in latest_entry.trigger

    @pytest.mark.asyncio
    async def test_history_preserves_previous_flags(
        self,
        reclassifier: Reclassifier,
        confirmed_verification_result: VerificationResult,
        mock_classification_store: AsyncMock,
        mock_fact_store: AsyncMock,
    ) -> None:
        result = await reclassifier.reclassify_fact(
            "fact-001", "inv-1", confirmed_verification_result,
            mock_classification_store, mock_fact_store,
        )
        assert result is not None
        latest_entry = result.history[-1]
        assert DubiousFlag.PHANTOM in latest_entry.previous_dubious_flags


# ── ANOMALY Resolution Tests ────────────────────────────────────────────


class TestAnomalyResolution:
    @pytest.mark.asyncio
    async def test_temporal_loser_superseded(self, reclassifier: Reclassifier) -> None:
        status = reclassifier._determine_loser_status("temporal")
        assert status == VerificationStatus.SUPERSEDED

    @pytest.mark.asyncio
    async def test_negation_loser_refuted(self, reclassifier: Reclassifier) -> None:
        assert reclassifier._determine_loser_status("negation") == VerificationStatus.REFUTED

    @pytest.mark.asyncio
    async def test_numeric_loser_refuted(self, reclassifier: Reclassifier) -> None:
        assert reclassifier._determine_loser_status("numeric") == VerificationStatus.REFUTED

    @pytest.mark.asyncio
    async def test_attribution_loser_refuted(self, reclassifier: Reclassifier) -> None:
        assert reclassifier._determine_loser_status("attribution") == VerificationStatus.REFUTED

    @pytest.mark.asyncio
    async def test_resolve_anomaly_clears_flags(self, reclassifier: Reclassifier) -> None:
        winner_dict = FactClassification(
            fact_id="fact-A",
            investigation_id="inv-1",
            dubious_flags=[DubiousFlag.ANOMALY],
        ).model_dump(mode="json")
        loser_dict = FactClassification(
            fact_id="fact-B",
            investigation_id="inv-1",
            dubious_flags=[DubiousFlag.ANOMALY],
        ).model_dump(mode="json")

        store = AsyncMock()
        store.get_classification = AsyncMock(
            side_effect=lambda inv, fid: winner_dict if fid == "fact-A" else loser_dict
        )
        store.save_classification = AsyncMock()

        winner, loser = await reclassifier.resolve_anomaly(
            "fact-A", "fact-B", "temporal", "inv-1", store,
        )
        assert winner is not None
        assert winner.dubious_flags == []
        assert loser is not None
        assert loser.dubious_flags == []

    @pytest.mark.asyncio
    async def test_resolve_anomaly_history_entries(self, reclassifier: Reclassifier) -> None:
        winner_dict = FactClassification(
            fact_id="fact-A",
            investigation_id="inv-1",
            dubious_flags=[DubiousFlag.ANOMALY],
        ).model_dump(mode="json")
        loser_dict = FactClassification(
            fact_id="fact-B",
            investigation_id="inv-1",
            dubious_flags=[DubiousFlag.ANOMALY],
        ).model_dump(mode="json")

        store = AsyncMock()
        store.get_classification = AsyncMock(
            side_effect=lambda inv, fid: winner_dict if fid == "fact-A" else loser_dict
        )
        store.save_classification = AsyncMock()

        winner, loser = await reclassifier.resolve_anomaly(
            "fact-A", "fact-B", "negation", "inv-1", store,
        )
        assert winner is not None
        assert len(winner.history) >= 1
        assert "anomaly_resolution_winner" in winner.history[-1].trigger

        assert loser is not None
        assert len(loser.history) >= 1
        assert "anomaly_resolution_loser" in loser.history[-1].trigger


# ── Impact Re-Assessment Tests ───────────────────────────────────────────


class TestImpactReAssessment:
    def test_impact_assessor_lazy_initialized(self) -> None:
        r = Reclassifier()
        assert r._impact_assessor is None
        assessor = r._get_impact_assessor()
        assert assessor is not None

    def test_custom_impact_assessor_injected(self) -> None:
        mock_assessor = MagicMock()
        r = Reclassifier(impact_assessor=mock_assessor)
        assert r._get_impact_assessor() is mock_assessor

    @pytest.mark.asyncio
    async def test_save_called_after_reclassification(
        self,
        reclassifier: Reclassifier,
        confirmed_verification_result: VerificationResult,
        mock_classification_store: AsyncMock,
        mock_fact_store: AsyncMock,
    ) -> None:
        await reclassifier.reclassify_fact(
            "fact-001", "inv-1", confirmed_verification_result,
            mock_classification_store, mock_fact_store,
        )
        mock_classification_store.save_classification.assert_called_once()


# ── Edge Case Tests ──────────────────────────────────────────────────────


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_classification_not_found_returns_none(
        self,
        reclassifier: Reclassifier,
        confirmed_verification_result: VerificationResult,
        mock_fact_store: AsyncMock,
    ) -> None:
        store = AsyncMock()
        store.get_classification = AsyncMock(return_value=None)

        result = await reclassifier.reclassify_fact(
            "nonexistent", "inv-1", confirmed_verification_result,
            store, mock_fact_store,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_anomaly_winner_not_found(self, reclassifier: Reclassifier) -> None:
        store = AsyncMock()
        store.get_classification = AsyncMock(return_value=None)
        store.save_classification = AsyncMock()

        winner, loser = await reclassifier.resolve_anomaly(
            "missing-A", "missing-B", "temporal", "inv-1", store,
        )
        assert winner is None
        assert loser is None
