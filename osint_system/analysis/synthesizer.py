"""LLM synthesis orchestrator for intelligence report generation.

Breaks synthesis into sectioned LLM calls (executive summary, key judgments,
alternative hypotheses, implications, source assessment) per RESEARCH.md
Pattern 3 -- avoids single monolithic prompt that would overflow context or
degrade quality.

Each LLM call is individually wrapped in try/except with graceful fallback so
partial failures produce degraded output rather than total failure.

Usage:
    from osint_system.analysis.synthesizer import Synthesizer
    from osint_system.config.analysis_config import AnalysisConfig

    config = AnalysisConfig.from_env()
    synth = Synthesizer(config=config)
    result = await synth.synthesize(snapshot)
    print(result.executive_summary)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import structlog

from osint_system.analysis.schemas import (
    AlternativeHypothesis,
    AnalysisSynthesis,
    ConfidenceAssessment,
    ContradictionEntry,
    InvestigationSnapshot,
    KeyJudgment,
)
from osint_system.config.analysis_config import AnalysisConfig
from osint_system.config.prompts.analysis_prompts import (
    ALTERNATIVE_HYPOTHESES_PROMPT,
    EXECUTIVE_SUMMARY_PROMPT,
    IMPLICATIONS_PROMPT,
    KEY_JUDGMENTS_PROMPT,
    SOURCE_ASSESSMENT_PROMPT,
)

logger = structlog.get_logger(__name__)


class Synthesizer:
    """Orchestrates sectioned LLM synthesis of investigation data.

    Generates IC-style key judgments, alternative hypotheses, implications,
    and executive summary from a pre-aggregated InvestigationSnapshot.

    Each synthesis section gets its own focused prompt with a relevant
    subset of the data context, keeping each call within the configured
    max_tokens_per_section budget.

    Attributes:
        _config: AnalysisConfig controlling model, temperature, token budgets.
        _llm_client: Optional pre-configured Gemini client.
        _log: Structured logger bound to this component.
    """

    def __init__(
        self,
        config: AnalysisConfig,
        llm_client: Any | None = None,
    ) -> None:
        """Initialize Synthesizer.

        Args:
            config: Analysis configuration for model, temperature, limits.
            llm_client: Optional pre-configured google.genai client. If None,
                lazy-initialized on first LLM call.
        """
        self._config = config
        self._llm_client = llm_client
        self._log = logger.bind(component="Synthesizer")

    @property
    def _client(self) -> Any:
        """Lazy-init LLM client — OpenRouter if configured, else direct Gemini."""
        if self._llm_client is None:
            import os

            openrouter_key = os.environ.get("OPENROUTER_API_KEY")
            if openrouter_key:
                try:
                    from osint_system.llm.openrouter_client import OpenRouterClient
                    self._llm_client = OpenRouterClient(api_key=openrouter_key)
                    self._log.info(
                        "openrouter_client_initialized",
                        model=self._config.synthesis_model,
                    )
                    return self._llm_client
                except Exception as exc:
                    self._log.warning("openrouter_init_failed", error=str(exc))

            try:
                from google import genai  # type: ignore[import-untyped]
                from osint_system.config.settings import settings

                self._llm_client = genai.Client(api_key=settings.gemini_api_key)
                self._log.info(
                    "gemini_client_initialized",
                    model=self._config.synthesis_model,
                )
            except Exception as exc:
                self._log.error("gemini_client_init_failed", error=str(exc))
                raise
        return self._llm_client

    async def synthesize(
        self,
        snapshot: InvestigationSnapshot,
    ) -> AnalysisSynthesis:
        """Generate a complete AnalysisSynthesis from investigation data.

        Runs sectioned LLM calls in sequence:
        1. Prepare facts context
        2. Executive summary
        3. Key judgments (JSON)
        4. Alternative hypotheses (JSON)
        5. Implications / forecasts (JSON)
        6. Source assessment (text)
        7. Compute overall confidence
        8. Assemble AnalysisSynthesis

        Each call has independent error handling; partial failures produce
        degraded output (empty lists, fallback text) rather than exceptions.

        Args:
            snapshot: Pre-aggregated investigation data.

        Returns:
            Populated AnalysisSynthesis ready for report rendering.
        """
        self._log.info(
            "synthesis_start",
            investigation_id=snapshot.investigation_id,
            fact_count=snapshot.fact_count,
        )

        facts_context = self._prepare_facts_context(snapshot)

        # --- 1. Executive summary ---
        executive_summary = await self._generate_executive_summary(
            snapshot, facts_context
        )

        # --- 2. Key judgments ---
        key_judgments = await self._generate_key_judgments(
            snapshot, facts_context
        )

        # --- 3. Alternative hypotheses ---
        alternative_hypotheses = await self._generate_alternative_hypotheses(
            key_judgments, facts_context, snapshot
        )

        # --- 4. Implications and forecasts ---
        implications, forecasts = await self._generate_implications(
            key_judgments, snapshot
        )

        # --- 5. Source assessment ---
        source_assessment = await self._generate_source_assessment(snapshot)

        # --- 6. Overall confidence ---
        overall_confidence = self._compute_overall_confidence(key_judgments)

        synthesis = AnalysisSynthesis(
            investigation_id=snapshot.investigation_id,
            executive_summary=executive_summary,
            key_judgments=key_judgments,
            alternative_hypotheses=alternative_hypotheses,
            contradictions=[],  # Filled by ContradictionAnalyzer downstream
            implications=implications,
            forecasts=forecasts,
            overall_confidence=overall_confidence,
            source_assessment=source_assessment,
            snapshot=snapshot,
            generated_at=datetime.now(timezone.utc),
            model_version=self._config.synthesis_model,
        )

        self._log.info(
            "synthesis_complete",
            investigation_id=snapshot.investigation_id,
            judgments=len(key_judgments),
            alternatives=len(alternative_hypotheses),
            confidence_level=overall_confidence.level,
        )

        return synthesis

    # ------------------------------------------------------------------
    # Section generators (each wraps its own LLM call + error handling)
    # ------------------------------------------------------------------

    async def _generate_executive_summary(
        self,
        snapshot: InvestigationSnapshot,
        facts_context: str,
    ) -> str:
        """Generate 1-2 paragraph executive summary."""
        try:
            prompt = EXECUTIVE_SUMMARY_PROMPT.format(
                objective=snapshot.objective or "General investigation",
                facts_context=facts_context,
                fact_count=snapshot.fact_count,
                confirmed_count=snapshot.confirmed_count,
                refuted_count=snapshot.refuted_count,
                unverifiable_count=snapshot.unverifiable_count,
            )
            return await self._call_llm(prompt, structured=False)
        except Exception as exc:
            self._log.error("executive_summary_failed", error=str(exc))
            return "Executive summary unavailable due to synthesis error."

    async def _generate_key_judgments(
        self,
        snapshot: InvestigationSnapshot,
        facts_context: str,
    ) -> list[KeyJudgment]:
        """Generate IC-style key judgments."""
        try:
            prompt = KEY_JUDGMENTS_PROMPT.format(
                objective=snapshot.objective or "General investigation",
                facts_context=facts_context,
                max_judgments=self._config.max_key_judgments,
            )
            response = await self._call_llm(prompt, structured=True)
            return self._parse_key_judgments(response)
        except Exception as exc:
            self._log.error("key_judgments_failed", error=str(exc))
            return []

    async def _generate_alternative_hypotheses(
        self,
        judgments: list[KeyJudgment],
        facts_context: str,
        snapshot: InvestigationSnapshot,
    ) -> list[AlternativeHypothesis]:
        """Generate alternative hypotheses for uncertain judgments."""
        # Only generate alternatives for moderate/low confidence judgments
        uncertain = [
            j for j in judgments if j.confidence.level in ("low", "moderate")
        ]
        if not uncertain:
            self._log.info("no_uncertain_judgments_for_alternatives")
            return []

        try:
            judgments_text = "\n".join(
                f"- [{j.confidence.level.upper()}] {j.judgment}"
                for j in uncertain
            )
            prompt = ALTERNATIVE_HYPOTHESES_PROMPT.format(
                judgments_context=judgments_text,
                facts_context=facts_context,
            )
            response = await self._call_llm(prompt, structured=True)
            return self._parse_alternative_hypotheses(response)
        except Exception as exc:
            self._log.error("alternative_hypotheses_failed", error=str(exc))
            return []

    async def _generate_implications(
        self,
        judgments: list[KeyJudgment],
        snapshot: InvestigationSnapshot,
    ) -> tuple[list[str], list[str]]:
        """Generate strategic implications and forecasts."""
        if not judgments:
            return [], []

        try:
            judgments_text = "\n".join(
                f"- [{j.confidence.level.upper()}] {j.judgment}"
                for j in judgments
            )
            prompt = IMPLICATIONS_PROMPT.format(
                judgments_context=judgments_text,
            )
            response = await self._call_llm(prompt, structured=True)
            data = json.loads(response)
            return (
                data.get("implications", []),
                data.get("forecasts", []),
            )
        except Exception as exc:
            self._log.error("implications_failed", error=str(exc))
            return [], []

    async def _generate_source_assessment(
        self,
        snapshot: InvestigationSnapshot,
    ) -> str:
        """Generate source quality assessment."""
        try:
            inventory_text = "\n".join(
                f"- {s.source_domain} ({s.source_type}): {s.fact_count} facts, "
                f"authority={s.authority_score:.2f}"
                for s in snapshot.source_inventory
            )
            if not inventory_text:
                inventory_text = "No source inventory available."

            prompt = SOURCE_ASSESSMENT_PROMPT.format(
                source_inventory=inventory_text,
                fact_count=snapshot.fact_count,
                source_count=len(snapshot.source_inventory),
            )
            return await self._call_llm(prompt, structured=False)
        except Exception as exc:
            self._log.error("source_assessment_failed", error=str(exc))
            return "Source assessment unavailable."

    # ------------------------------------------------------------------
    # LLM call abstraction
    # ------------------------------------------------------------------

    async def _call_llm(self, prompt: str, structured: bool = False) -> str:
        """Call Gemini API and return response text.

        Args:
            prompt: Full prompt string.
            structured: If True, appends "Respond with valid JSON only."

        Returns:
            Raw response text from the LLM.

        Raises:
            Exception: On API error (caller handles via try/except).
        """
        if structured:
            prompt = prompt.rstrip() + "\n\nRespond with valid JSON only."

        client = self._client

        config_dict: dict[str, Any] = {
            "temperature": self._config.temperature,
            "max_output_tokens": 20000,
        }
        if structured:
            config_dict["response_format"] = "json"

        response = await client.aio.models.generate_content(
            model=self._config.synthesis_model,
            contents=prompt,
            config=config_dict,
        )

        text = response.text

        # Strip markdown code fencing that Gemini often wraps around JSON
        if structured and text:
            stripped = text.strip()
            if stripped.startswith("```"):
                # Remove opening fence (```json or ```)
                first_newline = stripped.index("\n") if "\n" in stripped else len(stripped)
                stripped = stripped[first_newline + 1:]
                # Remove closing fence
                if stripped.rstrip().endswith("```"):
                    stripped = stripped.rstrip()[:-3].rstrip()
                text = stripped

        return text

    # ------------------------------------------------------------------
    # Context preparation
    # ------------------------------------------------------------------

    def _prepare_facts_context(
        self,
        snapshot: InvestigationSnapshot,
    ) -> str:
        """Format facts as concise bullet points for LLM prompts.

        Each fact is formatted as:
            - [FACT-{id}] {claim_text} (confidence: {score}, status: {status})

        Truncates to max_tokens_per_section characters (rough 4:1 ratio).

        Args:
            snapshot: InvestigationSnapshot with facts and verifications.

        Returns:
            Formatted facts context string.
        """
        # Index verification status by fact_id for quick lookup
        verif_status: dict[str, str] = {}
        verif_confidence: dict[str, float] = {}
        for vr in snapshot.verification_results:
            fid = vr.get("fact_id", "")
            verif_status[fid] = vr.get("status", "unknown")
            verif_confidence[fid] = vr.get("final_confidence", 0.5)

        lines: list[str] = []
        max_chars = self._config.max_tokens_per_section * 4

        for fact in snapshot.facts:
            fact_id = fact.get("fact_id", "unknown")
            claim = fact.get("claim", {})
            if isinstance(claim, dict):
                claim_text = claim.get("text", "")
            else:
                claim_text = str(claim)

            status = verif_status.get(fact_id, "unverified")
            confidence = verif_confidence.get(fact_id, 0.5)

            line = (
                f"- [FACT-{fact_id}] {claim_text} "
                f"(confidence: {confidence:.2f}, status: {status})"
            )
            lines.append(line)

            # Check rough character budget
            total = sum(len(l) for l in lines)
            if total > max_chars:
                lines.append(f"... ({len(snapshot.facts) - len(lines)} more facts truncated)")
                break

        return "\n".join(lines) if lines else "No facts available."

    # ------------------------------------------------------------------
    # JSON parsing helpers
    # ------------------------------------------------------------------

    def _parse_key_judgments(self, response: str) -> list[KeyJudgment]:
        """Parse LLM JSON response into KeyJudgment objects.

        Handles malformed JSON gracefully: returns empty list with warning.

        Args:
            response: Raw JSON string from LLM.

        Returns:
            Parsed list of KeyJudgment models.
        """
        try:
            data = json.loads(response)
        except json.JSONDecodeError as exc:
            self._log.warning(
                "key_judgments_json_parse_failed",
                error=str(exc),
                response_preview=response[:200],
            )
            return []

        raw_judgments = data.get("key_judgments", [])
        judgments: list[KeyJudgment] = []

        for raw in raw_judgments:
            try:
                confidence = ConfidenceAssessment(
                    level=raw.get("confidence_level", "moderate"),
                    numeric=float(raw.get("confidence_numeric", 0.5)),
                    reasoning=raw.get("confidence_reasoning", ""),
                )
                judgment = KeyJudgment(
                    judgment=raw.get("judgment", ""),
                    confidence=confidence,
                    supporting_fact_ids=raw.get("supporting_fact_ids", []),
                    reasoning=raw.get("reasoning", ""),
                )
                judgments.append(judgment)
            except Exception as exc:
                self._log.warning(
                    "key_judgment_parse_error",
                    error=str(exc),
                    raw=str(raw)[:200],
                )

        return judgments[: self._config.max_key_judgments]

    def _parse_alternative_hypotheses(
        self, response: str
    ) -> list[AlternativeHypothesis]:
        """Parse LLM JSON response into AlternativeHypothesis objects.

        Args:
            response: Raw JSON string from LLM.

        Returns:
            Parsed list of AlternativeHypothesis models.
        """
        try:
            data = json.loads(response)
        except json.JSONDecodeError as exc:
            self._log.warning(
                "alt_hypotheses_json_parse_failed",
                error=str(exc),
                response_preview=response[:200],
            )
            return []

        raw_hypotheses = data.get("alternative_hypotheses", [])
        hypotheses: list[AlternativeHypothesis] = []

        for raw in raw_hypotheses:
            try:
                hyp = AlternativeHypothesis(
                    hypothesis=raw.get("hypothesis", ""),
                    likelihood=raw.get("likelihood", "possible"),
                    supporting_evidence=raw.get("supporting_evidence", []),
                    weaknesses=raw.get("weaknesses", []),
                )
                hypotheses.append(hyp)
            except Exception as exc:
                self._log.warning(
                    "alt_hypothesis_parse_error",
                    error=str(exc),
                    raw=str(raw)[:200],
                )

        return hypotheses

    # ------------------------------------------------------------------
    # Confidence computation
    # ------------------------------------------------------------------

    def _compute_overall_confidence(
        self,
        judgments: list[KeyJudgment],
    ) -> ConfidenceAssessment:
        """Compute overall confidence from key judgments.

        Averages the numeric confidence across all judgments and maps
        to IC level: <0.4 = low, 0.4-0.7 = moderate, >0.7 = high.

        Args:
            judgments: List of key judgments with confidence scores.

        Returns:
            ConfidenceAssessment representing the overall analysis confidence.
        """
        if not judgments:
            return ConfidenceAssessment(
                level="low",
                numeric=0.0,
                reasoning="No key judgments generated.",
                source_count=0,
                highest_authority=0.0,
            )

        numeric_scores = [j.confidence.numeric for j in judgments]
        avg = sum(numeric_scores) / len(numeric_scores)

        if avg > 0.7:
            level = "high"
        elif avg >= 0.4:
            level = "moderate"
        else:
            level = "low"

        total_sources = sum(j.confidence.source_count for j in judgments)
        max_authority = max(
            (j.confidence.highest_authority for j in judgments), default=0.0
        )

        return ConfidenceAssessment(
            level=level,
            numeric=round(avg, 3),
            reasoning=(
                f"Weighted average of {len(judgments)} key judgment confidence scores. "
                f"Range: {min(numeric_scores):.2f} - {max(numeric_scores):.2f}."
            ),
            source_count=total_sources,
            highest_authority=max_authority,
        )
