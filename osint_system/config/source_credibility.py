"""Source credibility configuration for fact classification.

Per Phase 7 CONTEXT.md:
- Pre-configured baselines for known sources (hybrid approach)
- Type-based defaults for unknown sources
- Proximity decay factor for hop count

Source hierarchy (from most to least credible):
1. Wire services (Reuters, AP, AFP): 0.9
2. Official government sources (.gov): 0.85
3. Educational/research (.edu): 0.85
4. Major news outlets (BBC, NYT): 0.8
5. Regional/specialty news: 0.7
6. Non-profit organizations (.org): 0.7
7. Social media: 0.3
8. Anonymous/unknown: 0.2
"""

from typing import Dict

# Pre-configured baselines for known sources
# Key: domain or source identifier (lowercase)
# Value: credibility score 0.0-1.0
SOURCE_BASELINES: Dict[str, float] = {
    # Wire services (highest credibility)
    "reuters.com": 0.9,
    "apnews.com": 0.9,
    "afp.com": 0.9,
    "tass.com": 0.75,  # State-affiliated, lower than independent
    "xinhua.net": 0.7,  # State-affiliated

    # Major news outlets
    "bbc.com": 0.85,
    "bbc.co.uk": 0.85,
    "nytimes.com": 0.85,
    "washingtonpost.com": 0.85,
    "theguardian.com": 0.82,
    "economist.com": 0.85,
    "ft.com": 0.85,  # Financial Times
    "wsj.com": 0.85,  # Wall Street Journal
    "cnn.com": 0.75,
    "foxnews.com": 0.7,
    "aljazeera.com": 0.75,

    # Government sources (domain patterns handled separately)
    # These are defaults - specific .gov domains may override

    # Research/academic
    # .edu domains handled by type default

    # Known lower-credibility sources
    "rt.com": 0.4,  # State-controlled propaganda
    "sputniknews.com": 0.4,  # State-controlled propaganda
    "breitbart.com": 0.5,  # High bias
    "infowars.com": 0.2,  # Conspiracy/misinformation

    # Social media platforms (user-generated content)
    "twitter.com": 0.3,
    "x.com": 0.3,
    "reddit.com": 0.3,
    "facebook.com": 0.3,
    "telegram.org": 0.3,
}

# Type-based defaults for unknown sources
# Used when source not in SOURCE_BASELINES
SOURCE_TYPE_DEFAULTS: Dict[str, float] = {
    "wire_service": 0.85,
    "official_statement": 0.8,  # Government press releases
    "news_outlet": 0.6,  # Unknown news outlet
    "social_media": 0.3,
    "academic": 0.85,
    "document": 0.5,  # Leaked/unofficial documents
    "eyewitness": 0.6,  # Direct observation (varies widely)
    "unknown": 0.3,
}

# Domain pattern defaults (for TLD-based scoring)
DOMAIN_PATTERN_DEFAULTS: Dict[str, float] = {
    ".gov": 0.85,  # Government domains
    ".mil": 0.85,  # Military domains
    ".edu": 0.85,  # Educational institutions
    ".org": 0.7,   # Non-profit organizations
    ".int": 0.85,  # International organizations
}

# Proximity decay factor
# Per CONTEXT.md: 0.7^hop (moderate decay, secondary sources still meaningful)
# hop_count=0: 1.0, hop_count=1: 0.7, hop_count=2: 0.49, hop_count=3: 0.343
PROXIMITY_DECAY_FACTOR: float = 0.7

# Echo dampening factor (alpha)
# Per CONTEXT.md: alpha ~ 0.2
ECHO_DAMPENING_ALPHA: float = 0.2

# Precision scoring weights
PRECISION_WEIGHTS: Dict[str, float] = {
    "entity_count": 0.3,      # More entities = more precise
    "temporal_precision": 0.3, # Explicit dates = more precise
    "has_quote": 0.2,         # Direct quotes = more verifiable
    "has_document": 0.2,      # Document citation = more verifiable
}

# Entity significance scores (for impact assessment in Plan 03)
ENTITY_SIGNIFICANCE: Dict[str, float] = {
    "world_leader": 1.0,      # Presidents, prime ministers
    "senior_official": 0.8,   # Cabinet members, ambassadors
    "military_commander": 0.8,
    "government_official": 0.6,
    "company_executive": 0.5,
    "public_figure": 0.4,
    "organization": 0.4,
    "location_major": 0.6,    # Capitals, major cities
    "location_minor": 0.3,
    "unknown": 0.3,
}

# Event type significance (for impact assessment in Plan 03)
EVENT_TYPE_SIGNIFICANCE: Dict[str, float] = {
    "military_action": 1.0,
    "treaty_agreement": 0.9,
    "sanctions": 0.9,
    "diplomatic_meeting": 0.7,
    "policy_announcement": 0.6,
    "official_statement": 0.5,
    "routine_activity": 0.2,
    "unknown": 0.3,
}
