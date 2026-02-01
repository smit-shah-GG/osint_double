"""Authority scoring for source credibility assessment.

Implements domain-based authority scoring with metadata signal enhancement.
Used by crawlers to prioritize high-credibility sources.
"""

from typing import Optional, Dict, Any
from urllib.parse import urlparse
import logging


logger = logging.getLogger(__name__)


class AuthorityScorer:
    """
    Calculates authority scores for URLs based on domain and metadata signals.

    Authority scoring helps prioritize high-credibility sources during crawling
    and fact extraction. Scores range from 0.0 to 1.0.

    Domain-based scoring:
    - Major wire services (Reuters, AP): 0.9
    - Government/educational domains: 0.85
    - Established news organizations: 0.8
    - Organizational domains (.org): 0.7
    - Social media platforms: 0.3
    - Unknown sources: 0.5

    Scores are further adjusted based on metadata signals:
    - Author verification (+0.05)
    - Publication date present (+0.03)
    - High engagement metrics (+0.02)
    """

    # Domain authority scores
    AUTHORITY_DOMAINS: Dict[str, float] = {
        # Major wire services (highest authority)
        "reuters.com": 0.9,
        "apnews.com": 0.9,
        "afp.com": 0.9,
        # Major news organizations
        "bbc.com": 0.85,
        "bbc.co.uk": 0.85,
        "nytimes.com": 0.85,
        "washingtonpost.com": 0.85,
        "theguardian.com": 0.85,
        "economist.com": 0.85,
        # Government domains (by TLD)
        ".gov": 0.85,
        ".gov.uk": 0.85,
        ".gov.au": 0.85,
        ".mil": 0.85,
        # Educational domains
        ".edu": 0.85,
        ".ac.uk": 0.85,
        # Regional quality sources
        "aljazeera.com": 0.8,
        "dw.com": 0.8,
        "france24.com": 0.8,
        # Organizational domains
        ".org": 0.7,
        # Social media (lower authority)
        "reddit.com": 0.3,
        "twitter.com": 0.3,
        "x.com": 0.3,
        "facebook.com": 0.3,
    }

    # Source type weights for composite scoring
    SOURCE_TYPE_WEIGHTS: Dict[str, float] = {
        "official": 1.0,
        "news": 0.9,
        "academic": 0.85,
        "organization": 0.7,
        "social": 0.3,
        "unknown": 0.5,
    }

    def __init__(self, default_score: float = 0.5):
        """
        Initialize authority scorer.

        Args:
            default_score: Default score for unknown domains (0.0-1.0)
        """
        self.default_score = default_score
        logger.info(f"AuthorityScorer initialized with default score {default_score}")

    def calculate_score(
        self,
        url: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> float:
        """
        Calculate authority score for a URL.

        Combines domain-based scoring with metadata signal adjustments.

        Args:
            url: URL to score
            metadata: Optional metadata dict containing:
                - author_verified: bool
                - publication_date: str or datetime
                - engagement_metrics: dict with score, comments, etc.

        Returns:
            Authority score between 0.0 and 1.0
        """
        # Get base domain score
        domain_score = self._get_domain_score(url)

        # Adjust based on metadata signals
        if metadata:
            signal_adjustment = self._calculate_signal_adjustment(metadata)
            score = min(1.0, domain_score + signal_adjustment)
        else:
            score = domain_score

        logger.debug(
            f"Authority score calculated: {score:.2f} for {url}",
            extra={"url": url, "score": score, "domain_score": domain_score},
        )

        return score

    def _get_domain_score(self, url: str) -> float:
        """
        Get authority score based on domain.

        Args:
            url: URL to check

        Returns:
            Domain-based authority score
        """
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()

            # Remove www. prefix for matching
            if domain.startswith("www."):
                domain = domain[4:]

            # Check exact domain match first
            if domain in self.AUTHORITY_DOMAINS:
                return self.AUTHORITY_DOMAINS[domain]

            # Check TLD matches (e.g., .gov, .edu)
            for tld_pattern, score in self.AUTHORITY_DOMAINS.items():
                if tld_pattern.startswith(".") and domain.endswith(tld_pattern):
                    return score

            return self.default_score

        except Exception as e:
            logger.warning(f"Failed to parse URL for authority scoring: {e}")
            return self.default_score

    def _calculate_signal_adjustment(self, metadata: Dict[str, Any]) -> float:
        """
        Calculate score adjustment based on metadata signals.

        Args:
            metadata: Metadata dictionary with signal indicators

        Returns:
            Score adjustment (can be positive or negative)
        """
        adjustment = 0.0

        # Author verification bonus
        if metadata.get("author_verified"):
            adjustment += 0.05

        # Publication date presence bonus
        if metadata.get("publication_date"):
            adjustment += 0.03

        # Engagement metrics bonus
        engagement = metadata.get("engagement_metrics", {})
        if engagement:
            # High score/upvotes
            score = engagement.get("score", 0)
            if score > 100:
                adjustment += 0.02
            # High comment count indicates discussion
            comments = engagement.get("comments", 0)
            if comments > 50:
                adjustment += 0.01

        return adjustment

    def get_domain_category(self, url: str) -> str:
        """
        Get the category for a domain.

        Args:
            url: URL to categorize

        Returns:
            Category string: 'official', 'news', 'academic', 'organization', 'social', 'unknown'
        """
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()

            if domain.startswith("www."):
                domain = domain[4:]

            # Check for specific categories
            if any(tld in domain for tld in [".gov", ".mil"]):
                return "official"

            if any(tld in domain for tld in [".edu", ".ac."]):
                return "academic"

            news_domains = [
                "reuters.com", "apnews.com", "bbc.com", "nytimes.com",
                "washingtonpost.com", "theguardian.com", "aljazeera.com",
            ]
            if any(news in domain for news in news_domains):
                return "news"

            if ".org" in domain:
                return "organization"

            social_domains = ["reddit.com", "twitter.com", "x.com", "facebook.com"]
            if any(social in domain for social in social_domains):
                return "social"

            return "unknown"

        except Exception:
            return "unknown"

    def get_source_type_weight(self, source_type: str) -> float:
        """
        Get weight for a source type.

        Args:
            source_type: Type of source

        Returns:
            Weight multiplier for this source type
        """
        return self.SOURCE_TYPE_WEIGHTS.get(source_type.lower(), 0.5)
