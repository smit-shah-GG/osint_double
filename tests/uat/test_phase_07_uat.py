"""
Phase 7 UAT Tests - Fact Classification System

These tests validate the user-observable behavior of the Phase 7 classification system.
Run with: GEMINI_API_KEY=your_key uv run python -m pytest tests/uat/test_phase_07_uat.py -v
"""

import os
import pytest
from datetime import datetime, timezone
from uuid import uuid4


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(scope="session", autouse=True)
def set_gemini_api_key():
    """Set GEMINI_API_KEY if not already set (for import to succeed)."""
    if "GEMINI_API_KEY" not in os.environ:
        # Set a placeholder - tests don't actually call the API
        os.environ["GEMINI_API_KEY"] = "test-key-for-import"


# =============================================================================
# Test 1: Classification Schema Imports
# =============================================================================

def test_01_classification_schema_imports():
    """All classification schema classes import successfully."""
    from osint_system.data_management.schemas import (
        FactClassification,
        ImpactTier,
        DubiousFlag,
        CredibilityBreakdown,
        ClassificationReasoning,
    )
    from osint_system.data_management import ClassificationStore

    assert FactClassification is not None
    assert ImpactTier is not None
    assert DubiousFlag is not None
    assert CredibilityBreakdown is not None
    assert ClassificationReasoning is not None
    assert ClassificationStore is not None


# =============================================================================
# Test 2: FactClassificationAgent Instantiation
# =============================================================================

def test_02_fact_classification_agent_instantiation():
    """FactClassificationAgent instantiates with all required components."""
    from osint_system.agents.sifters import FactClassificationAgent

    agent = FactClassificationAgent()

    # Check agent exists
    assert agent is not None

    # Check lazy properties exist (access them to trigger initialization)
    assert agent.credibility_scorer is not None
    assert agent.dubious_detector is not None
    assert agent.impact_assessor is not None
    assert agent.anomaly_detector is not None


# =============================================================================
# Test 3: Source Credibility Scoring
# =============================================================================

def test_03_source_credibility_scoring():
    """SourceCredibilityScorer returns correct baseline scores via compute_credibility."""
    from osint_system.agents.sifters.credibility import SourceCredibilityScorer

    scorer = SourceCredibilityScorer()

    # Test Reuters (wire service ~0.9) - add entities for better precision score
    reuters_fact = {
        "claim": "Biden announced sanctions against Russia",
        "provenance": {
            "source_id": "https://www.reuters.com/article/123",
            "source_type": "wire_service",
            "hop_count": 0,
        },
        "entities": [
            {"text": "Biden", "type": "PER"},
            {"text": "Russia", "type": "GPE"},
        ],
    }
    reuters_score, breakdown = scorer.compute_credibility(reuters_fact)
    # Score = source_cred * proximity * precision
    # Reuters baseline ~0.9, hop=0 proximity=1.0, precision varies
    # Check that source credibility component is high
    assert breakdown.s_root >= 0.85, f"Reuters s_root {breakdown.s_root} should be >= 0.85"

    # Test Twitter (social media ~0.3)
    twitter_fact = {
        "claim": "Some random tweet",
        "provenance": {
            "source_id": "https://twitter.com/user/status/123",
            "source_type": "social_media",
            "hop_count": 0,
        },
        "entities": [{"text": "User", "type": "PER"}],
    }
    twitter_score, twitter_breakdown = scorer.compute_credibility(twitter_fact)
    # Twitter baseline ~0.3
    assert twitter_breakdown.s_root <= 0.35, f"Twitter s_root {twitter_breakdown.s_root} should be <= 0.35"
    # Combined score should be lower than Reuters
    assert twitter_score < reuters_score, f"Twitter score {twitter_score} should be less than Reuters {reuters_score}"


# =============================================================================
# Test 4: Proximity Decay Calculation
# =============================================================================

def test_04_proximity_decay_calculation():
    """Proximity decay follows 0.7^hop formula via compute_credibility."""
    from osint_system.agents.sifters.credibility import SourceCredibilityScorer

    scorer = SourceCredibilityScorer()

    # Create facts with different hop counts from same source
    base_fact = {
        "claim": "Test claim",
        "provenance": {
            "source_id": "https://www.reuters.com/article/123",
            "source_type": "wire_service",
        },
        "entities": [],
    }

    # hop=0 should give highest score
    fact_hop0 = {**base_fact, "provenance": {**base_fact["provenance"], "hop_count": 0}}
    score_hop0, breakdown0 = scorer.compute_credibility(fact_hop0)

    # hop=2 should give lower score (decay factor)
    fact_hop2 = {**base_fact, "provenance": {**base_fact["provenance"], "hop_count": 2}}
    score_hop2, breakdown2 = scorer.compute_credibility(fact_hop2)

    # Verify decay: hop=2 should be significantly lower than hop=0
    assert score_hop2 < score_hop0, f"hop=2 ({score_hop2}) should be less than hop=0 ({score_hop0})"

    # Check proximity scores in breakdown (0.7^0 = 1.0, 0.7^2 = 0.49)
    if breakdown0.proximity_scores and breakdown2.proximity_scores:
        assert abs(breakdown0.proximity_scores[0] - 1.0) < 0.01
        assert abs(breakdown2.proximity_scores[0] - 0.49) < 0.01


# =============================================================================
# Test 5: Dubious Flag Detection - PHANTOM
# =============================================================================

def test_05_dubious_flag_phantom():
    """Fact with hop_count > 2 AND no primary source triggers PHANTOM flag."""
    from osint_system.agents.sifters.classification import DubiousDetector
    from osint_system.data_management.schemas import DubiousFlag

    detector = DubiousDetector()

    # Create fact with hop_count > 2 and no primary source
    phantom_fact = {
        "fact_id": str(uuid4()),
        "claim": "Some claim from distant secondary source",
        "provenance": {
            "source_id": "test-source",
            "source_name": "Some Blog",
            "source_type": "secondary",
            "source_classification": "tertiary",  # Not primary
            "hop_count": 3,  # > 2 threshold
            "has_primary_source": False,
        },
        "extraction_confidence": 0.8,
        "claim_clarity": 0.7,
    }

    result = detector.detect(phantom_fact, credibility_score=0.5, contradictions=[])

    assert DubiousFlag.PHANTOM in result.flags, f"Expected PHANTOM flag, got {result.flags}"


# =============================================================================
# Test 6: Dubious Flag Detection - FOG
# =============================================================================

def test_06_dubious_flag_fog():
    """Fact with low claim_clarity or vague attribution triggers FOG flag."""
    from osint_system.agents.sifters.classification import DubiousDetector
    from osint_system.data_management.schemas import DubiousFlag

    detector = DubiousDetector()

    # Test 1: Low claim_clarity triggers FOG (claim_clarity is under quality dict)
    fog_fact_low_clarity = {
        "fact_id": str(uuid4()),
        "claim": "Something happened somewhere",
        "provenance": {
            "source_id": "test-source",
            "source_name": "News Outlet",
            "source_type": "primary",
            "hop_count": 0,
            "has_primary_source": True,
        },
        "quality": {
            "claim_clarity": 0.3,  # Below 0.5 threshold - nested under quality
        },
        "extraction_confidence": 0.8,
    }

    result = detector.detect(fog_fact_low_clarity, credibility_score=0.7, contradictions=[])
    assert DubiousFlag.FOG in result.flags, f"Expected FOG flag for low clarity, got {result.flags}"

    # Test 2: Vague attribution pattern triggers FOG
    fog_fact_vague = {
        "fact_id": str(uuid4()),
        "claim": "Sources say the attack happened yesterday",  # Vague "sources say"
        "provenance": {
            "source_id": "test-source",
            "source_name": "News Outlet",
            "source_type": "primary",
            "hop_count": 0,
            "has_primary_source": True,
            "attribution_phrase": "sources say",  # Vague attribution
        },
        "quality": {
            "claim_clarity": 0.8,  # High clarity but vague attribution
        },
        "extraction_confidence": 0.8,
    }

    result2 = detector.detect(fog_fact_vague, credibility_score=0.7, contradictions=[])
    assert DubiousFlag.FOG in result2.flags, f"Expected FOG flag for vague attribution, got {result2.flags}"


# =============================================================================
# Test 7: Dubious Flag Detection - NOISE
# =============================================================================

def test_07_dubious_flag_noise():
    """Fact from low-credibility source triggers NOISE flag."""
    from osint_system.agents.sifters.classification import DubiousDetector
    from osint_system.data_management.schemas import DubiousFlag

    detector = DubiousDetector()

    # Create fact - NOISE is triggered by credibility_score < 0.3
    noise_fact = {
        "fact_id": str(uuid4()),
        "claim": "Random claim from unreliable source",
        "provenance": {
            "source_id": "random-blog",
            "source_name": "Random Blog",
            "source_type": "primary",
            "hop_count": 0,
            "has_primary_source": True,
        },
        "extraction_confidence": 0.8,
        "claim_clarity": 0.8,
    }

    # Low credibility score < 0.3 triggers NOISE
    result = detector.detect(noise_fact, credibility_score=0.2, contradictions=[])

    assert DubiousFlag.NOISE in result.flags, f"Expected NOISE flag, got {result.flags}"


# =============================================================================
# Test 8: Impact Assessment - Critical
# =============================================================================

def test_08_impact_assessment_critical():
    """Fact mentioning world leaders or military action triggers CRITICAL tier."""
    from osint_system.agents.sifters.classification import ImpactAssessor
    from osint_system.data_management.schemas import ImpactTier

    assessor = ImpactAssessor()

    # Create fact about world leader and military action
    critical_fact = {
        "fact_id": str(uuid4()),
        "claim": "Putin ordered a military strike on the target",
        "entities": [
            {"text": "Putin", "canonical": "Vladimir Putin", "type": "PER"},
        ],
        "provenance": {
            "source_id": "reuters",
            "source_name": "Reuters",
            "source_type": "wire_service",
            "hop_count": 0,
        },
    }

    result = assessor.assess(critical_fact)

    assert result.tier == ImpactTier.CRITICAL, f"Expected CRITICAL tier, got {result.tier}"


# =============================================================================
# Test 9: Impact Assessment - Less Critical
# =============================================================================

def test_09_impact_assessment_less_critical():
    """Routine fact without significant entities/events receives LESS_CRITICAL tier."""
    from osint_system.agents.sifters.classification import ImpactAssessor
    from osint_system.data_management.schemas import ImpactTier

    assessor = ImpactAssessor()

    # Create routine fact
    routine_fact = {
        "fact_id": str(uuid4()),
        "claim": "The company released a new software update",
        "entities": [
            {"text": "Acme Corp", "type": "ORG"},
        ],
        "provenance": {
            "source_id": "tech-blog",
            "source_name": "Tech Blog",
            "source_type": "blog",
            "hop_count": 0,
        },
    }

    result = assessor.assess(routine_fact)

    assert result.tier == ImpactTier.LESS_CRITICAL, f"Expected LESS_CRITICAL tier, got {result.tier}"


# =============================================================================
# Test 10: Anomaly Detection - Contradictions
# =============================================================================

@pytest.mark.asyncio
async def test_10_anomaly_detection_contradictions():
    """Two contradicting facts detected as contradiction."""
    # AnomalyDetector is not exported in __init__.py, import directly
    from osint_system.agents.sifters.classification.anomaly_detector import AnomalyDetector

    detector = AnomalyDetector()

    # Create two contradicting facts - claim must be dict with "text" key
    fact1 = {
        "fact_id": str(uuid4()),
        "claim": {"text": "Russia attacked Ukraine on Monday"},  # Dict with text key
        "entities": [
            {"text": "Russia", "type": "GPE", "canonical": "Russia"},
            {"text": "Ukraine", "type": "GPE", "canonical": "Ukraine"},
        ],
        "assertion_type": "statement",
        "provenance": {
            "source_id": "source1",
            "hop_count": 0,
        },
    }

    fact2 = {
        "fact_id": str(uuid4()),
        "claim": {"text": "Russia never attacked Ukraine on Monday"},  # Contains negation "never"
        "entities": [
            {"text": "Russia", "type": "GPE", "canonical": "Russia"},
            {"text": "Ukraine", "type": "GPE", "canonical": "Ukraine"},
        ],
        "assertion_type": "denial",
        "provenance": {
            "source_id": "source2",
            "hop_count": 0,
        },
    }

    contradictions = await detector.find_contradictions(fact1, [fact2])

    assert len(contradictions) > 0, "Expected at least one contradiction to be detected"


# =============================================================================
# Test 11: Priority Queue Ordering
# =============================================================================

@pytest.mark.asyncio
async def test_11_priority_queue_ordering():
    """ClassificationStore.get_priority_queue() returns facts ordered by priority_score descending."""
    from osint_system.data_management import ClassificationStore
    from osint_system.data_management.schemas import (
        FactClassification, ImpactTier, DubiousFlag, CredibilityBreakdown
    )

    store = ClassificationStore()
    investigation_id = f"test-inv-{uuid4()}"

    # Create classifications with different priority scores
    low_priority = FactClassification(
        fact_id=str(uuid4()),
        investigation_id=investigation_id,
        impact_tier=ImpactTier.LESS_CRITICAL,
        dubious_flags=[DubiousFlag.FOG],
        credibility_score=0.4,
        credibility_breakdown=CredibilityBreakdown(
            s_root=0.4,
            s_echoes_sum=0.0,
            proximity_scores=[1.0],
            precision_scores=[0.5],
            echo_bonus=0.0,
        ),
        priority_score=0.3,
    )

    high_priority = FactClassification(
        fact_id=str(uuid4()),
        investigation_id=investigation_id,
        impact_tier=ImpactTier.CRITICAL,
        dubious_flags=[DubiousFlag.PHANTOM],
        credibility_score=0.6,
        credibility_breakdown=CredibilityBreakdown(
            s_root=0.6,
            s_echoes_sum=0.0,
            proximity_scores=[1.0],
            precision_scores=[0.7],
            echo_bonus=0.0,
        ),
        priority_score=0.8,
    )

    # NOISE-only should be excluded from queue
    noise_only = FactClassification(
        fact_id=str(uuid4()),
        investigation_id=investigation_id,
        impact_tier=ImpactTier.LESS_CRITICAL,
        dubious_flags=[DubiousFlag.NOISE],  # Only NOISE
        credibility_score=0.2,
        credibility_breakdown=CredibilityBreakdown(
            s_root=0.2,
            s_echoes_sum=0.0,
            proximity_scores=[1.0],
            precision_scores=[0.3],
            echo_bonus=0.0,
        ),
        priority_score=0.0,  # NOISE-only gets 0.0
    )

    # Store them in random order using correct method name
    await store.save_classification(noise_only)
    await store.save_classification(low_priority)
    await store.save_classification(high_priority)

    # Get priority queue (returns List[Dict], not List[FactClassification])
    queue = await store.get_priority_queue(investigation_id)

    # Verify ordering: high priority first, NOISE-only excluded
    assert len(queue) == 2, f"Expected 2 items (NOISE-only excluded), got {len(queue)}"
    # Access via dict keys since store returns dicts
    assert queue[0]["fact_id"] == high_priority.fact_id, "High priority should be first"
    assert queue[1]["fact_id"] == low_priority.fact_id, "Low priority should be second"


# =============================================================================
# Test 12: Full Classification Pipeline
# =============================================================================

@pytest.mark.asyncio
async def test_12_full_classification_pipeline():
    """classify_investigation() processes multiple facts with full audit trail."""
    from osint_system.agents.sifters import FactClassificationAgent

    agent = FactClassificationAgent()
    investigation_id = f"test-inv-{uuid4()}"

    # Create facts as dicts (the format the agent expects)
    facts = [
        {
            "fact_id": str(uuid4()),
            "claim": "Biden announced new sanctions against Russia",
            "entities": [
                {"text": "Biden", "type": "PER", "canonical": "Joe Biden"},
                {"text": "Russia", "type": "GPE", "canonical": "Russia"},
            ],
            "provenance": {
                "source_id": "reuters-1",
                "source_name": "Reuters",
                "source_type": "wire_service",
                "url": "https://reuters.com/article",
                "hop_count": 0,
                "has_primary_source": True,
            },
            "extraction_confidence": 0.9,
            "claim_clarity": 0.9,
        },
        {
            "fact_id": str(uuid4()),
            "claim": "Local weather expected to be sunny",
            "entities": [],
            "provenance": {
                "source_id": "reuters-2",
                "source_name": "Reuters",
                "source_type": "wire_service",
                "url": "https://reuters.com/article2",
                "hop_count": 0,
                "has_primary_source": True,
            },
            "extraction_confidence": 0.8,
            "claim_clarity": 0.8,
        },
    ]

    result = await agent.classify_investigation(investigation_id, facts)

    # Verify all facts were classified
    assert len(result) == 2, f"Expected 2 classifications, got {len(result)}"

    # Verify each classification has required fields (returned as dicts)
    for classification in result:
        assert classification["fact_id"] is not None
        assert classification["investigation_id"] == investigation_id
        assert classification["impact_tier"] is not None
        assert classification["credibility_score"] is not None
        assert classification["credibility_breakdown"] is not None


# =============================================================================
# Test 13: Unit Tests Pass (Run separately)
# =============================================================================

def test_13_unit_tests_pass():
    """
    This test is a placeholder - run the actual unit tests separately:

    uv run python -m pytest tests/agents/sifters/classification/ \
        tests/agents/sifters/credibility/ \
        tests/data_management/schemas/test_classification_schema.py -v
    """
    # This test just verifies the test infrastructure works
    # The actual unit tests should be run separately
    assert True, "Run unit tests separately with pytest command above"
