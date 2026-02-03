"""Classification logic components for fact classification.

This module provides the core detection logic for the Taxonomy of Doubt
and impact assessment for Phase 7 fact classification.

Components:
    DubiousDetector: Boolean logic gates for PHANTOM/FOG/ANOMALY/NOISE detection
    DubiousResult: Container for detection results with flags and reasoning
    ImpactAssessor: Geopolitical impact tier determination (critical/less_critical)
    ImpactResult: Container for impact assessment results

Usage:
    from osint_system.agents.sifters.classification import DubiousDetector, ImpactAssessor

    detector = DubiousDetector()
    result = detector.detect(fact_dict, credibility_score=0.5)
    if result.flags:
        print(f"Dubious: {[f.value for f in result.flags]}")

    assessor = ImpactAssessor()
    impact = assessor.assess(fact_dict)
    print(f"Impact: {impact.tier.value}, score={impact.score}")
"""

from osint_system.agents.sifters.classification.dubious_detector import (
    DubiousDetector,
    DubiousResult,
)
from osint_system.agents.sifters.classification.impact_assessor import (
    ImpactAssessor,
    ImpactResult,
)

__all__ = [
    "DubiousDetector",
    "DubiousResult",
    "ImpactAssessor",
    "ImpactResult",
]
