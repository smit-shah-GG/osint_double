"""Coordinator that integrates supervisor, registry, and message bus."""

from typing import Dict, Any, Optional, List
import asyncio
from loguru import logger
from osint_system.agents.registry import AgentRegistry
from osint_system.agents.communication.bus import MessageBus
from osint_system.orchestration.supervisor import SupervisorAgent
from osint_system.orchestration.graphs.base_graph import OrchestratorGraph
from osint_system.agents.simple_agent import SimpleAgent


class Coordinator:
    """
    Central coordinator that ties together supervisor, registry, and message bus.

    Provides high-level interface for executing objectives through the
    multi-agent system. Discovers available agents, constructs dynamic
    workflows, and handles failures gracefully.
    """

    def __init__(self, gemini_client=None):
        """
        Initialize the coordinator.

        Args:
            gemini_client: Optional Gemini client for agents
        """
        self.gemini_client = gemini_client
        self.registry = AgentRegistry()
        self.message_bus = MessageBus()
        self.supervisor = SupervisorAgent(gemini_client=gemini_client)
        self._graph = None
        self._agents = {}  # name -> agent instance
        self.logger = logger.bind(component="Coordinator")

        # Create fallback simple agent
        self._simple_agent = SimpleAgent()

        self.logger.info("Coordinator initialized")

    async def initialize(self):
        """
        Initialize all components and discover agents.

        Sets up heartbeat monitoring, subscribes to discovery,
        and builds initial workflow graph.
        """
        try:
            # Start registry heartbeat monitoring
            await self.registry.start_heartbeat_monitoring()

            # Subscribe registry to discovery messages
            await self.registry.subscribe_to_discovery(self.message_bus)

            # Register simple agent as fallback
            await self.registry.register_agent(
                name="simple_agent",
                capabilities=["general", "fallback", "basic_processing"],
                metadata={"type": "fallback"}
            )

            # Register simple agent with supervisor
            self.supervisor.register_agent(
                name="simple_agent",
                capabilities=["general", "fallback", "basic_processing"],
                keywords=["general", "simple", "basic", "default"]
            )

            # Build initial graph
            await self._build_workflow_graph()

            self.logger.info("Coordinator initialized successfully")

        except Exception as e:
            self.logger.error(f"Coordinator initialization failed: {e}")
            raise

    async def _build_workflow_graph(self):
        """
        Build or rebuild the workflow graph based on available agents.

        Discovers agents from registry and creates graph nodes dynamically.
        """
        # Create new graph with supervisor
        self._graph = OrchestratorGraph(supervisor=self.supervisor)

        # Get all active agents
        active_agents = await self.registry.get_active_agents()

        self.logger.info(f"Building graph with {len(active_agents)} active agents")

        # Add each agent as a node
        for agent_info in active_agents:
            agent_name = agent_info.name

            # Create agent function wrapper
            async def agent_func(state, name=agent_name):
                """Execute agent and return result."""
                agent = self._agents.get(name)

                if agent and hasattr(agent, 'process'):
                    # Use agent's process method if available
                    result = await agent.process(state.get("messages", []))
                    return result
                else:
                    # Fallback execution
                    self.logger.warning(f"Agent {name} has no process method, using fallback")
                    return f"Agent {name} processed task (fallback)"

            # Add node to graph
            self._graph.add_agent_node(agent_name, agent_func)

            # Register with supervisor for routing
            self.supervisor.register_agent(
                name=agent_name,
                capabilities=agent_info.capabilities
            )

        # Add placeholder agents if needed
        if len(active_agents) < 2:
            self.logger.info("Adding placeholder agents to graph")
            self._graph.add_placeholder_agents()

            # Register placeholders with supervisor
            for name in ["research_agent", "analysis_agent"]:
                self.supervisor.register_agent(
                    name=name,
                    capabilities=[name.replace("_agent", "")],
                    keywords=[name.split("_")[0]]
                )

        # Compile the graph
        self._graph.compile()

        self.logger.info("Workflow graph built and compiled",
                        nodes=len(self._graph._agent_nodes))

    async def discover_agents(self) -> List[str]:
        """
        Discover available agents via the registry.

        Returns:
            List of discovered agent names
        """
        active_agents = await self.registry.get_active_agents()
        agent_names = [agent.name for agent in active_agents]

        self.logger.info(f"Discovered {len(agent_names)} agents: {agent_names}")
        return agent_names

    async def execute_workflow(self, objective: str) -> Dict[str, Any]:
        """
        Execute a workflow for the given objective.

        Args:
            objective: Natural language description of the task

        Returns:
            Execution results with success status and outputs
        """
        self.logger.info(f"Executing workflow for objective: {objective[:100]}...")

        try:
            # Ensure graph is built
            if not self._graph:
                await self._build_workflow_graph()

            # Analyze objective for routing
            routing_analysis = self.supervisor.analyze_task(objective)

            self.logger.info("Routing analysis complete",
                           recommended_agent=routing_analysis.get("recommended_agent"),
                           confidence=routing_analysis.get("confidence"))

            # Execute through graph
            result = await self._graph.execute(objective)

            # Log execution summary
            self.logger.info("Workflow execution complete",
                           success=result.get("success"),
                           routing_history=result.get("routing_history"))

            return result

        except Exception as e:
            self.logger.error(f"Workflow execution failed: {e}", exc_info=True)

            # Fallback to simple agent
            try:
                self.logger.info("Attempting fallback with SimpleAgent")
                fallback_result = await self._simple_agent.process({"task": objective})

                return {
                    "success": True,
                    "result": fallback_result,
                    "routing_history": ["simple_agent (fallback)"],
                    "error": f"Primary workflow failed: {e}, used fallback"
                }

            except Exception as fallback_error:
                self.logger.error(f"Fallback also failed: {fallback_error}")
                return {
                    "success": False,
                    "error": f"All execution paths failed: {e}, {fallback_error}",
                    "routing_history": []
                }

    async def register_agent(self, agent_instance):
        """
        Register a new agent with the coordinator.

        Args:
            agent_instance: Agent instance with name and capabilities attributes
        """
        if not hasattr(agent_instance, 'name') or not hasattr(agent_instance, 'capabilities'):
            raise ValueError("Agent must have 'name' and 'capabilities' attributes")

        agent_name = agent_instance.name
        capabilities = agent_instance.capabilities

        # Store agent instance
        self._agents[agent_name] = agent_instance

        # Register with registry
        await self.registry.register_agent(
            name=agent_name,
            capabilities=capabilities,
            metadata={"type": type(agent_instance).__name__}
        )

        # Rebuild graph to include new agent
        await self._build_workflow_graph()

        self.logger.info(f"Registered new agent: {agent_name}",
                        capabilities=capabilities)

    async def unregister_agent(self, agent_name: str):
        """
        Remove an agent from the coordinator.

        Args:
            agent_name: Name of the agent to remove
        """
        # Remove from internal storage
        if agent_name in self._agents:
            del self._agents[agent_name]

        # Unregister from registry
        await self.registry.unregister_agent(agent_name)

        # Unregister from supervisor
        self.supervisor.unregister_agent(agent_name)

        # Rebuild graph without this agent
        await self._build_workflow_graph()

        self.logger.info(f"Unregistered agent: {agent_name}")

    def describe_system(self) -> str:
        """
        Generate a human-readable description of the system state.

        Returns:
            System description
        """
        lines = ["=== Coordinator System State ==="]

        # Registry stats
        stats = self.registry.get_statistics()
        lines.append(f"\nRegistry: {stats['active_agents']} active agents")

        # Supervisor routing
        lines.append(f"\n{self.supervisor.describe_routing_logic()}")

        # Graph structure
        if self._graph:
            lines.append(f"\n{self._graph.visualize()}")

        return "\n".join(lines)

    async def shutdown(self):
        """
        Gracefully shutdown the coordinator and all components.
        """
        self.logger.info("Shutting down coordinator")

        try:
            # Stop heartbeat monitoring
            await self.registry.stop_heartbeat_monitoring()

            # Close message bus connections
            await self.message_bus.close()

            self.logger.info("Coordinator shutdown complete")

        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}")