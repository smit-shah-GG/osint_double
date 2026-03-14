"""Analysis output Pydantic schemas for intelligence report generation.

Defines the typed data structures consumed by the synthesis engine, report
generator, and dashboard. All downstream Phase 10 components import these
schemas; they are the contract between the data aggregation layer and the
LLM synthesis / reporting layers.

Key models:
- ConfidenceAssessment: IC-style confidence with numeric backing
- KeyJudgment: Analytical judgment with confidence and evidence chain
- AlternativeHypothesis: Competing interpretation per IC Alternative Analysis
- ContradictionEntry: Unresolved or resolved contradictions between facts
- TimelineEntry: Chronologically ordered event with provenance
- SourceInventoryEntry: Per-source metadata and fact counts
- InvestigationSnapshot: Complete pre-aggregated data for synthesis
- AnalysisSynthesis: Full analysis output ready for report rendering

Design principles:
- IC-style confidence language (low/moderate/high) in prose, numeric in tables
- Every judgment links back to supporting fact IDs for audit trail
- InvestigationSnapshot is self-contained: everything needed for synthesis in one object
- AnalysisSynthesis is the complete output: can be serialized, versioned, diffed
"""

import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


class ConfidenceAssessment(BaseModel):
    """IC-style confidence assessment with numeric backing.

    Maps to Intelligence Community standard language:
    - low: significant uncertainties, limited corroboration
    - moderate: some uncertainties, partial corroboration
    - high: strong evidence, multiple independent sources

    The numeric score provides granularity within each level for
    sorting and comparison. source_count and highest_authority
    provide the evidence basis for the confidence level.

    Attributes:
        level: IC-standard confidence language.
        numeric: Numeric score (0.0-1.0) for sorting/comparison.
        reasoning: Why this confidence level was assigned.
        source_count: Number of independent sources supporting.
        highest_authority: Highest authority score among sources.
    """

    level: Literal["low", "moderate", "high"] = Field(
        ..., description="IC-style confidence level"
    )
    numeric: float = Field(
        ..., ge=0.0, le=1.0, description="Numeric confidence score"
    )
    reasoning: str = Field(
        ..., description="Why this confidence level was assigned"
    )
    source_count: int = Field(
        default=0,
        ge=0,
        description="Number of independent sources supporting",
    )
    highest_authority: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Highest authority score among supporting sources",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "level": "high",
                    "numeric": 0.92,
                    "reasoning": "Confirmed by 3 independent wire services",
                    "source_count": 3,
                    "highest_authority": 0.9,
                }
            ]
        }
    }


class KeyJudgment(BaseModel):
    """Analytical judgment with confidence and evidence chain.

    Each key judgment is a standalone analytical conclusion drawn from
    the evidence. It links back to specific fact IDs for full auditability.
    The reasoning field contains the analyst's (LLM's) reasoning chain,
    not just a restatement of the judgment.

    Attributes:
        judgment: The analytical judgment statement.
        confidence: IC-style confidence assessment.
        supporting_fact_ids: Fact IDs backing this judgment.
        reasoning: Analytical reasoning chain leading to this judgment.
    """

    judgment: str = Field(
        ..., description="The analytical judgment statement"
    )
    confidence: ConfidenceAssessment = Field(
        ..., description="IC-style confidence assessment"
    )
    supporting_fact_ids: list[str] = Field(
        default_factory=list,
        description="Fact IDs backing this judgment",
    )
    reasoning: str = Field(
        ..., description="Analytical reasoning chain"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "judgment": "Russia has escalated military operations in eastern Ukraine since January 2024",
                    "confidence": {
                        "level": "high",
                        "numeric": 0.88,
                        "reasoning": "Multiple wire services and satellite imagery confirm troop movements",
                        "source_count": 4,
                        "highest_authority": 0.9,
                    },
                    "supporting_fact_ids": ["fact-001", "fact-003", "fact-007"],
                    "reasoning": "Troop movement data from 3 wire services corroborated by satellite imagery analysis",
                }
            ]
        }
    }


class AlternativeHypothesis(BaseModel):
    """Competing interpretation per IC Alternative Analysis standards.

    Alternative hypotheses are structured competing interpretations
    generated for any finding with moderate or low confidence. Per
    CONTEXT.md: not wishy-washy, but structured competing interpretations.

    Attributes:
        hypothesis: The alternative interpretation statement.
        likelihood: Assessed likelihood of this hypothesis.
        supporting_evidence: Evidence points favoring this hypothesis.
        weaknesses: Why this hypothesis may be wrong.
    """

    hypothesis: str = Field(
        ..., description="The alternative interpretation"
    )
    likelihood: Literal["unlikely", "possible", "plausible"] = Field(
        ..., description="Assessed likelihood"
    )
    supporting_evidence: list[str] = Field(
        default_factory=list,
        description="Evidence points favoring this hypothesis",
    )
    weaknesses: list[str] = Field(
        default_factory=list,
        description="Why this hypothesis may be wrong",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "hypothesis": "Troop movements represent routine rotation rather than escalation",
                    "likelihood": "possible",
                    "supporting_evidence": [
                        "Annual rotation cycle matches timeline",
                        "No corresponding diplomatic escalation",
                    ],
                    "weaknesses": [
                        "Scale exceeds historical rotation sizes by 3x",
                        "Equipment types inconsistent with rotation",
                    ],
                }
            ]
        }
    }


class ContradictionEntry(BaseModel):
    """Contradiction between facts with resolution tracking.

    Tracks where sources disagree, including the resolution status.
    Unresolved contradictions appear in the "Contradictions & Unresolved
    Questions" section of the intelligence report.

    Attributes:
        description: What the contradiction is.
        fact_ids: Conflicting fact IDs.
        resolution_status: Current resolution state.
        resolution_notes: How it was resolved (if applicable).
    """

    description: str = Field(
        ..., description="What the contradiction is"
    )
    fact_ids: list[str] = Field(
        default_factory=list,
        description="Conflicting fact IDs",
    )
    resolution_status: Literal["resolved", "unresolved", "partially_resolved"] = Field(
        ..., description="Current resolution state"
    )
    resolution_notes: str = Field(
        default="",
        description="How it was resolved (if applicable)",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "description": "Casualty figures differ: AP reports 12, Reuters reports 8",
                    "fact_ids": ["fact-005", "fact-009"],
                    "resolution_status": "unresolved",
                    "resolution_notes": "",
                }
            ]
        }
    }


class TimelineEntry(BaseModel):
    """Chronologically ordered event with provenance.

    Extracted from facts with temporal markers, sorted by timestamp.
    Each entry links back to supporting fact IDs and carries its own
    confidence assessment.

    Attributes:
        timestamp: ISO-format date string.
        event: Event description.
        fact_ids: Supporting fact IDs.
        confidence: Confidence assessment for this timeline entry.
    """

    timestamp: str = Field(
        ..., description="ISO-format date string"
    )
    event: str = Field(
        ..., description="Event description"
    )
    fact_ids: list[str] = Field(
        default_factory=list,
        description="Supporting fact IDs",
    )
    confidence: ConfidenceAssessment = Field(
        ..., description="Confidence assessment for this timeline entry"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "timestamp": "2024-03-15",
                    "event": "Putin visited Beijing for bilateral summit",
                    "fact_ids": ["fact-001"],
                    "confidence": {
                        "level": "high",
                        "numeric": 0.95,
                        "reasoning": "Multiple official sources confirm",
                        "source_count": 5,
                        "highest_authority": 0.9,
                    },
                }
            ]
        }
    }


class SourceInventoryEntry(BaseModel):
    """Per-source metadata and fact counts for source assessment.

    Provides a summary of each source's contribution to the investigation,
    including authority score and fact count. Used in the report's source
    assessment section.

    Attributes:
        source_id: Unique source identifier.
        source_domain: Domain name of the source.
        source_type: Source category (wire_service, news_outlet, etc.).
        authority_score: Credibility authority score (0.0-1.0).
        fact_count: Number of facts from this source.
        last_accessed: ISO timestamp of last access.
    """

    source_id: str = Field(
        ..., description="Unique source identifier"
    )
    source_domain: str = Field(
        default="", description="Domain name of the source"
    )
    source_type: str = Field(
        default="unknown", description="Source category"
    )
    authority_score: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Credibility authority score",
    )
    fact_count: int = Field(
        default=0, ge=0, description="Number of facts from this source"
    )
    last_accessed: str = Field(
        default="", description="ISO timestamp of last access"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "source_id": "apnews.com/article/123",
                    "source_domain": "apnews.com",
                    "source_type": "wire_service",
                    "authority_score": 0.9,
                    "fact_count": 7,
                    "last_accessed": "2024-03-15T12:00:00Z",
                }
            ]
        }
    }


class InvestigationSnapshot(BaseModel):
    """Complete pre-aggregated investigation data for LLM synthesis.

    Self-contained container holding everything needed to generate an
    intelligence report. Built by DataAggregator from FactStore,
    ClassificationStore, VerificationStore, and GraphPipeline.

    The token_estimate() method provides a rough approximation of the
    serialized size for prompt budget planning. Per RESEARCH.md Pitfall 1,
    synthesis prompts should target 10K-30K tokens per section.

    Attributes:
        investigation_id: Investigation scope identifier.
        objective: Investigation objective/target description.
        facts: Raw fact dicts from FactStore.
        classifications: Classification dicts from ClassificationStore.
        verification_results: Verification result dicts from VerificationStore.
        graph_summary: Graph stats and key entities from GraphPipeline.
        fact_count: Total fact count.
        confirmed_count: Facts with CONFIRMED verification status.
        refuted_count: Facts with REFUTED verification status.
        unverifiable_count: Facts with UNVERIFIABLE verification status.
        dubious_count: Facts with dubious classification flags.
        source_inventory: Per-source metadata and fact counts.
        timeline_entries: Chronologically ordered events.
        created_at: Snapshot creation timestamp.
    """

    investigation_id: str = Field(
        ..., description="Investigation scope identifier"
    )
    objective: str = Field(
        default="", description="Investigation objective/target"
    )
    facts: list[dict[str, Any]] = Field(
        default_factory=list, description="Raw fact dicts from FactStore"
    )
    classifications: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Classification dicts from ClassificationStore",
    )
    verification_results: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Verification result dicts from VerificationStore",
    )
    graph_summary: dict[str, Any] = Field(
        default_factory=dict,
        description="Graph stats and key entities from GraphPipeline",
    )
    fact_count: int = Field(default=0, ge=0, description="Total fact count")
    confirmed_count: int = Field(
        default=0, ge=0, description="CONFIRMED verification count"
    )
    refuted_count: int = Field(
        default=0, ge=0, description="REFUTED verification count"
    )
    unverifiable_count: int = Field(
        default=0, ge=0, description="UNVERIFIABLE verification count"
    )
    dubious_count: int = Field(
        default=0, ge=0, description="Dubious classification count"
    )
    source_inventory: list[SourceInventoryEntry] = Field(
        default_factory=list,
        description="Per-source metadata and fact counts",
    )
    timeline_entries: list[TimelineEntry] = Field(
        default_factory=list,
        description="Chronologically ordered events",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Snapshot creation timestamp",
    )

    def token_estimate(self) -> int:
        """Rough estimate of total tokens when serialized.

        Uses the approximation: tokens ~= len(json_string) / 4.
        This is a heuristic for English text and JSON structure;
        actual token counts depend on the specific tokenizer.

        Returns:
            Estimated token count.
        """
        serialized = json.dumps(
            self.model_dump(mode="json"), default=str
        )
        return len(serialized) // 4

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "investigation_id": "inv-456",
                    "objective": "Track Russian military movements in eastern Ukraine",
                    "facts": [],
                    "classifications": [],
                    "verification_results": [],
                    "graph_summary": {
                        "node_count": 42,
                        "edge_count": 87,
                        "clusters": 3,
                    },
                    "fact_count": 25,
                    "confirmed_count": 15,
                    "refuted_count": 3,
                    "unverifiable_count": 4,
                    "dubious_count": 3,
                    "source_inventory": [],
                    "timeline_entries": [],
                    "created_at": "2024-03-15T12:00:00Z",
                }
            ]
        }
    }


class AnalysisSynthesis(BaseModel):
    """Complete analysis output ready for report rendering.

    The primary output of the LLM synthesis pipeline. Contains the
    executive summary, key judgments, alternative hypotheses, and all
    metadata needed to render an intelligence report. The snapshot
    field preserves the exact data this analysis was based on for
    reproducibility and audit.

    Attributes:
        investigation_id: Investigation scope identifier.
        executive_summary: 1-2 paragraph executive brief.
        key_judgments: Analytical judgments with confidence and evidence.
        alternative_hypotheses: Competing interpretations.
        contradictions: Contradictions between facts.
        implications: Strategic implications of the findings.
        forecasts: Forward-looking assessments.
        overall_confidence: Overall confidence in the analysis.
        source_assessment: Overall assessment of source quality/diversity.
        snapshot: The InvestigationSnapshot this analysis was based on.
        generated_at: When this synthesis was generated.
        model_version: Which LLM model was used.
        version: Report version number (increments on regeneration).
    """

    investigation_id: str = Field(
        ..., description="Investigation scope identifier"
    )
    executive_summary: str = Field(
        ..., description="1-2 paragraph executive brief"
    )
    key_judgments: list[KeyJudgment] = Field(
        default_factory=list,
        description="Analytical judgments with confidence and evidence",
    )
    alternative_hypotheses: list[AlternativeHypothesis] = Field(
        default_factory=list,
        description="Competing interpretations",
    )
    contradictions: list[ContradictionEntry] = Field(
        default_factory=list,
        description="Contradictions between facts",
    )
    implications: list[str] = Field(
        default_factory=list,
        description="Strategic implications of the findings",
    )
    forecasts: list[str] = Field(
        default_factory=list,
        description="Forward-looking assessments",
    )
    overall_confidence: ConfidenceAssessment = Field(
        ..., description="Overall confidence in the analysis"
    )
    source_assessment: str = Field(
        default="",
        description="Overall assessment of source quality/diversity",
    )
    snapshot: InvestigationSnapshot = Field(
        ..., description="The data this analysis was based on"
    )
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this synthesis was generated",
    )
    model_version: str = Field(
        default="", description="Which LLM model was used"
    )
    version: int = Field(
        default=1, ge=1, description="Report version number"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "investigation_id": "inv-456",
                    "executive_summary": "We assess with high confidence that Russia has escalated military operations in eastern Ukraine.",
                    "key_judgments": [],
                    "alternative_hypotheses": [],
                    "contradictions": [],
                    "implications": ["Potential for further territorial gains"],
                    "forecasts": ["Escalation likely to continue through Q2 2024"],
                    "overall_confidence": {
                        "level": "moderate",
                        "numeric": 0.72,
                        "reasoning": "Strong evidence base but limited access to closed-source intelligence",
                        "source_count": 12,
                        "highest_authority": 0.9,
                    },
                    "source_assessment": "Predominantly open-source; 3 wire services, 5 news outlets, 4 social media",
                    "snapshot": {
                        "investigation_id": "inv-456",
                        "facts": [],
                        "classifications": [],
                        "verification_results": [],
                        "created_at": "2024-03-15T12:00:00Z",
                    },
                    "generated_at": "2024-03-15T13:00:00Z",
                    "model_version": "gemini-1.5-pro",
                    "version": 1,
                }
            ]
        }
    }
