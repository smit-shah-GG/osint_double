"""Impact assessment for fact classification per Phase 7 CONTEXT.md.

Impact tier determination based on:
- Entity significance (world leaders > officials > others)
- Event type (military action > diplomatic > routine)
- Investigation context (relevance to objective)

Impact is orthogonal to trust - a fact can be CRITICAL and DUBIOUS.
High-impact dubious facts get priority verification in Phase 8.
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from loguru import logger

from osint_system.config.prompts.classification_prompts import (
    CRITICAL_ENTITY_PATTERNS,
    CRITICAL_EVENT_KEYWORDS,
)
from osint_system.config.source_credibility import (
    ENTITY_SIGNIFICANCE,
    EVENT_TYPE_SIGNIFICANCE,
)
from osint_system.data_management.schemas import ImpactTier


@dataclass
class ImpactResult:
    """Result of impact assessment.

    Attributes:
        tier: Impact tier (CRITICAL or LESS_CRITICAL)
        score: Combined impact score (0.0-1.0)
        entity_contribution: Contribution from entity significance (0.0-1.0)
        event_contribution: Contribution from event type (0.0-1.0)
        reasoning: Human-readable explanation for classification
    """

    tier: ImpactTier
    score: float
    entity_contribution: float
    event_contribution: float
    reasoning: str


class ImpactAssessor:
    """
    Assesses impact tier for facts based on geopolitical significance.

    Per CONTEXT.md:
    - Impact based on entity significance AND event type
    - Investigation-relative: same fact may be critical in one investigation
    - Orthogonal to trust: critical facts can also be dubious

    The assessor evaluates:
    1. Entity significance: World leaders score higher than local officials
    2. Event type: Military actions score higher than routine statements
    3. Investigation context: Optional boost for objective-relevant facts

    Usage:
        assessor = ImpactAssessor()
        result = assessor.assess(fact, investigation_context)
        if result.tier == ImpactTier.CRITICAL:
            print(f"Critical fact: {result.reasoning}")

    Example:
        >>> assessor = ImpactAssessor()
        >>> fact = {
        ...     'claim': {'text': 'Putin ordered military strike'},
        ...     'entities': [{'text': 'Putin', 'canonical': 'Vladimir Putin'}]
        ... }
        >>> result = assessor.assess(fact)
        >>> result.tier == ImpactTier.CRITICAL
        True
    """

    # Threshold for CRITICAL tier (0.6 = significant entity OR event)
    CRITICAL_THRESHOLD = 0.6

    def __init__(
        self,
        critical_threshold: float = CRITICAL_THRESHOLD,
        entity_weight: float = 0.5,
        event_weight: float = 0.5,
    ):
        """
        Initialize impact assessor.

        Args:
            critical_threshold: Score above which fact is CRITICAL (default 0.6)
            entity_weight: Weight for entity contribution (default 0.5)
            event_weight: Weight for event contribution (default 0.5)
        """
        self.critical_threshold = critical_threshold
        self.entity_weight = entity_weight
        self.event_weight = event_weight
        self.entity_patterns = [
            re.compile(p, re.IGNORECASE) for p in CRITICAL_ENTITY_PATTERNS
        ]
        self._logger = logger.bind(component="ImpactAssessor")

    def assess(
        self,
        fact: Dict[str, Any],
        investigation_context: Optional[Dict[str, Any]] = None,
    ) -> ImpactResult:
        """
        Assess impact tier for a fact.

        Impact is determined by combining entity significance and event type.
        Investigation context can provide additional boost for relevant facts.

        Args:
            fact: ExtractedFact dict with claim, entities, and metadata
            investigation_context: Optional investigation metadata for context-aware
                                  scoring. Can include:
                                  - objective_keywords: List[str]
                                  - entity_focus: List[str]

        Returns:
            ImpactResult with tier, score, contributions, and reasoning
        """
        # Assess entity significance
        entity_score, entity_reason = self._assess_entities(fact)

        # Assess event type significance
        event_score, event_reason = self._assess_event_type(fact)

        # Combine scores with weights
        combined_score = (
            self.entity_weight * entity_score + self.event_weight * event_score
        )

        # Apply investigation context boost if available
        if investigation_context:
            context_boost = self._apply_investigation_context(fact, investigation_context)
            combined_score = min(1.0, combined_score + context_boost)

        # Determine tier based on threshold
        if combined_score >= self.critical_threshold:
            tier = ImpactTier.CRITICAL
        else:
            tier = ImpactTier.LESS_CRITICAL

        # Build reasoning string
        reasoning_parts = []
        if entity_reason:
            reasoning_parts.append(f"Entity: {entity_reason}")
        if event_reason:
            reasoning_parts.append(f"Event: {event_reason}")
        reasoning = "; ".join(reasoning_parts) or "Default assessment (no significant signals)"

        result = ImpactResult(
            tier=tier,
            score=round(combined_score, 3),
            entity_contribution=round(entity_score, 3),
            event_contribution=round(event_score, 3),
            reasoning=reasoning,
        )

        self._logger.debug(
            f"Impact assessment: {tier.value}",
            fact_id=str(fact.get("fact_id", "unknown"))[:20],
            score=combined_score,
            entity=entity_score,
            event=event_score,
        )

        return result

    def _assess_entities(self, fact: Dict[str, Any]) -> tuple[float, str]:
        """
        Assess entity significance from fact entities and claim text.

        Entity significance tiers:
        - World leaders (Putin, Biden, Xi): 1.0
        - Senior officials (ministers, generals): 0.8
        - Organizations (NATO, UN): 0.6
        - Generic entities: 0.3-0.4

        Args:
            fact: ExtractedFact dict with entities and claim fields

        Returns:
            (significance_score, reasoning) tuple
        """
        entities = fact.get("entities") or []  # Handle None
        claim = fact.get("claim", {})
        claim_text = claim.get("text", "") if isinstance(claim, dict) else ""

        if not entities and not claim_text:
            return 0.3, "No entities found"

        max_significance = 0.3
        significant_entity = None

        # Check explicit entities in the entities list
        for entity in entities:
            entity_type = entity.get("type", "unknown") if isinstance(entity, dict) else "unknown"
            entity_text = (entity.get("text", "") if isinstance(entity, dict) else "").lower()
            canonical = (entity.get("canonical", "") if isinstance(entity, dict) else "").lower()

            # Look up significance based on entity content
            significance = self._get_entity_significance(entity_type, entity_text, canonical)
            if significance > max_significance:
                max_significance = significance
                significant_entity = (
                    entity.get("canonical") or entity.get("text")
                    if isinstance(entity, dict)
                    else str(entity)
                )

        # Check claim text for pattern matches (may catch entities not in list)
        for pattern in self.entity_patterns:
            match = pattern.search(claim_text)
            if match:
                # Pattern match implies high significance (0.8)
                if max_significance < 0.8:
                    max_significance = 0.8
                    if not significant_entity:
                        significant_entity = match.group(0)
                break

        if significant_entity:
            reason = f"{significant_entity} (score={max_significance:.2f})"
        else:
            reason = "Low significance entities"

        return max_significance, reason

    def _get_entity_significance(
        self,
        entity_type: str,
        entity_text: str,
        canonical: str,
    ) -> float:
        """
        Get significance score for a specific entity.

        Checks against known significant entities and patterns.

        Args:
            entity_type: Entity type (PERSON, ORGANIZATION, etc.)
            entity_text: Raw entity text
            canonical: Canonical form of entity

        Returns:
            Significance score (0.0-1.0)
        """
        combined = f"{entity_text} {canonical}".lower()

        # World leaders - highest significance
        world_leaders = [
            "putin", "biden", "xi", "jinping", "modi",
            "macron", "scholz", "sunak", "zelensky", "zelenskyy",
            "kim jong", "erdogan", "netanyahu", "khamenei"
        ]
        if any(leader in combined for leader in world_leaders):
            return ENTITY_SIGNIFICANCE.get("world_leader", 1.0)

        # Military/government titles
        senior_titles = [
            "president", "prime minister", "chancellor",
            "minister", "general", "admiral", "commander"
        ]
        if any(title in combined for title in senior_titles):
            return ENTITY_SIGNIFICANCE.get("senior_official", 0.8)

        # Major organizations
        major_orgs = [
            "nato", "un ", "united nations", "eu ", "european union",
            "g7", "g20", "pentagon", "kremlin", "white house",
            "brics", "opec", "asean", "who", "imf", "world bank"
        ]
        if any(org in combined for org in major_orgs):
            return ENTITY_SIGNIFICANCE.get("organization", 0.6)

        # Military entities
        military_keywords = ["army", "navy", "air force", "military", "troops", "forces"]
        if any(kw in combined for kw in military_keywords):
            return ENTITY_SIGNIFICANCE.get("military_commander", 0.8)

        # Entity type fallback scoring
        type_mapping = {
            "PERSON": 0.4,
            "PER": 0.4,
            "ORGANIZATION": 0.4,
            "ORG": 0.4,
            "LOCATION": 0.3,
            "LOC": 0.3,
            "GPE": 0.3,
            "EVENT": 0.5,
        }
        return type_mapping.get(entity_type.upper(), 0.3)

    def _assess_event_type(self, fact: Dict[str, Any]) -> tuple[float, str]:
        """
        Assess event type significance from claim content.

        Event type significance tiers:
        - Military actions (attack, strike, invasion): 1.0
        - Treaties/sanctions: 0.9
        - Diplomatic meetings: 0.7
        - Policy announcements: 0.6
        - Routine activities: 0.2

        Args:
            fact: ExtractedFact dict with claim field

        Returns:
            (significance_score, reasoning) tuple
        """
        claim = fact.get("claim", {})
        if isinstance(claim, dict):
            claim_text = claim.get("text", "").lower()
            claim_type = claim.get("claim_type", "event")
        else:
            claim_text = ""
            claim_type = "event"

        # Check for critical event keywords
        matched_keywords = []
        for keyword in CRITICAL_EVENT_KEYWORDS:
            if keyword in claim_text:
                matched_keywords.append(keyword)

        if matched_keywords:
            # Map keywords to event type categories
            military_keywords = [
                "attack", "strike", "invasion", "war", "conflict",
                "military", "nuclear", "missile", "weapon", "troops",
                "soldiers", "combat", "bomb", "airstrike"
            ]
            diplomatic_treaty = ["treaty", "agreement", "sanction", "embargo"]
            diplomatic_meeting = ["summit", "diplomatic", "negotiation", "ambassador"]
            major_events = ["election", "coup", "assassination", "emergency", "crisis"]

            if any(kw in matched_keywords for kw in military_keywords):
                return (
                    EVENT_TYPE_SIGNIFICANCE.get("military_action", 1.0),
                    f"Military: {matched_keywords[:3]}"
                )
            if any(kw in matched_keywords for kw in diplomatic_treaty):
                return (
                    EVENT_TYPE_SIGNIFICANCE.get("treaty_agreement", 0.9),
                    f"Treaty/sanction: {matched_keywords[:3]}"
                )
            if any(kw in matched_keywords for kw in major_events):
                return (
                    EVENT_TYPE_SIGNIFICANCE.get("policy_announcement", 0.8),
                    f"Major event: {matched_keywords[:3]}"
                )
            if any(kw in matched_keywords for kw in diplomatic_meeting):
                return (
                    EVENT_TYPE_SIGNIFICANCE.get("diplomatic_meeting", 0.7),
                    f"Diplomatic: {matched_keywords[:3]}"
                )

            # Generic matched keyword
            return 0.6, f"Keywords: {matched_keywords[:3]}"

        # Fall back to claim type scoring
        claim_type_scores = {
            "event": 0.5,
            "state": 0.3,
            "relationship": 0.4,
            "prediction": 0.6,
            "planned": 0.5,
        }
        score = claim_type_scores.get(claim_type, 0.3)
        return score, f"Claim type: {claim_type}"

    def _apply_investigation_context(
        self,
        fact: Dict[str, Any],
        context: Dict[str, Any],
    ) -> float:
        """
        Apply investigation context boost to impact score.

        Context-aware scoring allows the same fact to be more important
        in one investigation than another.

        Context can include:
        - objective_keywords: Keywords from investigation objective
        - entity_focus: Specific entities of interest
        - temporal_focus: If recency matters (not implemented)

        Args:
            fact: ExtractedFact dict
            context: Investigation context with keywords and entity focus

        Returns:
            Context boost (0.0-0.2)
        """
        boost = 0.0

        # Keyword matching from objective
        objective_keywords = context.get("objective_keywords", [])
        claim = fact.get("claim", {})
        claim_text = (claim.get("text", "") if isinstance(claim, dict) else "").lower()

        if objective_keywords and any(kw.lower() in claim_text for kw in objective_keywords):
            boost += 0.1

        # Entity focus matching
        entity_focus = context.get("entity_focus", [])
        entities = fact.get("entities", [])

        for entity in entities:
            if isinstance(entity, dict):
                entity_text = entity.get("text", "").lower()
                canonical = entity.get("canonical", "").lower()
                entity_combined = f"{entity_text} {canonical}"

                if any(focus.lower() in entity_combined for focus in entity_focus):
                    boost += 0.1
                    break  # Only one boost for entity match

        return min(0.2, boost)  # Cap at 0.2

    def bulk_assess(
        self,
        facts: List[Dict[str, Any]],
        investigation_context: Optional[Dict[str, Any]] = None,
    ) -> List[ImpactResult]:
        """
        Assess impact for multiple facts.

        Convenience method for batch processing.

        Args:
            facts: List of ExtractedFact dicts
            investigation_context: Optional context for all facts

        Returns:
            List of ImpactResult in same order as input facts
        """
        return [self.assess(fact, investigation_context) for fact in facts]


__all__ = ["ImpactAssessor", "ImpactResult"]
