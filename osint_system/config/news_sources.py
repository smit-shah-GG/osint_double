"""News source configurations with mixed authority levels and feed URLs.

This module defines configurable news sources with RSS feeds, credibility scores,
geographic focus, and rate limits. Sources are categorized by authority level
(1-5 scale) to enable intelligent source weighting during analysis.

Authority levels:
  5: Established mainstream media (BBC, Reuters, AP)
  4: Professional news agencies and journalists
  3: Specialist outlets with domain expertise (Defense One, War on the Rocks)
  2: Alternative/independent sources with selective coverage
  1: Niche/specialized sources with narrower audiences
"""

from typing import Dict, Any

# Global news source configuration
NEWS_SOURCES: Dict[str, Dict[str, Any]] = {
    # Mainstream Tier 5 - Established global news agencies
    "bbc": {
        "name": "BBC News",
        "url": "http://feeds.bbci.co.uk/news/rss.xml",
        "authority_level": 5,
        "topic_specialization": "General news",
        "geographic_focus": "Global",
        "update_frequency": "Continuous",
        "rate_limit_per_second": 5,
        "description": "British Broadcasting Corporation - established global news service",
    },
    "reuters": {
        "name": "Reuters Top News",
        "url": "http://feeds.reuters.com/reuters/topNews",
        "authority_level": 5,
        "topic_specialization": "General news, Business",
        "geographic_focus": "Global",
        "update_frequency": "Continuous",
        "rate_limit_per_second": 5,
        "description": "Reuters news agency - authoritative breaking news",
    },
    "ap": {
        "name": "AP News Top Stories",
        "url": "https://apnews.com/APF-TopNews",
        "authority_level": 5,
        "topic_specialization": "General news, US politics",
        "geographic_focus": "Global with US focus",
        "update_frequency": "Continuous",
        "rate_limit_per_second": 5,
        "description": "Associated Press - US-based global news agency",
    },

    # Mainstream/Professional Tier 4 - Established digital news outlets
    "guardian": {
        "name": "The Guardian",
        "url": "https://www.theguardian.com/world/rss",
        "authority_level": 4,
        "topic_specialization": "General news, Politics, Investigative",
        "geographic_focus": "Global",
        "update_frequency": "Continuous",
        "rate_limit_per_second": 3,
        "description": "British investigative news outlet",
    },
    "bbc_world": {
        "name": "BBC World",
        "url": "http://feeds.bbci.co.uk/news/world/rss.xml",
        "authority_level": 4,
        "topic_specialization": "International news",
        "geographic_focus": "Global",
        "update_frequency": "Continuous",
        "rate_limit_per_second": 5,
        "description": "BBC World service - international focused",
    },
    "dw_english": {
        "name": "Deutsche Welle (English)",
        "url": "https://www.dw.com/en/top-stories/s-7641",
        "authority_level": 4,
        "topic_specialization": "General news, Politics, Economics",
        "geographic_focus": "Global with Europe focus",
        "update_frequency": "Continuous",
        "rate_limit_per_second": 3,
        "description": "German public broadcaster - multilingual service",
    },

    # Specialist Tier 3 - Domain expertise outlets
    "defense_one": {
        "name": "Defense One",
        "url": "https://www.defenseone.com/feeds/defense-one-top-stories.xml",
        "authority_level": 3,
        "topic_specialization": "Defense, Military policy, National security",
        "geographic_focus": "Global",
        "update_frequency": "Daily",
        "rate_limit_per_second": 2,
        "description": "Specialist defense and military policy outlet",
    },
    "war_on_rocks": {
        "name": "War on the Rocks",
        "url": "https://warontherocks.com/feed/",
        "authority_level": 3,
        "topic_specialization": "Military strategy, Defense policy, Security analysis",
        "geographic_focus": "Global",
        "update_frequency": "Daily",
        "rate_limit_per_second": 2,
        "description": "Military strategy and analysis blog",
    },
    "lawfare": {
        "name": "Lawfare",
        "url": "https://www.lawfareblog.com/feed",
        "authority_level": 3,
        "topic_specialization": "Law, National security, Cybersecurity",
        "geographic_focus": "Global",
        "update_frequency": "Daily",
        "rate_limit_per_second": 2,
        "description": "Security law and policy analysis blog",
    },

    # International/Regional Tier 3-4
    "aljazeera": {
        "name": "Al Jazeera English",
        "url": "https://www.aljazeera.com/xml/rss/all.xml",
        "authority_level": 4,
        "topic_specialization": "General news, Middle East, World",
        "geographic_focus": "Global with Middle East focus",
        "update_frequency": "Continuous",
        "rate_limit_per_second": 3,
        "description": "Qatar-based international news network",
    },
    "france_24": {
        "name": "France 24",
        "url": "https://www.france24.com/en/rss",
        "authority_level": 4,
        "topic_specialization": "General news, Politics, Economics",
        "geographic_focus": "Global with Europe/Africa focus",
        "update_frequency": "Continuous",
        "rate_limit_per_second": 3,
        "description": "French public broadcaster - international service",
    },

    # Alternative Tier 2-3 - Independent journalists and outlets
    "quillette": {
        "name": "Quillette",
        "url": "https://quillette.com/feed/",
        "authority_level": 2,
        "topic_specialization": "Politics, Culture, Analysis",
        "geographic_focus": "Primarily Western",
        "update_frequency": "Daily",
        "rate_limit_per_second": 2,
        "description": "Independent online journal - contrarian perspectives",
    },
    "astute_news": {
        "name": "Astute Newswriters",
        "url": "https://astutenewswriters.substack.com/feed",
        "authority_level": 2,
        "topic_specialization": "Geopolitics, Analysis",
        "geographic_focus": "Global",
        "update_frequency": "Weekly",
        "rate_limit_per_second": 1,
        "description": "Independent geopolitical analysis",
    },

    # Specialized Tier 3 - Domain-specific analysis
    "think_global": {
        "name": "Think Tank Feeds (Aggregated)",
        "url": "https://www.brookings.edu/feed/",
        "authority_level": 3,
        "topic_specialization": "Policy analysis, Economics, Politics",
        "geographic_focus": "Global",
        "update_frequency": "Daily",
        "rate_limit_per_second": 2,
        "description": "Brookings Institution - major policy think tank",
    },
    "csis_feed": {
        "name": "Center for Strategic and International Studies",
        "url": "https://www.csis.org/newsandevents/feed",
        "authority_level": 3,
        "topic_specialization": "Strategic analysis, Geopolitics, Economics",
        "geographic_focus": "Global",
        "update_frequency": "Daily",
        "rate_limit_per_second": 2,
        "description": "CSIS - major research institution",
    },

    # Archive/Historical - Lower frequency but comprehensive
    "npr_news": {
        "name": "NPR News",
        "url": "https://feeds.npr.org/1001/rss.xml",
        "authority_level": 4,
        "topic_specialization": "General news, US focus",
        "geographic_focus": "Primarily US",
        "update_frequency": "Continuous",
        "rate_limit_per_second": 3,
        "description": "US public radio - quality journalism",
    },

    # Regional/Niche sources for breadth
    "bbc_asia": {
        "name": "BBC Asia-Pacific",
        "url": "http://feeds.bbci.co.uk/news/world/asia/rss.xml",
        "authority_level": 4,
        "topic_specialization": "Asia-Pacific news",
        "geographic_focus": "Asia-Pacific",
        "update_frequency": "Continuous",
        "rate_limit_per_second": 3,
        "description": "BBC regional service for Asia-Pacific",
    },
}


# Global configuration for news API service (NewsAPI.org)
NEWS_API_CONFIG: Dict[str, Any] = {
    "provider": "NewsAPI",
    "base_url": "https://newsapi.org/v2",
    "endpoint": "everything",
    "api_key_env_var": "NEWS_API_KEY",
    "free_tier_limits": {
        "requests_per_day": 100,
        "estimated_requests_per_hour": 4,
    },
    "default_parameters": {
        "language": "en",
        "sort_by": "relevancy",
        "page_size": 100,
    },
    "search_parameters": {
        "date_range_days": 30,  # Search up to 30 days back
        "min_confidence_score": 0.6,  # Minimum confidence for fact extraction
    },
}


def get_source_by_name(source_name: str) -> Dict[str, Any] | None:
    """
    Retrieve a news source configuration by name.

    Args:
        source_name: Key name of the source in NEWS_SOURCES

    Returns:
        Source configuration dict or None if not found
    """
    return NEWS_SOURCES.get(source_name)


def get_sources_by_authority(min_level: int = 1, max_level: int = 5) -> Dict[str, Dict[str, Any]]:
    """
    Get all sources within an authority level range.

    Useful for filtering sources by credibility for prioritization.

    Args:
        min_level: Minimum authority level (1-5)
        max_level: Maximum authority level (1-5)

    Returns:
        Dictionary of filtered sources
    """
    return {
        name: config
        for name, config in NEWS_SOURCES.items()
        if min_level <= config.get("authority_level", 3) <= max_level
    }


def get_sources_by_topic(topic: str) -> Dict[str, Dict[str, Any]]:
    """
    Get all sources covering a specific topic.

    Args:
        topic: Topic string to search in topic_specialization

    Returns:
        Dictionary of sources with matching topics
    """
    return {
        name: config
        for name, config in NEWS_SOURCES.items()
        if topic.lower() in config.get("topic_specialization", "").lower()
    }


def get_source_count() -> int:
    """Get total number of configured news sources."""
    return len(NEWS_SOURCES)


def validate_source_configuration() -> Dict[str, Any]:
    """
    Validate news source configuration for consistency.

    Returns:
        Validation report with any issues found
    """
    issues = []

    for source_name, config in NEWS_SOURCES.items():
        # Check required fields
        required_fields = ["name", "url", "authority_level", "topic_specialization"]
        for field in required_fields:
            if field not in config:
                issues.append(f"Source '{source_name}' missing required field: {field}")

        # Validate authority level
        auth_level = config.get("authority_level", 0)
        if not (1 <= auth_level <= 5):
            issues.append(f"Source '{source_name}' has invalid authority level: {auth_level}")

        # Validate URL format
        url = config.get("url", "")
        if not url.startswith(("http://", "https://")):
            issues.append(f"Source '{source_name}' has invalid URL: {url}")

    return {
        "total_sources": len(NEWS_SOURCES),
        "issues": issues,
        "valid": len(issues) == 0,
    }
