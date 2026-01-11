"""LangGraph supervisor agent for coordinating multiple workers."""

from typing import Dict, List, Any, Optional, Callable, Literal
from dataclasses import dataclass, field
import asyncio
from loguru import logger
from langgraph.graph import MessagesState
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage


@dataclass
class AgentCapability:
    """Represents a registered agent and its capabilities."""

    name: str
    capabilities: List[str]
    callback: Optional[Callable] = None
    keywords: List[str] = field(default_factory=list)


class SupervisorAgent:
    """
    Supervisor agent using LangGraph patterns for orchestration.

    Routes tasks to specialized worker agents based on their capabilities
    and the task requirements. Uses keyword matching and capability
    analysis for intelligent routing decisions.
    """

    def __init__(self, gemini_client=None):
        """
        Initialize the supervisor agent.

        Args:
            gemini_client: Optional Gemini client for LLM-based routing decisions
        """
        self._agents: Dict[str, AgentCapability] = {}
        self._gemini_client = gemini_client
        self.logger = logger.bind(component="SupervisorAgent")

        # Default routing keywords for common agent types
        self._routing_keywords = {
            "research": ["research", "search", "find", "discover", "investigate"],
            "analysis": ["analyze", "assess", "evaluate", "interpret", "examine"],
            "extraction": ["extract", "parse", "collect", "gather", "retrieve"],
            "verification": ["verify", "validate", "confirm", "check", "authenticate"],
            "reporting": ["report", "summarize", "synthesize", "compile", "present"]
        }

        self.logger.info("SupervisorAgent initialized")

    def register_agent(self, name: str, capabilities: List[str],
                      keywords: Optional[List[str]] = None,
                      callback: Optional[Callable] = None):
        """
        Register a worker agent with its capabilities.

        Args:
            name: Agent identifier
            capabilities: List of capabilities this agent provides
            keywords: Optional task keywords this agent handles
            callback: Optional callback function for direct invocation
        """
        agent = AgentCapability(
            name=name,
            capabilities=capabilities,
            callback=callback,
            keywords=keywords or []
        )

        self._agents[name] = agent

        # Auto-detect keywords from capabilities if not provided
        if not agent.keywords:
            for cap in capabilities:
                cap_lower = cap.lower()
                for category, category_keywords in self._routing_keywords.items():
                    if any(kw in cap_lower for kw in category_keywords):
                        agent.keywords.extend(category_keywords)
                        break

        self.logger.info(f"Registered agent: {name}",
                        capabilities=capabilities,
                        keywords=agent.keywords[:5])  # Log first 5 keywords

    def unregister_agent(self, name: str):
        """
        Remove an agent from the supervisor's registry.

        Args:
            name: Agent identifier to remove
        """
        if name in self._agents:
            del self._agents[name]
            self.logger.info(f"Unregistered agent: {name}")
        else:
            self.logger.warning(f"Agent not found for unregistration: {name}")

    def analyze_task(self, task_description: str) -> Dict[str, Any]:
        """
        Analyze a task description to determine routing.

        Args:
            task_description: Natural language task description

        Returns:
            Analysis results with routing recommendations
        """
        task_lower = task_description.lower()

        # Find matching agents based on keywords
        matches = []
        for agent_name, agent in self._agents.items():
            score = 0
            matched_keywords = []

            # Check keyword matches
            for keyword in agent.keywords:
                if keyword in task_lower:
                    score += 1
                    matched_keywords.append(keyword)

            # Check capability matches
            for capability in agent.capabilities:
                if capability.lower() in task_lower:
                    score += 2  # Capability match is weighted higher
                    matched_keywords.append(capability)

            if score > 0:
                matches.append({
                    "agent": agent_name,
                    "score": score,
                    "matched_keywords": matched_keywords,
                    "capabilities": agent.capabilities
                })

        # Sort by score (highest first)
        matches.sort(key=lambda x: x["score"], reverse=True)

        return {
            "task": task_description,
            "matches": matches,
            "recommended_agent": matches[0]["agent"] if matches else None,
            "confidence": "high" if matches and matches[0]["score"] > 2 else "medium" if matches else "low"
        }

    async def supervisor_node(self, state: MessagesState) -> Dict[str, Any]:
        """
        Supervisor node function for LangGraph integration.

        Analyzes the current state and decides which agent to route to next.

        Args:
            state: Current conversation/workflow state

        Returns:
            Routing decision with next agent selection
        """
        messages = state.get("messages", [])

        if not messages:
            return {"next_agent": "END", "reason": "No messages to process"}

        # Get the last human message for task analysis
        last_task = None
        for msg in reversed(messages):
            if isinstance(msg, (HumanMessage, str)):
                last_task = str(msg.content) if hasattr(msg, 'content') else str(msg)
                break

        if not last_task:
            return {"next_agent": "END", "reason": "No task found in messages"}

        # Analyze the task
        analysis = self.analyze_task(last_task)

        self.logger.info("Routing decision made",
                        task=last_task[:100],  # First 100 chars
                        selected_agent=analysis["recommended_agent"],
                        confidence=analysis["confidence"])

        if analysis["recommended_agent"]:
            return {
                "next_agent": analysis["recommended_agent"],
                "reason": f"Matched keywords: {analysis['matches'][0]['matched_keywords'][:3]}",
                "confidence": analysis["confidence"],
                "analysis": analysis
            }
        else:
            # Fallback routing
            return {
                "next_agent": "simple_agent",  # Default fallback
                "reason": "No specific match, using default agent",
                "confidence": "low",
                "analysis": analysis
            }

    def route_task(self, task: str) -> Optional[str]:
        """
        Simple synchronous routing for direct use without LangGraph.

        Args:
            task: Task description

        Returns:
            Name of the recommended agent or None
        """
        analysis = self.analyze_task(task)
        return analysis["recommended_agent"]

    async def route_task_async(self, task: str) -> Optional[str]:
        """
        Async version of route_task for async contexts.

        Args:
            task: Task description

        Returns:
            Name of the recommended agent or None
        """
        return self.route_task(task)

    def get_registered_agents(self) -> List[str]:
        """
        Get list of all registered agent names.

        Returns:
            List of agent names
        """
        return list(self._agents.keys())

    def get_agent_capabilities(self, agent_name: str) -> Optional[List[str]]:
        """
        Get capabilities of a specific agent.

        Args:
            agent_name: Name of the agent

        Returns:
            List of capabilities or None if agent not found
        """
        agent = self._agents.get(agent_name)
        return agent.capabilities if agent else None

    def describe_routing_logic(self) -> str:
        """
        Generate human-readable description of current routing configuration.

        Returns:
            Description of routing logic
        """
        lines = ["Supervisor Routing Configuration:"]
        lines.append(f"Registered agents: {len(self._agents)}")

        for name, agent in self._agents.items():
            lines.append(f"\n  Agent: {name}")
            lines.append(f"    Capabilities: {', '.join(agent.capabilities)}")
            if agent.keywords:
                lines.append(f"    Keywords: {', '.join(agent.keywords[:5])}...")

        return "\n".join(lines)