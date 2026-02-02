"""Base class for sifter agents that process and analyze crawled content.

Sifters are the analytical arm of the OSINT system. Unlike crawlers that acquire
raw data, sifters transform raw content into structured intelligence:
- FactExtractionAgent: Text -> ExtractedFact objects
- FactClassificationAgent: ExtractedFact -> Classified facts (critical/dubious)
- VerificationAgent: Dubious facts -> Verification verdicts

All sifters inherit from this base class and implement the sift() method.
"""

from abc import abstractmethod
from typing import Any

from osint_system.agents.base_agent import BaseAgent


class BaseSifter(BaseAgent):
    """
    Abstract base for sifter agents.

    Sifters receive raw content from crawlers and produce structured
    intelligence outputs (facts, classifications, verifications).

    Unlike crawlers that acquire data, sifters analyze and transform it.
    The process() method is implemented to route to the abstract sift()
    method, which subclasses must implement.

    Attributes:
        processed_count: Number of successfully processed items.
        error_count: Number of failed processing attempts.
    """

    def __init__(self, name: str, description: str = "", **kwargs):
        """
        Initialize base sifter with tracking counters.

        Args:
            name: Human-readable agent name.
            description: Brief description of agent purpose.
            **kwargs: Additional arguments passed to BaseAgent.
        """
        super().__init__(name=name, description=description, **kwargs)
        self.processed_count: int = 0
        self.error_count: int = 0

    @abstractmethod
    async def sift(self, content: dict) -> list[dict]:
        """
        Process content and extract structured output.

        This is the core analytical method. Subclasses implement specific
        extraction, classification, or verification logic here.

        Args:
            content: Raw content dict. Expected keys vary by sifter type:
                - FactExtractionAgent: 'text', 'source_id', 'metadata'
                - ClassificationAgent: 'facts' (list of ExtractedFact dicts)
                - VerificationAgent: 'fact', 'search_results'

        Returns:
            List of extracted items as dicts. The schema depends on sifter type:
                - FactExtractionAgent: List of ExtractedFact dicts
                - ClassificationAgent: List of ClassifiedFact dicts
                - VerificationAgent: List of VerificationResult dicts
        """
        pass

    async def process(self, input_data: dict) -> dict:
        """
        BaseAgent.process implementation routing to sift().

        Wraps sift() with error handling and metrics tracking.
        This method satisfies the BaseAgent abstract contract.

        Args:
            input_data: Dict with 'content' key containing data to process.

        Returns:
            Dict with:
                - success: bool
                - results: list of extracted items
                - count: number of items extracted
                - error: error message if failed
        """
        try:
            results = await self.sift(input_data.get("content", {}))
            self.processed_count += 1
            return {
                "success": True,
                "results": results,
                "count": len(results),
            }
        except Exception as e:
            self.error_count += 1
            self.logger.error(f"Sift failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "results": [],
            }

    def get_capabilities(self) -> list[str]:
        """
        Return base sifter capabilities.

        Subclasses should override to add specific capabilities
        (e.g., 'fact_extraction', 'classification', 'verification').

        Returns:
            List of capability identifiers.
        """
        return ["sifting", "analysis"]

    def get_stats(self) -> dict:
        """
        Return processing statistics.

        Returns:
            Dict with processed_count, error_count, and error_rate.
        """
        total = self.processed_count + self.error_count
        error_rate = self.error_count / total if total > 0 else 0.0
        return {
            "processed_count": self.processed_count,
            "error_count": self.error_count,
            "error_rate": error_rate,
        }
