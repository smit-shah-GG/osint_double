"""Event-driven graph ingestion from verification pipeline.

Subscribes to ``verification.complete`` events on the MessageBus and
automatically ingests verified facts into the knowledge graph. Provides
both single-fact and bulk investigation ingestion.

The ingestion flow:
1. Receive verification.complete event (or direct call)
2. Fetch full fact, verification result, and classification from stores
3. Map fact to graph nodes/edges via FactMapper
4. Extract additional relationships via RelationshipExtractor
5. Batch merge all nodes and edges into the graph adapter

Standalone usage (no MessageBus):
    ingestor = GraphIngestor(adapter=adapter, fact_store=fs, ...)
    stats = await ingestor.ingest_fact("inv-1", "fact-001")

Event-driven usage:
    ingestor = GraphIngestor(adapter=adapter, fact_store=fs, ..., bus=bus)
    ingestor.register()  # subscribes to verification.complete
    # ... events flow automatically

Bulk ingestion:
    stats = await ingestor.ingest_investigation("inv-1")  # only CONFIRMED+SUPERSEDED
    stats = await ingestor.ingest_investigation_all("inv-1")  # all statuses
"""

from __future__ import annotations

from typing import Any, Optional

import structlog

from osint_system.agents.communication.bus import MessageBus
from osint_system.agents.sifters.graph.fact_mapper import FactMapper
from osint_system.agents.sifters.graph.relationship_extractor import (
    RelationshipExtractor,
)
from osint_system.config.graph_config import GraphConfig
from osint_system.data_management.classification_store import ClassificationStore
from osint_system.data_management.fact_store import FactStore
from osint_system.data_management.graph.adapter import GraphAdapter
from osint_system.data_management.graph.schema import GraphEdge, GraphNode
from osint_system.data_management.schemas.classification_schema import (
    FactClassification,
)
from osint_system.data_management.schemas.fact_schema import ExtractedFact
from osint_system.data_management.schemas.verification_schema import (
    VerificationResult,
    VerificationStatus,
)
from osint_system.data_management.verification_store import VerificationStore


logger = structlog.get_logger(__name__)


# Statuses eligible for default ingestion (skip REFUTED, UNVERIFIABLE, PENDING, IN_PROGRESS)
_INGESTIBLE_STATUSES = {
    VerificationStatus.CONFIRMED,
    VerificationStatus.SUPERSEDED,
}


class GraphIngestor:
    """Event-driven graph ingestion handler.

    Listens for ``verification.complete`` events on the MessageBus and
    transforms verified facts into graph nodes and edges. Supports both
    event-driven and standalone operation modes.

    Entity resolution operates across facts within the same investigation
    via FactMapper's canonical name matching. Relationships are extracted
    using the hybrid rule-based + optional LLM extractor.

    Attributes:
        adapter: Graph storage backend (Neo4j or NetworkX).
        config: Graph layer configuration.
    """

    def __init__(
        self,
        adapter: GraphAdapter,
        fact_store: FactStore,
        verification_store: VerificationStore,
        classification_store: ClassificationStore,
        config: GraphConfig,
        bus: Optional[MessageBus] = None,
    ) -> None:
        """Initialize GraphIngestor.

        Args:
            adapter: Graph storage backend implementing GraphAdapter Protocol.
            fact_store: Store for fetching full fact data.
            verification_store: Store for fetching verification results.
            classification_store: Store for fetching fact classifications.
            config: Graph configuration (controls relationship extraction).
            bus: Optional MessageBus for event-driven mode. If None, operates
                in standalone mode (call ingest_fact/ingest_investigation directly).
        """
        self._adapter = adapter
        self._fact_store = fact_store
        self._verification_store = verification_store
        self._classification_store = classification_store
        self._config = config
        self._bus = bus
        self._log = logger.bind(component="GraphIngestor")

    def register(self, bus: Optional[MessageBus] = None) -> None:
        """Register as handler for ``verification.complete`` events.

        Subscribes to the MessageBus pattern ``verification.complete``.
        When an event arrives, ``_on_verification_complete`` is called
        with the full message dict.

        Args:
            bus: MessageBus to register with. Falls back to self._bus.
                If both are None, logs a warning and returns (standalone mode).
        """
        target_bus = bus or self._bus
        if target_bus is None:
            self._log.warning(
                "no_bus_available",
                msg="Cannot register without MessageBus; operating in standalone mode",
            )
            return

        # Store reference for future use
        if self._bus is None:
            self._bus = target_bus

        target_bus.subscribe_to_pattern(
            "graph_ingestor",
            "verification.complete",
            self._on_verification_complete,
        )
        self._log.info("registered", pattern="verification.complete")

    async def _on_verification_complete(self, message: dict) -> None:
        """Event handler for verification.complete messages.

        Extracts fact_id and investigation_id from the message payload
        and delegates to ``ingest_fact``.

        Args:
            message: Full message dict from MessageBus with structure:
                {"id": ..., "timestamp": ..., "key": ..., "payload": {...}}
        """
        payload = message.get("payload", {})
        fact_id = payload.get("fact_id")
        investigation_id = payload.get("investigation_id")

        if not fact_id or not investigation_id:
            self._log.warning(
                "incomplete_event",
                msg="verification.complete event missing fact_id or investigation_id",
                payload_keys=list(payload.keys()),
            )
            return

        try:
            stats = await self.ingest_fact(investigation_id, fact_id)
            self._log.info(
                "event_ingestion_complete",
                fact_id=fact_id,
                investigation_id=investigation_id,
                **stats,
            )
        except Exception as exc:
            self._log.error(
                "event_ingestion_failed",
                fact_id=fact_id,
                investigation_id=investigation_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    async def ingest_fact(
        self,
        investigation_id: str,
        fact_id: str,
    ) -> dict[str, int]:
        """Ingest a single verified fact into the graph.

        Fetches the full fact, verification result, and classification from
        their respective stores, maps to graph nodes/edges via FactMapper
        and RelationshipExtractor, then batch-merges into the adapter.

        Args:
            investigation_id: Investigation scope.
            fact_id: Fact identifier to ingest.

        Returns:
            Stats dict: {"nodes_merged": N, "edges_merged": M}
        """
        # Fetch fact from FactStore
        fact_dict = await self._fact_store.get_fact(investigation_id, fact_id)
        if fact_dict is None:
            self._log.warning(
                "fact_not_found",
                fact_id=fact_id,
                investigation_id=investigation_id,
            )
            return {"nodes_merged": 0, "edges_merged": 0}

        # Parse fact dict into Pydantic model
        fact = ExtractedFact.model_validate(fact_dict)

        # Fetch verification result (optional -- may ingest unverified facts)
        verification: Optional[VerificationResult] = None
        record = await self._verification_store.get_result(investigation_id, fact_id)
        if record is not None:
            # VerificationResultRecord IS-A VerificationResult; extract core fields
            verification = record.to_result()

        # Fetch classification (optional)
        classification: Optional[FactClassification] = None
        cls_dict = await self._classification_store.get_classification(
            investigation_id, fact_id
        )
        if cls_dict is not None:
            classification = FactClassification.model_validate(cls_dict)

        # Map fact to graph nodes and edges
        mapper = FactMapper(investigation_id=investigation_id)
        nodes, edges = mapper.map_fact(fact, verification, classification)

        # Extract additional relationships
        extractor = RelationshipExtractor(config=self._config)
        existing_facts = await self._get_investigation_facts(investigation_id)
        additional_edges = extractor.extract_relationships(
            fact, verification, existing_facts, investigation_id
        )
        edges.extend(additional_edges)

        # Batch merge nodes grouped by label
        total_nodes = await self._merge_nodes(nodes)
        total_edges = await self._merge_edges(edges)

        stats = {"nodes_merged": total_nodes, "edges_merged": total_edges}
        self._log.info(
            "fact_ingested",
            fact_id=fact_id,
            investigation_id=investigation_id,
            **stats,
        )
        return stats

    async def ingest_investigation(
        self,
        investigation_id: str,
    ) -> dict[str, int]:
        """Bulk ingest all verified facts for an investigation.

        Fetches all verification results, filters to CONFIRMED and SUPERSEDED
        statuses (skip REFUTED, UNVERIFIABLE, PENDING, IN_PROGRESS), then
        ingests each qualifying fact with shared entity resolution.

        Args:
            investigation_id: Investigation to ingest.

        Returns:
            Stats dict: {"nodes_merged": N, "edges_merged": M, "facts_ingested": K}
        """
        return await self._ingest_investigation_impl(
            investigation_id, filter_status=True
        )

    async def ingest_investigation_all(
        self,
        investigation_id: str,
    ) -> dict[str, int]:
        """Bulk ingest ALL facts for an investigation regardless of status.

        Includes CONFIRMED, SUPERSEDED, REFUTED, UNVERIFIABLE, and any other
        status. Useful for building a complete graph including disputed facts.

        Args:
            investigation_id: Investigation to ingest.

        Returns:
            Stats dict: {"nodes_merged": N, "edges_merged": M, "facts_ingested": K}
        """
        return await self._ingest_investigation_impl(
            investigation_id, filter_status=False
        )

    async def _ingest_investigation_impl(
        self,
        investigation_id: str,
        filter_status: bool,
    ) -> dict[str, int]:
        """Internal implementation for bulk investigation ingestion.

        Uses FactMapper.map_facts_batch() for batch entity resolution across
        all facts, then batch merges all nodes and edges.

        Args:
            investigation_id: Investigation to ingest.
            filter_status: If True, only ingest CONFIRMED and SUPERSEDED facts.

        Returns:
            Stats dict: {"nodes_merged": N, "edges_merged": M, "facts_ingested": K}
        """
        # Fetch all verification results
        all_records = await self._verification_store.get_all_results(investigation_id)

        if filter_status:
            # VerificationResultRecord inherits from VerificationResult, so
            # .status is directly accessible as VerificationStatus enum.
            records = [r for r in all_records if r.status in _INGESTIBLE_STATUSES]
        else:
            records = list(all_records)

        if not records:
            self._log.info(
                "no_records_to_ingest",
                investigation_id=investigation_id,
                filter_status=filter_status,
                total_records=len(all_records),
            )
            return {"nodes_merged": 0, "edges_merged": 0, "facts_ingested": 0}

        # Fetch facts and classifications for each record
        fact_tuples: list[
            tuple[ExtractedFact, Optional[VerificationResult], Optional[FactClassification]]
        ] = []

        for record in records:
            fact_dict = await self._fact_store.get_fact(
                investigation_id, record.fact_id
            )
            if fact_dict is None:
                self._log.warning(
                    "fact_not_found_during_bulk",
                    fact_id=record.fact_id,
                    investigation_id=investigation_id,
                )
                continue

            fact = ExtractedFact.model_validate(fact_dict)
            verification = record.to_result()

            classification: Optional[FactClassification] = None
            cls_dict = await self._classification_store.get_classification(
                investigation_id, record.fact_id
            )
            if cls_dict is not None:
                classification = FactClassification.model_validate(cls_dict)

            fact_tuples.append((fact, verification, classification))

        if not fact_tuples:
            return {"nodes_merged": 0, "edges_merged": 0, "facts_ingested": 0}

        # Batch map with shared entity resolution
        mapper = FactMapper(investigation_id=investigation_id)
        all_nodes, all_edges = mapper.map_facts_batch(fact_tuples)

        # Extract relationships for each fact
        extractor = RelationshipExtractor(config=self._config)
        existing_facts = [t[0] for t in fact_tuples]

        for fact, verification, _cls in fact_tuples:
            additional = extractor.extract_relationships(
                fact, verification, existing_facts, investigation_id
            )
            all_edges.extend(additional)

        # Batch merge
        total_nodes = await self._merge_nodes(all_nodes)
        total_edges = await self._merge_edges(all_edges)

        stats = {
            "nodes_merged": total_nodes,
            "edges_merged": total_edges,
            "facts_ingested": len(fact_tuples),
        }
        self._log.info(
            "investigation_ingested",
            investigation_id=investigation_id,
            filter_status=filter_status,
            **stats,
        )
        return stats

    # -- Internal helpers --------------------------------------------------

    async def _get_investigation_facts(
        self, investigation_id: str
    ) -> list[ExtractedFact]:
        """Fetch all facts for an investigation as ExtractedFact models.

        Used to provide context for relationship extraction.

        Args:
            investigation_id: Investigation scope.

        Returns:
            List of ExtractedFact models.
        """
        result = await self._fact_store.retrieve_by_investigation(investigation_id)
        facts: list[ExtractedFact] = []
        for fact_dict in result.get("facts", []):
            try:
                facts.append(ExtractedFact.model_validate(fact_dict))
            except Exception:
                # Skip facts that fail validation (defensive)
                continue
        return facts

    async def _merge_nodes(self, nodes: list[GraphNode]) -> int:
        """Batch merge nodes grouped by label for adapter efficiency.

        Groups nodes by their label (Fact, Entity, Source, Investigation)
        and calls adapter.batch_merge_nodes once per group.

        Args:
            nodes: All nodes to merge.

        Returns:
            Total number of nodes merged.
        """
        # Group by label
        by_label: dict[str, list[dict[str, Any]]] = {}
        key_props: dict[str, str] = {
            "Fact": "fact_id",
            "Entity": "entity_id",
            "Source": "source_id",
            "Investigation": "investigation_id",
            "Classification": "classification_id",
        }

        for node in nodes:
            label = node.label
            if label not in by_label:
                by_label[label] = []
            by_label[label].append(node.properties)

        total = 0
        for label, props_list in by_label.items():
            key_prop = key_props.get(label, "id")
            count = await self._adapter.batch_merge_nodes(
                label, props_list, key_property=key_prop
            )
            total += count

        return total

    async def _merge_edges(self, edges: list[GraphEdge]) -> int:
        """Batch merge all edges via adapter.

        Converts GraphEdge Pydantic models to the dict format expected by
        adapter.batch_merge_relationships.

        Args:
            edges: All edges to merge.

        Returns:
            Total number of edges merged.
        """
        if not edges:
            return 0

        rel_dicts = [
            {
                "from_id": edge.source_id,
                "to_id": edge.target_id,
                "rel_type": edge.edge_type.value,
                "properties": {
                    **edge.properties,
                    "weight": edge.weight,
                    "cross_investigation": edge.cross_investigation,
                },
            }
            for edge in edges
        ]

        return await self._adapter.batch_merge_relationships(rel_dicts)
