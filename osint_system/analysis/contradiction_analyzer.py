"""Contradiction identification across facts without LLM dependency.

Identifies unresolved contradictions from three sources:
1. Explicit "contradicts" relationships in fact relationship metadata
2. REFUTED verification results (refuting evidence contradicts the claim)
3. Same-entity conflicting claims (same entity, opposing assertion_types)

No LLM calls. Uses fact relationships, verification status, and assertion
types to detect conflicts programmatically.

Usage:
    from osint_system.analysis.contradiction_analyzer import ContradictionAnalyzer

    analyzer = ContradictionAnalyzer()
    contradictions = analyzer.find_contradictions(snapshot)
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import structlog

from osint_system.analysis.schemas import ContradictionEntry, InvestigationSnapshot

logger = structlog.get_logger(__name__)


class ContradictionAnalyzer:
    """Rule-based contradiction detection across investigation facts.

    Stateless analyzer that scans fact relationships, verification results,
    and assertion types to identify contradictions. Each contradiction is
    classified as resolved or unresolved based on verification outcomes.

    Produces ContradictionEntry objects suitable for inclusion in
    AnalysisSynthesis.contradictions.
    """

    def __init__(self) -> None:
        """Initialize ContradictionAnalyzer (stateless)."""
        self._log = logger.bind(component="ContradictionAnalyzer")

    def find_contradictions(
        self,
        snapshot: InvestigationSnapshot,
    ) -> list[ContradictionEntry]:
        """Identify contradictions from all available evidence.

        Sources checked (in order):
        1. Explicit contradicts relationships in fact metadata
        2. REFUTED verification results
        3. Same-entity conflicting claims (statement vs denial)

        Deduplicates by fact_id pairs to avoid reporting the same
        contradiction multiple times.

        Args:
            snapshot: Pre-aggregated investigation data.

        Returns:
            List of ContradictionEntry objects.
        """
        contradictions: list[ContradictionEntry] = []
        seen_pairs: set[frozenset[str]] = set()

        # Build lookup indices
        facts_by_id = {f.get("fact_id", ""): f for f in snapshot.facts}
        verif_by_id: dict[str, dict[str, Any]] = {}
        for vr in snapshot.verification_results:
            verif_by_id[vr.get("fact_id", "")] = vr

        # 1. Explicit contradicts relationships
        rel_contradictions = self._from_relationships(
            snapshot.facts, facts_by_id, verif_by_id
        )
        for entry in rel_contradictions:
            pair = frozenset(entry.fact_ids)
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                contradictions.append(entry)

        # 2. Refuted verification results
        refuted_contradictions = self._from_refuted_verifications(
            snapshot.verification_results, facts_by_id
        )
        for entry in refuted_contradictions:
            pair = frozenset(entry.fact_ids)
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                contradictions.append(entry)

        # 3. Same-entity conflicting claims
        entity_contradictions = self._from_conflicting_claims(
            snapshot.facts, verif_by_id
        )
        for entry in entity_contradictions:
            pair = frozenset(entry.fact_ids)
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                contradictions.append(entry)

        self._log.info(
            "contradictions_found",
            investigation_id=snapshot.investigation_id,
            total=len(contradictions),
            resolved=sum(1 for c in contradictions if c.resolution_status == "resolved"),
            unresolved=sum(1 for c in contradictions if c.resolution_status == "unresolved"),
        )

        return contradictions

    def _from_relationships(
        self,
        facts: list[dict[str, Any]],
        facts_by_id: dict[str, dict[str, Any]],
        verif_by_id: dict[str, dict[str, Any]],
    ) -> list[ContradictionEntry]:
        """Extract contradictions from explicit fact relationships.

        Looks for relationships with type "contradicts" in each fact's
        relationships list.

        Args:
            facts: All facts.
            facts_by_id: Fact lookup by ID.
            verif_by_id: Verification result lookup by fact ID.

        Returns:
            ContradictionEntry list from relationship data.
        """
        entries: list[ContradictionEntry] = []

        for fact in facts:
            fact_id = fact.get("fact_id", "")
            relationships = fact.get("relationships", [])
            if not relationships:
                continue

            for rel in relationships:
                rel_type = rel.get("type", "").lower()
                if rel_type != "contradicts":
                    continue

                target_id = rel.get("target_fact_id", rel.get("target_id", ""))
                if not target_id:
                    continue

                # Build description from claim texts
                claim_a = self._get_claim_text(fact)
                target_fact = facts_by_id.get(target_id, {})
                claim_b = self._get_claim_text(target_fact) if target_fact else target_id

                resolution = self._determine_resolution(
                    fact_id, target_id, verif_by_id
                )

                entries.append(
                    ContradictionEntry(
                        description=(
                            f"Explicit contradiction: \"{claim_a}\" vs \"{claim_b}\""
                        ),
                        fact_ids=[fact_id, target_id],
                        resolution_status=resolution,
                    )
                )

        return entries

    def _from_refuted_verifications(
        self,
        verification_results: list[dict[str, Any]],
        facts_by_id: dict[str, dict[str, Any]],
    ) -> list[ContradictionEntry]:
        """Extract contradictions from REFUTED verification results.

        A REFUTED fact means the refuting evidence contradicts the original
        claim. The contradiction is marked "resolved" since verification
        established the claim is false.

        Args:
            verification_results: All verification results.
            facts_by_id: Fact lookup by ID.

        Returns:
            ContradictionEntry list from refuted verifications.
        """
        entries: list[ContradictionEntry] = []

        for vr in verification_results:
            status = vr.get("status", "").lower()
            if status != "refuted":
                continue

            fact_id = vr.get("fact_id", "")
            fact = facts_by_id.get(fact_id, {})
            claim_text = self._get_claim_text(fact) if fact else fact_id

            reasoning = vr.get("reasoning", "Evidence contradicts the claim")

            entries.append(
                ContradictionEntry(
                    description=(
                        f"Refuted claim: \"{claim_text}\" -- {reasoning}"
                    ),
                    fact_ids=[fact_id],
                    resolution_status="resolved",
                    resolution_notes=(
                        f"Verification status: REFUTED. {reasoning}"
                    ),
                )
            )

        return entries

    def _from_conflicting_claims(
        self,
        facts: list[dict[str, Any]],
        verif_by_id: dict[str, dict[str, Any]],
    ) -> list[ContradictionEntry]:
        """Detect same-entity conflicting claims (statement vs denial).

        Groups facts by shared entity canonical names, then checks for
        opposing assertion_types within the same entity group:
        - "statement" vs "denial"
        - "claim" vs "denial"

        Args:
            facts: All facts.
            verif_by_id: Verification result lookup by fact ID.

        Returns:
            ContradictionEntry list from entity claim conflicts.
        """
        # Build entity set per fact for overlap checking
        fact_entities: dict[str, set[str]] = {}
        for fact in facts:
            fid = fact.get("fact_id", "")
            entities = fact.get("entities", [])
            canonical_names = set()
            for entity in entities:
                canonical = entity.get("canonical", entity.get("text", ""))
                if canonical:
                    canonical_names.add(canonical)
            fact_entities[fid] = canonical_names

        # Separate facts by assertion type
        denials: list[dict[str, Any]] = []
        statements: list[dict[str, Any]] = []

        for fact in facts:
            claim = fact.get("claim", {})
            atype = (claim.get("assertion_type", "") if isinstance(claim, dict) else "").lower()
            if atype == "denial":
                denials.append(fact)
            elif atype in ("statement", "claim"):
                statements.append(fact)

        entries: list[ContradictionEntry] = []

        # Only compare denials against statements (not all pairs)
        # Require at least 2 shared entities to avoid false positives from
        # broad entity co-occurrence (e.g., hundreds of facts mention "Russia")
        for denial in denials:
            denial_id = denial.get("fact_id", "")
            denial_entities = fact_entities.get(denial_id, set())
            if not denial_entities:
                continue

            for stmt in statements:
                stmt_id = stmt.get("fact_id", "")
                stmt_entities = fact_entities.get(stmt_id, set())

                shared = denial_entities & stmt_entities
                if len(shared) < 2:
                    continue

                text_a = self._get_claim_text(denial)
                text_b = self._get_claim_text(stmt)

                resolution = self._determine_resolution(
                    denial_id, stmt_id, verif_by_id
                )

                shared_str = ", ".join(sorted(shared)[:3])
                entries.append(
                    ContradictionEntry(
                        description=(
                            f"Conflicting claims ({shared_str}): "
                            f"\"{text_a}\" (denial) vs "
                            f"\"{text_b}\" (statement)"
                        ),
                        fact_ids=[denial_id, stmt_id],
                        resolution_status=resolution,
                    )
                )

        return entries

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_claim_text(fact: dict[str, Any]) -> str:
        """Extract claim text from a fact dict.

        Args:
            fact: Fact dict potentially containing nested claim.

        Returns:
            Claim text string, or empty string if unavailable.
        """
        claim = fact.get("claim", {})
        if isinstance(claim, dict):
            return claim.get("text", "")
        return str(claim) if claim else ""

    @staticmethod
    def _determine_resolution(
        fact_id_a: str,
        fact_id_b: str,
        verif_by_id: dict[str, dict[str, Any]],
    ) -> str:
        """Determine resolution status from verification results.

        Resolved if one fact is CONFIRMED and the other REFUTED.
        Otherwise unresolved.

        Args:
            fact_id_a: First fact ID.
            fact_id_b: Second fact ID.
            verif_by_id: Verification result lookup.

        Returns:
            "resolved" or "unresolved".
        """
        status_a = verif_by_id.get(fact_id_a, {}).get("status", "").lower()
        status_b = verif_by_id.get(fact_id_b, {}).get("status", "").lower()

        statuses = {status_a, status_b}

        if "confirmed" in statuses and "refuted" in statuses:
            return "resolved"

        return "unresolved"
