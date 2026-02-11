"""Comprehensive tests for Phase 8 verification domain schemas.

Tests cover:
- VerificationStatus enum (6 values, string behavior)
- EvidenceItem (construction, validation, defaults)
- VerificationQuery (variant types, flag linking)
- EvidenceEvaluation (status, evidence lists, confidence)
- VerificationResult (confidence capping, origin flags, ANOMALY fields)
- VerificationResultRecord (round-trip, storage timestamps)
"""

from datetime import datetime, timezone

import pytest

from osint_system.data_management.schemas.classification_schema import DubiousFlag
from osint_system.data_management.schemas.verification_schema import (
    EvidenceEvaluation,
    EvidenceItem,
    VerificationQuery,
    VerificationResult,
    VerificationResultRecord,
    VerificationStatus,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def sample_evidence_item() -> EvidenceItem:
    return EvidenceItem(
        source_url="https://www.reuters.com/article/example",
        source_domain="reuters.com",
        source_type="wire_service",
        authority_score=0.9,
        snippet="Officials confirmed the deployment.",
        supports_claim=True,
        relevance_score=0.95,
    )


@pytest.fixture
def sample_refuting_evidence() -> EvidenceItem:
    return EvidenceItem(
        source_url="https://www.bbc.com/news/world-12345",
        source_domain="bbc.com",
        source_type="news_outlet",
        authority_score=0.7,
        snippet="The ministry denied the claim.",
        supports_claim=False,
        relevance_score=0.85,
    )


@pytest.fixture
def sample_verification_result(sample_evidence_item: EvidenceItem) -> VerificationResult:
    return VerificationResult(
        fact_id="fact-001",
        investigation_id="inv-100",
        status=VerificationStatus.CONFIRMED,
        original_confidence=0.45,
        confidence_boost=0.3,
        final_confidence=0.75,
        supporting_evidence=[sample_evidence_item],
        refuting_evidence=[],
        query_attempts=1,
        queries_used=["Putin Ukraine official statement"],
        origin_dubious_flags=[DubiousFlag.PHANTOM],
        reasoning="High-authority wire service confirms claim",
    )


# ── VerificationStatus Tests ─────────────────────────────────────────────


class TestVerificationStatus:
    def test_all_six_values_exist(self) -> None:
        values = [s.value for s in VerificationStatus]
        assert len(values) == 6
        assert "pending" in values
        assert "in_progress" in values
        assert "confirmed" in values
        assert "refuted" in values
        assert "unverifiable" in values
        assert "superseded" in values

    def test_values_are_strings(self) -> None:
        for status in VerificationStatus:
            assert isinstance(status.value, str)
            assert isinstance(status, str)

    def test_conditional_comparison(self) -> None:
        status = VerificationStatus.CONFIRMED
        assert status == VerificationStatus.CONFIRMED
        assert status != VerificationStatus.REFUTED

    def test_string_comparison(self) -> None:
        assert VerificationStatus.PENDING == "pending"
        assert VerificationStatus.SUPERSEDED == "superseded"


# ── EvidenceItem Tests ────────────────────────────────────────────────────


class TestEvidenceItem:
    def test_valid_construction(self, sample_evidence_item: EvidenceItem) -> None:
        assert sample_evidence_item.source_url == "https://www.reuters.com/article/example"
        assert sample_evidence_item.source_domain == "reuters.com"
        assert sample_evidence_item.source_type == "wire_service"
        assert sample_evidence_item.authority_score == 0.9
        assert sample_evidence_item.supports_claim is True
        assert sample_evidence_item.relevance_score == 0.95

    def test_authority_score_lower_bound(self) -> None:
        with pytest.raises(Exception):
            EvidenceItem(
                source_url="https://example.com",
                source_domain="example.com",
                source_type="news_outlet",
                authority_score=-0.1,
                snippet="Test",
                supports_claim=True,
                relevance_score=0.5,
            )

    def test_authority_score_upper_bound(self) -> None:
        with pytest.raises(Exception):
            EvidenceItem(
                source_url="https://example.com",
                source_domain="example.com",
                source_type="news_outlet",
                authority_score=1.1,
                snippet="Test",
                supports_claim=True,
                relevance_score=0.5,
            )

    def test_relevance_score_bounds(self) -> None:
        with pytest.raises(Exception):
            EvidenceItem(
                source_url="https://example.com",
                source_domain="example.com",
                source_type="social_media",
                authority_score=0.3,
                snippet="Test",
                supports_claim=True,
                relevance_score=1.5,
            )

    def test_default_retrieved_at_is_utc(self) -> None:
        item = EvidenceItem(
            source_url="https://example.com",
            source_domain="example.com",
            source_type="news_outlet",
            authority_score=0.5,
            snippet="Test snippet",
            supports_claim=True,
            relevance_score=0.8,
        )
        assert item.retrieved_at.tzinfo is not None
        assert item.retrieved_at.tzinfo == timezone.utc

    def test_source_types_accepted(self) -> None:
        for source_type in ["wire_service", "news_outlet", "official_statement", "social_media"]:
            item = EvidenceItem(
                source_url="https://example.com",
                source_domain="example.com",
                source_type=source_type,
                authority_score=0.5,
                snippet="Test",
                supports_claim=True,
                relevance_score=0.5,
            )
            assert item.source_type == source_type

    def test_boundary_scores_accepted(self) -> None:
        item = EvidenceItem(
            source_url="https://example.com",
            source_domain="example.com",
            source_type="news_outlet",
            authority_score=0.0,
            snippet="Test",
            supports_claim=False,
            relevance_score=1.0,
        )
        assert item.authority_score == 0.0
        assert item.relevance_score == 1.0


# ── VerificationQuery Tests ──────────────────────────────────────────────


class TestVerificationQuery:
    def test_all_variant_types_valid(self) -> None:
        valid_types = [
            "entity_focused",
            "exact_phrase",
            "broader_context",
            "temporal_context",
            "authority_arbitration",
            "clarity_enhancement",
        ]
        for vt in valid_types:
            query = VerificationQuery(query="test query", variant_type=vt)
            assert query.variant_type == vt

    def test_invalid_variant_type_rejected(self) -> None:
        with pytest.raises(Exception):
            VerificationQuery(query="test", variant_type="invalid_type")

    def test_dubious_flag_links_to_enum(self) -> None:
        query = VerificationQuery(
            query="test",
            variant_type="entity_focused",
            dubious_flag=DubiousFlag.PHANTOM,
        )
        assert query.dubious_flag == DubiousFlag.PHANTOM
        assert isinstance(query.dubious_flag, DubiousFlag)

    def test_target_sources_accepts_list(self) -> None:
        query = VerificationQuery(
            query="test",
            variant_type="exact_phrase",
            target_sources=["wire_service", "official_statement"],
        )
        assert len(query.target_sources) == 2
        assert "wire_service" in query.target_sources

    def test_purpose_default_empty(self) -> None:
        query = VerificationQuery(query="test", variant_type="entity_focused")
        assert query.purpose == ""

    def test_dubious_flag_default_none(self) -> None:
        query = VerificationQuery(query="test", variant_type="entity_focused")
        assert query.dubious_flag is None


# ── EvidenceEvaluation Tests ─────────────────────────────────────────────


class TestEvidenceEvaluation:
    def test_status_accepts_verification_status(self) -> None:
        evaluation = EvidenceEvaluation(status=VerificationStatus.CONFIRMED)
        assert evaluation.status == VerificationStatus.CONFIRMED

    def test_empty_evidence_lists_default(self) -> None:
        evaluation = EvidenceEvaluation(status=VerificationStatus.PENDING)
        assert evaluation.supporting_evidence == []
        assert evaluation.refuting_evidence == []

    def test_confidence_boost_zero_default(self) -> None:
        evaluation = EvidenceEvaluation(status=VerificationStatus.PENDING)
        assert evaluation.confidence_boost == 0.0

    def test_confidence_boost_positive(self) -> None:
        evaluation = EvidenceEvaluation(
            status=VerificationStatus.CONFIRMED,
            confidence_boost=0.5,
        )
        assert evaluation.confidence_boost == 0.5

    def test_with_evidence_lists(
        self, sample_evidence_item: EvidenceItem, sample_refuting_evidence: EvidenceItem
    ) -> None:
        evaluation = EvidenceEvaluation(
            status=VerificationStatus.CONFIRMED,
            confidence_boost=0.3,
            supporting_evidence=[sample_evidence_item],
            refuting_evidence=[sample_refuting_evidence],
            reasoning="Mixed evidence, supporting outweighs",
        )
        assert len(evaluation.supporting_evidence) == 1
        assert len(evaluation.refuting_evidence) == 1
        assert evaluation.reasoning == "Mixed evidence, supporting outweighs"


# ── VerificationResult Tests ─────────────────────────────────────────────


class TestVerificationResult:
    def test_all_required_fields(self, sample_verification_result: VerificationResult) -> None:
        assert sample_verification_result.fact_id == "fact-001"
        assert sample_verification_result.investigation_id == "inv-100"
        assert sample_verification_result.status == VerificationStatus.CONFIRMED
        assert sample_verification_result.original_confidence == 0.45
        assert sample_verification_result.reasoning == "High-authority wire service confirms claim"

    def test_final_confidence_capped_at_one(self) -> None:
        result = VerificationResult(
            fact_id="test",
            investigation_id="inv",
            status=VerificationStatus.CONFIRMED,
            original_confidence=0.8,
            confidence_boost=0.5,
            final_confidence=1.3,
            reasoning="Test cap",
        )
        assert result.final_confidence == 1.0

    def test_final_confidence_auto_computed(self) -> None:
        result = VerificationResult(
            fact_id="test",
            investigation_id="inv",
            status=VerificationStatus.CONFIRMED,
            original_confidence=0.4,
            confidence_boost=0.3,
            reasoning="Test auto-compute",
        )
        assert result.final_confidence == pytest.approx(0.7)

    def test_origin_dubious_flags_preserved(self) -> None:
        result = VerificationResult(
            fact_id="test",
            investigation_id="inv",
            status=VerificationStatus.CONFIRMED,
            original_confidence=0.5,
            confidence_boost=0.2,
            final_confidence=0.7,
            origin_dubious_flags=[DubiousFlag.PHANTOM, DubiousFlag.FOG],
            reasoning="Multi-flag preservation test",
        )
        assert len(result.origin_dubious_flags) == 2
        assert DubiousFlag.PHANTOM in result.origin_dubious_flags
        assert DubiousFlag.FOG in result.origin_dubious_flags

    def test_requires_human_review_defaults_false(self) -> None:
        result = VerificationResult(
            fact_id="test",
            investigation_id="inv",
            status=VerificationStatus.CONFIRMED,
            original_confidence=0.5,
            final_confidence=0.7,
            reasoning="Default test",
        )
        assert result.requires_human_review is False
        assert result.human_review_completed is False
        assert result.human_reviewer_notes is None

    def test_anomaly_related_fields(self) -> None:
        result = VerificationResult(
            fact_id="fact-A",
            investigation_id="inv",
            status=VerificationStatus.CONFIRMED,
            original_confidence=0.5,
            final_confidence=0.8,
            related_fact_id="fact-B",
            contradiction_type="temporal",
            reasoning="Temporal contradiction resolved",
        )
        assert result.related_fact_id == "fact-B"
        assert result.contradiction_type == "temporal"

    def test_query_attempts_max_three(self) -> None:
        with pytest.raises(Exception):
            VerificationResult(
                fact_id="test",
                investigation_id="inv",
                status=VerificationStatus.UNVERIFIABLE,
                original_confidence=0.3,
                final_confidence=0.3,
                query_attempts=4,
                reasoning="Over limit",
            )

    def test_query_attempts_valid_range(self) -> None:
        for attempts in [0, 1, 2, 3]:
            result = VerificationResult(
                fact_id="test",
                investigation_id="inv",
                status=VerificationStatus.UNVERIFIABLE,
                original_confidence=0.3,
                final_confidence=0.3,
                query_attempts=attempts,
                reasoning=f"Attempts: {attempts}",
            )
            assert result.query_attempts == attempts

    def test_verified_at_default_utc(self) -> None:
        result = VerificationResult(
            fact_id="test",
            investigation_id="inv",
            status=VerificationStatus.PENDING,
            original_confidence=0.5,
            final_confidence=0.5,
            reasoning="Timestamp test",
        )
        assert result.verified_at.tzinfo is not None

    def test_empty_evidence_lists_default(self) -> None:
        result = VerificationResult(
            fact_id="test",
            investigation_id="inv",
            status=VerificationStatus.UNVERIFIABLE,
            original_confidence=0.3,
            final_confidence=0.3,
            reasoning="No evidence",
        )
        assert result.supporting_evidence == []
        assert result.refuting_evidence == []
        assert result.queries_used == []


# ── VerificationResultRecord Tests ───────────────────────────────────────


class TestVerificationResultRecord:
    def test_from_result_creates_valid_record(
        self, sample_verification_result: VerificationResult
    ) -> None:
        record = VerificationResultRecord.from_result(sample_verification_result)
        assert record.fact_id == sample_verification_result.fact_id
        assert record.status == sample_verification_result.status
        assert record.original_confidence == sample_verification_result.original_confidence
        assert record.created_at is not None
        assert record.updated_at is not None

    def test_to_result_returns_verification_result(
        self, sample_verification_result: VerificationResult
    ) -> None:
        record = VerificationResultRecord.from_result(sample_verification_result)
        result = record.to_result()
        assert isinstance(result, VerificationResult)
        assert not isinstance(result, VerificationResultRecord)
        assert result.fact_id == sample_verification_result.fact_id
        assert result.status == sample_verification_result.status

    def test_round_trip_preservation(
        self, sample_verification_result: VerificationResult
    ) -> None:
        record = VerificationResultRecord.from_result(sample_verification_result)
        result = record.to_result()
        assert result.fact_id == sample_verification_result.fact_id
        assert result.investigation_id == sample_verification_result.investigation_id
        assert result.status == sample_verification_result.status
        assert result.original_confidence == sample_verification_result.original_confidence
        assert result.confidence_boost == sample_verification_result.confidence_boost
        assert result.final_confidence == sample_verification_result.final_confidence
        assert result.query_attempts == sample_verification_result.query_attempts
        assert result.reasoning == sample_verification_result.reasoning
        assert result.origin_dubious_flags == sample_verification_result.origin_dubious_flags

    def test_storage_timestamps_set(
        self, sample_verification_result: VerificationResult
    ) -> None:
        before = datetime.now(timezone.utc)
        record = VerificationResultRecord.from_result(sample_verification_result)
        after = datetime.now(timezone.utc)
        assert before <= record.created_at <= after
        assert before <= record.updated_at <= after

    def test_record_inherits_all_fields(
        self, sample_verification_result: VerificationResult
    ) -> None:
        record = VerificationResultRecord.from_result(sample_verification_result)
        assert hasattr(record, "created_at")
        assert hasattr(record, "updated_at")
        assert hasattr(record, "fact_id")
        assert hasattr(record, "origin_dubious_flags")
        assert hasattr(record, "requires_human_review")
