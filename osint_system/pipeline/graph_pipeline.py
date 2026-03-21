"""Standalone graph pipeline for bulk ingestion and event-driven flow.

Follows the same pattern as VerificationPipeline (lazy init, event registration,
standalone mode). Provides both automatic event-driven ingestion from
verification.complete events and standalone bulk ingestion for existing
investigation data.

Can be registered with an InvestigationPipeline for automatic event flow:
    classification.complete -> verification -> verification.complete -> graph ingestion

Standalone usage:
    pipeline = GraphPipeline()
    stats = await pipeline.run_ingestion("inv-123")

Event-driven usage:
    pipeline = GraphPipeline()
    pipeline.register_with_pipeline(investigation_pipeline)
    # Automatically handles verification.complete events

Query convenience:
    result = await pipeline.query("entity_network", entity_id="inv-1:Putin")
"""

from __future__ import annotations

from typing import Any, Optional

import structlog

from osint_system.agents.sifters.graph.graph_ingestor import GraphIngestor
from osint_system.config.graph_config import GraphConfig
from osint_system.data_management.classification_store import ClassificationStore
from osint_system.data_management.fact_store import FactStore
from osint_system.data_management.graph.adapter import GraphAdapter
from osint_system.data_management.graph.schema import QueryResult
from osint_system.data_management.verification_store import VerificationStore


logger = structlog.get_logger(__name__)


class GraphPipeline:
    """Orchestrates verification -> graph ingestion flow.

    Provides both event-driven (register_with_pipeline) and standalone
    (run_ingestion) operation modes. Lazy-initializes GraphIngestor and
    adapter from config when not pre-configured.

    Per CONTEXT.md chain:
        classification.complete -> verification -> verification.complete -> graph ingestion

    Attributes:
        config: GraphConfig for adapter and ingestor setup.
    """

    def __init__(
        self,
        graph_ingestor: Optional[GraphIngestor] = None,
        adapter: Optional[GraphAdapter] = None,
        fact_store: Optional[FactStore] = None,
        verification_store: Optional[VerificationStore] = None,
        classification_store: Optional[ClassificationStore] = None,
        config: Optional[GraphConfig] = None,
    ) -> None:
        """Initialize GraphPipeline.

        Args:
            graph_ingestor: Pre-configured ingestor. Lazy-initialized if None.
            adapter: Pre-configured graph adapter. Lazy-initialized if None.
            fact_store: Shared fact store. Created fresh if None.
            verification_store: Shared verification store. Created fresh if None.
            classification_store: Shared classification store. Created fresh if None.
            config: Graph configuration. Uses from_env() if None.
        """
        self._graph_ingestor = graph_ingestor
        self._adapter = adapter
        self._fact_store = fact_store
        self._verification_store = verification_store
        self._classification_store = classification_store
        self._config = config
        self._adapter_initialized = False
        self._message_bus: Any | None = None
        self._log = logger.bind(component="GraphPipeline")

    def set_message_bus(self, bus: Any) -> None:
        """Store a MessageBus reference for downstream event emission.

        Args:
            bus: MessageBus instance with async publish() method.
        """
        self._message_bus = bus

    @property
    def config(self) -> GraphConfig:
        """Lazy-load GraphConfig from environment if not provided."""
        if self._config is None:
            self._config = GraphConfig.from_env()
        return self._config

    def _get_adapter(self) -> GraphAdapter:
        """Lazy-init graph adapter based on config.

        If use_networkx_fallback is True, creates a NetworkXAdapter.
        Otherwise, creates a MemgraphAdapter (requires Memgraph running).

        Returns:
            Initialized GraphAdapter.
        """
        if self._adapter is not None:
            return self._adapter

        if self.config.use_networkx_fallback:
            from osint_system.data_management.graph.networkx_adapter import (
                NetworkXAdapter,
            )

            self._adapter = NetworkXAdapter()
        else:
            from osint_system.data_management.graph.memgraph_adapter import (
                MemgraphAdapter,
            )

            self._adapter = MemgraphAdapter(self.config)

        return self._adapter

    async def _ensure_adapter_initialized(self) -> None:
        """Initialize the adapter if not already done."""
        if not self._adapter_initialized:
            adapter = self._get_adapter()
            await adapter.initialize()
            self._adapter_initialized = True

    def _get_ingestor(self) -> GraphIngestor:
        """Lazy-init GraphIngestor with shared stores and adapter.

        Returns:
            Configured GraphIngestor.
        """
        if self._graph_ingestor is not None:
            return self._graph_ingestor

        self._graph_ingestor = GraphIngestor(
            adapter=self._get_adapter(),
            fact_store=self._fact_store or FactStore(),
            verification_store=self._verification_store or VerificationStore(),
            classification_store=self._classification_store or ClassificationStore(),
            config=self.config,
        )
        return self._graph_ingestor

    async def on_verification_complete(
        self,
        investigation_id: str,
        verification_summary: dict[str, Any],
    ) -> dict[str, Any]:
        """Handler for verification.complete events.

        Delegates to GraphIngestor.ingest_investigation to ingest all
        verified facts for the investigation.

        Args:
            investigation_id: Investigation to ingest.
            verification_summary: Summary from verification phase (for logging).

        Returns:
            Ingestion stats dict.
        """
        await self._ensure_adapter_initialized()

        self._log.info(
            "graph_ingestion_triggered",
            investigation_id=investigation_id,
            verification_total=verification_summary.get("total_verified", 0),
        )

        ingestor = self._get_ingestor()
        stats = await ingestor.ingest_investigation(investigation_id)

        self._log.info(
            "graph_ingestion_complete",
            investigation_id=investigation_id,
            **stats,
        )

        # Emit graph.ingested event for downstream pipelines (e.g. AnalysisPipeline)
        if self._message_bus is not None:
            await self._message_bus.publish(
                "graph.ingested",
                {
                    "investigation_id": investigation_id,
                    "ingestion_stats": stats,
                },
            )

        return stats

    async def run_ingestion(
        self,
        investigation_id: str,
        include_all: bool = False,
    ) -> dict[str, Any]:
        """Standalone mode: ingest an investigation's facts into the graph.

        Args:
            investigation_id: Investigation to ingest.
            include_all: If True, includes all facts regardless of verification
                status. If False, only CONFIRMED and SUPERSEDED.

        Returns:
            Ingestion stats dict.
        """
        await self._ensure_adapter_initialized()

        self._log.info(
            "standalone_ingestion",
            investigation_id=investigation_id,
            include_all=include_all,
        )

        ingestor = self._get_ingestor()

        if include_all:
            return await ingestor.ingest_investigation_all(investigation_id)
        return await ingestor.ingest_investigation(investigation_id)

    def register_with_pipeline(
        self,
        investigation_pipeline: Any,
    ) -> None:
        """Register as handler for verification.complete events.

        Hooks into the investigation pipeline's event system, extending
        the pipeline chain: classification -> verification -> graph.

        Args:
            investigation_pipeline: InvestigationPipeline with on_event method.
        """
        if hasattr(investigation_pipeline, "message_bus"):
            self._message_bus = investigation_pipeline.message_bus

        if hasattr(investigation_pipeline, "on_event"):
            investigation_pipeline.on_event(
                "verification.complete",
                self.on_verification_complete,
            )
            self._log.info("graph_pipeline_registered")
        else:
            self._log.warning(
                "pipeline_registration_failed",
                msg="Investigation pipeline does not support on_event",
            )

    async def query(
        self,
        query_type: str,
        **kwargs: Any,
    ) -> QueryResult:
        """Convenience method for querying the graph.

        Delegates to the appropriate adapter query method based on query_type.

        Args:
            query_type: One of "entity_network", "corroboration_clusters",
                "timeline", "shortest_path".
            **kwargs: Query-specific parameters passed to the adapter method.

        Returns:
            QueryResult from the adapter.

        Raises:
            ValueError: If query_type is not recognized.
        """
        await self._ensure_adapter_initialized()
        adapter = self._get_adapter()

        if query_type == "entity_network":
            return await adapter.query_entity_network(**kwargs)
        elif query_type == "corroboration_clusters":
            return await adapter.query_corroboration_clusters(**kwargs)
        elif query_type == "timeline":
            return await adapter.query_timeline(**kwargs)
        elif query_type == "shortest_path":
            return await adapter.query_shortest_path(**kwargs)
        else:
            raise ValueError(
                f"Unknown query_type {query_type!r}. "
                f"Supported: entity_network, corroboration_clusters, timeline, shortest_path"
            )
