"""Credibility scoring components for fact classification.

This package provides the building blocks for the CONTEXT.md credibility formula:
- SourceCredibilityScorer: Multi-factor credibility computation (SourceCred x Proximity x Precision)
- EchoDetector: Root source diversity and logarithmic echo dampening

The formula: Total = S_root + (alpha * log10(1 + sum(S_echoes)))
Prevents gaming via botnet spam by crushing additional echoes through logarithm.
"""

from osint_system.agents.sifters.credibility.source_scorer import (
    SourceCredibilityScorer,
    SourceScore,
)
from osint_system.agents.sifters.credibility.echo_detector import (
    EchoDetector,
    EchoScore,
    EchoCluster,
)

__all__ = [
    "SourceCredibilityScorer",
    "SourceScore",
    "EchoDetector",
    "EchoScore",
    "EchoCluster",
]
