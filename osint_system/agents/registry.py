"""Agent registry for discovery and capability-based lookup."""

import asyncio
from typing import Dict, List, Optional, Set, Any
from datetime import datetime, timedelta
import uuid
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class AgentInfo:
    """Information about a registered agent."""

    id: str
    name: str
    capabilities: List[str] = field(default_factory=list)
    status: str = "active"  # active, inactive, unknown
    last_seen: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


class AgentRegistry:
    """
    Registry for agent discovery and tracking.

    Maintains a directory of active agents with their capabilities,
    enabling capability-based lookup and service discovery.

    Features:
    - Agent registration with capabilities
    - Capability-based search
    - Heartbeat monitoring
    - Auto-discovery via message bus
    - Thread-safe operations
    """

    def __init__(self, heartbeat_timeout_seconds: int = 60):
        """
        Initialize the agent registry.

        Args:
            heartbeat_timeout_seconds: Time before marking agent as inactive
        """
        self._agents: Dict[str, AgentInfo] = {}
        self._capability_index: Dict[str, Set[str]] = {}  # capability -> agent_ids
        self._lock = asyncio.Lock()
        self._heartbeat_timeout = timedelta(seconds=heartbeat_timeout_seconds)
        self.logger = logger.bind(component="AgentRegistry")
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._message_bus = None  # Will be set when subscribing to discovery

        self.logger.info("AgentRegistry initialized",
                        heartbeat_timeout=heartbeat_timeout_seconds)

    async def register_agent(self, name: str, capabilities: List[str],
                           agent_id: Optional[str] = None,
                           metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Register an agent with the registry.

        Args:
            name: Human-readable agent name
            capabilities: List of capability strings
            agent_id: Optional agent ID (generated if not provided)
            metadata: Optional metadata about the agent

        Returns:
            The agent's ID
        """
        async with self._lock:
            # Generate ID if not provided
            if not agent_id:
                agent_id = str(uuid.uuid4())

            # Create or update agent info
            agent_info = AgentInfo(
                id=agent_id,
                name=name,
                capabilities=capabilities,
                status="active",
                last_seen=datetime.utcnow(),
                metadata=metadata or {}
            )

            # If agent already exists, clean up old capability index
            if agent_id in self._agents:
                old_agent = self._agents[agent_id]
                for capability in old_agent.capabilities:
                    if capability in self._capability_index:
                        self._capability_index[capability].discard(agent_id)

            # Store agent
            self._agents[agent_id] = agent_info

            # Update capability index
            for capability in capabilities:
                if capability not in self._capability_index:
                    self._capability_index[capability] = set()
                self._capability_index[capability].add(agent_id)

            self.logger.info(f"Agent registered: {name}",
                           agent_id=agent_id,
                           capabilities=capabilities)

            return agent_id

    async def unregister_agent(self, agent_id: str) -> bool:
        """
        Remove an agent from the registry.

        Args:
            agent_id: The agent's ID

        Returns:
            True if agent was removed, False if not found
        """
        async with self._lock:
            if agent_id not in self._agents:
                self.logger.warning(f"Agent not found for unregistration: {agent_id}")
                return False

            agent_info = self._agents[agent_id]

            # Remove from capability index
            for capability in agent_info.capabilities:
                if capability in self._capability_index:
                    self._capability_index[capability].discard(agent_id)
                    # Clean up empty sets
                    if not self._capability_index[capability]:
                        del self._capability_index[capability]

            # Remove agent
            del self._agents[agent_id]

            self.logger.info(f"Agent unregistered: {agent_info.name}",
                           agent_id=agent_id)
            return True

    async def find_agents_by_capability(self, capability: str) -> List[AgentInfo]:
        """
        Find all agents with a specific capability.

        Args:
            capability: The capability to search for

        Returns:
            List of matching agents (may be empty)
        """
        async with self._lock:
            if capability not in self._capability_index:
                return []

            agent_ids = self._capability_index[capability]
            agents = []

            for agent_id in agent_ids:
                if agent_id in self._agents:
                    agent = self._agents[agent_id]
                    if agent.status == "active":
                        agents.append(agent)

            self.logger.debug(f"Found {len(agents)} agents with capability: {capability}")
            return agents

    async def get_active_agents(self) -> List[AgentInfo]:
        """
        Get all currently active agents.

        Returns:
            List of active agents
        """
        async with self._lock:
            active_agents = [
                agent for agent in self._agents.values()
                if agent.status == "active"
            ]

            self.logger.debug(f"Active agents: {len(active_agents)}/{len(self._agents)}")
            return active_agents

    async def get_agent(self, agent_id: str) -> Optional[AgentInfo]:
        """
        Get information about a specific agent.

        Args:
            agent_id: The agent's ID

        Returns:
            AgentInfo if found, None otherwise
        """
        async with self._lock:
            return self._agents.get(agent_id)

    async def update_heartbeat(self, agent_id: str) -> bool:
        """
        Update an agent's last seen timestamp.

        Args:
            agent_id: The agent's ID

        Returns:
            True if updated, False if agent not found
        """
        async with self._lock:
            if agent_id not in self._agents:
                return False

            agent = self._agents[agent_id]
            agent.last_seen = datetime.utcnow()
            agent.status = "active"

            self.logger.debug(f"Heartbeat updated for {agent.name}", agent_id=agent_id)
            return True

    async def check_heartbeats(self):
        """
        Check all agents for heartbeat timeout.

        Marks agents as inactive if they haven't been seen recently.
        """
        async with self._lock:
            now = datetime.utcnow()
            inactive_count = 0

            for agent_id, agent in self._agents.items():
                if agent.status == "active":
                    time_since_seen = now - agent.last_seen
                    if time_since_seen > self._heartbeat_timeout:
                        agent.status = "inactive"
                        inactive_count += 1
                        self.logger.warning(f"Agent marked inactive: {agent.name}",
                                          agent_id=agent_id,
                                          last_seen=agent.last_seen)

            if inactive_count > 0:
                self.logger.info(f"Marked {inactive_count} agents as inactive")

    async def start_heartbeat_monitoring(self):
        """
        Start the background task for heartbeat monitoring.
        """
        if self._heartbeat_task and not self._heartbeat_task.done():
            self.logger.warning("Heartbeat monitoring already running")
            return

        async def monitor():
            """Background task to periodically check heartbeats."""
            while True:
                try:
                    await asyncio.sleep(self._heartbeat_timeout.total_seconds() / 2)
                    await self.check_heartbeats()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self.logger.error(f"Heartbeat monitoring error: {e}", exc_info=True)

        self._heartbeat_task = asyncio.create_task(monitor())
        self.logger.info("Heartbeat monitoring started")

    async def stop_heartbeat_monitoring(self):
        """
        Stop the heartbeat monitoring task.
        """
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self.logger.info("Heartbeat monitoring stopped")

    async def subscribe_to_discovery(self, message_bus):
        """
        Subscribe to discovery messages on the message bus.

        Auto-registers agents that broadcast their capabilities.

        Args:
            message_bus: The MessageBus instance to subscribe to
        """
        self._message_bus = message_bus

        async def handle_announcement(message):
            """Handle capability announcement messages."""
            try:
                payload = message.get("payload", {})
                agent_name = payload.get("agent_name")
                capabilities = payload.get("capabilities", [])

                if agent_name and capabilities:
                    # Auto-register the announcing agent
                    await self.register_agent(agent_name, capabilities)
                    self.logger.info(f"Auto-registered agent from announcement: {agent_name}")

            except Exception as e:
                self.logger.error(f"Error handling announcement: {e}", exc_info=True)

        # Subscribe to discovery announcements
        self._message_bus.subscribe_to_pattern(
            "AgentRegistry",
            "discovery.announce",
            handle_announcement
        )

        self.logger.info("Subscribed to discovery announcements")

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get registry statistics for monitoring.

        Returns:
            Dictionary with registry stats
        """
        total_agents = len(self._agents)
        active_agents = sum(1 for a in self._agents.values() if a.status == "active")
        inactive_agents = sum(1 for a in self._agents.values() if a.status == "inactive")
        total_capabilities = len(self._capability_index)

        return {
            "total_agents": total_agents,
            "active_agents": active_agents,
            "inactive_agents": inactive_agents,
            "total_capabilities": total_capabilities,
            "capabilities": list(self._capability_index.keys())
        }

    async def __aenter__(self):
        """Async context manager entry."""
        await self.start_heartbeat_monitoring()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.stop_heartbeat_monitoring()