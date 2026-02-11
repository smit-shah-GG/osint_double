"""Core verification agent orchestrating the verification loop.

Processes dubious facts from Phase 7's priority queue through targeted
searches, evidence aggregation, and re-classification. Operates in
parallel batches of 5-10 concurrent verifications per CONTEXT.md.

Verification flow per fact:
1. Generate species-specialized queries (QueryGenerator)
2. Execute searches with rate limiting (SearchExecutor)
3. Aggregate evidence with authority weighting (EvidenceAggregator)
4. Reclassify with origin preservation (Reclassifier)
5. Store result (VerificationStore)

Usage:
    from osint_system.agents.sifters.verification import VerificationAgent

    agent = VerificationAgent(
        classification_store=cs,
        fact_store=fs,
        verification_store=vs,
    )
    stats = await agent.verify_investigation("inv-123")
"""

import asyncio
from typing import Any, Awaitable, Callable, Optional

import structlog

from osint_system.agents.sifters.verification.evidence_aggregator import (
    EvidenceAggregator,
)
from osint_system.agents.sifters.verification.query_generator import QueryGenerator
from osint_system.agents.sifters.verification.reclassifier import Reclassifier
from osint_system.agents.sifters.verification.schemas import (
    EvidenceItem,
    VerificationResult,
    VerificationStatus,
)
from osint_system.agents.sifters.verification.search_executor import SearchExecutor
from osint_system.data_management.classification_store import ClassificationStore
from osint_system.data_management.fact_store import FactStore
from osint_system.data_management.schemas import (
    DubiousFlag,
    FactClassification,
    ImpactTier,
)
from osint_system.data_management.verification_store import VerificationStore


class VerificationAgent:
    """Orchestrates verification loop for dubious facts.

    Per CONTEXT.md:
    - Processes facts in parallel batches of 5-10 concurrent
    - Up to 3 query attempts per fact before UNVERIFIABLE
    - Human-in-the-loop for CRITICAL tier
    - Progress updates via structlog
    """

    def __init__(
        self,
        classification_store: Optional[ClassificationStore] = None,
        fact_store: Optional[FactStore] = None,
        verification_store: Optional[VerificationStore] = None,
        query_generator: Optional[QueryGenerator] = None,
        search_executor: Optional[SearchExecutor] = None,
        evidence_aggregator: Optional[EvidenceAggregator] = None,
        reclassifier: Optional[Reclassifier] = None,
        batch_size: int = 10,
        max_query_attempts: int = 3,
    ) -> None:
        """Initialize VerificationAgent.

        Args:
            classification_store: Store for reading/updating classifications.
            fact_store: Store for reading facts (needed for impact re-assessment).
            verification_store: Store for persisting verification results.
            query_generator: Species-specialized query generator.
            search_executor: Search API executor.
            evidence_aggregator: Authority-weighted evidence evaluator.
            reclassifier: Status transition and re-classification logic.
            batch_size: Concurrent verifications per batch (default 10).
            max_query_attempts: Maximum queries per fact (default 3).
        """
        self.classification_store = classification_store or ClassificationStore()
        self.fact_store = fact_store or FactStore()
        self.verification_store = verification_store or VerificationStore()
        self.query_generator = query_generator or QueryGenerator()
        self.search_executor = search_executor or SearchExecutor()
        self.evidence_aggregator = evidence_aggregator or EvidenceAggregator()
        self.reclassifier = reclassifier or Reclassifier()
        self.batch_size = batch_size
        self.max_query_attempts = max_query_attempts
        self._logger = structlog.get_logger().bind(component="VerificationAgent")

    async def verify_investigation(
        self,
        investigation_id: str,
        progress_callback: Optional[Callable[[VerificationResult], Awaitable[None]]] = None,
    ) -> dict[str, Any]:
        """Verify all dubious facts for an investigation.

        Per CONTEXT.md: Pulls priority queue, processes in batches,
        emits progress updates, returns summary stats.

        Args:
            investigation_id: Investigation to verify.
            progress_callback: Optional async callback for each verified fact.

        Returns:
            Summary stats with counts by status.
        """
        # Get priority queue (excludes NOISE-only per Phase 7)
        queue = await self.classification_store.get_priority_queue(investigation_id)

        if not queue:
            self._logger.info("empty_queue", investigation_id=investigation_id)
            return self._empty_stats(investigation_id)

        self._logger.info(
            "verification_started",
            investigation_id=investigation_id,
            queue_size=len(queue),
        )

        stats = {
            "investigation_id": investigation_id,
            "total_verified": 0,
            "confirmed": 0,
            "refuted": 0,
            "unverifiable": 0,
            "superseded": 0,
            "pending_review": 0,
        }

        # Process in batches
        for i in range(0, len(queue), self.batch_size):
            batch = queue[i : i + self.batch_size]
            classifications = [FactClassification(**c) for c in batch]

            results = await self._process_batch(
                classifications, investigation_id, progress_callback
            )

            # Update stats
            for result in results:
                stats["total_verified"] += 1
                status = result.status
                if status == VerificationStatus.CONFIRMED:
                    stats["confirmed"] += 1
                elif status == VerificationStatus.REFUTED:
                    stats["refuted"] += 1
                elif status == VerificationStatus.UNVERIFIABLE:
                    stats["unverifiable"] += 1
                elif status == VerificationStatus.SUPERSEDED:
                    stats["superseded"] += 1
                if result.requires_human_review:
                    stats["pending_review"] += 1

            self._logger.info(
                "batch_complete",
                batch_start=i,
                batch_size=len(batch),
                cumulative_verified=stats["total_verified"],
            )

        self._logger.info(
            "verification_complete",
            **stats,
        )

        return stats

    async def _process_batch(
        self,
        classifications: list[FactClassification],
        investigation_id: str,
        progress_callback: Optional[Callable[[VerificationResult], Awaitable[None]]],
    ) -> list[VerificationResult]:
        """Process a batch with controlled concurrency.

        Uses asyncio.Semaphore to limit concurrent verifications.
        Uses asyncio.gather with return_exceptions=True for resilience.

        Args:
            classifications: Batch of classifications to verify.
            investigation_id: Investigation scope.
            progress_callback: Optional progress callback.

        Returns:
            List of VerificationResult objects (successful only).
        """
        semaphore = asyncio.Semaphore(self.batch_size)

        async def verify_with_semaphore(
            classification: FactClassification,
        ) -> Optional[VerificationResult]:
            async with semaphore:
                try:
                    result = await self._verify_fact(
                        classification.fact_id,
                        classification,
                        investigation_id,
                    )
                    if progress_callback:
                        await progress_callback(result)
                    return result
                except Exception as e:
                    self._logger.error(
                        "fact_verification_failed",
                        fact_id=classification.fact_id,
                        error=str(e),
                    )
                    return None

        raw_results = await asyncio.gather(
            *[verify_with_semaphore(c) for c in classifications],
            return_exceptions=True,
        )

        results: list[VerificationResult] = []
        for r in raw_results:
            if isinstance(r, VerificationResult):
                results.append(r)
            elif isinstance(r, Exception):
                self._logger.error("batch_exception", error=str(r))

        return results

    async def _verify_fact(
        self,
        fact_id: str,
        classification: FactClassification,
        investigation_id: str,
    ) -> VerificationResult:
        """Verify a single fact through query-search-evaluate loop.

        Per CONTEXT.md 3-query limit with short-circuit on definitive result.

        Args:
            fact_id: Fact identifier.
            classification: Current classification with dubious flags.
            investigation_id: Investigation scope.

        Returns:
            VerificationResult with status and evidence.
        """
        # Get fact data for query generation
        fact = await self.fact_store.get_fact(investigation_id, fact_id)
        if fact is None:
            fact = {"fact_id": fact_id, "claim": {}, "entities": []}

        # Generate queries
        queries = await self.query_generator.generate_queries(fact, classification)

        all_evidence: list[EvidenceItem] = []
        queries_used: list[str] = []
        query_attempts = 0
        evaluation = None

        # Execute queries with 3-attempt limit and short-circuit
        for query in queries[: self.max_query_attempts]:
            query_attempts += 1
            queries_used.append(query.query)

            query_evidence = await self.search_executor.execute_query(query)
            all_evidence.extend(query_evidence)

            evaluation = await self.evidence_aggregator.evaluate_evidence(
                fact, all_evidence
            )

            # Short-circuit on definitive result
            if evaluation.status in (
                VerificationStatus.CONFIRMED,
                VerificationStatus.REFUTED,
            ):
                break

        # Determine final status
        if evaluation is None or evaluation.status == VerificationStatus.PENDING:
            final_status = VerificationStatus.UNVERIFIABLE
            confidence_boost = 0.0
            reasoning = f"Unverifiable after {query_attempts} query attempts"
        else:
            final_status = evaluation.status
            confidence_boost = evaluation.confidence_boost
            reasoning = evaluation.reasoning

        # Build result
        result = VerificationResult(
            fact_id=fact_id,
            investigation_id=investigation_id,
            status=final_status,
            original_confidence=classification.credibility_score,
            confidence_boost=confidence_boost,
            supporting_evidence=evaluation.supporting_evidence if evaluation else [],
            refuting_evidence=evaluation.refuting_evidence if evaluation else [],
            query_attempts=query_attempts,
            queries_used=queries_used,
            origin_dubious_flags=list(classification.dubious_flags),
            reasoning=reasoning,
        )

        # Human review for CRITICAL tier
        if classification.impact_tier == ImpactTier.CRITICAL:
            result.requires_human_review = True

        # Store result
        await self.verification_store.save_result(result)

        # Reclassify (skip if human review pending on CRITICAL)
        if not result.requires_human_review:
            await self.reclassifier.reclassify_fact(
                fact_id,
                investigation_id,
                result,
                self.classification_store,
                self.fact_store,
            )

        # Progress log
        self._logger.info(
            "fact_verified",
            fact_id=fact_id,
            status=final_status.value,
            confidence_boost=confidence_boost,
            query_attempts=query_attempts,
            origin_flags=[f.value for f in classification.dubious_flags],
            requires_review=result.requires_human_review,
        )

        return result

    def _empty_stats(self, investigation_id: str) -> dict[str, Any]:
        """Return empty stats for an empty queue."""
        return {
            "investigation_id": investigation_id,
            "total_verified": 0,
            "confirmed": 0,
            "refuted": 0,
            "unverifiable": 0,
            "superseded": 0,
            "pending_review": 0,
        }
