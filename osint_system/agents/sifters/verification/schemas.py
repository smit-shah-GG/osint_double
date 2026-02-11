"""Verification domain schemas for Phase 8 verification loop.

Defines data structures for verification status tracking, evidence collection,
query generation, and result storage. All Phase 8 components consume these schemas.

Per CONTEXT.md decisions:
- 6 verification statuses (PENDING, IN_PROGRESS, CONFIRMED, REFUTED, UNVERIFIABLE, SUPERSEDED)
- Authority-weighted confidence boosts (+0.3 wire, +0.2 news, +0.1 social)
- 3 query variants per fact before abandonment
- Origin dubious flags preserved after verification
- Context-dependent loser handling for ANOMALY contradictions
- NOISE facts excluded from individual verification (batch only)

Import DubiousFlag from classification_schema (not redefined here).
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from osint_system.data_management.schemas.classification_schema import DubiousFlag


class VerificationStatus(str, Enum):
    """Verification status per CONTEXT.md decisions.

    Represents the outcome of the verification process for a dubious fact.
    Each status has distinct semantic meaning for downstream analysis:

    PENDING: Fact is queued for verification but not yet processed.
    IN_PROGRESS: Verification is actively running (queries executing).
    CONFIRMED: Evidence found that supports the claim.
    REFUTED: Evidence found that contradicts the claim.
    UNVERIFIABLE: 3 query variants exhausted, no sufficient evidence either way.
    SUPERSEDED: Temporal contradiction resolved - claim was true, no longer current.
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    CONFIRMED = "confirmed"
    REFUTED = "refuted"
    UNVERIFIABLE = "unverifiable"
    SUPERSEDED = "superseded"


class EvidenceItem(BaseModel):
    """Single piece of evidence from verification search.

    Captures source metadata for corroboration evaluation.
    Authority scoring comes from Phase 7's SourceCredibilityScorer hierarchy:
    - Wire services (AP, Reuters, AFP): 0.9
    - .gov/.edu domains: 0.85
    - .org domains: 0.7
    - Default news: 0.5
    - Social media: 0.3

    Per CONTEXT.md: A single high-authority source (>= 0.85) can confirm a claim.
    Lower-authority sources require 2+ independent confirmations.
    """

    source_url: str = Field(..., description="URL of the evidence source")
    source_domain: str = Field(
        ..., description="Domain extracted from URL (e.g., 'reuters.com')"
    )
    source_type: str = Field(
        ...,
        description=(
            "Source category: wire_service, news_outlet, "
            "official_statement, social_media"
        ),
    )
    authority_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Authority score from SourceCredibilityScorer (0.0-1.0)",
    )
    snippet: str = Field(..., description="Relevant text excerpt from source")
    retrieved_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When evidence was retrieved",
    )
    supports_claim: bool = Field(
        ..., description="True if evidence supports claim, False if refutes"
    )
    relevance_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="How relevant this evidence is to the claim (0.0-1.0)",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "source_url": "https://apnews.com/article/example-12345",
                    "source_domain": "apnews.com",
                    "source_type": "wire_service",
                    "authority_score": 0.9,
                    "snippet": "The State Department confirmed the meeting took place on Tuesday.",
                    "retrieved_at": "2026-02-10T12:00:00Z",
                    "supports_claim": True,
                    "relevance_score": 0.95,
                }
            ]
        }
    }


class VerificationQuery(BaseModel):
    """Query for verification search, specialized per dubious species.

    Per CONTEXT.md: Up to 3 query reformulations per dubious fact before
    abandonment. Query variants are species-specialized:

    - entity_focused: Extract key entities, search directly (highest precision)
    - exact_phrase: Search for distinctive phrases from the claim in quotes
    - broader_context: Widen scope to related events/topics
    - temporal_context: Find dated/timestamped versions (ANOMALY resolution)
    - authority_arbitration: Find higher-authority sources (ANOMALY resolution)
    - clarity_enhancement: Find more specific/quantified versions (ANOMALY/FOG)

    PHANTOM facts use source-chain queries (entity_focused targeting wire services
    and official statements) to trace back to root attribution.
    FOG facts use clarity-seeking queries to find harder/clearer claim versions.
    ANOMALY facts use compound approach: temporal + authority + clarity.
    """

    query: str = Field(..., description="The search query text")
    variant_type: Literal[
        "entity_focused",
        "exact_phrase",
        "broader_context",
        "temporal_context",
        "authority_arbitration",
        "clarity_enhancement",
    ] = Field(..., description="Query variant type for tracking and optimization")
    target_sources: list[str] = Field(
        default_factory=list,
        description=(
            "Preferred source types: wire_service, official_statement, "
            "news_outlet, social_media"
        ),
    )
    purpose: str = Field(
        default="",
        description="Why this query is being used (aids debugging and optimization)",
    )
    dubious_flag: Optional[DubiousFlag] = Field(
        default=None,
        description="Which dubious flag this query addresses (PHANTOM/FOG/ANOMALY)",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "query": "Putin Ukraine official statement press release",
                    "variant_type": "entity_focused",
                    "target_sources": ["wire_service", "official_statement"],
                    "purpose": "Trace PHANTOM attribution to named source",
                    "dubious_flag": "phantom",
                }
            ]
        }
    }


class EvidenceEvaluation(BaseModel):
    """Result of evidence aggregation for a single verification attempt.

    Produced by the EvidenceAggregator after assessing all collected evidence.
    Used to determine whether to finalize verification or retry with another
    query variant.

    Per CONTEXT.md:
    - Confirmation requires 1 high-authority (>= 0.85) OR 2+ independent lower sources
    - Refutation requires credible contradicting evidence (authority >= 0.7)
    - Insufficient evidence leads to retry (up to 3 attempts) then UNVERIFIABLE
    """

    status: VerificationStatus = Field(
        ..., description="Recommended verification status based on evidence"
    )
    confidence_boost: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Cumulative confidence boost from evidence: "
            "+0.3 wire, +0.2 news, +0.1 social"
        ),
    )
    supporting_evidence: list[EvidenceItem] = Field(
        default_factory=list,
        description="Evidence items that support the claim",
    )
    refuting_evidence: list[EvidenceItem] = Field(
        default_factory=list,
        description="Evidence items that refute the claim",
    )
    reasoning: str = Field(
        default="",
        description="Explanation of how evidence was evaluated",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "status": "confirmed",
                    "confidence_boost": 0.3,
                    "supporting_evidence": [],
                    "refuting_evidence": [],
                    "reasoning": "High-authority source (0.90) confirms claim",
                }
            ]
        }
    }


class VerificationResult(BaseModel):
    """Complete verification outcome for a single fact.

    The primary output of the verification loop. Contains the full evidence
    trail, confidence updates, query history, and metadata needed for
    re-classification and audit.

    Per CONTEXT.md:
    - final_confidence = min(1.0, original_confidence + confidence_boost)
    - origin_dubious_flags preserved after verification (not cleared)
    - requires_human_review = True for CRITICAL tier facts
    - related_fact_id and contradiction_type populated for ANOMALY resolution
    - query_attempts tracks how many of the 3 allowed queries were used
    """

    # Identity
    fact_id: str = Field(..., description="ID of the fact being verified")
    investigation_id: str = Field(..., description="Investigation scope")

    # Verification outcome
    status: VerificationStatus = Field(
        ..., description="Final verification status"
    )

    # Confidence tracking
    original_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score before verification",
    )
    confidence_boost: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Cumulative confidence boost from evidence: "
            "+0.3 wire, +0.2 news, +0.1 social"
        ),
    )
    final_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="min(1.0, original_confidence + confidence_boost)",
    )

    # Evidence trail
    supporting_evidence: list[EvidenceItem] = Field(
        default_factory=list,
        description="Evidence items that support the claim",
    )
    refuting_evidence: list[EvidenceItem] = Field(
        default_factory=list,
        description="Evidence items that refute the claim",
    )

    # Query tracking
    query_attempts: int = Field(
        default=0,
        ge=0,
        le=3,
        description="Number of query variants attempted (max 3)",
    )
    queries_used: list[str] = Field(
        default_factory=list,
        description="The actual query strings executed",
    )

    # Origin preservation per CONTEXT.md
    origin_dubious_flags: list[DubiousFlag] = Field(
        default_factory=list,
        description=(
            "Original dubious flags from Phase 7 classification. "
            "Preserved after verification for provenance transparency."
        ),
    )

    # ANOMALY resolution fields
    related_fact_id: Optional[str] = Field(
        default=None,
        description="Linked fact ID for ANOMALY contradiction resolution",
    )
    contradiction_type: Optional[str] = Field(
        default=None,
        description=(
            "Type of contradiction: negation, numeric, temporal, attribution. "
            "Determines loser handling (temporal -> SUPERSEDED, others -> REFUTED)."
        ),
    )

    # Reasoning
    reasoning: str = Field(
        ..., description="Explanation of verification outcome"
    )

    # Timestamps
    verified_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When verification completed",
    )

    # Human review (CRITICAL tier per CONTEXT.md)
    requires_human_review: bool = Field(
        default=False,
        description="True for CRITICAL tier facts per CONTEXT.md",
    )
    human_review_completed: bool = Field(
        default=False,
        description="True after human analyst approves/modifies result",
    )
    human_reviewer_notes: Optional[str] = Field(
        default=None,
        description="Notes from human reviewer if review was conducted",
    )

    @model_validator(mode="before")
    @classmethod
    def cap_final_confidence(cls, data: dict) -> dict:
        """Ensure final_confidence is capped at 1.0 before field validation.

        Per CONTEXT.md: final_confidence = min(1.0, original + boost).
        This validator clamps the value and auto-computes if needed.
        """
        if isinstance(data, dict):
            original = data.get("original_confidence", 0.0)
            boost = data.get("confidence_boost", 0.0)
            final = data.get("final_confidence")
            if final is None:
                # Auto-compute if not provided
                data["final_confidence"] = min(1.0, original + boost)
            else:
                # Clamp to 1.0
                data["final_confidence"] = min(1.0, final)
        return data

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "fact_id": "fact-uuid-123",
                    "investigation_id": "inv-456",
                    "status": "confirmed",
                    "original_confidence": 0.45,
                    "confidence_boost": 0.3,
                    "final_confidence": 0.75,
                    "supporting_evidence": [
                        {
                            "source_url": "https://apnews.com/article/12345",
                            "source_domain": "apnews.com",
                            "source_type": "wire_service",
                            "authority_score": 0.9,
                            "snippet": "Officials confirmed the event.",
                            "supports_claim": True,
                            "relevance_score": 0.95,
                        }
                    ],
                    "refuting_evidence": [],
                    "query_attempts": 1,
                    "queries_used": [
                        "Putin Ukraine official statement press release"
                    ],
                    "origin_dubious_flags": ["phantom"],
                    "reasoning": "High-authority wire service (AP, 0.90) confirms claim",
                    "requires_human_review": False,
                }
            ]
        }
    }
