"""Fact classification agent for categorizing extracted facts.

Per Phase 7 CONTEXT.md:
- Impact tier (critical/less_critical) based on geopolitical significance
- Trust status via dubious flags (phantom/fog/anomaly/noise)
- Credibility scoring with full breakdown
- Classifications are SEPARATE from facts (facts immutable)

Classification flow:
1. Compute credibility score (SourceCredibilityScorer)
2. Assess impact tier (critical vs less-critical)
3. Detect dubious flags via Boolean logic gates
4. Calculate priority score (Impact x Fixability)
5. Store classification record
"""

from typing import Any, Dict, List, Optional

from loguru import logger

from osint_system.agents.sifters.base_sifter import BaseSifter
from osint_system.agents.sifters.credibility import (
    EchoDetector,
    SourceCredibilityScorer,
)
from osint_system.data_management.classification_store import ClassificationStore
from osint_system.data_management.fact_store import FactStore
from osint_system.data_management.schemas import (
    ClassificationReasoning,
    CredibilityBreakdown,
    DubiousFlag,
    FactClassification,
    ImpactTier,
)


class FactClassificationAgent(BaseSifter):
    """
    Classifies extracted facts into impact tiers with dubious detection.

    Per Phase 7 CONTEXT.md:
    - Impact and trust are orthogonal dimensions
    - A fact can be both "critical" AND "dubious"
    - High-impact dubious facts get priority verification

    Classification flow:
    1. Compute credibility score (Plan 02)
    2. Assess impact tier (critical vs less-critical)
    3. Detect dubious flags via Boolean logic gates (Plan 03)
    4. Calculate priority score (Impact x Fixability)
    5. Store classification record

    Attributes:
        classification_store: Storage for classification records
        fact_store: Read access to facts being classified
    """

    def __init__(
        self,
        classification_store: Optional[ClassificationStore] = None,
        fact_store: Optional[FactStore] = None,
    ):
        """
        Initialize fact classification agent.

        Args:
            classification_store: Store for classification records (creates default if None)
            fact_store: Store for reading facts (creates default if None)
        """
        super().__init__(
            name="FactClassificationAgent",
            description="Classifies extracted facts into impact tiers with dubious detection",
        )
        self._classification_store = classification_store
        self._fact_store = fact_store
        self.logger = logger.bind(component="FactClassificationAgent")

        self.logger.info("FactClassificationAgent initialized")

    @property
    def classification_store(self) -> ClassificationStore:
        """Lazy initialization of classification store."""
        if self._classification_store is None:
            self._classification_store = ClassificationStore()
        return self._classification_store

    @property
    def fact_store(self) -> FactStore:
        """Lazy initialization of fact store."""
        if self._fact_store is None:
            self._fact_store = FactStore()
        return self._fact_store

    @property
    def credibility_scorer(self) -> SourceCredibilityScorer:
        """Lazy initialization of credibility scorer."""
        if not hasattr(self, "_credibility_scorer") or self._credibility_scorer is None:
            self._credibility_scorer = SourceCredibilityScorer()
        return self._credibility_scorer

    @property
    def echo_detector(self) -> EchoDetector:
        """Lazy initialization of echo detector."""
        if not hasattr(self, "_echo_detector") or self._echo_detector is None:
            self._echo_detector = EchoDetector()
        return self._echo_detector

    async def sift(self, content: dict) -> list[dict]:
        """
        Classify facts and return classifications.

        This is the core sifter method per BaseSifter contract.

        Args:
            content: {
                'facts': list of ExtractedFact dicts,
                'investigation_id': str
            }

        Returns:
            List of FactClassification dicts
        """
        facts = content.get("facts", [])
        investigation_id = content.get("investigation_id", "default")

        if not facts:
            self.logger.warning("No facts to classify")
            return []

        self.logger.info(
            f"Classifying {len(facts)} facts",
            investigation_id=investigation_id,
        )

        classifications = []
        for fact in facts:
            try:
                classification = await self.classify_fact(fact, investigation_id)
                classifications.append(classification.model_dump(mode="json"))
            except Exception as e:
                self.logger.error(
                    f"Failed to classify fact {fact.get('fact_id', 'unknown')}: {e}",
                    exc_info=True,
                )
                continue

        # Save all classifications
        if classifications:
            await self.classification_store.save_classifications(
                investigation_id,
                [FactClassification(**c) for c in classifications],
            )

        self.logger.info(
            f"Classified {len(classifications)} facts",
            investigation_id=investigation_id,
            critical=len([c for c in classifications if c.get("impact_tier") == "critical"]),
            dubious=len([c for c in classifications if c.get("dubious_flags")]),
        )

        return classifications

    async def classify_fact(
        self,
        fact: Dict[str, Any],
        investigation_id: str,
    ) -> FactClassification:
        """
        Classify a single fact.

        Args:
            fact: ExtractedFact dict
            investigation_id: Investigation scope

        Returns:
            FactClassification for the fact
        """
        fact_id = fact.get("fact_id", "unknown")

        # Step 1: Compute credibility score (Plan 02 implements this)
        credibility_score, credibility_breakdown = self._compute_credibility(fact)

        # Step 2: Assess impact tier
        impact_tier, impact_reasoning = self._assess_impact(fact, investigation_id)

        # Step 3: Detect dubious flags (Plan 03 implements this)
        dubious_flags, classification_reasoning = self._detect_dubious(
            fact, credibility_score
        )

        # Step 4: Calculate priority score (Impact x Fixability)
        priority_score = self._calculate_priority(
            impact_tier, dubious_flags, credibility_score
        )

        classification = FactClassification(
            fact_id=fact_id,
            investigation_id=investigation_id,
            impact_tier=impact_tier,
            dubious_flags=dubious_flags,
            priority_score=priority_score,
            credibility_score=credibility_score,
            credibility_breakdown=credibility_breakdown,
            classification_reasoning=classification_reasoning,
            impact_reasoning=impact_reasoning,
        )

        self.logger.debug(
            f"Classified fact {fact_id}",
            impact=impact_tier.value,
            dubious_count=len(dubious_flags),
            credibility=credibility_score,
            priority=priority_score,
        )

        return classification

    def _compute_credibility(
        self,
        fact: Dict[str, Any],
    ) -> tuple[float, Optional[CredibilityBreakdown]]:
        """
        Compute credibility score for a fact.

        Per CONTEXT.md formula: Claim Score = Sum(SourceCred x Proximity x Precision)
        Plus logarithmic echo dampening for multiple sources.

        LIMITATION (Phase 7): This plan scores primary source only.
        Full multi-source echo dampening requires Phase 8 variant provenance
        enrichment. The EchoDetector infrastructure is in place, but
        variant provenances are not yet fetched/wired. See Phase 8 for
        complete implementation with variant provenance fetching.

        Args:
            fact: ExtractedFact dict

        Returns:
            (credibility_score, breakdown) tuple
        """
        # Single source scoring (Phase 7 limitation)
        # Phase 8 will add variant provenance fetching for full echo dampening
        score, breakdown = self.credibility_scorer.compute_credibility(fact)

        # Note: EchoDetector is available for Phase 8 integration:
        # When Phase 8 provides variant provenances, the flow becomes:
        #
        # variants = fact.get("variants", [])
        # if variants:
        #     variant_provenances = [
        #         await fact_store.get_provenance(v) for v in variants
        #     ]
        #     all_provenances = [fact.get("provenance")] + variant_provenances
        #     score, breakdown, source_scores = (
        #         self.credibility_scorer.score_multiple_sources(fact, variant_provenances)
        #     )
        #     echo_score = self.echo_detector.analyze_sources(
        #         all_provenances,
        #         [s.combined for s in source_scores]
        #     )
        #     breakdown = self.echo_detector.update_breakdown(breakdown, echo_score)
        #     score = echo_score.total_score

        return score, breakdown

    def _assess_impact(
        self,
        fact: Dict[str, Any],
        investigation_id: str,
    ) -> tuple[ImpactTier, Optional[str]]:
        """
        Assess impact tier based on geopolitical significance.

        Per CONTEXT.md: Impact based on:
        - Entity significance (world leaders > local officials)
        - Event type (military action > diplomatic meeting > routine statement)
        - Investigation context (recency, objective relevance)

        Plan 03 implements the full algorithm. This is the shell.

        Args:
            fact: ExtractedFact dict
            investigation_id: Investigation scope (for context)

        Returns:
            (impact_tier, reasoning) tuple
        """
        # Placeholder: Plan 03 implements context-aware impact assessment
        # For now: default to less_critical
        return ImpactTier.LESS_CRITICAL, "Default classification pending full implementation"

    def _detect_dubious(
        self,
        fact: Dict[str, Any],
        credibility_score: float,
    ) -> tuple[list[DubiousFlag], list[ClassificationReasoning]]:
        """
        Detect dubious flags using Boolean logic gates.

        Per CONTEXT.md taxonomy:
        - PHANTOM: hop_count > 2 AND primary_source IS NULL
        - FOG: claim_clarity < 0.5 OR attribution ~= "sources say"
        - ANOMALY: contradiction_count > 0
        - NOISE: source_credibility < 0.3

        Plan 03 implements the full detection logic. This is the shell.

        Args:
            fact: ExtractedFact dict
            credibility_score: Pre-computed credibility score

        Returns:
            (dubious_flags, classification_reasoning) tuple
        """
        # Placeholder: Plan 03 implements Boolean logic gates
        flags: List[DubiousFlag] = []
        reasoning: List[ClassificationReasoning] = []

        # Basic noise detection based on credibility
        if credibility_score < 0.3:
            flags.append(DubiousFlag.NOISE)
            reasoning.append(
                ClassificationReasoning(
                    flag=DubiousFlag.NOISE,
                    reason=f"credibility_score ({credibility_score:.2f}) < 0.3",
                    trigger_values={"credibility_score": credibility_score},
                )
            )

        # Basic fog detection based on claim_clarity
        quality = fact.get("quality", {})
        claim_clarity = quality.get("claim_clarity", 0.5) if quality else 0.5
        if claim_clarity < 0.5:
            flags.append(DubiousFlag.FOG)
            reasoning.append(
                ClassificationReasoning(
                    flag=DubiousFlag.FOG,
                    reason=f"claim_clarity ({claim_clarity:.2f}) < 0.5",
                    trigger_values={"claim_clarity": claim_clarity},
                )
            )

        return flags, reasoning

    def _calculate_priority(
        self,
        impact_tier: ImpactTier,
        dubious_flags: List[DubiousFlag],
        credibility_score: float,
    ) -> float:
        """
        Calculate priority score for Phase 8 queue ordering.

        Per CONTEXT.md: Priority = Impact × Fixability
        - High-impact fixable claims get priority
        - NOISE does not enter individual verification queue

        Args:
            impact_tier: Critical or less_critical
            dubious_flags: List of dubious flags
            credibility_score: Pre-computed credibility

        Returns:
            Priority score 0.0-1.0
        """
        # Impact factor: critical facts are higher priority
        impact_factor = 1.0 if impact_tier == ImpactTier.CRITICAL else 0.5

        # Fixability factor (NOISE is not fixable individually)
        if DubiousFlag.NOISE in dubious_flags and len(dubious_flags) == 1:
            # Pure noise: batch analysis only, no individual verification
            fixability = 0.0
        elif not dubious_flags:
            # Not dubious: no verification needed
            fixability = 0.0
        else:
            # Dubious but fixable: higher credibility = easier to verify
            # (more likely to find corroborating sources)
            # Range: 0.3 (low cred) to 1.0 (high cred)
            fixability = 0.3 + (credibility_score * 0.7)

        return round(impact_factor * fixability, 3)

    async def reclassify_fact(
        self,
        investigation_id: str,
        fact_id: str,
        trigger: str,
    ) -> Optional[FactClassification]:
        """
        Re-classify a fact (e.g., after new corroborating evidence).

        Per CONTEXT.md: Classifications are dynamic, update as new info arrives.

        Args:
            investigation_id: Investigation scope
            fact_id: Fact to re-classify
            trigger: What triggered re-classification

        Returns:
            Updated classification, or None if fact not found
        """
        # Get current classification
        current = await self.classification_store.get_classification(
            investigation_id, fact_id
        )
        if not current:
            self.logger.warning(f"No classification found for {fact_id}")
            return None

        # Get fact from fact store
        fact = await self.fact_store.get_fact(investigation_id, fact_id)
        if not fact:
            self.logger.warning(f"Fact not found: {fact_id}")
            return None

        # Re-classify
        new_classification = await self.classify_fact(fact, investigation_id)

        # Add history entry for the re-classification
        new_classification.add_history_entry(trigger)

        # Save updated classification (overwrites existing)
        await self.classification_store.save_classification(new_classification)

        self.logger.info(f"Re-classified fact {fact_id}", trigger=trigger)

        return new_classification

    async def classify_investigation(
        self,
        investigation_id: str,
    ) -> Dict[str, Any]:
        """
        Classify all facts in an investigation.

        Retrieves facts from FactStore and classifies them.

        Args:
            investigation_id: Investigation to classify

        Returns:
            Classification stats
        """
        # Get all facts for investigation
        result = await self.fact_store.retrieve_by_investigation(investigation_id)
        facts = result.get("facts", [])

        if not facts:
            self.logger.warning(f"No facts found for investigation {investigation_id}")
            return {"classified": 0, "investigation_id": investigation_id}

        # Classify via sift()
        classifications = await self.sift(
            {"facts": facts, "investigation_id": investigation_id}
        )

        return {
            "classified": len(classifications),
            "investigation_id": investigation_id,
            "stats": await self.classification_store.get_stats(investigation_id),
        }

    async def get_classification_stats(
        self,
        investigation_id: str,
    ) -> Dict[str, Any]:
        """Get classification statistics for an investigation."""
        return await self.classification_store.get_stats(investigation_id)

    async def get_dubious_facts(
        self,
        investigation_id: str,
        exclude_noise: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Get all dubious facts for an investigation.

        Args:
            investigation_id: Investigation identifier
            exclude_noise: Exclude noise-only facts

        Returns:
            List of dubious classification dicts
        """
        return await self.classification_store.get_dubious_facts(
            investigation_id, exclude_noise
        )

    async def get_priority_queue(
        self,
        investigation_id: str,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get priority-ordered classification queue for Phase 8.

        Args:
            investigation_id: Investigation identifier
            limit: Maximum items to return

        Returns:
            Priority-ordered list of classification dicts
        """
        return await self.classification_store.get_priority_queue(
            investigation_id, exclude_noise=True, limit=limit
        )

    def get_capabilities(self) -> list[str]:
        """Return agent capabilities."""
        return [
            "fact_classification",
            "impact_assessment",
            "dubious_detection",
            "credibility_scoring",
            "priority_calculation",
        ]
