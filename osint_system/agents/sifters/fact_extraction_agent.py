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
    FACT_EXTRACTION_CHUNK_PROMPT,
)


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
        model_name: Gemini model to use (default: gemini-1.5-flash)
        chunk_size: Max characters per extraction chunk
        min_confidence: Minimum extraction_confidence to keep fact
        gemini_client: Injected Gemini client (or auto-initialized)
    """

    # Chunk size for long documents (leave room for prompt ~4000 tokens)
    DEFAULT_CHUNK_SIZE = 12000
    # Minimum text length for meaningful extraction
    MIN_TEXT_LENGTH = 50

    def __init__(
        self,
        model_name: str = "gemini-1.5-flash",
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        min_confidence: float = 0.0,  # Default: include all per CONTEXT.md
        gemini_client: Optional[Any] = None,
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
        """
        super().__init__(
            name="FactExtractionAgent",
            description="Extracts structured facts from text using LLM",
        )
        self.model_name = model_name
        self.chunk_size = chunk_size
        self.min_confidence = min_confidence
        self._gemini_client = gemini_client

        self.logger.info(
            "FactExtractionAgent initialized",
            model=model_name,
            chunk_size=chunk_size,
            min_confidence=min_confidence,
        )

    @property
    def gemini_client(self):
        """Lazy-load Gemini client on first access."""
        if self._gemini_client is None:
            self._gemini_client = self._get_gemini_client()
        return self._gemini_client

    def _get_gemini_client(self):
        """Initialize Gemini client from settings."""
        try:
            import google.generativeai as genai
            from osint_system.config.settings import settings

            genai.configure(api_key=settings.gemini_api_key)
            return genai
        except ImportError:
            self.logger.warning("google.generativeai not installed")
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
        source_id = content.get("source_id", "unknown")
        source_type = content.get("source_type", "unknown")
        pub_date = content.get("publication_date", "")

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
            return await self._extract_chunked(text, source_id, source_type, pub_date)

        return await self._extract_single(text, source_id, source_type, pub_date)

    async def _extract_single(
        self,
        text: str,
        source_id: str,
        source_type: str,
        pub_date: str,
    ) -> list[dict]:
        """Extract facts from a single text chunk."""
        if not self.gemini_client:
            self.logger.error("Gemini client not available")
            return []

        try:
            model = self.gemini_client.GenerativeModel(
                self.model_name,
                system_instruction=FACT_EXTRACTION_SYSTEM_PROMPT,
            )

            prompt = FACT_EXTRACTION_USER_PROMPT.format(
                source_id=source_id,
                source_type=source_type,
                publication_date=pub_date or "unknown",
                text=text,
            )

            response = model.generate_content(prompt)
            raw_json = self._extract_json_from_response(response.text)

            if not raw_json:
                self.logger.warning("No valid JSON in response")
                return []

            facts = self._parse_and_validate(raw_json, source_id)

            self.logger.info(
                f"Extracted {len(facts)} facts",
                source_id=source_id,
                text_length=len(text),
            )

            return [f.model_dump() for f in facts]

        except Exception as e:
            self.logger.error(f"Extraction failed: {e}", exc_info=True)
            return []

    async def _extract_chunked(
        self,
        text: str,
        source_id: str,
        source_type: str,
        pub_date: str,
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
                # First chunk uses standard prompt
                chunk_facts = await self._extract_single(
                    chunk, source_id, source_type, pub_date
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

        try:
            model = self.gemini_client.GenerativeModel(
                self.model_name,
                system_instruction=FACT_EXTRACTION_SYSTEM_PROMPT,
            )

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

            response = model.generate_content(prompt)
            raw_json = self._extract_json_from_response(response.text)

            if not raw_json:
                return []

            facts = self._parse_and_validate(raw_json, source_id)
            return [f.model_dump() for f in facts]

        except Exception as e:
            self.logger.error(f"Chunk extraction failed: {e}")
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

        claim = Claim(
            text=claim_text,
            assertion_type=claim_data.get("assertion_type", "statement"),
            claim_type=claim_data.get("claim_type", "event"),
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
