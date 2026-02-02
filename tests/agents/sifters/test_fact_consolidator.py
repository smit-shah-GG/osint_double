"""Comprehensive tests for FactConsolidator.

Tests cover:
1. Hash deduplication (exact match)
2. Variant linking for same-hash facts
3. Different hashes remain separate
4. Empty input handling
5. Batch consolidation
6. Store integration
7. Confidence filtering
8. Provenance merging
"""

import asyncio
import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from osint_system.agents.sifters.fact_consolidator import (
    ConsolidationStats,
    FactConsolidator,
)
from osint_system.data_management.schemas import ExtractedFact, Claim


class TestFactConsolidatorHashDeduplication:
    """Tests for hash-based deduplication."""

    @pytest.fixture
    def consolidator(self):
        """Create a fresh consolidator for each test."""
        return FactConsolidator()

    @pytest.mark.asyncio
    async def test_exact_duplicate_detection(self, consolidator):
        """Facts with identical claim text produce same hash and dedupe."""
        facts = [
            {"fact_id": "f-001", "claim": {"text": "Putin visited Beijing"}},
            {"fact_id": "f-002", "claim": {"text": "Putin visited Beijing"}},
        ]
        result = await consolidator.sift({"facts": facts, "investigation_id": "inv-001"})

        assert len(result) == 1
        # First fact should be canonical with second as variant
        canonical = result[0]
        assert canonical["fact_id"] == "f-001"
        assert "f-002" in canonical["variants"]

    @pytest.mark.asyncio
    async def test_different_claims_no_dedup(self, consolidator):
        """Facts with different claims remain separate."""
        facts = [
            {"fact_id": "f-001", "claim": {"text": "Putin visited Beijing"}},
            {"fact_id": "f-002", "claim": {"text": "Xi visited Moscow"}},
        ]
        result = await consolidator.sift({"facts": facts, "investigation_id": "inv-001"})

        assert len(result) == 2
        fact_ids = {f["fact_id"] for f in result}
        assert fact_ids == {"f-001", "f-002"}

    @pytest.mark.asyncio
    async def test_provided_hash_used(self, consolidator):
        """Pre-computed content_hash is used for dedup."""
        # Same hash but different text would be treated as duplicates
        facts = [
            {"fact_id": "f-001", "content_hash": "same-hash", "claim": {"text": "Claim 1"}},
            {"fact_id": "f-002", "content_hash": "same-hash", "claim": {"text": "Claim 2"}},
        ]
        result = await consolidator.sift({"facts": facts, "investigation_id": "inv-001"})

        # Same hash = same claim semantically
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_hash_computed_when_missing(self, consolidator):
        """Content hash computed from claim text if not provided."""
        facts = [
            {"fact_id": "f-001", "claim": {"text": "Test claim"}},
        ]
        result = await consolidator.sift({"facts": facts, "investigation_id": "inv-001"})

        expected_hash = hashlib.sha256("Test claim".encode()).hexdigest()
        assert result[0]["content_hash"] == expected_hash


class TestFactConsolidatorVariantLinking:
    """Tests for variant linking behavior."""

    @pytest.fixture
    def consolidator(self):
        return FactConsolidator()

    @pytest.mark.asyncio
    async def test_multiple_variants_linked(self, consolidator):
        """Multiple facts with same hash all become variants of first."""
        facts = [
            {"fact_id": f"f-{i}", "claim": {"text": "Same claim"}}
            for i in range(5)
        ]
        result = await consolidator.sift({"facts": facts, "investigation_id": "inv-001"})

        assert len(result) == 1
        canonical = result[0]
        assert canonical["fact_id"] == "f-0"
        assert len(canonical["variants"]) == 4
        for i in range(1, 5):
            assert f"f-{i}" in canonical["variants"]

    @pytest.mark.asyncio
    async def test_variant_provenance_merged(self, consolidator):
        """Variant provenance tracked in canonical fact."""
        facts = [
            {"fact_id": "f-001", "claim": {"text": "Same claim"},
             "provenance": {"source_id": "source-A"}},
            {"fact_id": "f-002", "claim": {"text": "Same claim"},
             "provenance": {"source_id": "source-B"}},
        ]
        result = await consolidator.sift({"facts": facts, "investigation_id": "inv-001"})

        assert len(result) == 1
        canonical = result[0]
        assert "additional_sources" in canonical
        assert len(canonical["additional_sources"]) == 1
        assert canonical["additional_sources"][0]["source_id"] == "source-B"

    @pytest.mark.asyncio
    async def test_existing_variants_preserved(self, consolidator):
        """Pre-existing variants list is not overwritten."""
        facts = [
            {"fact_id": "f-001", "claim": {"text": "Same claim"},
             "variants": ["f-existing"]},
            {"fact_id": "f-002", "claim": {"text": "Same claim"}},
        ]
        result = await consolidator.sift({"facts": facts, "investigation_id": "inv-001"})

        canonical = result[0]
        # Should have both existing and new variant
        assert "f-existing" in canonical["variants"]
        assert "f-002" in canonical["variants"]


class TestFactConsolidatorEmptyAndEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.fixture
    def consolidator(self):
        return FactConsolidator()

    @pytest.mark.asyncio
    async def test_empty_input(self, consolidator):
        """Empty input returns empty output."""
        result = await consolidator.sift({"facts": [], "investigation_id": "inv-001"})
        assert result == []

    @pytest.mark.asyncio
    async def test_single_fact(self, consolidator):
        """Single fact passes through unchanged."""
        fact = {"fact_id": "f-001", "claim": {"text": "Test"}}
        result = await consolidator.sift({"facts": [fact], "investigation_id": "inv-001"})

        assert len(result) == 1
        assert result[0]["fact_id"] == "f-001"

    @pytest.mark.asyncio
    async def test_fact_without_id_skipped(self, consolidator):
        """Facts without fact_id are skipped."""
        facts = [
            {"claim": {"text": "No ID fact"}},  # Missing fact_id
            {"fact_id": "f-001", "claim": {"text": "Valid fact"}},
        ]
        result = await consolidator.sift({"facts": facts, "investigation_id": "inv-001"})

        assert len(result) == 1
        assert result[0]["fact_id"] == "f-001"

    @pytest.mark.asyncio
    async def test_pydantic_model_input(self, consolidator):
        """Can process ExtractedFact Pydantic models."""
        fact = ExtractedFact(claim=Claim(text="Pydantic fact"))
        result = await consolidator.sift({
            "facts": [fact],
            "investigation_id": "inv-001"
        })

        assert len(result) == 1
        assert "Pydantic fact" in result[0]["claim"]["text"]


class TestFactConsolidatorBatchProcessing:
    """Tests for batch consolidation."""

    @pytest.fixture
    def consolidator(self):
        return FactConsolidator()

    @pytest.mark.asyncio
    async def test_large_batch(self, consolidator):
        """Handle large batch with mixed duplicates."""
        facts = []
        # 50 unique claims
        for i in range(50):
            facts.append({"fact_id": f"unique-{i}", "claim": {"text": f"Unique claim {i}"}})
        # 25 duplicates of first claim
        for i in range(25):
            facts.append({"fact_id": f"dup-{i}", "claim": {"text": "Unique claim 0"}})

        result = await consolidator.sift({"facts": facts, "investigation_id": "inv-001"})

        # 50 unique claims, but "Unique claim 0" has duplicates
        assert len(result) == 50
        # Find the canonical for "Unique claim 0"
        canonical = next(f for f in result if f["fact_id"] == "unique-0")
        assert len(canonical["variants"]) == 25

    @pytest.mark.asyncio
    async def test_stats_tracking(self, consolidator):
        """Consolidation stats accurately tracked."""
        facts = [
            {"fact_id": "f-001", "claim": {"text": "Claim A"}},
            {"fact_id": "f-002", "claim": {"text": "Claim A"}},  # dup
            {"fact_id": "f-003", "claim": {"text": "Claim A"}},  # dup
            {"fact_id": "f-004", "claim": {"text": "Claim B"}},
        ]
        await consolidator.sift({"facts": facts, "investigation_id": "inv-001"})

        stats = consolidator.get_consolidation_stats()
        assert stats["total_input"] == 4
        assert stats["hash_duplicates"] == 2
        assert stats["unique_claims"] == 2


class TestFactConsolidatorConfidenceFiltering:
    """Tests for confidence-based filtering."""

    @pytest.fixture
    def consolidator(self):
        return FactConsolidator()

    @pytest.mark.asyncio
    async def test_filter_low_confidence(self, consolidator):
        """Facts below min_confidence are filtered."""
        facts = [
            {"fact_id": "f-001", "claim": {"text": "High conf"},
             "quality": {"extraction_confidence": 0.9, "claim_clarity": 0.8}},
            {"fact_id": "f-002", "claim": {"text": "Low conf"},
             "quality": {"extraction_confidence": 0.2, "claim_clarity": 0.8}},
        ]
        result = await consolidator.sift({
            "facts": facts,
            "investigation_id": "inv-001",
            "min_confidence": 0.3
        })

        assert len(result) == 1
        assert result[0]["fact_id"] == "f-001"

    @pytest.mark.asyncio
    async def test_default_no_filter(self, consolidator):
        """Default min_confidence=0.0 includes all facts."""
        facts = [
            {"fact_id": "f-001", "claim": {"text": "Low conf"},
             "quality": {"extraction_confidence": 0.1, "claim_clarity": 0.8}},
        ]
        result = await consolidator.sift({
            "facts": facts,
            "investigation_id": "inv-001"
        })

        assert len(result) == 1


class TestFactConsolidatorStoreIntegration:
    """Tests for FactStore integration."""

    @pytest.mark.asyncio
    async def test_persist_to_store(self):
        """Consolidated facts are persisted to store."""
        mock_store = MagicMock()
        mock_store.save_facts = AsyncMock(return_value={"saved": 1})

        consolidator = FactConsolidator(fact_store=mock_store)
        facts = [{"fact_id": "f-001", "claim": {"text": "Test"}}]

        await consolidator.sift({
            "facts": facts,
            "investigation_id": "inv-001"
        })

        mock_store.save_facts.assert_called_once()
        call_args = mock_store.save_facts.call_args
        assert call_args[0][0] == "inv-001"  # investigation_id
        assert len(call_args[0][1]) == 1  # consolidated facts

    @pytest.mark.asyncio
    async def test_no_persistence_without_store(self):
        """Works without store (no persistence)."""
        consolidator = FactConsolidator()  # No store
        facts = [{"fact_id": "f-001", "claim": {"text": "Test"}}]

        # Should not raise
        result = await consolidator.sift({
            "facts": facts,
            "investigation_id": "inv-001"
        })
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_no_persistence_without_investigation_id(self):
        """No persistence if investigation_id not provided."""
        mock_store = MagicMock()
        mock_store.save_facts = AsyncMock()

        consolidator = FactConsolidator(fact_store=mock_store)
        facts = [{"fact_id": "f-001", "claim": {"text": "Test"}}]

        await consolidator.sift({
            "facts": facts
            # No investigation_id
        })

        mock_store.save_facts.assert_not_called()


class TestFactConsolidatorCapabilities:
    """Tests for capabilities reporting."""

    @pytest.fixture
    def consolidator(self):
        return FactConsolidator()

    def test_basic_capabilities(self, consolidator):
        """Base capabilities include dedup and linking."""
        caps = consolidator.get_capabilities()
        assert "fact_consolidation" in caps
        assert "deduplication" in caps
        assert "variant_linking" in caps

    def test_semantic_capability_when_enabled(self):
        """Semantic capability only when enabled with model."""
        mock_model = MagicMock()
        consolidator = FactConsolidator(
            enable_semantic=True,
            embedding_model=mock_model
        )
        caps = consolidator.get_capabilities()
        assert "semantic_deduplication" in caps

    def test_no_semantic_without_model(self):
        """Semantic capability not present without model."""
        consolidator = FactConsolidator(enable_semantic=True)  # No model
        caps = consolidator.get_capabilities()
        assert "semantic_deduplication" not in caps


class TestConsolidationStats:
    """Tests for ConsolidationStats dataclass."""

    def test_to_dict(self):
        """Stats convert to dict correctly."""
        stats = ConsolidationStats(
            total_input=10,
            hash_duplicates=3,
            semantic_duplicates=1,
            below_threshold=2,
            unique_claims=4
        )
        d = stats.to_dict()

        assert d["total_input"] == 10
        assert d["hash_duplicates"] == 3
        assert d["semantic_duplicates"] == 1
        assert d["below_threshold"] == 2
        assert d["unique_claims"] == 4

    def test_default_values(self):
        """Default stats are all zero."""
        stats = ConsolidationStats()
        assert stats.total_input == 0
        assert stats.unique_claims == 0


class TestFactConsolidatorSemanticDedup:
    """Tests for semantic deduplication (when enabled)."""

    @pytest.mark.asyncio
    async def test_semantic_disabled_by_default(self):
        """Semantic dedup disabled without embedding model."""
        consolidator = FactConsolidator()

        # These would be semantic duplicates but not hash duplicates
        facts = [
            {"fact_id": "f-001", "claim": {"text": "Putin visited Beijing"}},
            {"fact_id": "f-002", "claim": {"text": "Russian President went to Beijing"}},
        ]
        result = await consolidator.sift({"facts": facts, "investigation_id": "inv-001"})

        # Without semantic dedup, both remain separate
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_semantic_enabled_with_mock_model(self):
        """Semantic dedup works with embedding model."""
        # Create mock embedding model with sync embed (checked first if no embed_async)
        mock_model = MagicMock()
        # Don't have embed_async so it falls back to embed
        del mock_model.embed_async
        # Return similar embeddings for semantic duplicates
        mock_model.embed = MagicMock(side_effect=[
            [1.0, 0.0, 0.0],  # First fact
            [0.95, 0.05, 0.0],  # Second fact - similar
        ])

        consolidator = FactConsolidator(
            enable_semantic=True,
            embedding_model=mock_model,
            semantic_threshold=0.3
        )

        facts = [
            {"fact_id": "f-001", "claim": {"text": "Putin visited Beijing"}},
            {"fact_id": "f-002", "claim": {"text": "Russian President went to Beijing"}},
        ]
        result = await consolidator.sift({"facts": facts, "investigation_id": "inv-001"})

        # With semantic dedup, should consolidate similar facts
        assert len(result) == 1
