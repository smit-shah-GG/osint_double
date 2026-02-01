"""Crawler coordination components for collaborative intelligence gathering.

This module provides coordination infrastructure for crawlers to work together:
- URL deduplication and normalization
- Authority scoring for source prioritization
- Shared context for entity tracking and topic expansion
"""

# Lazy imports to allow incremental module creation
__all__ = [
    "URLManager",
    "AuthorityScorer",
    "ContextCoordinator",
]


def __getattr__(name: str):
    """Lazy import coordination components."""
    if name == "URLManager":
        from osint_system.agents.crawlers.coordination.url_manager import URLManager
        return URLManager
    elif name == "AuthorityScorer":
        from osint_system.agents.crawlers.coordination.authority_scorer import AuthorityScorer
        return AuthorityScorer
    elif name == "ContextCoordinator":
        from osint_system.agents.crawlers.coordination.context_coordinator import ContextCoordinator
        return ContextCoordinator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
