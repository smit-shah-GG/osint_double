"""Tests for PatternDetector and ContradictionAnalyzer.

Validates:
- Recurring entity detection (3+ occurrences)
- No recurring entities when all different
- Temporal clustering by day
- Contradiction detection from relationships
- Escalation detection (less_critical -> critical)
"""

from __future__ import annotations

from typing import Any

import pytest

from osint_system.analysis.contradiction_analyzer import ContradictionAnalyzer
from osint_system.analysis.pattern_detector import PatternDetector
from osint_system.analysis.schemas import InvestigationSnapshot


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_fact(
    fact_id: str,
    claim_text: str,
    entities: list[dict[str, Any]],
    source_type: str = "wire_service",
    temporal: dict[str, Any] | None = None,
    assertion_type: str = "statement",
    relationships: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a minimal fact dict for testing."""
    fact: dict[str, Any] = {
        "fact_id": fact_id,
        "claim": {
            "text": claim_text,
            "assertion_type": assertion_type,
            "claim_type": "event",
        },
        "entities": entities,
        "provenance": {
            "source_id": f"src-{fact_id}",
            "source_type": source_type,
        },
    }
    if temporal is not None:
        fact["temporal"] = temporal
    if relationships is not None:
        fact["relationships"] = relationships
    return fact


def _make_entity(
    eid: str,
    text: str,
    etype: str = "PERSON",
    canonical: str | None = None,
) -> dict[str, Any]:
    return {
        "id": eid,
        "text": text,
        "type": etype,
        "canonical": canonical or text,
    }


# ------------------------------------------------------------------
# PatternDetector tests
# ------------------------------------------------------------------


class TestRecurringEntities:
    """Recurring entity detection tests."""

    def test_recurring_entities(self) -> None:
        """3 facts mentioning Putin -> recurring_entities contains Putin."""
        detector = PatternDetector()
        snapshot = InvestigationSnapshot(
            investigation_id="inv-recur",
            facts=[
                _make_fact("f1", "Putin visited Beijing", [_make_entity("E1", "Putin", canonical="Vladimir Putin")]),
                _make_fact("f2", "Putin met Xi Jinping", [_make_entity("E1", "Putin", canonical="Vladimir Putin")]),
                _make_fact("f3", "Putin addressed parliament", [_make_entity("E1", "Putin", canonical="Vladimir Putin")]),
            ],
        )

        patterns = detector.detect_patterns(snapshot)

        assert len(patterns["recurring_entities"]) == 1
        putin = patterns["recurring_entities"][0]
        assert putin["entity"] == "Vladimir Putin"
        assert putin["count"] == 3
        assert set(putin["fact_ids"]) == {"f1", "f2", "f3"}

    def test_no_recurring_entities(self) -> None:
        """All facts mention different entities -> empty recurring_entities."""
        detector = PatternDetector()
        snapshot = InvestigationSnapshot(
            investigation_id="inv-no-recur",
            facts=[
                _make_fact("f1", "Putin visited", [_make_entity("E1", "Putin", canonical="Vladimir Putin")]),
                _make_fact("f2", "Macron spoke", [_make_entity("E1", "Macron", canonical="Emmanuel Macron")]),
                _make_fact("f3", "Biden signed", [_make_entity("E1", "Biden", canonical="Joe Biden")]),
            ],
        )

        patterns = detector.detect_patterns(snapshot)

        assert len(patterns["recurring_entities"]) == 0


class TestTemporalClusters:
    """Temporal clustering tests."""

    def test_temporal_clusters(self) -> None:
        """Facts with same day temporal markers grouped together."""
        detector = PatternDetector()
        snapshot = InvestigationSnapshot(
            investigation_id="inv-temporal",
            facts=[
                _make_fact(
                    "f1", "Event A",
                    [_make_entity("E1", "A")],
                    temporal={"value": "2024-03-15T10:00:00Z", "precision": "day"},
                ),
                _make_fact(
                    "f2", "Event B",
                    [_make_entity("E1", "B")],
                    temporal={"value": "2024-03-15T14:30:00Z", "precision": "day"},
                ),
                _make_fact(
                    "f3", "Event C",
                    [_make_entity("E1", "C")],
                    temporal={"value": "2024-04-01T08:00:00Z", "precision": "day"},
                ),
            ],
        )

        patterns = detector.detect_patterns(snapshot)

        # f1 and f2 share the same day (2024-03-15)
        assert len(patterns["temporal_clusters"]) == 1
        cluster = patterns["temporal_clusters"][0]
        assert cluster["date"] == "2024-03-15"
        assert cluster["fact_count"] == 2
        assert set(cluster["fact_ids"]) == {"f1", "f2"}

    def test_no_temporal_clusters(self) -> None:
        """Facts without temporal markers produce no clusters."""
        detector = PatternDetector()
        snapshot = InvestigationSnapshot(
            investigation_id="inv-no-temporal",
            facts=[
                _make_fact("f1", "Event A", [_make_entity("E1", "A")]),
                _make_fact("f2", "Event B", [_make_entity("E1", "B")]),
            ],
        )

        patterns = detector.detect_patterns(snapshot)
        assert len(patterns["temporal_clusters"]) == 0


class TestEscalationDetection:
    """Escalation indicator detection tests."""

    def test_escalation_detection(self) -> None:
        """Facts about same entity progressing from less_critical to critical."""
        detector = PatternDetector()
        snapshot = InvestigationSnapshot(
            investigation_id="inv-escalation",
            facts=[
                _make_fact(
                    "f1", "Putin made statement",
                    [_make_entity("E1", "Putin", canonical="Vladimir Putin")],
                    temporal={"value": "2024-01-10", "precision": "day"},
                ),
                _make_fact(
                    "f2", "Putin deployed troops",
                    [_make_entity("E1", "Putin", canonical="Vladimir Putin")],
                    temporal={"value": "2024-03-15", "precision": "day"},
                ),
            ],
            classifications=[
                {"fact_id": "f1", "impact_tier": "less_critical"},
                {"fact_id": "f2", "impact_tier": "critical"},
            ],
        )

        patterns = detector.detect_patterns(snapshot)

        assert len(patterns["escalation_indicators"]) == 1
        ind = patterns["escalation_indicators"][0]
        assert ind["entity"] == "Vladimir Putin"
        assert "less_critical" in ind["escalation_type"]
        assert "critical" in ind["escalation_type"]

    def test_no_escalation_same_tier(self) -> None:
        """Same tier for all facts -> no escalation."""
        detector = PatternDetector()
        snapshot = InvestigationSnapshot(
            investigation_id="inv-no-esc",
            facts=[
                _make_fact(
                    "f1", "Putin statement",
                    [_make_entity("E1", "Putin", canonical="Vladimir Putin")],
                    temporal={"value": "2024-01-10", "precision": "day"},
                ),
                _make_fact(
                    "f2", "Putin visit",
                    [_make_entity("E1", "Putin", canonical="Vladimir Putin")],
                    temporal={"value": "2024-03-15", "precision": "day"},
                ),
            ],
            classifications=[
                {"fact_id": "f1", "impact_tier": "critical"},
                {"fact_id": "f2", "impact_tier": "critical"},
            ],
        )

        patterns = detector.detect_patterns(snapshot)
        assert len(patterns["escalation_indicators"]) == 0


class TestSourceClusters:
    """Source cluster detection tests."""

    def test_source_clusters(self) -> None:
        """Facts grouped by source type."""
        detector = PatternDetector()
        snapshot = InvestigationSnapshot(
            investigation_id="inv-src",
            facts=[
                _make_fact("f1", "A", [_make_entity("E1", "A")], source_type="wire_service"),
                _make_fact("f2", "B", [_make_entity("E1", "B")], source_type="wire_service"),
                _make_fact("f3", "C", [_make_entity("E1", "C")], source_type="news_outlet"),
            ],
        )

        patterns = detector.detect_patterns(snapshot)

        assert len(patterns["source_clusters"]) == 2
        # Sorted by count descending
        assert patterns["source_clusters"][0]["source_type"] == "wire_service"
        assert patterns["source_clusters"][0]["fact_count"] == 2


# ------------------------------------------------------------------
# ContradictionAnalyzer tests
# ------------------------------------------------------------------


class TestContradictions:
    """Contradiction detection tests."""

    def test_contradictions_from_relationships(self) -> None:
        """Facts with contradicts relationship produce ContradictionEntry."""
        analyzer = ContradictionAnalyzer()
        snapshot = InvestigationSnapshot(
            investigation_id="inv-contra",
            facts=[
                _make_fact(
                    "f1", "12 casualties reported",
                    [_make_entity("E1", "Ukraine")],
                    relationships=[{"type": "contradicts", "target_fact_id": "f2"}],
                ),
                _make_fact(
                    "f2", "8 casualties reported",
                    [_make_entity("E1", "Ukraine")],
                ),
            ],
            verification_results=[
                {"fact_id": "f1", "status": "confirmed"},
                {"fact_id": "f2", "status": "confirmed"},
            ],
        )

        contradictions = analyzer.find_contradictions(snapshot)

        assert len(contradictions) >= 1
        entry = contradictions[0]
        assert "f1" in entry.fact_ids
        assert "f2" in entry.fact_ids
        assert entry.resolution_status == "unresolved"

    def test_contradictions_from_refuted(self) -> None:
        """REFUTED verification produces resolved contradiction."""
        analyzer = ContradictionAnalyzer()
        snapshot = InvestigationSnapshot(
            investigation_id="inv-refuted",
            facts=[
                _make_fact(
                    "f1", "Troops withdrew from border",
                    [_make_entity("E1", "Troops")],
                ),
            ],
            verification_results=[
                {"fact_id": "f1", "status": "refuted", "reasoning": "Satellite imagery shows continued presence"},
            ],
        )

        contradictions = analyzer.find_contradictions(snapshot)

        assert len(contradictions) == 1
        assert contradictions[0].resolution_status == "resolved"
        assert "refuted" in contradictions[0].description.lower()

    def test_contradictions_from_conflicting_claims(self) -> None:
        """Statement vs denial about same entity -> contradiction."""
        analyzer = ContradictionAnalyzer()
        snapshot = InvestigationSnapshot(
            investigation_id="inv-conflict",
            facts=[
                _make_fact(
                    "f1", "Putin authorized attack",
                    [_make_entity("E1", "Putin", canonical="Vladimir Putin")],
                    assertion_type="statement",
                ),
                _make_fact(
                    "f2", "Putin denied authorizing attack",
                    [_make_entity("E1", "Putin", canonical="Vladimir Putin")],
                    assertion_type="denial",
                ),
            ],
            verification_results=[],
        )

        contradictions = analyzer.find_contradictions(snapshot)

        assert len(contradictions) >= 1
        # Find the conflicting claims contradiction
        conflict = [c for c in contradictions if "conflicting" in c.description.lower()]
        assert len(conflict) == 1
        assert "Vladimir Putin" in conflict[0].description

    def test_resolved_contradiction(self) -> None:
        """One confirmed, one refuted -> resolved."""
        analyzer = ContradictionAnalyzer()
        snapshot = InvestigationSnapshot(
            investigation_id="inv-resolved",
            facts=[
                _make_fact(
                    "f1", "Attack confirmed",
                    [_make_entity("E1", "X", canonical="X")],
                    assertion_type="statement",
                ),
                _make_fact(
                    "f2", "Attack denied",
                    [_make_entity("E1", "X", canonical="X")],
                    assertion_type="denial",
                ),
            ],
            verification_results=[
                {"fact_id": "f1", "status": "confirmed"},
                {"fact_id": "f2", "status": "refuted", "reasoning": "Denied claim was refuted"},
            ],
        )

        contradictions = analyzer.find_contradictions(snapshot)

        # Should have at least the conflicting claims contradiction
        conflicts = [c for c in contradictions if "conflicting" in c.description.lower()]
        assert len(conflicts) >= 1
        # This one should be resolved (one confirmed, one refuted)
        assert conflicts[0].resolution_status == "resolved"

    def test_no_contradictions(self) -> None:
        """Facts without conflicts produce empty list."""
        analyzer = ContradictionAnalyzer()
        snapshot = InvestigationSnapshot(
            investigation_id="inv-clean",
            facts=[
                _make_fact("f1", "Event A", [_make_entity("E1", "A", canonical="A")]),
                _make_fact("f2", "Event B", [_make_entity("E1", "B", canonical="B")]),
            ],
            verification_results=[
                {"fact_id": "f1", "status": "confirmed"},
                {"fact_id": "f2", "status": "confirmed"},
            ],
        )

        contradictions = analyzer.find_contradictions(snapshot)
        assert len(contradictions) == 0
