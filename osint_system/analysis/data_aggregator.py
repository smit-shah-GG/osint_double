"""Data aggregation layer for collecting investigation data into InvestigationSnapshot.

DataAggregator fetches and structures all investigation data from FactStore,
ClassificationStore, VerificationStore, and optionally GraphPipeline into a
single InvestigationSnapshot ready for LLM synthesis and report generation.

The aggregator is the bridge between the raw store data and the analysis engine.
All downstream synthesis, reporting, and export components consume
InvestigationSnapshot rather than querying stores directly.

Usage:
    from osint_system.analysis.data_aggregator import DataAggregator

    aggregator = DataAggregator(
        fact_store=fact_store,
        classification_store=classification_store,
        verification_store=verification_store,
        graph_pipeline=graph_pipeline,  # optional
    )
    snapshot = await aggregator.aggregate("inv-123")
    print(snapshot.fact_count, snapshot.confirmed_count)
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

import structlog

from osint_system.analysis.schemas import (
    ConfidenceAssessment,
    InvestigationSnapshot,
    SourceInventoryEntry,
    TimelineEntry,
)
from osint_system.data_management.classification_store import ClassificationStore
from osint_system.data_management.fact_store import FactStore
from osint_system.data_management.verification_store import VerificationStore

if TYPE_CHECKING:
    from osint_system.pipeline.graph_pipeline import GraphPipeline


logger = structlog.get_logger(__name__)


class DataAggregator:
    """Collects all investigation data from stores into InvestigationSnapshot.

    Fetches facts, classifications, verification results, and optional graph
    data in parallel where possible, then structures the data into a single
    typed snapshot for downstream synthesis.

    The aggregator handles missing/empty data gracefully: an investigation
    with no facts returns a snapshot with zero counts and empty lists, not
    an error.

    Attributes:
        _fact_store: FactStore for fact retrieval.
        _classification_store: ClassificationStore for classification data.
        _verification_store: VerificationStore for verification results.
        _graph_pipeline: Optional GraphPipeline for graph queries.
    """

    def __init__(
        self,
        fact_store: FactStore,
        classification_store: ClassificationStore,
        verification_store: VerificationStore,
        graph_pipeline: Optional[Any] = None,
    ) -> None:
        """Initialize DataAggregator.

        Args:
            fact_store: FactStore for retrieving investigation facts.
            classification_store: ClassificationStore for classification data.
            verification_store: VerificationStore for verification results.
            graph_pipeline: Optional GraphPipeline for graph queries.
                Skipped if None -- graph_summary will be empty dict.
        """
        self._fact_store = fact_store
        self._classification_store = classification_store
        self._verification_store = verification_store
        self._graph_pipeline = graph_pipeline
        self._log = logger.bind(component="DataAggregator")

    async def aggregate(self, investigation_id: str) -> InvestigationSnapshot:
        """Collect all investigation data into a single InvestigationSnapshot.

        Fetches from all stores in parallel, then computes derived fields
        (counts, source inventory, timeline).

        Args:
            investigation_id: Investigation scope identifier.

        Returns:
            Populated InvestigationSnapshot with all available data.
        """
        self._log.info("aggregate_start", investigation_id=investigation_id)

        # Parallel fetch from all stores
        facts_result, class_stats, verification_records = await asyncio.gather(
            self._fact_store.retrieve_by_investigation(investigation_id),
            self._classification_store.get_stats(investigation_id),
            self._verification_store.get_all_results(investigation_id),
        )

        facts = facts_result.get("facts", [])
        objective = facts_result.get("metadata", {}).get("objective", "")

        # Fetch all classifications (not just stats)
        all_classifications = await self._classification_store.get_priority_queue(
            investigation_id, exclude_noise=False
        )

        # Serialize verification records to dicts
        verification_dicts = [
            record.model_dump(mode="json") for record in verification_records
        ]

        # Graph summary (optional, best-effort)
        graph_summary = await self._fetch_graph_summary(investigation_id)

        # Compute verification status counts
        status_counts = self._count_by_verification_status(verification_dicts)

        # Count dubious from classifications
        dubious_count = self._count_dubious(all_classifications)

        # Build source inventory from facts and verifications
        source_inventory = self._build_source_inventory(facts, verification_dicts)

        # Build chronological timeline from facts with temporal markers
        timeline_entries = self._build_timeline(facts, all_classifications)

        snapshot = InvestigationSnapshot(
            investigation_id=investigation_id,
            objective=objective,
            facts=facts,
            classifications=all_classifications,
            verification_results=verification_dicts,
            graph_summary=graph_summary,
            fact_count=len(facts),
            confirmed_count=status_counts.get("confirmed", 0),
            refuted_count=status_counts.get("refuted", 0),
            unverifiable_count=status_counts.get("unverifiable", 0),
            dubious_count=dubious_count,
            source_inventory=source_inventory,
            timeline_entries=timeline_entries,
            created_at=datetime.now(timezone.utc),
        )

        self._log.info(
            "aggregate_complete",
            investigation_id=investigation_id,
            fact_count=snapshot.fact_count,
            confirmed=snapshot.confirmed_count,
            refuted=snapshot.refuted_count,
            dubious=snapshot.dubious_count,
            token_estimate=snapshot.token_estimate(),
        )

        return snapshot

    async def _fetch_graph_summary(self, investigation_id: str) -> dict[str, Any]:
        """Fetch graph summary data from GraphPipeline.

        Wraps the graph query in try/except so graph unavailability does not
        block aggregation. Returns empty dict if graph pipeline is not
        configured or query fails.

        Args:
            investigation_id: Investigation scope identifier.

        Returns:
            Graph summary dict with node_count, edge_count, clusters.
        """
        if self._graph_pipeline is None:
            return {}

        try:
            corr = await self._graph_pipeline.query(
                "corroboration_clusters",
                investigation_id=investigation_id,
            )
            return {
                "node_count": corr.node_count,
                "edge_count": corr.edge_count,
                "clusters": len(corr.metadata.get("clusters", [])),
            }
        except Exception as exc:
            self._log.warning(
                "graph_query_failed",
                investigation_id=investigation_id,
                error=str(exc),
            )
            return {}

    def _build_source_inventory(
        self,
        facts: list[dict[str, Any]],
        verifications: list[dict[str, Any]],
    ) -> list[SourceInventoryEntry]:
        """Build source inventory from facts and verification evidence.

        Groups facts by source_id from provenance metadata. For each unique
        source, extracts domain, type, and authority from available data.

        Args:
            facts: List of fact dicts from FactStore.
            verifications: List of verification result dicts.

        Returns:
            List of SourceInventoryEntry, one per unique source.
        """
        # Index verification evidence by source_domain for authority lookup
        authority_by_domain: dict[str, float] = {}
        type_by_domain: dict[str, str] = {}
        for vr in verifications:
            for evidence in vr.get("supporting_evidence", []):
                domain = evidence.get("source_domain", "")
                if domain:
                    authority_by_domain[domain] = max(
                        authority_by_domain.get(domain, 0.0),
                        evidence.get("authority_score", 0.5),
                    )
                    type_by_domain.setdefault(domain, evidence.get("source_type", "unknown"))
            for evidence in vr.get("refuting_evidence", []):
                domain = evidence.get("source_domain", "")
                if domain:
                    authority_by_domain[domain] = max(
                        authority_by_domain.get(domain, 0.0),
                        evidence.get("authority_score", 0.5),
                    )
                    type_by_domain.setdefault(domain, evidence.get("source_type", "unknown"))

        # Group facts by source_id
        source_facts: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for fact in facts:
            provenance = fact.get("provenance") or {}
            source_id = provenance.get("source_id", "")
            if not source_id:
                source_url = provenance.get("source_url", "")
                source_id = source_url if source_url else "unknown"
            source_facts[source_id].append(fact)

        entries: list[SourceInventoryEntry] = []
        for source_id, grouped_facts in source_facts.items():
            # Extract domain from source_id or provenance
            domain = ""
            source_type = "unknown"
            authority = 0.5
            last_accessed = ""

            sample = grouped_facts[0]
            prov = sample.get("provenance") or {}

            # Try to get domain from provenance source_url
            source_url = prov.get("source_url", "")
            if source_url:
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(source_url)
                    domain = parsed.netloc or source_id
                except Exception:
                    domain = source_id
            else:
                domain = source_id

            # Look up authority and type from verification evidence
            if domain in authority_by_domain:
                authority = authority_by_domain[domain]
            if domain in type_by_domain:
                source_type = type_by_domain[domain]

            # Get source_type from provenance if not found in verification
            if source_type == "unknown":
                source_type = prov.get("source_type", "unknown")

            # Last accessed from stored_at of the latest fact
            stored_timestamps = [f.get("stored_at", "") for f in grouped_facts if f.get("stored_at")]
            if stored_timestamps:
                last_accessed = max(stored_timestamps)

            entries.append(
                SourceInventoryEntry(
                    source_id=source_id,
                    source_domain=domain,
                    source_type=source_type,
                    authority_score=min(1.0, max(0.0, authority)),
                    fact_count=len(grouped_facts),
                    last_accessed=last_accessed,
                )
            )

        # Sort by fact_count descending for readability
        entries.sort(key=lambda e: e.fact_count, reverse=True)
        return entries

    def _build_timeline(
        self,
        facts: list[dict[str, Any]],
        classifications: list[dict[str, Any]],
    ) -> list[TimelineEntry]:
        """Build chronological timeline from facts with temporal markers.

        Extracts temporal markers from facts, creates TimelineEntry for each,
        and sorts by timestamp. Confidence is derived from classification
        credibility score when available.

        Args:
            facts: List of fact dicts from FactStore.
            classifications: List of classification dicts.

        Returns:
            Chronologically sorted list of TimelineEntry objects.
        """
        # Index classifications by fact_id for credibility lookup
        cred_by_fact: dict[str, float] = {}
        for cls in classifications:
            fact_id = cls.get("fact_id", "")
            cred_score = cls.get("credibility_score", 0.5)
            if fact_id:
                cred_by_fact[fact_id] = cred_score

        entries: list[TimelineEntry] = []
        seen_facts: set[str] = set()

        for fact in facts:
            fact_id = fact.get("fact_id", "")
            if not fact_id or fact_id in seen_facts:
                continue

            temporal = fact.get("temporal")
            if temporal is None:
                continue

            seen_facts.add(fact_id)

            timestamp = temporal.get("value", "")
            if not timestamp:
                continue

            claim = fact.get("claim", {})
            event_text = claim.get("text", "") if isinstance(claim, dict) else str(claim)

            # Derive confidence from classification credibility
            cred = cred_by_fact.get(fact_id, 0.5)
            if cred >= 0.7:
                level = "high"
            elif cred >= 0.4:
                level = "moderate"
            else:
                level = "low"

            confidence = ConfidenceAssessment(
                level=level,
                numeric=cred,
                reasoning=f"Derived from classification credibility score {cred:.2f}",
                source_count=1,
                highest_authority=cred,
            )

            entries.append(
                TimelineEntry(
                    timestamp=timestamp,
                    event=event_text,
                    fact_ids=[fact_id],
                    confidence=confidence,
                )
            )

        # Sort chronologically by timestamp string (ISO format sorts correctly)
        entries.sort(key=lambda e: e.timestamp)
        return entries

    @staticmethod
    def _count_by_verification_status(
        verifications: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Count verification results by status string.

        Args:
            verifications: List of verification result dicts.

        Returns:
            Dict mapping status string to count.
        """
        counts: dict[str, int] = defaultdict(int)
        for vr in verifications:
            status = vr.get("status", "unknown")
            counts[status] += 1
        return dict(counts)

    @staticmethod
    def _count_dubious(classifications: list[dict[str, Any]]) -> int:
        """Count classifications with at least one dubious flag.

        Args:
            classifications: List of classification dicts.

        Returns:
            Number of classifications with non-empty dubious_flags.
        """
        return sum(
            1 for cls in classifications if cls.get("dubious_flags")
        )
