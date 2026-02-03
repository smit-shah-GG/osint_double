"""Tests for FactClassificationAgent.

Tests cover:
- Agent initialization and capabilities
- BaseSifter inheritance
- sift() method with various fact inputs
- classify_fact() basic flow
- Priority calculation logic
- Dubious flag detection
- ClassificationStore integration
- Empty input handling
"""

import pytest
from unittest.mock import MagicMock, AsyncMock

from osint_system.agents.sifters.fact_classification_agent import FactClassificationAgent
from osint_system.agents.sifters.base_sifter import BaseSifter
from osint_system.data_management.classification_store import ClassificationStore
from osint_system.data_management.fact_store import FactStore
from osint_system.data_management.schemas import (
    FactClassification,
    ImpactTier,
    DubiousFlag,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def classification_store():
    """Create a fresh classification store for testing."""
    return ClassificationStore()


@pytest.fixture
def fact_store():
    """Create a fresh fact store for testing."""
    return FactStore()


@pytest.fixture
def agent(classification_store, fact_store):
    """Create agent with injected stores."""
    return FactClassificationAgent(
        classification_store=classification_store,
        fact_store=fact_store,
    )


@pytest.fixture
def high_quality_fact():
    """Create a high-quality fact for testing."""
    return {
        "fact_id": "high-quality-fact-123",
        "claim": {
            "text": "[E1:Putin] visited [E2:Beijing] in [T1:March 2024]",
            "assertion_type": "statement",
            "claim_type": "event",
        },
        "entities": [
            {"id": "E1", "text": "Putin", "type": "PERSON"},
            {"id": "E2", "text": "Beijing", "type": "LOCATION"},
        ],
        "quality": {
            "extraction_confidence": 0.95,
            "claim_clarity": 0.9,
        },
        "provenance": {
            "source_id": "reuters-article-123",
            "hop_count": 1,
        },
    }


@pytest.fixture
def low_quality_fact():
    """Create a low-quality dubious fact for testing."""
    return {
        "fact_id": "low-quality-fact-456",
        "claim": {
            "text": "Sources say something happened",
            "assertion_type": "claim",
            "claim_type": "event",
        },
        "entities": [],
        "quality": {
            "extraction_confidence": 0.6,
            "claim_clarity": 0.2,  # Below fog threshold
        },
        "provenance": {
            "source_id": "unknown-source",
            "hop_count": 4,
        },
    }


# ============================================================================
# Initialization Tests
# ============================================================================


class TestAgentInitialization:
    """Tests for agent initialization and configuration."""

    def test_initialization_defaults(self):
        """Agent initializes with correct defaults."""
        agent = FactClassificationAgent()
        assert agent.name == "FactClassificationAgent"
        assert "dubious detection" in agent.description

    def test_initialization_with_stores(self, classification_store, fact_store):
        """Agent accepts injected stores."""
        agent = FactClassificationAgent(
            classification_store=classification_store,
            fact_store=fact_store,
        )
        assert agent._classification_store is classification_store
        assert agent._fact_store is fact_store

    def test_lazy_store_initialization(self):
        """Stores are lazily initialized on first access."""
        agent = FactClassificationAgent()
        assert agent._classification_store is None
        assert agent._fact_store is None

        # Access triggers initialization
        _ = agent.classification_store
        _ = agent.fact_store

        assert agent._classification_store is not None
        assert agent._fact_store is not None

    def test_inherits_from_base_sifter(self, agent):
        """Agent inherits from BaseSifter."""
        assert isinstance(agent, BaseSifter)

    def test_capabilities(self, agent):
        """Agent reports correct capabilities."""
        caps = agent.get_capabilities()
        assert "fact_classification" in caps
        assert "impact_assessment" in caps
        assert "dubious_detection" in caps
        assert "credibility_scoring" in caps
        assert "priority_calculation" in caps


# ============================================================================
# sift() Method Tests
# ============================================================================


class TestSiftMethod:
    """Tests for sift() method."""

    @pytest.mark.asyncio
    async def test_sift_empty_facts_returns_empty(self, agent):
        """Empty facts list returns empty list."""
        result = await agent.sift({"facts": [], "investigation_id": "test-inv"})
        assert result == []

    @pytest.mark.asyncio
    async def test_sift_missing_facts_returns_empty(self, agent):
        """Missing facts key returns empty list."""
        result = await agent.sift({"investigation_id": "test-inv"})
        assert result == []

    @pytest.mark.asyncio
    async def test_sift_single_fact(self, agent, high_quality_fact):
        """Sift classifies a single fact."""
        result = await agent.sift({
            "facts": [high_quality_fact],
            "investigation_id": "test-inv",
        })

        assert len(result) == 1
        classification = result[0]
        assert classification["fact_id"] == "high-quality-fact-123"
        assert classification["investigation_id"] == "test-inv"
        assert "impact_tier" in classification
        assert "dubious_flags" in classification
        assert "credibility_score" in classification
        assert "priority_score" in classification

    @pytest.mark.asyncio
    async def test_sift_multiple_facts(self, agent, high_quality_fact, low_quality_fact):
        """Sift classifies multiple facts."""
        result = await agent.sift({
            "facts": [high_quality_fact, low_quality_fact],
            "investigation_id": "test-inv",
        })

        assert len(result) == 2
        fact_ids = {c["fact_id"] for c in result}
        assert "high-quality-fact-123" in fact_ids
        assert "low-quality-fact-456" in fact_ids

    @pytest.mark.asyncio
    async def test_sift_saves_to_store(self, agent, classification_store, high_quality_fact):
        """Sift saves classifications to store."""
        await agent.sift({
            "facts": [high_quality_fact],
            "investigation_id": "test-inv",
        })

        # Verify stored in classification store
        stored = await classification_store.get_classification(
            "test-inv", "high-quality-fact-123"
        )
        assert stored is not None
        assert stored["fact_id"] == "high-quality-fact-123"

    @pytest.mark.asyncio
    async def test_sift_uses_default_investigation_id(self, agent, high_quality_fact):
        """Sift uses 'default' investigation_id if not provided."""
        result = await agent.sift({
            "facts": [high_quality_fact],
        })

        assert len(result) == 1
        assert result[0]["investigation_id"] == "default"


# ============================================================================
# classify_fact() Tests
# ============================================================================


class TestClassifyFact:
    """Tests for classify_fact() method."""

    @pytest.mark.asyncio
    async def test_classify_fact_returns_classification(self, agent, high_quality_fact):
        """classify_fact returns FactClassification."""
        classification = await agent.classify_fact(high_quality_fact, "test-inv")

        assert isinstance(classification, FactClassification)
        assert classification.fact_id == "high-quality-fact-123"
        assert classification.investigation_id == "test-inv"

    @pytest.mark.asyncio
    async def test_classify_high_quality_fact(self, agent, high_quality_fact):
        """High-quality fact gets no dubious flags."""
        classification = await agent.classify_fact(high_quality_fact, "test-inv")

        # High claim_clarity (0.9) should not trigger fog
        # Using shell implementation, claim_clarity becomes credibility
        assert classification.credibility_score == 0.9
        assert DubiousFlag.FOG not in classification.dubious_flags
        assert DubiousFlag.NOISE not in classification.dubious_flags

    @pytest.mark.asyncio
    async def test_classify_low_quality_fact(self, agent, low_quality_fact):
        """Low-quality fact gets dubious flags."""
        classification = await agent.classify_fact(low_quality_fact, "test-inv")

        # Low claim_clarity (0.2) triggers fog (< 0.5) and noise (< 0.3)
        assert classification.credibility_score == 0.2
        assert DubiousFlag.FOG in classification.dubious_flags
        assert DubiousFlag.NOISE in classification.dubious_flags

    @pytest.mark.asyncio
    async def test_classify_fact_with_reasoning(self, agent, low_quality_fact):
        """Classification includes reasoning for flags."""
        classification = await agent.classify_fact(low_quality_fact, "test-inv")

        assert len(classification.classification_reasoning) > 0
        # Find fog reasoning
        fog_reasoning = classification.get_flag_reasoning(DubiousFlag.FOG)
        assert fog_reasoning is not None
        assert "claim_clarity" in fog_reasoning.reason


# ============================================================================
# Priority Calculation Tests
# ============================================================================


class TestPriorityCalculation:
    """Tests for priority score calculation."""

    def test_priority_not_dubious_is_zero(self, agent):
        """Non-dubious facts have zero priority (no verification needed)."""
        priority = agent._calculate_priority(
            ImpactTier.CRITICAL,
            [],  # No dubious flags
            0.8,
        )
        assert priority == 0.0

    def test_priority_noise_only_is_zero(self, agent):
        """Noise-only facts have zero priority (batch analysis only)."""
        priority = agent._calculate_priority(
            ImpactTier.CRITICAL,
            [DubiousFlag.NOISE],
            0.2,
        )
        assert priority == 0.0

    def test_priority_critical_higher_than_less_critical(self, agent):
        """Critical tier has higher priority than less-critical."""
        critical_priority = agent._calculate_priority(
            ImpactTier.CRITICAL,
            [DubiousFlag.PHANTOM],
            0.5,
        )
        less_critical_priority = agent._calculate_priority(
            ImpactTier.LESS_CRITICAL,
            [DubiousFlag.PHANTOM],
            0.5,
        )
        assert critical_priority > less_critical_priority

    def test_priority_higher_credibility_higher_fixability(self, agent):
        """Higher credibility facts have higher fixability."""
        high_cred_priority = agent._calculate_priority(
            ImpactTier.CRITICAL,
            [DubiousFlag.PHANTOM],
            0.9,  # High credibility
        )
        low_cred_priority = agent._calculate_priority(
            ImpactTier.CRITICAL,
            [DubiousFlag.PHANTOM],
            0.3,  # Low credibility
        )
        assert high_cred_priority > low_cred_priority

    def test_priority_noise_plus_other_gets_priority(self, agent):
        """Noise + other flags still gets priority."""
        priority = agent._calculate_priority(
            ImpactTier.CRITICAL,
            [DubiousFlag.NOISE, DubiousFlag.FOG],  # Multiple flags
            0.5,
        )
        assert priority > 0.0


# ============================================================================
# Dubious Flag Detection Tests
# ============================================================================


class TestDubiousFlagDetection:
    """Tests for dubious flag detection (shell implementation)."""

    def test_detect_noise_below_threshold(self, agent):
        """Noise flag when credibility < 0.3."""
        flags, reasoning = agent._detect_dubious(
            {"quality": {"claim_clarity": 0.2}},
            credibility_score=0.2,
        )
        assert DubiousFlag.NOISE in flags
        noise_reason = [r for r in reasoning if r.flag == DubiousFlag.NOISE][0]
        assert "credibility_score" in noise_reason.reason

    def test_detect_fog_low_clarity(self, agent):
        """Fog flag when claim_clarity < 0.5."""
        flags, reasoning = agent._detect_dubious(
            {"quality": {"claim_clarity": 0.4}},
            credibility_score=0.5,
        )
        assert DubiousFlag.FOG in flags
        fog_reason = [r for r in reasoning if r.flag == DubiousFlag.FOG][0]
        assert "claim_clarity" in fog_reason.reason

    def test_no_flags_high_quality(self, agent):
        """No flags for high-quality facts."""
        flags, reasoning = agent._detect_dubious(
            {"quality": {"claim_clarity": 0.9}},
            credibility_score=0.9,
        )
        assert len(flags) == 0
        assert len(reasoning) == 0


# ============================================================================
# Store Integration Tests
# ============================================================================


class TestStoreIntegration:
    """Tests for ClassificationStore integration."""

    @pytest.mark.asyncio
    async def test_get_classification_stats(self, agent, classification_store, high_quality_fact):
        """get_classification_stats returns store stats."""
        await agent.sift({
            "facts": [high_quality_fact],
            "investigation_id": "test-inv",
        })

        stats = await agent.get_classification_stats("test-inv")

        assert stats["exists"] is True
        assert stats["total_classifications"] == 1
        assert stats["investigation_id"] == "test-inv"

    @pytest.mark.asyncio
    async def test_get_dubious_facts(self, agent, classification_store, high_quality_fact, low_quality_fact):
        """get_dubious_facts returns dubious classifications."""
        await agent.sift({
            "facts": [high_quality_fact, low_quality_fact],
            "investigation_id": "test-inv",
        })

        dubious = await agent.get_dubious_facts("test-inv")

        # Only low_quality_fact should be dubious
        assert len(dubious) == 1
        assert dubious[0]["fact_id"] == "low-quality-fact-456"

    @pytest.mark.asyncio
    async def test_get_priority_queue(self, agent, classification_store, high_quality_fact, low_quality_fact):
        """get_priority_queue returns ordered classifications."""
        await agent.sift({
            "facts": [high_quality_fact, low_quality_fact],
            "investigation_id": "test-inv",
        })

        queue = await agent.get_priority_queue("test-inv")

        # Queue should exclude noise-only and be ordered by priority
        assert isinstance(queue, list)


# ============================================================================
# Edge Cases
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_fact_without_quality_uses_defaults(self, agent):
        """Fact without quality metrics uses defaults."""
        fact = {
            "fact_id": "no-quality",
            "claim": {"text": "Test claim"},
        }

        classification = await agent.classify_fact(fact, "test-inv")

        # Should use default claim_clarity (0.5) which is at fog threshold
        assert classification.credibility_score == 0.5

    @pytest.mark.asyncio
    async def test_fact_with_none_quality(self, agent):
        """Fact with None quality uses defaults."""
        fact = {
            "fact_id": "none-quality",
            "claim": {"text": "Test claim"},
            "quality": None,
        }

        classification = await agent.classify_fact(fact, "test-inv")
        assert classification.credibility_score == 0.5

    @pytest.mark.asyncio
    async def test_fact_missing_fact_id_uses_unknown(self, agent):
        """Fact without fact_id uses 'unknown'."""
        fact = {
            "claim": {"text": "Test claim"},
            "quality": {"claim_clarity": 0.7},
        }

        classification = await agent.classify_fact(fact, "test-inv")
        assert classification.fact_id == "unknown"


# ============================================================================
# Process Method Tests (BaseSifter Contract)
# ============================================================================


class TestProcessMethod:
    """Tests for BaseSifter.process() wrapper."""

    @pytest.mark.asyncio
    async def test_process_wraps_sift(self, agent, high_quality_fact):
        """process() correctly wraps sift()."""
        result = await agent.process({
            "content": {
                "facts": [high_quality_fact],
                "investigation_id": "test-inv",
            }
        })

        assert result["success"] is True
        assert result["count"] == 1
        assert len(result["results"]) == 1

    @pytest.mark.asyncio
    async def test_process_empty_content(self, agent):
        """process() handles empty content."""
        result = await agent.process({"content": {}})

        assert result["success"] is True
        assert result["count"] == 0
        assert result["results"] == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
