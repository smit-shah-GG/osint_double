"""Re-classification logic per CONTEXT.md decisions.

Applies verification results to update fact classifications:
- Preserves origin_dubious_flags before clearing (audit trail)
- Updates credibility score with confidence boost (capped at 1.0)
- Re-assesses impact tier with new evidence for CONFIRMED facts
- Context-dependent ANOMALY resolution (temporal->SUPERSEDED, factual->REFUTED)
- Records history entries for full audit trail

Usage:
    from osint_system.agents.sifters.verification.reclassifier import Reclassifier

    reclassifier = Reclassifier()
    updated = await reclassifier.reclassify_fact(
        fact_id, investigation_id, verification_result,
        classification_store, fact_store,
    )
"""

from typing import Any, Optional

import structlog

from osint_system.agents.sifters.classification.impact_assessor import ImpactAssessor
from osint_system.agents.sifters.verification.schemas import (
    VerificationResult,
    VerificationStatus,
)
from osint_system.data_management.classification_store import ClassificationStore
from osint_system.data_management.fact_store import FactStore
from osint_system.data_management.schemas import (
    DubiousFlag,
    FactClassification,
)


class Reclassifier:
    """Re-classification logic per CONTEXT.md decisions.

    Key behaviors:
    - Preserve origin_dubious_flags before clearing (audit trail)
    - Re-assess impact tier with new evidence
    - Context-dependent ANOMALY resolution (temporal->SUPERSEDED, factual->REFUTED)
    - Update ClassificationStore with new status
    """

    def __init__(
        self,
        impact_assessor: Optional[ImpactAssessor] = None,
    ) -> None:
        """Initialize Reclassifier.

        Args:
            impact_assessor: Phase 7 assessor for impact re-assessment.
                           Lazy-initialized on first use if not provided.
        """
        self._impact_assessor = impact_assessor
        self._logger = structlog.get_logger().bind(component="Reclassifier")

    def _get_impact_assessor(self) -> ImpactAssessor:
        """Lazy-init ImpactAssessor on first use."""
        if self._impact_assessor is None:
            self._impact_assessor = ImpactAssessor()
        return self._impact_assessor

    async def reclassify_fact(
        self,
        fact_id: str,
        investigation_id: str,
        verification_result: VerificationResult,
        classification_store: ClassificationStore,
        fact_store: FactStore,
    ) -> Optional[FactClassification]:
        """Apply verification result to update classification.

        Per CONTEXT.md:
        1. Preserve origin_dubious_flags before clearing
        2. Add history entry with verification trigger
        3. Clear current dubious_flags (resolved)
        4. Apply confidence boost (capped at 1.0)
        5. Re-assess impact tier with new evidence (for CONFIRMED)
        6. Save updated classification

        Args:
            fact_id: Fact identifier.
            investigation_id: Investigation scope.
            verification_result: Completed verification result.
            classification_store: Store for classification persistence.
            fact_store: Store for fact retrieval (needed for impact re-assessment).

        Returns:
            Updated FactClassification, or None if classification not found.
        """
        # Retrieve current classification
        classification_dict = await classification_store.get_classification(
            investigation_id, fact_id
        )
        if classification_dict is None:
            self._logger.warning(
                "classification_not_found",
                fact_id=fact_id,
                investigation_id=investigation_id,
            )
            return None

        classification = FactClassification(**classification_dict)

        # 1. Preserve origin dubious flags
        origin_flags = list(classification.dubious_flags)

        # 2. Add history entry before modification
        classification.add_history_entry(
            f"verification_{verification_result.status.value}"
        )

        # 3. Clear current dubious flags (they're resolved)
        classification.dubious_flags = []

        # 4. Apply confidence boost (capped at 1.0)
        new_credibility = min(
            1.0,
            classification.credibility_score + verification_result.confidence_boost,
        )
        classification.credibility_score = new_credibility

        # 5. Re-assess impact tier for CONFIRMED facts
        if verification_result.status == VerificationStatus.CONFIRMED:
            await self._reassess_impact(
                classification, fact_id, investigation_id, verification_result, fact_store
            )

        # 6. Save updated classification
        await classification_store.save_classification(classification)

        self._logger.info(
            "fact_reclassified",
            fact_id=fact_id,
            status=verification_result.status.value,
            origin_flags=[f.value for f in origin_flags],
            new_credibility=new_credibility,
            impact_tier=classification.impact_tier.value,
        )

        return classification

    async def resolve_anomaly(
        self,
        winner_id: str,
        loser_id: str,
        contradiction_type: str,
        investigation_id: str,
        classification_store: ClassificationStore,
    ) -> tuple[Optional[FactClassification], Optional[FactClassification]]:
        """Resolve ANOMALY contradiction per CONTEXT.md context-dependent rules.

        Per CONTEXT.md:
        - Temporal contradictions -> loser marked SUPERSEDED
        - Factual contradictions (negation, numeric, attribution) -> loser marked REFUTED

        Args:
            winner_id: Fact ID of the winning claim.
            loser_id: Fact ID of the losing claim.
            contradiction_type: Type of contradiction (temporal, negation, numeric, attribution).
            investigation_id: Investigation scope.
            classification_store: Store for classification persistence.

        Returns:
            (winner_classification, loser_classification) tuple.
            Either may be None if not found.
        """
        # Get winner classification
        winner_dict = await classification_store.get_classification(
            investigation_id, winner_id
        )
        loser_dict = await classification_store.get_classification(
            investigation_id, loser_id
        )

        winner_classification = None
        loser_classification = None

        # Update winner → CONFIRMED
        if winner_dict is not None:
            winner_classification = FactClassification(**winner_dict)
            winner_classification.add_history_entry(
                f"anomaly_resolution_winner_{contradiction_type}"
            )
            winner_classification.dubious_flags = []
            await classification_store.save_classification(winner_classification)

        # Update loser → SUPERSEDED or REFUTED
        if loser_dict is not None:
            loser_classification = FactClassification(**loser_dict)
            loser_status = self._determine_loser_status(contradiction_type)
            loser_classification.add_history_entry(
                f"anomaly_resolution_loser_{loser_status.value}"
            )
            loser_classification.dubious_flags = []
            await classification_store.save_classification(loser_classification)

        self._logger.info(
            "anomaly_resolved",
            winner_id=winner_id,
            loser_id=loser_id,
            contradiction_type=contradiction_type,
            loser_status=self._determine_loser_status(contradiction_type).value,
        )

        return winner_classification, loser_classification

    def _determine_loser_status(self, contradiction_type: str) -> VerificationStatus:
        """Determine loser status based on contradiction type.

        Per CONTEXT.md:
        - temporal -> SUPERSEDED (was true, no longer current)
        - negation, numeric, attribution -> REFUTED (was never true)

        Args:
            contradiction_type: Type of contradiction.

        Returns:
            VerificationStatus for the loser.
        """
        if contradiction_type == "temporal":
            return VerificationStatus.SUPERSEDED
        return VerificationStatus.REFUTED

    async def _reassess_impact(
        self,
        classification: FactClassification,
        fact_id: str,
        investigation_id: str,
        verification_result: VerificationResult,
        fact_store: FactStore,
    ) -> None:
        """Re-assess impact tier for confirmed facts using ImpactAssessor.

        Per CONTEXT.md: "Re-assess impact tier with new evidence, not simply inherited."

        Args:
            classification: Current classification being updated.
            fact_id: Fact identifier.
            investigation_id: Investigation scope.
            verification_result: Verification result with evidence.
            fact_store: Store for fact retrieval.
        """
        fact = await fact_store.get_fact(investigation_id, fact_id)
        if fact is None:
            self._logger.warning(
                "fact_not_found_for_impact_reassessment",
                fact_id=fact_id,
            )
            return

        # Enrich context with verification evidence
        enriched_context: dict[str, Any] = {
            "objective_keywords": [],
            "verification_evidence": [
                e.model_dump() for e in verification_result.supporting_evidence
            ],
        }

        assessor = self._get_impact_assessor()
        impact_result = assessor.assess(fact, enriched_context)

        if impact_result.tier != classification.impact_tier:
            self._logger.info(
                "impact_tier_changed",
                fact_id=fact_id,
                old_tier=classification.impact_tier.value,
                new_tier=impact_result.tier.value,
                reasoning=impact_result.reasoning,
            )
            classification.impact_tier = impact_result.tier
            classification.impact_reasoning = impact_result.reasoning
