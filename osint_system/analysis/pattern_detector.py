"""Cross-fact pattern detection without LLM dependency.

Identifies recurring entities, temporal clusters, source clusters, and
escalation indicators from structured investigation data. All analysis
is rule-based: entity counting, temporal proximity grouping, and
classification severity progression.

No LLM calls. No external dependencies beyond the standard library.

Usage:
    from osint_system.analysis.pattern_detector import PatternDetector

    detector = PatternDetector()
    patterns = detector.detect_patterns(snapshot)
    print(patterns["recurring_entities"])
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

import structlog

from osint_system.analysis.schemas import InvestigationSnapshot

logger = structlog.get_logger(__name__)


class PatternDetector:
    """Rule-based cross-fact pattern detection.

    Stateless detector that analyzes InvestigationSnapshot data for:
    - Recurring entities: entities appearing in 3+ facts
    - Source clusters: facts grouped by source type
    - Temporal clusters: facts grouped by time proximity
    - Escalation indicators: severity progression for an entity over time

    All methods are pure functions of the input data. No LLM calls.
    """

    def __init__(self) -> None:
        """Initialize PatternDetector (stateless)."""
        self._log = logger.bind(component="PatternDetector")

    def detect_patterns(
        self,
        snapshot: InvestigationSnapshot,
    ) -> dict[str, Any]:
        """Run all pattern detection methods on the snapshot.

        Args:
            snapshot: Pre-aggregated investigation data.

        Returns:
            Dict with keys: recurring_entities, source_clusters,
            temporal_clusters, escalation_indicators.
        """
        facts = snapshot.facts
        classifications = snapshot.classifications

        recurring = self._find_recurring_entities(facts)
        source_clusters = self._find_source_clusters(facts)
        temporal = self._find_temporal_clusters(facts)
        escalation = self._find_escalation_indicators(facts, classifications)

        self._log.info(
            "patterns_detected",
            investigation_id=snapshot.investigation_id,
            recurring_entities=len(recurring),
            source_clusters=len(source_clusters),
            temporal_clusters=len(temporal),
            escalation_indicators=len(escalation),
        )

        return {
            "recurring_entities": recurring,
            "source_clusters": source_clusters,
            "temporal_clusters": temporal,
            "escalation_indicators": escalation,
        }

    def _find_recurring_entities(
        self,
        facts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Find entities appearing in 3 or more facts.

        Extracts canonical entity names from each fact's entities list,
        counts occurrences, and returns entities with count >= 3 sorted
        by frequency descending.

        Args:
            facts: List of fact dicts from the snapshot.

        Returns:
            List of dicts: {"entity": str, "type": str, "count": int, "fact_ids": list[str]}
        """
        entity_facts: dict[str, list[str]] = defaultdict(list)
        entity_types: dict[str, str] = {}

        for fact in facts:
            fact_id = fact.get("fact_id", "")
            entities = fact.get("entities", [])

            for entity in entities:
                canonical = entity.get("canonical", entity.get("text", ""))
                if not canonical:
                    continue

                entity_facts[canonical].append(fact_id)
                if canonical not in entity_types:
                    entity_types[canonical] = entity.get("type", "unknown")

        recurring = [
            {
                "entity": name,
                "type": entity_types.get(name, "unknown"),
                "count": len(fact_ids),
                "fact_ids": list(set(fact_ids)),  # Deduplicate
            }
            for name, fact_ids in entity_facts.items()
            if len(set(fact_ids)) >= 3
        ]

        # Sort by count descending
        recurring.sort(key=lambda e: e["count"], reverse=True)
        return recurring

    def _find_source_clusters(
        self,
        facts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Group facts by source type.

        Args:
            facts: List of fact dicts from the snapshot.

        Returns:
            List of dicts: {"source_type": str, "fact_count": int, "fact_ids": list[str]}
        """
        type_facts: dict[str, list[str]] = defaultdict(list)

        for fact in facts:
            fact_id = fact.get("fact_id", "")
            provenance = fact.get("provenance") or {}
            source_type = provenance.get("source_type", "unknown")
            type_facts[source_type].append(fact_id)

        clusters = [
            {
                "source_type": stype,
                "fact_count": len(fact_ids),
                "fact_ids": fact_ids,
            }
            for stype, fact_ids in type_facts.items()
        ]

        clusters.sort(key=lambda c: c["fact_count"], reverse=True)
        return clusters

    def _find_temporal_clusters(
        self,
        facts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Group facts by temporal proximity (same day).

        Extracts temporal markers from facts, groups by date, and returns
        clusters of 2 or more facts on the same day.

        Args:
            facts: List of fact dicts from the snapshot.

        Returns:
            List of dicts: {"date": str, "fact_count": int, "fact_ids": list[str]}
        """
        date_facts: dict[str, list[str]] = defaultdict(list)

        for fact in facts:
            fact_id = fact.get("fact_id", "")
            temporal = fact.get("temporal")
            if temporal is None:
                continue

            value = temporal.get("value", "")
            if not value:
                continue

            # Normalize to date only (YYYY-MM-DD)
            date_str = value[:10]
            date_facts[date_str].append(fact_id)

        clusters = [
            {
                "date": date,
                "fact_count": len(fact_ids),
                "fact_ids": fact_ids,
            }
            for date, fact_ids in date_facts.items()
            if len(fact_ids) >= 2
        ]

        clusters.sort(key=lambda c: c["date"])
        return clusters

    def _find_escalation_indicators(
        self,
        facts: list[dict[str, Any]],
        classifications: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Detect entities whose facts escalate from less_critical to critical.

        For each entity appearing in multiple facts, checks whether the
        classification impact tier increases over time (less_critical -> critical).

        Args:
            facts: List of fact dicts from the snapshot.
            classifications: List of classification dicts.

        Returns:
            List of dicts: {"entity": str, "fact_sequence": list[dict], "escalation_type": str}
        """
        # Index classifications by fact_id
        tier_by_fact: dict[str, str] = {}
        for cls in classifications:
            fact_id = cls.get("fact_id", "")
            tier_by_fact[fact_id] = cls.get("impact_tier", "unknown")

        # Group facts by entity
        entity_facts_map: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for fact in facts:
            fact_id = fact.get("fact_id", "")
            entities = fact.get("entities", [])
            temporal = fact.get("temporal")

            # Extract timestamp for ordering (use stored_at as fallback)
            ts = ""
            if temporal:
                ts = temporal.get("value", "")
            if not ts:
                ts = fact.get("stored_at", "")

            for entity in entities:
                canonical = entity.get("canonical", entity.get("text", ""))
                if canonical:
                    entity_facts_map[canonical].append({
                        "fact_id": fact_id,
                        "timestamp": ts,
                        "tier": tier_by_fact.get(fact_id, "unknown"),
                    })

        # Detect escalation patterns
        tier_severity = {
            "less_critical": 1,
            "LESS_CRITICAL": 1,
            "critical": 2,
            "CRITICAL": 2,
        }

        indicators: list[dict[str, Any]] = []

        for entity, entries in entity_facts_map.items():
            if len(entries) < 2:
                continue

            # Sort by timestamp
            sorted_entries = sorted(entries, key=lambda e: e["timestamp"])

            # Check for escalation: any transition from lower to higher severity
            for i in range(len(sorted_entries) - 1):
                current_tier = sorted_entries[i]["tier"]
                next_tier = sorted_entries[i + 1]["tier"]

                current_severity = tier_severity.get(current_tier, 0)
                next_severity = tier_severity.get(next_tier, 0)

                if next_severity > current_severity > 0:
                    indicators.append({
                        "entity": entity,
                        "fact_sequence": [
                            {
                                "fact_id": sorted_entries[i]["fact_id"],
                                "tier": current_tier,
                                "timestamp": sorted_entries[i]["timestamp"],
                            },
                            {
                                "fact_id": sorted_entries[i + 1]["fact_id"],
                                "tier": next_tier,
                                "timestamp": sorted_entries[i + 1]["timestamp"],
                            },
                        ],
                        "escalation_type": f"{current_tier} -> {next_tier}",
                    })
                    break  # One escalation per entity is sufficient

        return indicators
