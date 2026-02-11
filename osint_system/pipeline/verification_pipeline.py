"""Automatic classification -> verification pipeline per CONTEXT.md.

Per CONTEXT.md: "Verification runs automatically after classification
completes — dubious facts flow directly into the verification queue
without requiring explicit user/system trigger."

Can be used standalone or registered with an InvestigationPipeline
for event-based triggering.

Usage:
    from osint_system.pipeline import VerificationPipeline

    pipeline = VerificationPipeline()
    stats = await pipeline.run_verification("inv-123")

    # Or as event handler:
    await pipeline.on_classification_complete("inv-123", summary)
"""

from typing import Any, Awaitable, Callable, Optional

import structlog

from osint_system.agents.sifters.verification.verification_agent import (
    VerificationAgent,
)
from osint_system.data_management.classification_store import ClassificationStore
from osint_system.data_management.fact_store import FactStore
from osint_system.data_management.verification_store import VerificationStore


class VerificationPipeline:
    """Orchestrates automatic classification -> verification flow.

    Per CONTEXT.md:
    - Verification runs automatically after classification completes
    - No manual trigger required
    - Can register with InvestigationPipeline for event-based flow
    """

    def __init__(
        self,
        verification_agent: Optional[VerificationAgent] = None,
        classification_store: Optional[ClassificationStore] = None,
        fact_store: Optional[FactStore] = None,
        verification_store: Optional[VerificationStore] = None,
    ) -> None:
        """Initialize VerificationPipeline.

        Args:
            verification_agent: Pre-configured agent. Lazy-initialized if None.
            classification_store: Shared classification store.
            fact_store: Shared fact store.
            verification_store: Shared verification store.
        """
        self._verification_agent = verification_agent
        self._classification_store = classification_store
        self._fact_store = fact_store
        self._verification_store = verification_store
        self._logger = structlog.get_logger().bind(component="VerificationPipeline")

    def _get_agent(self) -> VerificationAgent:
        """Lazy-init VerificationAgent with shared stores."""
        if self._verification_agent is None:
            self._verification_agent = VerificationAgent(
                classification_store=self._classification_store or ClassificationStore(),
                fact_store=self._fact_store or FactStore(),
                verification_store=self._verification_store or VerificationStore(),
            )
        return self._verification_agent

    async def on_classification_complete(
        self,
        investigation_id: str,
        classification_summary: dict[str, Any],
    ) -> dict[str, Any]:
        """Handler for classification.complete event.

        Called automatically when FactClassificationAgent completes.
        Triggers verification for all dubious facts in the investigation.

        Args:
            investigation_id: Investigation to verify.
            classification_summary: Summary from classification phase.

        Returns:
            Verification summary stats.
        """
        dubious_count = classification_summary.get("dubious_count", 0)
        self._logger.info(
            "verification_triggered",
            investigation_id=investigation_id,
            dubious_count=dubious_count,
        )

        if dubious_count == 0:
            self._logger.info(
                "no_dubious_facts",
                investigation_id=investigation_id,
            )
            return {
                "investigation_id": investigation_id,
                "total_verified": 0,
                "skipped": "no dubious facts",
            }

        agent = self._get_agent()
        return await agent.verify_investigation(investigation_id)

    async def run_verification(
        self,
        investigation_id: str,
        progress_callback: Optional[Callable[..., Awaitable[None]]] = None,
    ) -> dict[str, Any]:
        """Run verification for an investigation (standalone mode).

        Use this when not running as part of automatic pipeline.

        Args:
            investigation_id: Investigation to verify.
            progress_callback: Optional progress callback.

        Returns:
            Verification summary stats.
        """
        self._logger.info(
            "standalone_verification",
            investigation_id=investigation_id,
        )
        agent = self._get_agent()
        return await agent.verify_investigation(investigation_id, progress_callback)

    def register_with_pipeline(
        self,
        investigation_pipeline: Any,
    ) -> None:
        """Register as handler for classification.complete events.

        Hooks into the investigation pipeline's event system.

        Args:
            investigation_pipeline: InvestigationPipeline with on_event method.
        """
        if hasattr(investigation_pipeline, "on_event"):
            investigation_pipeline.on_event(
                "classification.complete",
                self.on_classification_complete,
            )
            self._logger.info("verification_pipeline_registered")
        else:
            self._logger.warning(
                "pipeline_registration_failed",
                msg="Investigation pipeline does not support on_event",
            )
