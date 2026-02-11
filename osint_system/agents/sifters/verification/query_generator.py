"""Species-specialized query generation per CONTEXT.md decisions.

Generates up to 3 query variants per fact based on dubious flag type.
Each species has a different verification strategy:
- PHANTOM: Source-chain queries (trace back to root source attribution)
- FOG: Clarity-seeking queries (find harder/clearer claim versions)
- ANOMALY: Compound queries (temporal + authority + clarity together)
- NOISE: Skipped (batch analysis only, per CONTEXT.md)

Usage:
    from osint_system.agents.sifters.verification.query_generator import QueryGenerator

    generator = QueryGenerator()
    queries = await generator.generate_queries(fact, classification)
"""

import re
from typing import Any, Optional

import structlog

from osint_system.agents.sifters.verification.schemas import (
    DubiousFlag,
    VerificationQuery,
)
from osint_system.data_management.schemas.classification_schema import (
    ClassificationReasoning,
    FactClassification,
)

# Compiled patterns for detecting vague language in claims
_VAGUE_QUANTITY_PATTERNS = re.compile(
    r"\b(dozens|many|several|some|numerous|multiple|various|few|certain)\b",
    re.IGNORECASE,
)
_VAGUE_TEMPORAL_PATTERNS = re.compile(
    r"\b(recently|soon|shortly|later|earlier|imminent|upcoming|near future)\b",
    re.IGNORECASE,
)


class QueryGenerator:
    """Species-specialized query generation per CONTEXT.md decisions.

    Generates up to 3 query variants per fact based on dubious flag type.
    Each species has different verification strategy:
    - PHANTOM: Source-chain queries (trace back to root source)
    - FOG: Clarity-seeking queries (find harder/clearer claims)
    - ANOMALY: Compound queries (temporal + authority + clarity)
    - NOISE: Skipped (batch analysis only)
    """

    def __init__(self, max_queries: int = 3) -> None:
        """Initialize QueryGenerator.

        Args:
            max_queries: Maximum queries per fact (default 3, per CONTEXT.md).
        """
        self.max_queries = max_queries
        self._logger = structlog.get_logger().bind(component="QueryGenerator")

    async def generate_queries(
        self,
        fact: dict[str, Any],
        classification: FactClassification,
    ) -> list[VerificationQuery]:
        """Generate up to max_queries query variants per dubious flag.

        Returns empty list if:
        - No dubious flags
        - Only NOISE flag (batch analysis only per CONTEXT.md)

        Args:
            fact: Fact dict with claim, entities, provenance fields.
            classification: FactClassification with dubious_flags.

        Returns:
            List of VerificationQuery objects, up to max_queries total.
        """
        if not classification.dubious_flags:
            return []

        # Pure NOISE facts excluded per CONTEXT.md
        if classification.is_noise:
            self._logger.debug("noise_skipped", fact_id=classification.fact_id)
            return []

        all_queries: list[VerificationQuery] = []

        for flag in classification.dubious_flags:
            if flag == DubiousFlag.NOISE:
                continue  # Skip NOISE, handled in batch

            reasoning = classification.get_flag_reasoning(flag)
            flag_queries = self._generate_for_flag(fact, flag, reasoning)
            all_queries.extend(flag_queries)

        # Limit total to max_queries
        limited = all_queries[: self.max_queries]

        self._logger.info(
            "queries_generated",
            fact_id=classification.fact_id,
            flags=[f.value for f in classification.dubious_flags],
            generated=len(all_queries),
            limited_to=len(limited),
        )

        return limited

    def _generate_for_flag(
        self,
        fact: dict[str, Any],
        flag: DubiousFlag,
        reasoning: Optional[ClassificationReasoning],
    ) -> list[VerificationQuery]:
        """Dispatch to species-specific query generator."""
        if flag == DubiousFlag.PHANTOM:
            return self._generate_phantom_queries(fact, reasoning)
        elif flag == DubiousFlag.FOG:
            return self._generate_fog_queries(fact, reasoning)
        elif flag == DubiousFlag.ANOMALY:
            return self._generate_anomaly_queries(fact, reasoning)
        return []

    # ── PHANTOM: Source-chain queries ─────────────────────────────────

    def _generate_phantom_queries(
        self,
        fact: dict[str, Any],
        reasoning: Optional[ClassificationReasoning],
    ) -> list[VerificationQuery]:
        """Generate source-chain queries for PHANTOM facts.

        Per CONTEXT.md: Extract vague attribution, search for explicit versions.
        Prioritize wire services and official statements.
        """
        entities = self._extract_entity_names(fact)
        entity_str = " ".join(entities[:3]) if entities else ""
        claim_text = self._extract_claim_text(fact)

        queries: list[VerificationQuery] = []

        # 1. Entity-focused: search for named sources
        if entity_str:
            queries.append(
                VerificationQuery(
                    query=f"{entity_str} official statement press release",
                    variant_type="entity_focused",
                    target_sources=["wire_service", "official_statement"],
                    purpose="Find named sources for entities mentioned in claim",
                    dubious_flag=DubiousFlag.PHANTOM,
                )
            )

        # 2. Exact phrase: find original publication
        if claim_text:
            phrase = claim_text[:100].strip()
            queries.append(
                VerificationQuery(
                    query=f'"{phrase}"',
                    variant_type="exact_phrase",
                    target_sources=["news_outlet"],
                    purpose="Find original publication of this specific claim",
                    dubious_flag=DubiousFlag.PHANTOM,
                )
            )

        # 3. Broader context: find interviews/statements
        if entity_str:
            queries.append(
                VerificationQuery(
                    query=f"{entity_str} transcript interview statement",
                    variant_type="broader_context",
                    target_sources=["official_statement", "wire_service"],
                    purpose="Find primary source interview or statement",
                    dubious_flag=DubiousFlag.PHANTOM,
                )
            )

        return queries

    # ── FOG: Clarity-seeking queries ──────────────────────────────────

    def _generate_fog_queries(
        self,
        fact: dict[str, Any],
        reasoning: Optional[ClassificationReasoning],
    ) -> list[VerificationQuery]:
        """Generate clarity-seeking queries for FOG facts.

        Per CONTEXT.md: Find harder/clearer version of claim.
        Detect vague quantities and temporal references, search for specifics.
        """
        entities = self._extract_entity_names(fact)
        entity_str = " ".join(entities[:3]) if entities else ""
        claim_text = self._extract_claim_text(fact)

        queries: list[VerificationQuery] = []

        # 1. Entity-focused: confirmed/official versions
        if entity_str:
            queries.append(
                VerificationQuery(
                    query=f"{entity_str} confirmed report official",
                    variant_type="entity_focused",
                    target_sources=["wire_service", "official_statement"],
                    purpose="Find confirmed version of vague claim",
                    dubious_flag=DubiousFlag.FOG,
                )
            )

        # 2. Clarity enhancement: target vague language
        if claim_text:
            if _VAGUE_QUANTITY_PATTERNS.search(claim_text):
                queries.append(
                    VerificationQuery(
                        query=f"{entity_str} exact number confirmed figure",
                        variant_type="clarity_enhancement",
                        target_sources=["wire_service"],
                        purpose="Find more precise/quantified version",
                        dubious_flag=DubiousFlag.FOG,
                    )
                )
            elif _VAGUE_TEMPORAL_PATTERNS.search(claim_text):
                queries.append(
                    VerificationQuery(
                        query=f"{entity_str} date confirmed when",
                        variant_type="clarity_enhancement",
                        target_sources=["wire_service"],
                        purpose="Find more precise temporal version",
                        dubious_flag=DubiousFlag.FOG,
                    )
                )
            else:
                phrase = claim_text[:80].strip()
                queries.append(
                    VerificationQuery(
                        query=f'"{phrase}" site:reuters.com OR site:apnews.com',
                        variant_type="clarity_enhancement",
                        target_sources=["wire_service"],
                        purpose="Find wire service version for clarity",
                        dubious_flag=DubiousFlag.FOG,
                    )
                )

        # 3. Exact phrase: trace origin
        if claim_text:
            # Find a distinctive phrase (not just the first N chars)
            phrase = claim_text[:80].strip()
            queries.append(
                VerificationQuery(
                    query=f'"{phrase}"',
                    variant_type="exact_phrase",
                    target_sources=["news_outlet"],
                    purpose="Trace origin of specific claim language",
                    dubious_flag=DubiousFlag.FOG,
                )
            )

        return queries

    # ── ANOMALY: Compound queries ─────────────────────────────────────

    def _generate_anomaly_queries(
        self,
        fact: dict[str, Any],
        reasoning: Optional[ClassificationReasoning],
    ) -> list[VerificationQuery]:
        """Generate compound queries for ANOMALY facts.

        Per CONTEXT.md: Compound approach - temporal + authority + clarity
        together, not sequential. ANOMALY facts have contradictions that
        require multi-dimensional resolution.
        """
        entities = self._extract_entity_names(fact)
        entity_str = " ".join(entities[:3]) if entities else ""
        claim_text = self._extract_claim_text(fact)

        # Extract temporal value if present in fact
        temporal_value = self._extract_temporal_value(fact)

        queries: list[VerificationQuery] = []

        # 1. Temporal context: find dated versions
        if temporal_value and entity_str:
            queries.append(
                VerificationQuery(
                    query=f"{entity_str} {temporal_value} timeline chronology",
                    variant_type="temporal_context",
                    target_sources=["wire_service", "news_outlet"],
                    purpose="Find dated versions to resolve if this is temporal progression",
                    dubious_flag=DubiousFlag.ANOMALY,
                )
            )
        elif entity_str:
            queries.append(
                VerificationQuery(
                    query=f"{entity_str} latest update current status",
                    variant_type="temporal_context",
                    target_sources=["wire_service", "news_outlet"],
                    purpose="Find current status to determine temporal progression",
                    dubious_flag=DubiousFlag.ANOMALY,
                )
            )

        # 2. Authority arbitration: higher-authority sources
        if entity_str:
            queries.append(
                VerificationQuery(
                    query=f"{entity_str} official statement press release .gov",
                    variant_type="authority_arbitration",
                    target_sources=["official_statement", "wire_service"],
                    purpose="Find higher-authority source to settle dispute",
                    dubious_flag=DubiousFlag.ANOMALY,
                )
            )

        # 3. Clarity enhancement: more specific versions
        if claim_text:
            if _VAGUE_QUANTITY_PATTERNS.search(claim_text):
                queries.append(
                    VerificationQuery(
                        query=f"{entity_str} exact number confirmed figure",
                        variant_type="clarity_enhancement",
                        target_sources=["wire_service"],
                        purpose="Find more precise version to resolve ambiguity",
                        dubious_flag=DubiousFlag.ANOMALY,
                    )
                )
            else:
                phrase = claim_text[:80].strip()
                queries.append(
                    VerificationQuery(
                        query=f'"{phrase}" site:reuters.com OR site:apnews.com',
                        variant_type="clarity_enhancement",
                        target_sources=["wire_service"],
                        purpose="Find wire service version to resolve ambiguity",
                        dubious_flag=DubiousFlag.ANOMALY,
                    )
                )

        return queries

    # ── Helpers ────────────────────────────────────────────────────────

    def _extract_entity_names(self, fact: dict[str, Any]) -> list[str]:
        """Extract entity names from fact structure.

        Handles both list-of-dicts and list-of-strings entity formats.
        """
        entities = fact.get("entities", [])
        names: list[str] = []
        for entity in entities:
            if isinstance(entity, dict):
                name = entity.get("canonical_name") or entity.get("text", "")
                if name:
                    names.append(name)
            elif isinstance(entity, str):
                names.append(entity)
        return names

    def _extract_claim_text(self, fact: dict[str, Any]) -> str:
        """Extract claim text from fact structure."""
        claim = fact.get("claim", {})
        if isinstance(claim, dict):
            return claim.get("text", "")
        elif isinstance(claim, str):
            return claim
        return ""

    def _extract_temporal_value(self, fact: dict[str, Any]) -> str:
        """Extract temporal marker value from fact if present."""
        temporal = fact.get("temporal_markers", [])
        if temporal and isinstance(temporal, list) and len(temporal) > 0:
            marker = temporal[0]
            if isinstance(marker, dict):
                return marker.get("value", "")
        return ""
