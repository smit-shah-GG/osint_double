"""Tests for FactExtractionAgent.

Tests cover:
- Agent initialization and capabilities
- JSON extraction from various response formats
- Raw-to-ExtractedFact conversion
- Empty/short text handling
- Chunk splitting logic
- Entity parsing with various types
- Denial assertion handling
- Mock Gemini response end-to-end

All tests use mocked Gemini responses - no actual API calls.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from osint_system.agents.sifters import FactExtractionAgent, BaseSifter
from osint_system.data_management.schemas import (
    ExtractedFact,
    Claim,
    Entity,
    EntityType,
    QualityMetrics,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def agent():
    """Create agent with no Gemini client for unit testing."""
    return FactExtractionAgent(gemini_client=None)


@pytest.fixture
def mock_gemini_response():
    """Create a mock Gemini response with a single fact."""
    return """[
        {
            "claim": {
                "text": "[E1:Putin] visited [E2:Beijing] in [T1:March 2024]",
                "assertion_type": "statement",
                "claim_type": "event"
            },
            "entities": [
                {"id": "E1", "text": "Putin", "type": "PERSON", "canonical": "Vladimir Putin"},
                {"id": "E2", "text": "Beijing", "type": "LOCATION", "canonical": "Beijing, China"}
            ],
            "temporal": {
                "id": "T1",
                "value": "2024-03",
                "precision": "month",
                "temporal_precision": "explicit"
            },
            "quality": {
                "extraction_confidence": 0.92,
                "claim_clarity": 0.88
            },
            "provenance": {
                "quote": "Russian President Vladimir Putin visited Beijing in March 2024",
                "offsets": {"start": 100, "end": 160},
                "hop_count": 1
            }
        }
    ]"""


@pytest.fixture
def denial_response():
    """Create a mock response with a denial assertion."""
    return """[
        {
            "claim": {
                "text": "[E1:Russia] involvement in [E2:the cyber attack]",
                "assertion_type": "denial",
                "claim_type": "event"
            },
            "entities": [
                {"id": "E1", "text": "Russia", "type": "ORGANIZATION"},
                {"id": "E2", "text": "the cyber attack", "type": "EVENT"}
            ],
            "quality": {
                "extraction_confidence": 0.85,
                "claim_clarity": 0.70
            }
        }
    ]"""


# ============================================================================
# Initialization Tests
# ============================================================================


class TestAgentInitialization:
    """Tests for agent initialization and configuration."""

    def test_initialization_defaults(self, agent):
        """Agent initializes with correct defaults."""
        assert agent.name == "FactExtractionAgent"
        assert agent.model_name == "gemini-1.5-flash"
        assert agent.chunk_size == 12000
        assert agent.min_confidence == 0.0

    def test_initialization_custom_values(self):
        """Agent accepts custom configuration."""
        agent = FactExtractionAgent(
            model_name="gemini-1.5-pro",
            chunk_size=8000,
            min_confidence=0.5,
            gemini_client=None,
        )
        assert agent.model_name == "gemini-1.5-pro"
        assert agent.chunk_size == 8000
        assert agent.min_confidence == 0.5

    def test_inherits_from_base_sifter(self, agent):
        """Agent inherits from BaseSifter."""
        assert isinstance(agent, BaseSifter)

    def test_capabilities(self, agent):
        """Agent reports correct capabilities."""
        caps = agent.get_capabilities()
        assert "fact_extraction" in caps
        assert "entity_extraction" in caps
        assert "confidence_scoring" in caps
        assert "denial_extraction" in caps


# ============================================================================
# JSON Extraction Tests
# ============================================================================


class TestJsonExtraction:
    """Tests for _extract_json_from_response."""

    def test_plain_json_array(self, agent):
        """Extracts plain JSON array."""
        response = '[{"claim": {"text": "Test"}}]'
        result = agent._extract_json_from_response(response)
        assert result is not None
        assert len(result) == 1
        assert result[0]["claim"]["text"] == "Test"

    def test_markdown_json_block(self, agent):
        """Extracts JSON from markdown code block."""
        response = '```json\n[{"claim": {"text": "Test"}}]\n```'
        result = agent._extract_json_from_response(response)
        assert result is not None
        assert len(result) == 1

    def test_markdown_block_no_language(self, agent):
        """Extracts JSON from markdown block without language tag."""
        response = '```\n[{"claim": {"text": "Test"}}]\n```'
        result = agent._extract_json_from_response(response)
        assert result is not None
        assert len(result) == 1

    def test_json_with_surrounding_text(self, agent):
        """Extracts JSON from response with surrounding text."""
        response = 'Here are the facts: [{"claim": {"text": "Test"}}] as requested.'
        result = agent._extract_json_from_response(response)
        assert result is not None
        assert len(result) == 1

    def test_single_object_wrapped_in_array(self, agent):
        """Wraps single object in array."""
        response = '{"claim": {"text": "Test"}}'
        result = agent._extract_json_from_response(response)
        assert result is not None
        assert len(result) == 1

    def test_invalid_json_returns_none(self, agent):
        """Returns None for invalid JSON."""
        response = "This is not JSON at all"
        result = agent._extract_json_from_response(response)
        assert result is None

    def test_empty_array(self, agent):
        """Handles empty array."""
        response = "[]"
        result = agent._extract_json_from_response(response)
        assert result == []


# ============================================================================
# Raw-to-ExtractedFact Conversion Tests
# ============================================================================


class TestRawToExtractedFact:
    """Tests for _raw_to_extracted_fact conversion."""

    def test_basic_conversion(self, agent):
        """Converts basic raw fact to ExtractedFact."""
        raw = {
            "claim": {"text": "[E1:Putin] visited Beijing", "assertion_type": "statement"},
            "entities": [{"id": "E1", "text": "Putin", "type": "PERSON"}],
            "quality": {"extraction_confidence": 0.9, "claim_clarity": 0.85},
        }
        fact = agent._raw_to_extracted_fact(raw, "test-source")

        assert isinstance(fact, ExtractedFact)
        assert fact.claim.text == "[E1:Putin] visited Beijing"
        assert fact.claim.assertion_type == "statement"
        assert len(fact.entities) == 1
        assert fact.entities[0].type == EntityType.PERSON
        assert fact.quality.extraction_confidence == 0.9
        assert fact.quality.claim_clarity == 0.85

    def test_claim_as_string(self, agent):
        """Handles claim as plain string."""
        raw = {
            "claim": "Simple claim text",
            "entities": [],
            "quality": {"extraction_confidence": 0.8, "claim_clarity": 0.8},
        }
        fact = agent._raw_to_extracted_fact(raw, "test")
        assert fact.claim.text == "Simple claim text"
        assert fact.claim.assertion_type == "statement"  # default

    def test_missing_claim_raises(self, agent):
        """Raises ValueError if claim text is missing."""
        raw = {"entities": [], "quality": {}}
        with pytest.raises(ValueError, match="Missing claim text"):
            agent._raw_to_extracted_fact(raw, "test")

    def test_entity_type_normalization(self, agent):
        """Normalizes common entity type variations."""
        raw = {
            "claim": {"text": "Test"},
            "entities": [
                {"id": "E1", "text": "Russia", "type": "ORG"},
                {"id": "E2", "text": "Moscow", "type": "LOC"},
                {"id": "E3", "text": "Putin", "type": "PER"},
                {"id": "E4", "text": "Crimea", "type": "GPE"},
            ],
        }
        fact = agent._raw_to_extracted_fact(raw, "test")

        assert fact.entities[0].type == EntityType.ORGANIZATION
        assert fact.entities[1].type == EntityType.LOCATION
        assert fact.entities[2].type == EntityType.PERSON
        assert fact.entities[3].type == EntityType.LOCATION  # GPE -> LOCATION

    def test_default_quality_metrics(self, agent):
        """Provides default quality metrics if missing."""
        raw = {"claim": {"text": "Test"}, "entities": []}
        fact = agent._raw_to_extracted_fact(raw, "test")

        assert fact.quality is not None
        assert fact.quality.extraction_confidence == 0.8
        assert fact.quality.claim_clarity == 0.8

    def test_temporal_marker_extraction(self, agent):
        """Extracts temporal marker correctly."""
        raw = {
            "claim": {"text": "Test"},
            "entities": [],
            "temporal": {
                "id": "T1",
                "value": "2024-03-15",
                "precision": "day",
                "temporal_precision": "explicit",
            },
        }
        fact = agent._raw_to_extracted_fact(raw, "test")

        assert fact.temporal is not None
        assert fact.temporal.id == "T1"
        assert fact.temporal.value == "2024-03-15"
        assert fact.temporal.precision == "day"
        assert fact.temporal.temporal_precision == "explicit"

    def test_provenance_extraction(self, agent):
        """Extracts provenance correctly."""
        raw = {
            "claim": {"text": "Test claim"},
            "entities": [],
            "provenance": {
                "quote": "The original quote from source",
                "offsets": {"start": 100, "end": 130},
                "hop_count": 2,
                "attribution_phrase": "according to officials",
            },
        }
        fact = agent._raw_to_extracted_fact(raw, "test-source")

        assert fact.provenance is not None
        assert fact.provenance.source_id == "test-source"
        assert fact.provenance.quote == "The original quote from source"
        assert fact.provenance.hop_count == 2
        assert fact.provenance.attribution_phrase == "according to officials"

    def test_denial_assertion_type(self, agent):
        """Handles denial assertion type correctly."""
        raw = {
            "claim": {
                "text": "[E1:Russia] involvement in [E2:the incident]",
                "assertion_type": "denial",
                "claim_type": "event",
            },
            "entities": [
                {"id": "E1", "text": "Russia", "type": "ORGANIZATION"},
                {"id": "E2", "text": "the incident", "type": "EVENT"},
            ],
        }
        fact = agent._raw_to_extracted_fact(raw, "test")

        assert fact.claim.assertion_type == "denial"
        assert "[E1:Russia]" in fact.claim.text


# ============================================================================
# Chunking Tests
# ============================================================================


class TestChunking:
    """Tests for _split_into_chunks."""

    def test_short_text_no_split(self, agent):
        """Short text returns single chunk."""
        text = "This is a short text."
        chunks = agent._split_into_chunks(text)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_respects_chunk_size_limit(self, agent):
        """No chunk exceeds chunk_size."""
        # Create text with ~34000 chars (should split into 3 chunks)
        long_text = ("This is a paragraph." + " More text here." * 20 + "\n\n") * 100
        chunks = agent._split_into_chunks(long_text)

        for chunk in chunks:
            assert len(chunk) <= agent.chunk_size

    def test_splits_on_paragraph_boundaries(self, agent):
        """Prefers paragraph boundaries for splits."""
        # Create two paragraphs that together exceed chunk size
        agent.chunk_size = 50
        text = "First paragraph content here.\n\nSecond paragraph content here."
        chunks = agent._split_into_chunks(text)

        # Should split between paragraphs (61 chars > 50 chunk_size)
        assert len(chunks) == 2
        assert "First" in chunks[0]
        assert "Second" in chunks[1]

    def test_handles_large_paragraph(self, agent):
        """Handles paragraphs larger than chunk_size by splitting sentences."""
        agent.chunk_size = 100
        # Single paragraph with multiple sentences
        text = "First sentence here. Second sentence here. Third sentence here. Fourth sentence here."
        chunks = agent._split_into_chunks(text)

        assert len(chunks) >= 1
        for chunk in chunks:
            assert len(chunk) <= agent.chunk_size


# ============================================================================
# Empty/Malformed Input Tests
# ============================================================================


class TestInputValidation:
    """Tests for handling empty/malformed input."""

    @pytest.mark.asyncio
    async def test_empty_text_returns_empty_list(self, agent):
        """Empty text returns empty list."""
        result = await agent.sift({"text": "", "source_id": "test"})
        assert result == []

    @pytest.mark.asyncio
    async def test_short_text_returns_empty_list(self, agent):
        """Text below MIN_TEXT_LENGTH returns empty list."""
        result = await agent.sift({"text": "Too short", "source_id": "test"})
        assert result == []

    @pytest.mark.asyncio
    async def test_missing_text_returns_empty_list(self, agent):
        """Missing text key returns empty list."""
        result = await agent.sift({"source_id": "test"})
        assert result == []

    @pytest.mark.asyncio
    async def test_none_content_returns_empty_list(self, agent):
        """None content returns empty list."""
        result = await agent.sift({})
        assert result == []


# ============================================================================
# Entity Parsing Tests
# ============================================================================


class TestEntityParsing:
    """Tests for _parse_entities."""

    def test_parses_valid_entities(self, agent):
        """Parses list of valid entities."""
        raw = [
            {"id": "E1", "text": "Putin", "type": "PERSON", "canonical": "Vladimir Putin"},
            {"id": "E2", "text": "Moscow", "type": "LOCATION"},
        ]
        entities = agent._parse_entities(raw)

        assert len(entities) == 2
        assert entities[0].id == "E1"
        assert entities[0].canonical == "Vladimir Putin"
        assert entities[1].type == EntityType.LOCATION

    def test_handles_unknown_entity_type(self, agent):
        """Falls back to PERSON for unknown entity types."""
        raw = [{"id": "E1", "text": "Something", "type": "UNKNOWN_TYPE"}]
        entities = agent._parse_entities(raw)

        assert len(entities) == 1
        assert entities[0].type == EntityType.PERSON  # fallback

    def test_skips_non_dict_entities(self, agent):
        """Skips non-dict items in entity list."""
        raw = [
            {"id": "E1", "text": "Valid", "type": "PERSON"},
            "not a dict",
            None,
            {"id": "E2", "text": "Also valid", "type": "LOCATION"},
        ]
        entities = agent._parse_entities(raw)
        assert len(entities) == 2

    def test_handles_missing_fields(self, agent):
        """Handles entities with missing optional fields."""
        raw = [{"id": "E1", "text": "Minimal", "type": "PERSON"}]
        entities = agent._parse_entities(raw)

        assert len(entities) == 1
        assert entities[0].canonical is None
        assert entities[0].cluster_id is None


# ============================================================================
# Confidence Filtering Tests
# ============================================================================


class TestConfidenceFiltering:
    """Tests for minimum confidence threshold filtering."""

    def test_filters_below_threshold(self):
        """Facts below min_confidence are filtered."""
        agent = FactExtractionAgent(min_confidence=0.8, gemini_client=None)

        raw_facts = [
            {
                "claim": {"text": "High confidence fact"},
                "entities": [],
                "quality": {"extraction_confidence": 0.9, "claim_clarity": 0.8},
            },
            {
                "claim": {"text": "Low confidence fact"},
                "entities": [],
                "quality": {"extraction_confidence": 0.5, "claim_clarity": 0.8},
            },
        ]
        validated = agent._parse_and_validate(raw_facts, "test")

        assert len(validated) == 1
        assert "High confidence" in validated[0].claim.text

    def test_includes_at_threshold(self):
        """Facts at exactly min_confidence are included."""
        agent = FactExtractionAgent(min_confidence=0.8, gemini_client=None)

        raw_facts = [
            {
                "claim": {"text": "Exactly at threshold"},
                "entities": [],
                "quality": {"extraction_confidence": 0.8, "claim_clarity": 0.8},
            }
        ]
        validated = agent._parse_and_validate(raw_facts, "test")
        assert len(validated) == 1


# ============================================================================
# Mock Gemini Integration Tests
# ============================================================================


class TestMockGeminiIntegration:
    """Tests with mocked Gemini responses."""

    @pytest.mark.asyncio
    async def test_extraction_with_mock_response(self, mock_gemini_response):
        """Full extraction flow with mocked Gemini."""
        # Create mock Gemini client
        mock_model = MagicMock()
        mock_model.generate_content.return_value = MagicMock(text=mock_gemini_response)

        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        agent = FactExtractionAgent(gemini_client=mock_genai)

        content = {
            "text": "Russian President Vladimir Putin visited Beijing in March 2024. " * 5,
            "source_id": "test-article-001",
            "source_type": "news_outlet",
            "publication_date": "2024-03-15",
        }

        results = await agent.sift(content)

        assert len(results) == 1
        fact = results[0]

        # Verify fact structure
        assert "[E1:Putin]" in fact["claim"]["text"]
        assert fact["claim"]["assertion_type"] == "statement"
        assert len(fact["entities"]) == 2
        assert fact["quality"]["extraction_confidence"] == 0.92
        assert fact["quality"]["claim_clarity"] == 0.88

    @pytest.mark.asyncio
    async def test_denial_extraction_with_mock(self, denial_response):
        """Denial assertion extraction with mocked Gemini."""
        mock_model = MagicMock()
        mock_model.generate_content.return_value = MagicMock(text=denial_response)

        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        agent = FactExtractionAgent(gemini_client=mock_genai)

        content = {
            "text": "Russia denied any involvement in the cyber attack that targeted the government. " * 5,
            "source_id": "test-article-002",
        }

        results = await agent.sift(content)

        assert len(results) == 1
        fact = results[0]

        # Verify denial handling
        assert fact["claim"]["assertion_type"] == "denial"
        assert "[E1:Russia]" in fact["claim"]["text"]

    @pytest.mark.asyncio
    async def test_gemini_error_returns_empty(self):
        """Gemini error returns empty list, doesn't raise."""
        mock_model = MagicMock()
        mock_model.generate_content.side_effect = Exception("API Error")

        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        agent = FactExtractionAgent(gemini_client=mock_genai)

        content = {
            "text": "Some text that would normally be extracted. " * 5,
            "source_id": "test",
        }

        results = await agent.sift(content)
        assert results == []

    @pytest.mark.asyncio
    async def test_process_method_wraps_sift(self, mock_gemini_response):
        """BaseSifter.process() correctly wraps sift()."""
        mock_model = MagicMock()
        mock_model.generate_content.return_value = MagicMock(text=mock_gemini_response)

        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        agent = FactExtractionAgent(gemini_client=mock_genai)

        input_data = {
            "content": {
                "text": "Putin visited Beijing in March. " * 10,
                "source_id": "test",
            }
        }

        result = await agent.process(input_data)

        assert result["success"] is True
        assert result["count"] == 1
        assert len(result["results"]) == 1


# ============================================================================
# Content Hash Tests
# ============================================================================


class TestContentHash:
    """Tests for content hash auto-computation."""

    def test_content_hash_computed(self, agent):
        """Content hash is auto-computed from claim text."""
        raw = {
            "claim": {"text": "[E1:Putin] visited [E2:Beijing]"},
            "entities": [],
        }
        fact = agent._raw_to_extracted_fact(raw, "test")

        # ExtractedFact should have content_hash computed
        assert fact.content_hash is not None
        assert len(fact.content_hash) == 64  # SHA256 hex length

    def test_same_claim_same_hash(self, agent):
        """Same claim text produces same hash."""
        raw1 = {"claim": {"text": "Test claim"}, "entities": []}
        raw2 = {"claim": {"text": "Test claim"}, "entities": []}

        fact1 = agent._raw_to_extracted_fact(raw1, "source1")
        fact2 = agent._raw_to_extracted_fact(raw2, "source2")

        assert fact1.content_hash == fact2.content_hash

    def test_different_claim_different_hash(self, agent):
        """Different claim text produces different hash."""
        raw1 = {"claim": {"text": "First claim"}, "entities": []}
        raw2 = {"claim": {"text": "Second claim"}, "entities": []}

        fact1 = agent._raw_to_extracted_fact(raw1, "test")
        fact2 = agent._raw_to_extracted_fact(raw2, "test")

        assert fact1.content_hash != fact2.content_hash
