"""Fact extraction agent using Gemini for structured fact identification.

This agent implements the core fact extraction pipeline per Phase 6 CONTEXT.md:
- Extracts discrete, verifiable facts from raw text
- Produces ExtractedFact objects with entity markers
- Handles denials, quoted speech, implicit facts
- Tracks separate extraction_confidence and claim_clarity

Token optimization: Uses chunk-based processing for long documents with
entity continuity between chunks.
"""

import json
import re
from typing import Optional, Any
from datetime import datetime

from osint_system.agents.sifters.base_sifter import BaseSifter
from osint_system.data_management.schemas import (
    ExtractedFact,
    Claim,
    Entity,
    Provenance,
    QualityMetrics,
    ExtractionMetadata,
    TemporalMarker,
    SourceType,
    EntityType,
)
from osint_system.config.prompts.fact_extraction_prompts import (
    FACT_EXTRACTION_SYSTEM_PROMPT,
    FACT_EXTRACTION_USER_PROMPT,
    FACT_EXTRACTION_USER_PROMPT_V2,
    FACT_EXTRACTION_CHUNK_PROMPT,
)


# Normalize LLM-emitted claim_type values to valid schema values.
# Models in the fallback chain (DeepSeek, Hermes, Nemotron) emit non-standard
# values that Pydantic would either silently default or reject.
_CLAIM_TYPE_NORMALIZE: dict[str, str] = {
    "statement": "statement",
    "action": "event",
    "fact": "statement",
    "opinion": "statement",
    "assertion": "statement",
    "observation": "state",
    "description": "state",
    "claim": "event",
    "announcement": "event",
    "plan": "planned",
    "forecast": "prediction",
    "analysis": "state",
}
_VALID_CLAIM_TYPES = {"event", "state", "relationship", "prediction", "planned", "statement"}

# Normalize LLM-emitted assertion_type values to valid schema values.
# LLMs also return non-standard assertion_type values that must be mapped
# to the Literal["statement", "denial", "claim", "prediction", "quote"].
_ASSERTION_TYPE_NORMALIZE: dict[str, str] = {
    "statement": "statement",
    "denial": "denial",
    "claim": "claim",
    "prediction": "prediction",
    "quote": "quote",
    "fact": "statement",
    "opinion": "statement",
    "analysis": "statement",
    "assertion": "claim",
    "observation": "statement",
    "report": "statement",
    "allegation": "claim",
}
_VALID_ASSERTION_TYPES = {"statement", "denial", "claim", "prediction", "quote"}


class FactExtractionAgent(BaseSifter):
    """
    Extracts structured facts from raw text using Gemini.

    Produces ExtractedFact objects conforming to Phase 6 schema with:
    - Entity-marked claim text [E1:Putin] visited [E2:Beijing]
    - Separate extraction_confidence and claim_clarity
    - Full provenance with attribution chains
    - Relationship hints between facts

    The agent handles long documents via chunking with entity ID continuity
    between chunks. It gracefully handles empty/malformed input.

    Attributes:
        model_name: Gemini model to use (default: gemini-3-pro-preview)
        chunk_size: Max characters per extraction chunk
        min_confidence: Minimum extraction_confidence to keep fact
        gemini_client: Injected Gemini client (or auto-initialized)
    """

    # Chunk size for long documents (~10K tokens, well within Gemini's context window)
    DEFAULT_CHUNK_SIZE = 40000
    # Minimum text length for meaningful extraction
    MIN_TEXT_LENGTH = 50

    def __init__(
        self,
        model_name: str = "gemini-3-flash",
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        min_confidence: float = 0.0,  # Default: include all per CONTEXT.md
        gemini_client: Optional[Any] = None,
        objective: str = "",
    ):
        """
        Initialize FactExtractionAgent.

        Args:
            model_name: Gemini model identifier for extraction.
            chunk_size: Maximum characters per extraction chunk.
            min_confidence: Minimum extraction_confidence threshold (0.0-1.0).
                Facts below this threshold are filtered. Default 0.0 includes all.
            gemini_client: Optional pre-configured Gemini client.
                If None, auto-initializes from settings.
            objective: Investigation objective for relevance filtering.
                When non-empty, uses objective-aware prompt (V2) to filter
                irrelevant facts at extraction time.
        """
        super().__init__(
            name="FactExtractionAgent",
            description="Extracts structured facts from text using LLM",
        )
        self.model_name = model_name
        self.chunk_size = chunk_size
        self.min_confidence = min_confidence
        self._gemini_client = gemini_client
        self.objective = objective

        self.logger.info(
            "FactExtractionAgent initialized",
            model=model_name,
            chunk_size=chunk_size,
            min_confidence=min_confidence,
            objective=objective[:80] if objective else "",
        )

    @property
    def gemini_client(self):
        """Lazy-load Gemini client on first access."""
        if self._gemini_client is None:
            self._gemini_client = self._get_gemini_client()
        return self._gemini_client

    def _get_gemini_client(self):
        """Initialize LLM client — OpenRouter if configured, else direct Gemini."""
        import os

        openrouter_key = os.environ.get("OPENROUTER_API_KEY")
        if openrouter_key:
            try:
                from osint_system.llm.openrouter_client import OpenRouterClient
                self.logger.info("Using OpenRouter backend")
                return OpenRouterClient(api_key=openrouter_key)
            except Exception as e:
                self.logger.warning(f"OpenRouter init failed, falling back to Gemini: {e}")

        try:
            from google import genai
            from osint_system.config.settings import settings

            return genai.Client(api_key=settings.gemini_api_key)
        except ImportError:
            self.logger.warning("google-genai not installed")
            return None
        except Exception as e:
            self.logger.warning(f"Failed to initialize Gemini: {e}")
            return None

    async def sift(self, content: dict) -> list[dict]:
        """
        Extract facts from content.

        This is the main entry point called by BaseSifter.process().

        Args:
            content: Dict with:
                - text (str): Raw text to extract from
                - source_id (str): Source document identifier
                - source_type (str, optional): news/social/document
                - publication_date (str, optional): ISO date
                - metadata (dict, optional): Additional context

        Returns:
            List of ExtractedFact objects as dicts.
            Empty list if text too short or extraction fails.
        """
        text = content.get("text", "")
        source_id = content.get("source_id") or "unknown"
        source_type = content.get("source_type", "unknown")
        pub_date = content.get("publication_date", "")
        # Prefer per-request objective from content dict, fall back to instance default
        objective = content.get("objective", self.objective) or ""

        # Validate input
        if not text or len(text.strip()) < self.MIN_TEXT_LENGTH:
            self.logger.warning(
                "Text too short for extraction",
                length=len(text) if text else 0,
                min_required=self.MIN_TEXT_LENGTH,
            )
            return []

        # Handle long documents with chunking
        if len(text) > self.chunk_size:
            return await self._extract_chunked(text, source_id, source_type, pub_date, objective=objective)

        return await self._extract_single(text, source_id, source_type, pub_date, objective=objective)

    MAX_RETRIES = 2

    async def _extract_single(
        self,
        text: str,
        source_id: str,
        source_type: str,
        pub_date: str,
        objective: str = "",
    ) -> list[dict]:
        """Extract facts from a single text chunk with retry on failure."""
        if not self.gemini_client:
            self.logger.error("Gemini client not available")
            return []

        if objective:
            prompt = FACT_EXTRACTION_USER_PROMPT_V2.format(
                objective=objective,
                source_id=source_id,
                source_type=source_type,
                publication_date=pub_date or "unknown",
                text=text,
            )
        else:
            prompt = FACT_EXTRACTION_USER_PROMPT.format(
                source_id=source_id,
                source_type=source_type,
                publication_date=pub_date or "unknown",
                text=text,
            )

        for attempt in range(1, self.MAX_RETRIES + 2):  # 1 initial + MAX_RETRIES
            try:
                response = await self.gemini_client.aio.models.generate_content(
                    model=self.model_name,
                    contents=[prompt],
                    config={
                        "system_instruction": FACT_EXTRACTION_SYSTEM_PROMPT,
                        "temperature": 0.2,
                        "max_output_tokens": 16384,
                        "response_format": "json",
                    },
                )
                raw_json = self._extract_json_from_response(response.text)

                if not raw_json:
                    if attempt <= self.MAX_RETRIES:
                        self.logger.warning(
                            f"No valid JSON (attempt {attempt}/{self.MAX_RETRIES + 1}), retrying",
                            source_id=source_id[:60],
                        )
                        continue
                    self.logger.warning("No valid JSON after retries")
                    return []

                facts = self._parse_and_validate(raw_json, source_id)

                self.logger.info(
                    f"Extracted {len(facts)} facts",
                    source_id=source_id,
                    text_length=len(text),
                    attempt=attempt if attempt > 1 else None,
                )

                return [f.model_dump() for f in facts]

            except Exception as e:
                if attempt <= self.MAX_RETRIES:
                    self.logger.warning(
                        f"Extraction attempt {attempt} failed, retrying: {e}",
                        source_id=source_id[:60],
                    )
                    continue
                self.logger.error(f"Extraction failed after {attempt} attempts: {e}")
                return []

        return []

    async def _extract_chunked(
        self,
        text: str,
        source_id: str,
        source_type: str,
        pub_date: str,
        objective: str = "",
    ) -> list[dict]:
        """Extract from long text using chunking with entity continuity."""
        chunks = self._split_into_chunks(text)
        all_facts: list[dict] = []
        previous_entities: list[dict] = []
        next_entity_id = 1

        self.logger.info(
            f"Processing {len(chunks)} chunks for {source_id}",
            total_length=len(text),
        )

        for i, chunk in enumerate(chunks):
            if i == 0:
                # First chunk uses standard prompt (with objective if available)
                chunk_facts = await self._extract_single(
                    chunk, source_id, source_type, pub_date, objective=objective
                )
            else:
                # Subsequent chunks maintain entity continuity
                chunk_facts = await self._extract_continuation(
                    chunk,
                    source_id,
                    previous_entities,
                    len(all_facts),
                    i + 1,
                    len(chunks),
                    next_entity_id,
                )

            all_facts.extend(chunk_facts)

            # Update entity list and ID counter for continuity
            for fact in chunk_facts:
                if isinstance(fact, dict) and "entities" in fact:
                    for ent in fact["entities"]:
                        previous_entities.append(ent)
                        # Track highest entity ID
                        ent_id = ent.get("id", "E0")
                        if ent_id.startswith("E"):
                            try:
                                id_num = int(ent_id[1:])
                                next_entity_id = max(next_entity_id, id_num + 1)
                            except ValueError:
                                pass

        return all_facts

    async def _extract_continuation(
        self,
        text: str,
        source_id: str,
        previous_entities: list[dict],
        previous_count: int,
        chunk_num: int,
        total_chunks: int,
        next_entity_id: int,
    ) -> list[dict]:
        """Extract from continuation chunk with entity context."""
        if not self.gemini_client:
            return []

        # Format previous entities for context (last 10)
        entity_summary = ", ".join(
            [
                f"{e.get('id')}: {e.get('canonical', e.get('text'))}"
                for e in previous_entities[-10:]
            ]
        )

        prompt = FACT_EXTRACTION_CHUNK_PROMPT.format(
            previous_entities=entity_summary or "none",
            previous_count=previous_count,
            chunk_num=chunk_num,
            total_chunks=total_chunks,
            next_entity_id=next_entity_id,
            text=text,
        )

        for attempt in range(1, self.MAX_RETRIES + 2):
            try:
                response = await self.gemini_client.aio.models.generate_content(
                    model=self.model_name,
                    contents=[prompt],
                    config={
                        "system_instruction": FACT_EXTRACTION_SYSTEM_PROMPT,
                        "temperature": 0.2,
                        "max_output_tokens": 16384,
                        "response_format": "json",
                    },
                )
                raw_json = self._extract_json_from_response(response.text)

                if not raw_json:
                    if attempt <= self.MAX_RETRIES:
                        self.logger.warning(
                            f"Chunk {chunk_num}: no valid JSON (attempt {attempt}), retrying",
                        )
                        continue
                    return []

                facts = self._parse_and_validate(raw_json, source_id)
                return [f.model_dump() for f in facts]

            except Exception as e:
                if attempt <= self.MAX_RETRIES:
                    self.logger.warning(f"Chunk {chunk_num} attempt {attempt} failed, retrying: {e}")
                    continue
                self.logger.error(f"Chunk extraction failed after retries: {e}")
                return []

        return []

    def _split_into_chunks(self, text: str) -> list[str]:
        """
        Split text into chunks, preferring paragraph boundaries.

        Attempts to split at paragraph boundaries (\n\n) to preserve
        semantic coherence. Falls back to sentence boundaries for
        paragraphs exceeding chunk_size.

        Args:
            text: Full text to split.

        Returns:
            List of text chunks, each <= chunk_size.
        """
        if len(text) <= self.chunk_size:
            return [text]

        chunks: list[str] = []
        paragraphs = text.split("\n\n")
        current_chunk = ""

        for para in paragraphs:
            # Can we add this paragraph to current chunk?
            if len(current_chunk) + len(para) + 2 <= self.chunk_size:
                current_chunk += para + "\n\n"
            else:
                # Save current chunk if non-empty
                if current_chunk.strip():
                    chunks.append(current_chunk.strip())

                # Handle paragraphs larger than chunk_size
                if len(para) > self.chunk_size:
                    # Split by sentences
                    sentences = re.split(r"(?<=[.!?])\s+", para)
                    current_chunk = ""
                    for sent in sentences:
                        if len(current_chunk) + len(sent) + 1 <= self.chunk_size:
                            current_chunk += sent + " "
                        else:
                            if current_chunk.strip():
                                chunks.append(current_chunk.strip())
                            # Handle sentences longer than chunk_size (rare)
                            if len(sent) > self.chunk_size:
                                # Force split at chunk_size
                                for j in range(0, len(sent), self.chunk_size):
                                    chunk_part = sent[j : j + self.chunk_size]
                                    if chunk_part.strip():
                                        chunks.append(chunk_part.strip())
                                current_chunk = ""
                            else:
                                current_chunk = sent + " "
                else:
                    current_chunk = para + "\n\n"

        # Don't forget the last chunk
        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        return chunks

    def _extract_json_from_response(self, response_text: str) -> Optional[list]:
        """
        Extract JSON array from LLM response, handling markdown blocks.

        The LLM may return JSON in various formats:
        - Raw JSON array
        - JSON in markdown code block (```json ... ```)
        - JSON with surrounding text

        Args:
            response_text: Raw response text from LLM.

        Returns:
            Parsed JSON list, or None if parsing fails.
        """
        text = response_text.strip()

        # Strip <think>...</think> reasoning blocks (Qwen, DeepSeek R1)
        text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
        # Also handle unclosed think tags (truncated reasoning)
        text = re.sub(r"<think>[\s\S]*$", "", text).strip()

        # Strip \n literal escape sequences that some models produce
        text = text.replace("\\n", "\n")

        # Try to find JSON in markdown code block
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if json_match:
            text = json_match.group(1).strip()

        # Try to find array directly
        array_match = re.search(r"\[[\s\S]*\]", text)
        if array_match:
            text = array_match.group(0)

        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
            elif isinstance(parsed, dict):
                # Sometimes LLM wraps in object
                return [parsed]
            return None
        except json.JSONDecodeError as e:
            self.logger.warning(f"Failed to parse JSON: {e}")

            # Attempt lightweight repair for common Flash JSON errors
            repaired = self._repair_json(text)
            if repaired is not None:
                self.logger.info(f"JSON repair recovered {len(repaired)} facts")
                return repaired
            return None

    @staticmethod
    def _repair_json(text: str) -> Optional[list]:
        """Attempt to repair malformed JSON from LLM responses.

        Handles:
        - Truncated responses: find last complete object in array
        - Missing commas between objects: }{ → },{
        - Trailing commas before ] or }

        Returns parsed list on success, None on failure.
        """
        # Fix missing commas between objects: }{ or }\n{
        repaired = re.sub(r"\}\s*\{", "},{", text)
        # Fix trailing commas before closing brackets
        repaired = re.sub(r",\s*\]", "]", repaired)
        repaired = re.sub(r",\s*\}", "}", repaired)

        # Try parsing the repaired text
        try:
            parsed = json.loads(repaired)
            if isinstance(parsed, list):
                return parsed
            elif isinstance(parsed, dict):
                return [parsed]
        except json.JSONDecodeError:
            pass

        # Truncated response: find last complete object and close the array
        last_complete = repaired.rfind("}")
        if last_complete > 0:
            truncated = repaired[:last_complete + 1]
            # Ensure it starts with [
            bracket_start = truncated.find("[")
            if bracket_start >= 0:
                truncated = truncated[bracket_start:] + "]"
                try:
                    parsed = json.loads(truncated)
                    if isinstance(parsed, list):
                        return parsed
                except json.JSONDecodeError:
                    pass

        return None

    def _parse_and_validate(
        self,
        raw_facts: list,
        source_id: str,
    ) -> list[ExtractedFact]:
        """
        Parse raw JSON and validate into ExtractedFact objects.

        Applies schema validation and minimum confidence filtering.
        Invalid facts are logged and skipped, not raised as errors.

        Args:
            raw_facts: List of raw fact dicts from LLM.
            source_id: Source document ID for provenance.

        Returns:
            List of validated ExtractedFact objects.
        """
        validated: list[ExtractedFact] = []

        for i, raw in enumerate(raw_facts):
            try:
                fact = self._raw_to_extracted_fact(raw, source_id)

                # Apply minimum confidence filter
                if fact.quality and fact.quality.extraction_confidence < self.min_confidence:
                    self.logger.debug(
                        f"Fact {i} below confidence threshold",
                        confidence=fact.quality.extraction_confidence,
                        threshold=self.min_confidence,
                    )
                    continue

                validated.append(fact)

            except Exception as e:
                self.logger.debug(
                    f"Fact validation failed: {e}",
                    fact_index=i,
                    raw_keys=list(raw.keys()) if isinstance(raw, dict) else None,
                )
                continue

        return validated

    def _raw_to_extracted_fact(self, raw: dict, source_id: str) -> ExtractedFact:
        """
        Convert raw LLM output to ExtractedFact.

        Handles various LLM output formats and normalizes to schema.

        Args:
            raw: Raw fact dict from LLM.
            source_id: Source document ID.

        Returns:
            Validated ExtractedFact object.

        Raises:
            ValueError: If claim text is missing.
        """
        # Extract claim
        claim_data = raw.get("claim", {})
        if isinstance(claim_data, str):
            claim_data = {"text": claim_data}

        claim_text = claim_data.get("text", raw.get("text", ""))
        if not claim_text:
            raise ValueError("Missing claim text")

        # Normalize claim_type — LLMs in the fallback chain emit non-standard values
        raw_claim_type = claim_data.get("claim_type", "event")
        if isinstance(raw_claim_type, str):
            normalized_claim_type = _CLAIM_TYPE_NORMALIZE.get(raw_claim_type.lower(), raw_claim_type.lower())
            if normalized_claim_type not in _VALID_CLAIM_TYPES:
                normalized_claim_type = "event"  # Final fallback for completely unknown values
        else:
            normalized_claim_type = "event"

        # Normalize assertion_type — same issue with non-standard LLM values
        raw_assertion_type = claim_data.get("assertion_type", "statement")
        if isinstance(raw_assertion_type, str):
            normalized_assertion_type = _ASSERTION_TYPE_NORMALIZE.get(raw_assertion_type.lower(), raw_assertion_type.lower())
            if normalized_assertion_type not in _VALID_ASSERTION_TYPES:
                normalized_assertion_type = "statement"  # Final fallback
        else:
            normalized_assertion_type = "statement"

        claim = Claim(
            text=claim_text,
            assertion_type=normalized_assertion_type,
            claim_type=normalized_claim_type,
        )

        # Extract entities
        entities = self._parse_entities(raw.get("entities", []))

        # Extract quality metrics
        quality = self._parse_quality(raw.get("quality", {}))

        # Extract provenance
        provenance = self._parse_provenance(raw.get("provenance", {}), source_id, claim.text)

        # Extract temporal
        temporal = self._parse_temporal(raw.get("temporal"))

        # Extract metadata
        extraction = ExtractionMetadata(
            model_version=self.model_name,
            extraction_type=raw.get("extraction", {}).get("extraction_type", "explicit"),
        )

        return ExtractedFact(
            claim=claim,
            entities=entities,
            quality=quality,
            provenance=provenance,
            temporal=temporal,
            extraction=extraction,
        )

    def _parse_entities(self, raw_entities: list) -> list[Entity]:
        """Parse and validate entity list."""
        entities: list[Entity] = []

        for i, ent in enumerate(raw_entities):
            if not isinstance(ent, dict):
                continue

            try:
                entity_type_str = ent.get("type", "PERSON")
                if isinstance(entity_type_str, str):
                    # Normalize to uppercase for enum matching
                    entity_type_str = entity_type_str.upper()
                    # Handle common variations
                    type_mapping = {
                        "ORG": "ORGANIZATION",
                        "LOC": "LOCATION",
                        "PER": "PERSON",
                        "GPE": "LOCATION",  # Geo-political entity
                    }
                    entity_type_str = type_mapping.get(entity_type_str, entity_type_str)
                    try:
                        entity_type = EntityType(entity_type_str)
                    except ValueError:
                        entity_type = EntityType.PERSON  # Default fallback
                else:
                    entity_type = EntityType.PERSON

                entities.append(
                    Entity(
                        id=ent.get("id", f"E{i+1}"),
                        text=ent.get("text", ""),
                        type=entity_type,
                        canonical=ent.get("canonical"),
                        cluster_id=ent.get("cluster_id"),
                    )
                )
            except Exception as e:
                self.logger.debug(f"Entity parse failed: {e}", entity=ent)
                continue

        return entities

    def _parse_quality(self, raw_quality: dict) -> Optional[QualityMetrics]:
        """Parse quality metrics with defaults."""
        if not raw_quality:
            # Provide sensible defaults if LLM didn't output quality
            return QualityMetrics(
                extraction_confidence=0.8,
                claim_clarity=0.8,
            )

        return QualityMetrics(
            extraction_confidence=float(raw_quality.get("extraction_confidence", 0.8)),
            claim_clarity=float(raw_quality.get("claim_clarity", 0.8)),
        )

    def _parse_provenance(
        self, raw_prov: dict, source_id: str, claim_text: str
    ) -> Optional[Provenance]:
        """Parse provenance with source_id fallback."""
        quote = raw_prov.get("quote", claim_text)
        offsets = raw_prov.get("offsets", {"start": 0, "end": len(quote)})

        # Parse source_type
        source_type_str = raw_prov.get("source_type", "unknown")
        if isinstance(source_type_str, str):
            source_type_str = source_type_str.lower()
            try:
                source_type = SourceType(source_type_str)
            except ValueError:
                source_type = SourceType.UNKNOWN
        else:
            source_type = SourceType.UNKNOWN

        return Provenance(
            source_id=source_id,
            quote=quote,
            offsets=offsets,
            hop_count=raw_prov.get("hop_count", 1),
            source_type=source_type,
            attribution_phrase=raw_prov.get("attribution_phrase"),
        )

    def _parse_temporal(self, raw_temporal: Optional[dict]) -> Optional[TemporalMarker]:
        """Parse temporal marker if present."""
        if not raw_temporal:
            return None

        value = raw_temporal.get("value")
        if not value:
            return None

        return TemporalMarker(
            id=raw_temporal.get("id", "T1"),
            value=value,
            precision=raw_temporal.get("precision", "day"),
            temporal_precision=raw_temporal.get("temporal_precision", "unknown"),
        )

    def get_capabilities(self) -> list[str]:
        """Return fact extraction capabilities."""
        return [
            "fact_extraction",
            "entity_extraction",
            "claim_identification",
            "confidence_scoring",
            "provenance_tracking",
            "denial_extraction",
            "quoted_speech_extraction",
        ]
