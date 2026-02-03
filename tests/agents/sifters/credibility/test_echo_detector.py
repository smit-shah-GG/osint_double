"""Tests for EchoDetector.

Tests cover:
- Single source analysis (no echoes)
- Multiple independent sources
- Logarithmic dampening values
- Circular reporting detection
- Root clustering by attribution chain
- Corroboration strength calculation
- Breakdown update
"""

import math
import pytest

from osint_system.agents.sifters.credibility.echo_detector import (
    EchoDetector,
    EchoScore,
    EchoCluster,
)
from osint_system.config.source_credibility import ECHO_DAMPENING_ALPHA
from osint_system.data_management.schemas import CredibilityBreakdown


class TestEchoDetector:
    """Tests for EchoDetector class."""

    def test_initialization_default(self):
        """Detector initializes with default alpha."""
        detector = EchoDetector()
        assert detector.alpha == ECHO_DAMPENING_ALPHA

    def test_initialization_custom(self):
        """Detector accepts custom alpha."""
        detector = EchoDetector(alpha=0.5)
        assert detector.alpha == 0.5


class TestSingleSourceAnalysis:
    """Tests for single source analysis (no echoes)."""

    @pytest.fixture
    def detector(self):
        return EchoDetector()

    def test_single_source(self, detector):
        """Single source has no echo bonus."""
        provenances = [
            {
                "source_id": "reuters.com",
                "hop_count": 1,
                "attribution_chain": [],
            }
        ]
        scores = [0.9]

        result = detector.analyze_sources(provenances, scores)

        assert result.root_score == 0.9
        assert result.echo_sum == 0.0
        assert result.echo_bonus == 0.0
        assert result.total_score == 0.9
        assert result.circular_warning is False

    def test_analyze_single_source_convenience(self, detector):
        """Convenience method for single source."""
        provenance = {"source_id": "reuters.com", "hop_count": 1}
        result = detector.analyze_single_source(provenance, 0.85)

        assert result.root_score == 0.85
        assert result.echo_sum == 0.0
        assert result.echo_bonus == 0.0
        assert result.total_score == 0.85
        assert result.unique_roots == 1

    def test_empty_provenances(self, detector):
        """Empty provenances returns zero score."""
        result = detector.analyze_sources([], [])

        assert result.root_score == 0.0
        assert result.echo_sum == 0.0
        assert result.echo_bonus == 0.0
        assert result.total_score == 0.0


class TestMultipleIndependentSources:
    """Tests for multiple independent sources."""

    @pytest.fixture
    def detector(self):
        return EchoDetector()

    def test_two_independent_sources(self, detector):
        """Two independent sources add echo bonus."""
        provenances = [
            {
                "source_id": "reuters.com",
                "hop_count": 0,
                "attribution_chain": [
                    {"entity": "White House", "type": "official_statement", "hop": 0},
                ],
            },
            {
                "source_id": "bbc.com",
                "hop_count": 0,
                "attribution_chain": [
                    {"entity": "Pentagon", "type": "official_statement", "hop": 0},
                ],
            },
        ]
        scores = [0.9, 0.85]

        result = detector.analyze_sources(provenances, scores)

        assert result.root_score == 0.9  # Highest score
        assert result.echo_sum == 0.85  # Other sources
        assert result.echo_bonus > 0  # Has bonus
        assert result.total_score > 0.9  # More than root alone

    def test_three_independent_sources(self, detector):
        """Three independent sources increase unique roots."""
        provenances = [
            {
                "source_id": "source1.com",
                "hop_count": 0,
                "attribution_chain": [{"entity": "Source1", "hop": 0}],
            },
            {
                "source_id": "source2.com",
                "hop_count": 0,
                "attribution_chain": [{"entity": "Source2", "hop": 0}],
            },
            {
                "source_id": "source3.com",
                "hop_count": 0,
                "attribution_chain": [{"entity": "Source3", "hop": 0}],
            },
        ]
        scores = [0.8, 0.75, 0.7]

        result = detector.analyze_sources(provenances, scores)

        assert result.unique_roots == 3


class TestLogarithmicDampening:
    """Tests for logarithmic dampening values."""

    @pytest.fixture
    def detector(self):
        return EchoDetector(alpha=0.2)

    def test_echo_bonus_zero(self, detector):
        """Zero echoes = zero bonus."""
        bonus = detector._compute_echo_bonus(0)
        assert bonus == 0.0

    def test_echo_bonus_one(self, detector):
        """One echo adds small bonus."""
        bonus = detector._compute_echo_bonus(1)
        expected = 0.2 * math.log10(2)  # ~0.060
        assert bonus == pytest.approx(expected, rel=0.01)

    def test_echo_bonus_ten(self, detector):
        """Ten echoes add moderate bonus."""
        bonus = detector._compute_echo_bonus(10)
        expected = 0.2 * math.log10(11)  # ~0.208
        assert bonus == pytest.approx(expected, rel=0.01)

    def test_echo_bonus_hundred(self, detector):
        """Hundred echoes add significant but limited bonus."""
        bonus = detector._compute_echo_bonus(100)
        expected = 0.2 * math.log10(101)  # ~0.401
        assert bonus == pytest.approx(expected, rel=0.01)

    def test_echo_bonus_thousand(self, detector):
        """Thousand echoes still limited by log."""
        bonus = detector._compute_echo_bonus(1000)
        expected = 0.2 * math.log10(1001)  # ~0.600
        assert bonus == pytest.approx(expected, rel=0.01)

    def test_echo_bonus_ten_thousand(self, detector):
        """Ten thousand echoes effectively capped."""
        bonus = detector._compute_echo_bonus(10000)
        expected = 0.2 * math.log10(10001)  # ~0.800
        assert bonus == pytest.approx(expected, rel=0.01)

    def test_botnet_crushing(self, detector):
        """Million echoes adds little more than ten thousand.

        The logarithmic function means:
        - 10k echoes: 0.2 * log10(10001) ~ 0.80
        - 1M echoes: 0.2 * log10(1000001) ~ 1.20

        So 1M adds only ~0.4 more than 10k, demonstrating crushing effect.
        Going from 10k to 1M (100x increase) only doubles the bonus.
        """
        bonus_10k = detector._compute_echo_bonus(10000)
        bonus_1m = detector._compute_echo_bonus(1000000)

        # 1M adds only ~0.4 more than 10k (100x sources for 50% more credit)
        difference = bonus_1m - bonus_10k
        assert difference < 0.5

    def test_diminishing_returns(self, detector):
        """Logarithmic curve shows diminishing returns per source added.

        The key property is that adding 10x more sources doesn't give 10x more credit.
        - 10 echoes: ~0.21 bonus
        - 100 echoes (10x more): ~0.40 bonus (only ~2x more)
        - 1000 echoes (10x more): ~0.60 bonus (only ~1.5x more)

        This prevents gaming by volume.
        """
        bonus_10 = detector._compute_echo_bonus(10)
        bonus_100 = detector._compute_echo_bonus(100)
        bonus_1000 = detector._compute_echo_bonus(1000)

        # 100 echoes is 10x more than 10, but bonus < 2x
        ratio_10_to_100 = bonus_100 / bonus_10
        assert ratio_10_to_100 < 2.5  # Much less than 10x

        # 1000 echoes is 10x more than 100, but bonus < 2x
        ratio_100_to_1000 = bonus_1000 / bonus_100
        assert ratio_100_to_1000 < 2.0  # Much less than 10x

        # Overall: 1000 sources gives less than 3x the bonus of 10 sources
        ratio_10_to_1000 = bonus_1000 / bonus_10
        assert ratio_10_to_1000 < 3.0


class TestCircularReportingDetection:
    """Tests for circular reporting detection."""

    @pytest.fixture
    def detector(self):
        return EchoDetector()

    def test_all_same_root_warning(self, detector):
        """All sources from same non-primary root triggers warning."""
        provenances = [
            {
                "source_id": "news1.com",
                "hop_count": 2,
                "attribution_chain": [
                    {"entity": "Anonymous Source", "type": "unknown", "hop": 1},
                ],
            },
            {
                "source_id": "news2.com",
                "hop_count": 2,
                "attribution_chain": [
                    {"entity": "Anonymous Source", "type": "unknown", "hop": 1},
                ],
            },
            {
                "source_id": "news3.com",
                "hop_count": 2,
                "attribution_chain": [
                    {"entity": "Anonymous Source", "type": "unknown", "hop": 1},
                ],
            },
        ]
        scores = [0.6, 0.55, 0.5]

        result = detector.analyze_sources(provenances, scores)

        assert result.circular_warning is True

    def test_no_primary_warning(self, detector):
        """No primary sources among many triggers warning."""
        provenances = [
            {"source_id": "s1", "hop_count": 2, "attribution_chain": []},
            {"source_id": "s2", "hop_count": 3, "attribution_chain": []},
            {"source_id": "s3", "hop_count": 2, "attribution_chain": []},
            {"source_id": "s4", "hop_count": 4, "attribution_chain": []},
        ]
        scores = [0.5, 0.5, 0.5, 0.5]

        result = detector.analyze_sources(provenances, scores)

        assert result.circular_warning is True

    def test_has_primary_no_warning(self, detector):
        """Primary source present = no warning."""
        provenances = [
            {"source_id": "eyewitness", "hop_count": 0, "attribution_chain": []},
            {"source_id": "news1", "hop_count": 1, "attribution_chain": []},
            {"source_id": "news2", "hop_count": 2, "attribution_chain": []},
        ]
        scores = [0.6, 0.5, 0.5]

        result = detector.analyze_sources(provenances, scores)

        assert result.circular_warning is False

    def test_primary_classification(self, detector):
        """Source with 'primary' classification counts as primary."""
        provenances = [
            {"source_id": "s1", "hop_count": 2, "source_classification": "primary"},
            {"source_id": "s2", "hop_count": 2, "attribution_chain": []},
            {"source_id": "s3", "hop_count": 2, "attribution_chain": []},
            {"source_id": "s4", "hop_count": 2, "attribution_chain": []},
        ]
        scores = [0.5, 0.5, 0.5, 0.5]

        result = detector.analyze_sources(provenances, scores)

        assert result.circular_warning is False


class TestRootClustering:
    """Tests for root clustering by attribution chain."""

    @pytest.fixture
    def detector(self):
        return EchoDetector()

    def test_cluster_by_root(self, detector):
        """Sources cluster by root entity."""
        provenances = [
            {
                "source_id": "news1.com",
                "hop_count": 1,
                "attribution_chain": [
                    {"entity": "White House", "type": "official", "hop": 0},
                ],
            },
            {
                "source_id": "news2.com",
                "hop_count": 1,
                "attribution_chain": [
                    {"entity": "White House", "type": "official", "hop": 0},
                ],
            },
            {
                "source_id": "news3.com",
                "hop_count": 1,
                "attribution_chain": [
                    {"entity": "Pentagon", "type": "official", "hop": 0},
                ],
            },
        ]
        scores = [0.8, 0.75, 0.7]

        result = detector.analyze_sources(provenances, scores)

        # Two clusters: White House and Pentagon
        assert len(result.echo_clusters) == 2

    def test_find_root_with_chain(self, detector):
        """Root found from attribution chain."""
        provenance = {
            "source_id": "news.com",
            "attribution_chain": [
                {"entity": "Official", "type": "official", "hop": 0},
                {"entity": "Wire Service", "type": "wire", "hop": 1},
            ],
        }

        root_entity, root_hop = detector._find_root(provenance)

        assert root_entity == "Official"
        assert root_hop == 0

    def test_find_root_no_chain(self, detector):
        """Root defaults to source_id without chain."""
        provenance = {
            "source_id": "eyewitness-report",
            "hop_count": 0,
            "attribution_chain": [],
        }

        root_entity, root_hop = detector._find_root(provenance)

        assert root_entity == "eyewitness-report"
        assert root_hop == 0


class TestCorroborationStrength:
    """Tests for corroboration strength calculation."""

    @pytest.fixture
    def detector(self):
        return EchoDetector()

    def test_single_source_weak(self, detector):
        """Single source = weak corroboration (0.3)."""
        strength = detector.compute_corroboration_strength(1, 0.9)
        assert strength == 0.3

    def test_two_sources_moderate(self, detector):
        """Two sources = moderate corroboration."""
        strength = detector.compute_corroboration_strength(2, 0.8)
        assert strength > 0.3
        assert strength < 0.7

    def test_many_sources_strong(self, detector):
        """Many sources = strong corroboration."""
        strength = detector.compute_corroboration_strength(5, 0.85)
        assert strength > 0.7

    def test_root_quality_matters(self, detector):
        """Higher root quality increases corroboration."""
        strength_high = detector.compute_corroboration_strength(3, 0.9)
        strength_low = detector.compute_corroboration_strength(3, 0.4)
        assert strength_high > strength_low


class TestBreakdownUpdate:
    """Tests for credibility breakdown update."""

    @pytest.fixture
    def detector(self):
        return EchoDetector()

    def test_update_breakdown(self, detector):
        """Breakdown updated with echo analysis."""
        breakdown = CredibilityBreakdown(
            s_root=0.8,
            s_echoes_sum=0.0,
            proximity_scores=[1.0],
            precision_scores=[0.9],
            echo_bonus=0.0,
        )

        echo_score = EchoScore(
            root_score=0.85,
            echo_sum=1.5,
            echo_bonus=0.08,
            total_score=0.93,
            unique_roots=2,
        )

        updated = detector.update_breakdown(breakdown, echo_score)

        assert updated.s_root == 0.85
        assert updated.s_echoes_sum == 1.5
        assert updated.echo_bonus == 0.08

    def test_breakdown_compute_total_matches(self, detector):
        """Breakdown compute_total matches EchoDetector formula."""
        provenances = [
            {"source_id": "s1", "hop_count": 0, "attribution_chain": []},
            {"source_id": "s2", "hop_count": 1, "attribution_chain": []},
        ]
        scores = [0.9, 0.7]

        result = detector.analyze_sources(provenances, scores)

        breakdown = CredibilityBreakdown(
            s_root=result.root_score,
            s_echoes_sum=result.echo_sum,
            proximity_scores=[1.0, 0.7],
            precision_scores=[0.8, 0.6],
            echo_bonus=result.echo_bonus,
            alpha=detector.alpha,
        )

        assert breakdown.compute_total() == pytest.approx(result.total_score, rel=0.01)


class TestEdgeCases:
    """Tests for edge cases."""

    @pytest.fixture
    def detector(self):
        return EchoDetector()

    def test_mismatched_scores_length(self, detector):
        """Handles mismatched scores length."""
        provenances = [
            {"source_id": "s1", "hop_count": 1},
            {"source_id": "s2", "hop_count": 1},
            {"source_id": "s3", "hop_count": 1},
        ]
        scores = [0.8]  # Only one score for three provenances

        # Should not raise, uses default 0.5 for missing
        result = detector.analyze_sources(provenances, scores)

        assert result.root_score > 0
        assert result.total_score > 0

    def test_negative_echo_sum(self, detector):
        """Negative echo sum returns zero bonus."""
        bonus = detector._compute_echo_bonus(-5)
        assert bonus == 0.0

    def test_empty_attribution_chain(self, detector):
        """Empty attribution chain uses source_id as root."""
        provenance = {
            "source_id": "direct-source",
            "hop_count": 0,
            "attribution_chain": [],
        }

        root, hop = detector._find_root(provenance)

        assert root == "direct-source"
        assert hop == 0
