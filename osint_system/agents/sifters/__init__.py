"""Sifter agents for processing and analyzing crawled content.

Sifters are the analytical arm of the OSINT system:
- FactExtractionAgent: Text -> ExtractedFact objects
- FactConsolidator: Deduplicates and links variant facts
- FactClassificationAgent: ExtractedFact -> Classified facts (Phase 7)
- VerificationAgent: Dubious facts -> Verification verdicts
- AnalysisReportingAgent: Facts -> Intelligence products

All sifters inherit from BaseSifter and implement the sift() method.
"""

from osint_system.agents.sifters.base_sifter import BaseSifter
from osint_system.agents.sifters.fact_consolidator import FactConsolidator
from osint_system.agents.sifters.fact_extraction_agent import FactExtractionAgent
from osint_system.agents.sifters.fact_classification_agent import FactClassificationAgent

__all__ = [
    "BaseSifter",
    "FactConsolidator",
    "FactExtractionAgent",
    "FactClassificationAgent",
]
