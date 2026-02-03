"""Tests for SourceCredibilityScorer.

Tests cover:
- Known source baseline lookups (Reuters, AP, BBC)
- Unknown source type defaults
- Domain extraction from URLs
- Domain pattern matching (.gov, .edu)
- Proximity decay calculation
- Precision scoring with entities/temporal/quotes
- Multiple source scoring
"""

import pytest

from osint_system.agents.sifters.credibility.source_scorer import (
    SourceCredibilityScorer,
    SourceScore,
)
from osint_system.config.source_credibility import (
    SOURCE_BASELINES,
    SOURCE_TYPE_DEFAULTS,
    PROXIMITY_DECAY_FACTOR,
)
from osint_system.data_management.schemas import CredibilityBreakdown


class TestSourceCredibilityScorer:
    """Tests for SourceCredibilityScorer class."""

    def test_initialization_default(self):
        """Scorer initializes with default baselines."""
        scorer = SourceCredibilityScorer()
        assert scorer.baselines == SOURCE_BASELINES
        assert scorer.type_defaults == SOURCE_TYPE_DEFAULTS
        assert scorer.proximity_decay == PROXIMITY_DECAY_FACTOR

    def test_initialization_custom(self):
        """Scorer accepts custom baselines."""
        custom_baselines = {"custom.com": 0.75}
        custom_defaults = {"custom_type": 0.6}
        scorer = SourceCredibilityScorer(
            baselines=custom_baselines,
            type_defaults=custom_defaults,
            proximity_decay=0.8,
        )
        assert scorer.baselines == custom_baselines
        assert scorer.type_defaults == custom_defaults
        assert scorer.proximity_decay == 0.8


class TestKnownSourceBaselines:
    """Tests for known source baseline lookups."""

    @pytest.fixture
    def scorer(self):
        return SourceCredibilityScorer()

    def test_reuters_baseline(self, scorer):
        """Reuters gets high credibility (0.9)."""
        fact = self._make_fact("https://reuters.com/article/123", "wire_service")
        score, breakdown = scorer.compute_credibility(fact)
        assert breakdown.s_root == 0.9

    def test_ap_baseline(self, scorer):
        """AP News gets high credibility (0.9)."""
        fact = self._make_fact("https://apnews.com/article/xyz", "wire_service")
        score, breakdown = scorer.compute_credibility(fact)
        assert breakdown.s_root == 0.9

    def test_bbc_baseline(self, scorer):
        """BBC gets high credibility (0.85)."""
        fact = self._make_fact("https://bbc.com/news/world-123", "news_outlet")
        score, breakdown = scorer.compute_credibility(fact)
        assert breakdown.s_root == 0.85

    def test_nytimes_baseline(self, scorer):
        """NYTimes gets high credibility (0.85)."""
        fact = self._make_fact("https://nytimes.com/2024/story", "news_outlet")
        score, breakdown = scorer.compute_credibility(fact)
        assert breakdown.s_root == 0.85

    def test_rt_lower_baseline(self, scorer):
        """RT (state propaganda) gets lower credibility (0.4)."""
        fact = self._make_fact("https://rt.com/news/article", "news_outlet")
        score, breakdown = scorer.compute_credibility(fact)
        assert breakdown.s_root == 0.4

    def test_social_media_baseline(self, scorer):
        """Twitter/X gets low credibility (0.3)."""
        fact = self._make_fact("https://twitter.com/user/status/123", "social_media")
        score, breakdown = scorer.compute_credibility(fact)
        assert breakdown.s_root == 0.3

    def _make_fact(self, source_id: str, source_type: str) -> dict:
        """Create minimal fact with provenance."""
        return {
            "fact_id": "test-1",
            "provenance": {
                "source_id": source_id,
                "source_type": source_type,
                "hop_count": 0,
                "offsets": {"start": 0, "end": 50},
            },
        }


class TestUnknownSourceDefaults:
    """Tests for unknown source type defaults."""

    @pytest.fixture
    def scorer(self):
        return SourceCredibilityScorer()

    def test_unknown_wire_service(self, scorer):
        """Unknown wire service gets type default (0.85)."""
        fact = {
            "fact_id": "test-1",
            "provenance": {
                "source_id": "unknown-wire.agency",
                "source_type": "wire_service",
                "hop_count": 0,
                "offsets": {"start": 0, "end": 50},
            },
        }
        score, breakdown = scorer.compute_credibility(fact)
        assert breakdown.s_root == 0.85

    def test_unknown_news_outlet(self, scorer):
        """Unknown news outlet gets type default (0.6)."""
        fact = {
            "fact_id": "test-1",
            "provenance": {
                "source_id": "random-news-site.com",
                "source_type": "news_outlet",
                "hop_count": 0,
                "offsets": {"start": 0, "end": 50},
            },
        }
        score, breakdown = scorer.compute_credibility(fact)
        assert breakdown.s_root == 0.6

    def test_unknown_type_default(self, scorer):
        """Unknown source type gets fallback (0.3)."""
        fact = {
            "fact_id": "test-1",
            "provenance": {
                "source_id": "mystery-source",
                "source_type": "unknown",
                "hop_count": 0,
                "offsets": {"start": 0, "end": 50},
            },
        }
        score, breakdown = scorer.compute_credibility(fact)
        assert breakdown.s_root == 0.3


class TestDomainExtraction:
    """Tests for domain extraction from URLs."""

    @pytest.fixture
    def scorer(self):
        return SourceCredibilityScorer()

    def test_extract_domain_from_url(self, scorer):
        """Domain extracted from full URL."""
        domain = scorer._extract_domain("https://www.reuters.com/article/123")
        assert domain == "reuters.com"

    def test_extract_domain_without_www(self, scorer):
        """Domain extracted without www prefix."""
        domain = scorer._extract_domain("https://reuters.com/article/123")
        assert domain == "reuters.com"

    def test_extract_domain_direct(self, scorer):
        """Direct domain without URL path."""
        domain = scorer._extract_domain("reuters.com")
        assert domain == "reuters.com"

    def test_extract_domain_empty(self, scorer):
        """Empty string returns None."""
        domain = scorer._extract_domain("")
        assert domain is None

    def test_extract_domain_invalid(self, scorer):
        """Invalid URL returns None."""
        domain = scorer._extract_domain("not-a-url")
        assert domain is None


class TestDomainPatternMatching:
    """Tests for domain pattern matching (.gov, .edu, etc.)."""

    @pytest.fixture
    def scorer(self):
        return SourceCredibilityScorer()

    def test_gov_domain(self, scorer):
        """Government domains get high credibility (0.85)."""
        fact = {
            "fact_id": "test-1",
            "provenance": {
                "source_id": "https://state.gov/press-release",
                "source_type": "official_statement",
                "hop_count": 0,
                "offsets": {"start": 0, "end": 50},
            },
        }
        score, breakdown = scorer.compute_credibility(fact)
        assert breakdown.s_root == 0.85

    def test_edu_domain(self, scorer):
        """Educational domains get high credibility (0.85)."""
        fact = {
            "fact_id": "test-1",
            "provenance": {
                "source_id": "https://mit.edu/research/paper",
                "source_type": "academic",
                "hop_count": 0,
                "offsets": {"start": 0, "end": 50},
            },
        }
        score, breakdown = scorer.compute_credibility(fact)
        assert breakdown.s_root == 0.85

    def test_org_domain(self, scorer):
        """Non-profit domains get moderate credibility (0.7)."""
        fact = {
            "fact_id": "test-1",
            "provenance": {
                "source_id": "https://amnesty.org/report",
                "source_type": "document",
                "hop_count": 0,
                "offsets": {"start": 0, "end": 50},
            },
        }
        score, breakdown = scorer.compute_credibility(fact)
        assert breakdown.s_root == 0.7


class TestProximityDecay:
    """Tests for proximity decay calculation."""

    @pytest.fixture
    def scorer(self):
        return SourceCredibilityScorer()

    def test_hop_0_proximity(self, scorer):
        """Hop 0 (eyewitness) = proximity 1.0."""
        proximity = scorer._compute_proximity(0)
        assert proximity == 1.0

    def test_hop_1_proximity(self, scorer):
        """Hop 1 = proximity 0.7."""
        proximity = scorer._compute_proximity(1)
        assert proximity == pytest.approx(0.7, rel=0.01)

    def test_hop_2_proximity(self, scorer):
        """Hop 2 = proximity 0.49."""
        proximity = scorer._compute_proximity(2)
        assert proximity == pytest.approx(0.49, rel=0.01)

    def test_hop_3_proximity(self, scorer):
        """Hop 3 = proximity 0.343."""
        proximity = scorer._compute_proximity(3)
        assert proximity == pytest.approx(0.343, rel=0.01)

    def test_high_hop_count(self, scorer):
        """High hop count approaches zero."""
        proximity = scorer._compute_proximity(10)
        assert proximity < 0.03


class TestPrecisionScoring:
    """Tests for precision scoring with verifiability signals."""

    @pytest.fixture
    def scorer(self):
        return SourceCredibilityScorer()

    def test_precision_with_entities(self, scorer):
        """More entities increase precision."""
        fact_few = {
            "entities": [{"id": "E1"}],
            "provenance": {"offsets": {"start": 0, "end": 50}},
        }
        fact_many = {
            "entities": [{"id": "E1"}, {"id": "E2"}, {"id": "E3"}, {"id": "E4"}],
            "provenance": {"offsets": {"start": 0, "end": 50}},
        }

        precision_few = scorer._compute_precision(fact_few, fact_few["provenance"])
        precision_many = scorer._compute_precision(fact_many, fact_many["provenance"])

        assert precision_many > precision_few

    def test_precision_with_temporal(self, scorer):
        """Explicit temporal precision increases score."""
        fact_explicit = {
            "temporal": {"temporal_precision": "explicit"},
            "provenance": {"offsets": {"start": 0, "end": 50}},
        }
        fact_inferred = {
            "temporal": {"temporal_precision": "inferred"},
            "provenance": {"offsets": {"start": 0, "end": 50}},
        }
        fact_none = {
            "provenance": {"offsets": {"start": 0, "end": 50}},
        }

        prec_explicit = scorer._compute_precision(fact_explicit, fact_explicit["provenance"])
        prec_inferred = scorer._compute_precision(fact_inferred, fact_inferred["provenance"])
        prec_none = scorer._compute_precision(fact_none, fact_none["provenance"])

        assert prec_explicit > prec_inferred > prec_none

    def test_precision_with_quote(self, scorer):
        """Direct quotes increase precision."""
        fact_quote = {
            "provenance": {
                "quote": '"We will not tolerate this," said the official',
                "attribution_phrase": "said the official",
                "offsets": {"start": 0, "end": 50},
            },
        }
        fact_no_quote = {
            "provenance": {
                "quote": "There was some discussion",
                "attribution_phrase": "according to reports",
                "offsets": {"start": 0, "end": 50},
            },
        }

        prec_quote = scorer._compute_precision(fact_quote, fact_quote["provenance"])
        prec_no = scorer._compute_precision(fact_no_quote, fact_no_quote["provenance"])

        assert prec_quote > prec_no

    def test_precision_with_document(self, scorer):
        """Document citations increase precision."""
        fact_doc = {
            "provenance": {
                "attribution_chain": [
                    {"entity": "UN Report", "type": "document", "hop": 0},
                ],
                "offsets": {"start": 0, "end": 50},
            },
        }
        fact_no_doc = {
            "provenance": {
                "attribution_chain": [],
                "offsets": {"start": 0, "end": 50},
            },
        }

        prec_doc = scorer._compute_precision(fact_doc, fact_doc["provenance"])
        prec_no = scorer._compute_precision(fact_no_doc, fact_no_doc["provenance"])

        assert prec_doc > prec_no


class TestCombinedScoring:
    """Tests for combined credibility scoring."""

    @pytest.fixture
    def scorer(self):
        return SourceCredibilityScorer()

    def test_high_credibility_fact(self, scorer):
        """High-quality fact from reputable source scores high."""
        fact = {
            "fact_id": "test-1",
            "entities": [
                {"id": "E1", "text": "Putin", "type": "PERSON"},
                {"id": "E2", "text": "Beijing", "type": "LOCATION"},
            ],
            "temporal": {"temporal_precision": "explicit"},
            "provenance": {
                "source_id": "https://reuters.com/article/123",
                "source_type": "wire_service",
                "hop_count": 0,
                "quote": '"Putin arrived in Beijing," said the spokesperson',
                "attribution_phrase": "said the spokesperson",
                "offsets": {"start": 0, "end": 100},
            },
        }
        score, breakdown = scorer.compute_credibility(fact)
        assert score > 0.5
        assert breakdown.s_root == 0.9

    def test_low_credibility_fact(self, scorer):
        """Low-quality fact from unknown source scores low."""
        fact = {
            "fact_id": "test-2",
            "provenance": {
                "source_id": "random-blog.xyz",
                "source_type": "unknown",
                "hop_count": 4,
                "offsets": {"start": 0, "end": 50},
            },
        }
        score, breakdown = scorer.compute_credibility(fact)
        assert score < 0.1
        assert breakdown.s_root == 0.3

    def test_no_provenance(self, scorer):
        """Fact without provenance gets default low score."""
        fact = {"fact_id": "test-3"}
        score, breakdown = scorer.compute_credibility(fact)
        assert score == 0.3
        assert breakdown.s_root == 0.3

    def test_score_ordering(self, scorer):
        """Reuters > Unknown News > Random Blog."""
        reuters = {
            "provenance": {
                "source_id": "reuters.com",
                "source_type": "wire_service",
                "hop_count": 1,
                "offsets": {"start": 0, "end": 50},
            },
        }
        news = {
            "provenance": {
                "source_id": "unknown-news.com",
                "source_type": "news_outlet",
                "hop_count": 1,
                "offsets": {"start": 0, "end": 50},
            },
        }
        blog = {
            "provenance": {
                "source_id": "random-blog.xyz",
                "source_type": "unknown",
                "hop_count": 1,
                "offsets": {"start": 0, "end": 50},
            },
        }

        score_r, _ = scorer.compute_credibility(reuters)
        score_n, _ = scorer.compute_credibility(news)
        score_b, _ = scorer.compute_credibility(blog)

        assert score_r > score_n > score_b


class TestMultipleSourceScoring:
    """Tests for multiple source scoring."""

    @pytest.fixture
    def scorer(self):
        return SourceCredibilityScorer()

    def test_score_multiple_sources(self, scorer):
        """Multiple sources scored correctly."""
        fact = {
            "fact_id": "test-1",
            "entities": [{"id": "E1"}],
            "provenance": {
                "source_id": "reuters.com",
                "source_type": "wire_service",
                "hop_count": 1,
                "offsets": {"start": 0, "end": 50},
            },
        }
        additional = [
            {
                "source_id": "bbc.com",
                "source_type": "news_outlet",
                "hop_count": 2,
                "offsets": {"start": 0, "end": 50},
            },
            {
                "source_id": "nytimes.com",
                "source_type": "news_outlet",
                "hop_count": 2,
                "offsets": {"start": 0, "end": 50},
            },
        ]

        score, breakdown, source_scores = scorer.score_multiple_sources(fact, additional)

        assert len(source_scores) == 3
        assert breakdown.s_echoes_sum > 0
        # Root should be highest scoring source
        assert source_scores[0].is_root

    def test_empty_additional_sources(self, scorer):
        """Empty additional sources returns primary only."""
        fact = {
            "fact_id": "test-1",
            "provenance": {
                "source_id": "reuters.com",
                "source_type": "wire_service",
                "hop_count": 0,
                "offsets": {"start": 0, "end": 50},
            },
        }

        score, breakdown, source_scores = scorer.score_multiple_sources(fact, [])

        assert len(source_scores) == 1
        assert source_scores[0].is_root
