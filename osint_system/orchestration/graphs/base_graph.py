"""Base workflow graph using LangGraph StateGraph."""

from typing import Dict, Any, List, Literal, Optional, Sequence, TypedDict
from langgraph.graph import StateGraph, END, MessagesState
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from loguru import logger
import asyncio


class AgentState(TypedDict):
    """State for agent workflow execution."""

    messages: Sequence[BaseMessage]
    next_agent: str
    task_result: Optional[Dict[str, Any]]
    routing_history: List[str]
    current_agent: str
    error: Optional[str]


class OrchestratorGraph:
    """
    Workflow graph for agent orchestration using LangGraph.

    Creates a dynamic graph structure where a supervisor routes
    tasks to specialized agent nodes based on capabilities.
    """

    def __init__(self, supervisor=None):
        """
        Initialize the orchestrator graph.

        Args:
            supervisor: Optional SupervisorAgent instance for routing
        """
        self.supervisor = supervisor
        self.graph = StateGraph(AgentState)
        self._agent_nodes = {}
        self.logger = logger.bind(component="OrchestratorGraph")
        self._compiled_app = None

        # Add supervisor as entry point
        self._setup_supervisor_node()

        self.logger.info("OrchestratorGraph initialized")

    def _setup_supervisor_node(self):
        """Set up the supervisor node as the entry point."""

        async def supervisor_node(state: AgentState) -> AgentState:
            """Supervisor analyzes state and decides routing."""
            messages = state.get("messages", [])
            routing_history = state.get("routing_history", [])

            if not messages:
                self.logger.warning("No messages in state for routing")
                return {
                    **state,
                    "next_agent": END,
                    "error": "No messages to process"
                }

            # Get last message for task analysis
            last_message = messages[-1] if messages else None
            if not last_message:
                return {
                    **state,
                    "next_agent": END,
                    "error": "No task message found"
                }

            task_content = last_message.content if hasattr(last_message, 'content') else str(last_message)

            # Use supervisor if available, otherwise simple routing
            if self.supervisor:
                routing_decision = await self.supervisor.supervisor_node({"messages": messages})
                next_agent = routing_decision.get("next_agent", END)
                reason = routing_decision.get("reason", "Unknown")

                self.logger.info(f"Supervisor routing decision",
                               next_agent=next_agent,
                               reason=reason)
            else:
                # Simple fallback routing without supervisor
                if "research" in task_content.lower():
                    next_agent = "research_agent"
                elif "analysis" in task_content.lower():
                    next_agent = "analysis_agent"
                else:
                    next_agent = "simple_agent"

                self.logger.info(f"Fallback routing", next_agent=next_agent)

            # Update routing history
            routing_history.append(next_agent)

            return {
                **state,
                "next_agent": next_agent,
                "routing_history": routing_history,
                "current_agent": "supervisor"
            }

        # Add supervisor node to graph
        self.graph.add_node("supervisor", supervisor_node)
        self.graph.set_entry_point("supervisor")

    def add_agent_node(self, name: str, agent_func):
        """
        Add an agent node to the graph.

        Args:
            name: Unique name for the agent node
            agent_func: Async function that processes state
        """
        async def agent_wrapper(state: AgentState) -> AgentState:
            """Wrapper to handle agent execution."""
            try:
                self.logger.info(f"Executing agent: {name}")

                # Call the agent function
                result = await agent_func(state)

                # Append result as message
                messages = list(state.get("messages", []))
                if isinstance(result, dict):
                    messages.append(AIMessage(content=f"Agent {name} result: {result}"))
                elif isinstance(result, str):
                    messages.append(AIMessage(content=result))

                return {
                    **state,
                    "messages": messages,
                    "task_result": result if isinstance(result, dict) else {"output": result},
                    "current_agent": name,
                    "next_agent": "supervisor"  # Return to supervisor
                }

            except Exception as e:
                self.logger.error(f"Agent {name} failed: {e}")
                return {
                    **state,
                    "error": str(e),
                    "current_agent": name,
                    "next_agent": END
                }

        # Add node to graph if it doesn't already exist
        if name not in self.graph.nodes:
            self.graph.add_node(name, agent_wrapper)
            self._agent_nodes[name] = agent_func

            # Add edge from this agent back to supervisor
            self.graph.add_edge(name, "supervisor")
        else:
            # Update existing node
            self._agent_nodes[name] = agent_func
            self.logger.debug(f"Updated existing node: {name}")

        self.logger.info(f"Added agent node: {name}")

    def add_placeholder_agents(self):
        """Add placeholder nodes for common agent types."""

        async def research_agent(state: AgentState) -> str:
            """Placeholder research agent."""
            self.logger.info("Research agent executing (placeholder)")
            return "Research completed (placeholder)"

        async def analysis_agent(state: AgentState) -> str:
            """Placeholder analysis agent."""
            self.logger.info("Analysis agent executing (placeholder)")
            return "Analysis completed (placeholder)"

        async def simple_agent(state: AgentState) -> str:
            """Placeholder simple agent."""
            self.logger.info("Simple agent executing (placeholder)")
            return "Task processed (placeholder)"

        # Add placeholder nodes
        self.add_agent_node("research_agent", research_agent)
        self.add_agent_node("analysis_agent", analysis_agent)
        self.add_agent_node("simple_agent", simple_agent)

    def _routing_function(self, state: AgentState) -> str:
        """
        Conditional routing function for supervisor decisions.

        Args:
            state: Current workflow state

        Returns:
            Name of next node or END
        """
        next_agent = state.get("next_agent", END)

        # Check if agent exists
        if next_agent == END:
            return END
        elif next_agent in self._agent_nodes:
            return next_agent
        else:
            self.logger.warning(f"Unknown agent: {next_agent}, ending workflow")
            return END

    def compile(self):
        """
        Compile the graph into an executable application.

        Returns:
            Compiled LangGraph application
        """
        # Add conditional edges from supervisor
        self.graph.add_conditional_edges(
            "supervisor",
            self._routing_function,
            {
                **{name: name for name in self._agent_nodes.keys()},
                END: END
            }
        )

        # Compile the graph
        self._compiled_app = self.graph.compile()

        self.logger.info(f"Graph compiled with {len(self._agent_nodes)} agent nodes")
        return self._compiled_app

    async def execute(self, task: str) -> Dict[str, Any]:
        """
        Execute a task through the workflow.

        Args:
            task: Task description to process

        Returns:
            Execution results
        """
        if not self._compiled_app:
            self.compile()

        initial_state = {
            "messages": [HumanMessage(content=task)],
            "next_agent": "",
            "task_result": None,
            "routing_history": [],
            "current_agent": "start",
            "error": None
        }

        self.logger.info(f"Executing workflow for task: {task[:100]}...")

        try:
            # Run the workflow
            final_state = await self._compiled_app.ainvoke(initial_state)

            return {
                "success": final_state.get("error") is None,
                "result": final_state.get("task_result"),
                "routing_history": final_state.get("routing_history", []),
                "error": final_state.get("error"),
                "messages": final_state.get("messages", [])
            }

        except Exception as e:
            self.logger.error(f"Workflow execution failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "routing_history": initial_state.get("routing_history", [])
            }

    def visualize(self) -> str:
        """
        Generate a text representation of the graph structure.

        Returns:
            Text diagram of the graph
        """
        lines = ["Workflow Graph Structure:"]
        lines.append("  [START] -> supervisor")

        for agent_name in self._agent_nodes:
            lines.append(f"  supervisor -> {agent_name}")
            lines.append(f"  {agent_name} -> supervisor")

        lines.append("  supervisor -> [END]")

        return "\n".join(lines)


def create_base_graph(supervisor=None) -> OrchestratorGraph:
    """
    Factory function to create a base workflow graph.

    Args:
        supervisor: Optional SupervisorAgent for routing

    Returns:
        Configured OrchestratorGraph instance
    """
    graph = OrchestratorGraph(supervisor=supervisor)

    # Add placeholder agents
    graph.add_placeholder_agents()

    # Compile the graph
    graph.compile()

    logger.info("Base graph created and compiled")
    return graph