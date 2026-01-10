"""Abstract base class for all OSINT agents."""

from abc import ABC, abstractmethod
import uuid
from datetime import datetime
from loguru import logger


class BaseAgent(ABC):
    """
    Abstract base class defining the common interface for all agents.

    Provides unique identification, logging context binding, and
    standardized capabilities discovery. All concrete agents must
    implement the process() method for task execution and
    get_capabilities() for capability advertisement.

    Attributes:
        agent_id: Unique UUID identifier for this agent instance
        name: Human-readable agent name
        description: Brief description of agent purpose
        logger: Loguru logger bound with agent context
        created_at: UTC timestamp of agent instantiation
    """

    def __init__(self, name: str, description: str = ""):
        """
        Initialize base agent with common attributes.

        Args:
            name: Human-readable agent name
            description: Optional description of agent purpose
        """
        self.agent_id = str(uuid.uuid4())
        self.name = name
        self.description = description
        self.logger = logger.bind(agent_id=self.agent_id, agent_name=name)
        self.created_at = datetime.utcnow()

        self.logger.info(f"Agent {name} initialized with ID {self.agent_id}")

    @abstractmethod
    async def process(self, input_data: dict) -> dict:
        """
        Process input data and return results.

        This is the core execution method that all agents must implement.
        Should handle errors gracefully and return structured results.

        Args:
            input_data: Dictionary containing task parameters and data

        Returns:
            Dictionary containing processing results and status
        """
        pass

    @abstractmethod
    def get_capabilities(self) -> list[str]:
        """
        Return list of agent capabilities.

        Used for agent discovery and task routing. Capabilities should
        be concise strings identifying specific skills or functions.

        Returns:
            List of capability identifiers
        """
        pass
