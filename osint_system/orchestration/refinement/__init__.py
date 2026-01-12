"""Refinement subsystem for signal analysis and coverage tracking."""

from .analysis import calculate_signal_strength, CoverageMetrics, check_diminishing_returns

__all__ = [
    "calculate_signal_strength",
    "CoverageMetrics",
    "check_diminishing_returns",
]
