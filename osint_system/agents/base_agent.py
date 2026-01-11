"""Abstract base class for all OSINT agents."""

from abc import ABC, abstractmethod
import uuid
from datetime import datetime
from typing import Optional, Any
import asyncio
from loguru import logger


class BaseAgent(ABC):
    """
    Abstract base class defining the common interface for all agents.

    Provides unique identification, logging context binding, and
    standardized capabilities discovery. All concrete agents must
    implement the process() method for task execution and
    get_capabilities() for capability advertisement.

    Optionally supports MCP (Model Context Protocol) client for tool access.

    Attributes:
        agent_id: Unique UUID identifier for this agent instance
        name: Human-readable agent name
        description: Brief description of agent purpose
        logger: Loguru logger bound with agent context
        created_at: UTC timestamp of agent instantiation
        mcp_enabled: Whether MCP client is enabled for this agent
        mcp_client: Optional MCP client session for tool access
        mcp_server_command: Optional command to start MCP server
    """

    def __init__(
        self,
        name: str,
        description: str = "",
        mcp_enabled: bool = False,
        mcp_server_command: Optional[list[str]] = None,
    ):
        """
        Initialize base agent with common attributes and optional MCP support.

        Args:
            name: Human-readable agent name
            description: Optional description of agent purpose
            mcp_enabled: Whether to enable MCP client for tool access
            mcp_server_command: Command to start MCP server (e.g., ["python", "tool_server.py"])
        """
        self.agent_id = str(uuid.uuid4())
        self.name = name
        self.description = description
        self.logger = logger.bind(agent_id=self.agent_id, agent_name=name)
        self.created_at = datetime.utcnow()

        # MCP client configuration
        self.mcp_enabled = mcp_enabled
        self.mcp_server_command = mcp_server_command
        self.mcp_client = None
        self._mcp_session = None

        self.logger.info(
            f"Agent {name} initialized with ID {self.agent_id}",
            mcp_enabled=mcp_enabled
        )

    async def _initialize_mcp_client(self) -> None:
        """
        Initialize MCP client session if enabled.

        This method attempts to connect to an MCP server using the stdio protocol.
        If MCP is not available or fails to initialize, it logs a warning but
        continues operation without MCP support.
        """
        if not self.mcp_enabled or not self.mcp_server_command:
            return

        try:
            # Try to import MCP components - if not available, skip
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            # Set up stdio connection to MCP server
            params = StdioServerParameters(
                command=self.mcp_server_command[0],
                args=self.mcp_server_command[1:] if len(self.mcp_server_command) > 1 else []
            )

            self._read_stream, self._write_stream = await stdio_client(params).__aenter__()
            self._mcp_session = ClientSession(self._read_stream, self._write_stream)
            await self._mcp_session.initialize()

            self.mcp_client = self._mcp_session
            self.logger.info("MCP client initialized successfully")

        except ImportError:
            self.logger.warning("MCP not available - agent will run without tool access")
            self.mcp_enabled = False
        except Exception as e:
            self.logger.error(f"Failed to initialize MCP client: {e}")
            self.mcp_enabled = False

    async def _cleanup_mcp_client(self) -> None:
        """Clean up MCP client session on agent shutdown."""
        if self._mcp_session:
            try:
                await self._mcp_session.__aexit__(None, None, None)
                self.logger.info("MCP client cleaned up")
            except Exception as e:
                self.logger.error(f"Error cleaning up MCP client: {e}")

    async def __aenter__(self):
        """Async context manager entry - initializes MCP if enabled."""
        await self._initialize_mcp_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - cleans up MCP session."""
        await self._cleanup_mcp_client()

    async def call_tool(self, tool_name: str, arguments: dict) -> Any:
        """
        Call an MCP tool if client is available.

        Args:
            tool_name: Name of the tool to invoke
            arguments: Tool arguments as dictionary

        Returns:
            Tool execution result

        Raises:
            RuntimeError: If MCP is not enabled or tool call fails
        """
        if not self.mcp_client:
            raise RuntimeError("MCP client not initialized - enable MCP to use tools")

        try:
            result = await self.mcp_client.call_tool(tool_name, arguments)
            return result
        except Exception as e:
            self.logger.error(f"Tool call failed: {tool_name}", error=str(e))
            raise

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
