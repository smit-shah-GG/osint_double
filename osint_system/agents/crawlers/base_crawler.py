"""Base class for all crawler agents."""

from abc import abstractmethod
from typing import Optional, Any
from osint_system.agents.base_agent import BaseAgent


class BaseCrawler(BaseAgent):
    """
    Abstract base class for all data acquisition agents (crawlers).

    Crawlers are specialized agents responsible for fetching raw data from
    external sources (RSS feeds, web pages, APIs). They implement the
    generic crawler interface while delegating source-specific logic to
    subclasses.

    Attributes:
        source_configs: Dictionary of source configurations for this crawler
        investigation_context: Optional context about the current investigation
    """

    def __init__(
        self,
        name: str,
        description: str = "",
        source_configs: Optional[dict] = None,
        investigation_context: Optional[dict] = None,
        mcp_enabled: bool = False,
        mcp_server_command: Optional[list[str]] = None,
    ):
        """
        Initialize crawler agent.

        Args:
            name: Human-readable crawler name
            description: Optional description of crawler purpose
            source_configs: Dictionary of source-specific configurations
            investigation_context: Optional context about current investigation
            mcp_enabled: Whether to enable MCP client for tool access
            mcp_server_command: Command to start MCP server
        """
        super().__init__(
            name=name,
            description=description,
            mcp_enabled=mcp_enabled,
            mcp_server_command=mcp_server_command,
        )
        self.source_configs = source_configs or {}
        self.investigation_context = investigation_context or {}

    @abstractmethod
    async def fetch_data(self, source: str, **kwargs) -> dict:
        """
        Fetch raw data from a source.

        Must be implemented by subclasses. Should return structured data
        with raw content and metadata preserved.

        Args:
            source: Source identifier or URL
            **kwargs: Additional source-specific parameters

        Returns:
            Dictionary containing fetched data with metadata
        """
        pass

    @abstractmethod
    async def filter_relevance(self, data: dict) -> bool:
        """
        Determine if fetched data is relevant to investigation.

        Crawlers typically do minimal filtering, preferring to return all
        data and let downstream agents make prioritization decisions.

        Args:
            data: Fetched data to evaluate

        Returns:
            True if data is relevant, False otherwise
        """
        pass

    @abstractmethod
    async def extract_metadata(self, data: dict) -> dict:
        """
        Extract standardized metadata from source data.

        Ensures metadata consistency across different source types.
        Must preserve:
        - Source URL
        - Author/Publication
        - Publication date
        - Retrieval timestamp
        - Source credibility indicators

        Args:
            data: Fetched data with embedded metadata

        Returns:
            Standardized metadata dictionary
        """
        pass

    def get_capabilities(self) -> list[str]:
        """
        Return crawler capabilities.

        Returns:
            List of capability identifiers this crawler provides
        """
        return [
            "data_acquisition",
            "source_crawling",
            "metadata_extraction",
        ]
