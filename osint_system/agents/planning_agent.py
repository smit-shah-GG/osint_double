"""Planning & Orchestration Agent for objective decomposition and task distribution."""

import json
import uuid
from datetime import datetime
from typing import Any, Optional, Literal, AsyncIterator
import asyncio

from loguru import logger
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from osint_system.agents.base_agent import BaseAgent
from osint_system.orchestration.state_schemas import (
    OrchestratorState,
    Subtask,
    Finding,
    Conflict,
)
from osint_system.orchestration.task_queue import TaskQueue, Task
from osint_system.orchestration.refinement.analysis import (
    calculate_signal_strength,
    CoverageMetrics,
    check_diminishing_returns,
)
from osint_system.config.settings import settings


class PlanningOrchestrator(BaseAgent):
    """
    Intelligent coordinator agent for OSINT investigations.

    Decomposes objectives into actionable subtasks, orchestrates agent cohorts,
    evaluates findings through adaptive routing, and manages iterative refinement.

    Uses LangGraph StateGraph for workflow control and implements transparency
    features to explain routing decisions and provide status updates.

    Attributes:
        registry: AgentRegistry for discovering available agents
        message_bus: MessageBus for inter-agent communication
        gemini_client: Gemini API client for LLM operations
        graph: Compiled LangGraph StateGraph for workflow execution
    """

    def __init__(
        self,
        registry=None,
        message_bus=None,
        gemini_client=None,
        max_refinements: int = 7,
    ):
        """
        Initialize the Planning Orchestrator.

        Args:
            registry: AgentRegistry instance for agent discovery
            message_bus: MessageBus instance for inter-agent communication
            gemini_client: Gemini API client (uses default if not provided)
            max_refinements: Maximum refinement iterations to prevent infinite loops
        """
        super().__init__(
            name="PlanningOrchestrator",
            description="Decomposes objectives and orchestrates multi-agent investigations",
        )

        self.registry = registry
        self.message_bus = message_bus
        self.gemini_client = gemini_client or self._get_default_gemini_client()
        self.max_refinements = max_refinements

        # Thresholds for routing decisions
        self.signal_strength_threshold = 0.75
        self.coverage_target = {"source_diversity": 0.7, "geographic_coverage": 0.6}
        self.diminishing_returns_threshold = 0.2  # <20% new information = diminishing returns

        # Task management
        self.task_queue = TaskQueue()
        self.coverage_metrics = None  # Initialized per investigation
        self.previous_findings = []  # For diminishing returns detection

        # Build the LangGraph workflow
        self.graph = self._build_graph()

        self.logger.info(
            "PlanningOrchestrator initialized",
            max_refinements=max_refinements,
            registry_available=registry is not None,
            message_bus_available=message_bus is not None,
        )

    def _get_default_gemini_client(self):
        """Get or initialize the default Gemini client."""
        if hasattr(settings, "gemini_client"):
            return settings.gemini_client

        try:
            import google.generativeai as genai

            genai.configure(api_key=settings.GEMINI_API_KEY)
            return genai
        except Exception as e:
            self.logger.warning(f"Failed to initialize Gemini client: {e}")
            return None

    def _build_graph(self) -> Any:
        """
        Build the LangGraph StateGraph for orchestration workflow.

        Creates nodes for: analyze_objective, assign_agents, coordinate_execution,
        evaluate_findings. Implements adaptive routing based on findings analysis.

        Returns:
            Compiled graph with MemorySaver checkpointing
        """
        graph = StateGraph(OrchestratorState)

        # Add workflow nodes (keeping async for proper execution)
        graph.add_node("analyze_objective", self.analyze_objective)
        graph.add_node("assign_agents", self.assign_agents)
        graph.add_node("coordinate_execution", self.coordinate_execution)
        graph.add_node("evaluate_findings", self.evaluate_findings)
        graph.add_node("refine_approach", self.refine_approach)
        graph.add_node("synthesize_results", self.synthesize_results)

        # Set entry point
        graph.set_entry_point("analyze_objective")

        # Linear edges for initial analysis and assignment
        graph.add_edge("analyze_objective", "assign_agents")
        graph.add_edge("assign_agents", "coordinate_execution")
        graph.add_edge("coordinate_execution", "evaluate_findings")

        # Conditional edges based on evaluation
        graph.add_conditional_edges(
            "evaluate_findings",
            lambda x: x.get("next_action", "end"),
            {
                "explore": "assign_agents",  # More exploration
                "refine": "refine_approach",  # Refine current approach
                "synthesize": "synthesize_results",  # Produce final synthesis
                "end": END,  # End execution
            },
        )

        # Refinement loop back to assignment
        graph.add_edge("refine_approach", "assign_agents")

        # Final synthesis ends execution
        graph.add_edge("synthesize_results", END)

        # Add in-memory checkpointing for state persistence
        checkpointer = MemorySaver()
        compiled_graph = graph.compile(checkpointer=checkpointer)

        self.logger.info("LangGraph StateGraph built and compiled")
        return compiled_graph

    async def analyze_objective(self, state: OrchestratorState) -> OrchestratorState:
        """
        Decompose the objective into actionable subtasks.

        Uses Gemini API to intelligently break down the objective into discrete,
        verifiable subtasks with priorities and suggested agents.

        Args:
            state: Current orchestrator state

        Returns:
            Updated state with decomposed subtasks
        """
        objective = state.get("objective", "")

        if not objective:
            self.logger.warning("No objective provided to analyze")
            return {
                **state,
                "subtasks": [],
                "messages": state.get("messages", []) + ["No objective to analyze"],
            }

        self.logger.info(f"Analyzing objective: {objective[:100]}...")

        try:
            # Use Gemini to decompose objective
            subtasks = await self._decompose_objective(objective)

            reasoning = (
                f"Objective decomposed into {len(subtasks)} subtasks:\n"
                + "\n".join(
                    [f"  {i+1}. [{st['priority']}] {st['description']}" for i, st in enumerate(subtasks)]
                )
            )

            self.logger.info("Objective decomposition complete", count=len(subtasks))

            return {
                **state,
                "subtasks": subtasks,
                "refinement_count": 0,
                "coverage_metrics": {
                    "source_diversity": 0.0,
                    "geographic_coverage": 0.0,
                    "topical_coverage": 0.0,
                },
                "signal_strength": 0.0,
                "conflicts": [],
                "messages": state.get("messages", []) + [reasoning],
            }

        except Exception as e:
            self.logger.error(f"Objective decomposition failed: {e}")
            return {
                **state,
                "subtasks": [],
                "messages": state.get("messages", []) + [f"Error analyzing objective: {str(e)}"],
            }

    async def _decompose_objective(self, objective: str) -> list[dict]:
        """
        Use Gemini API to decompose objective into subtasks.

        Generates structured JSON output with subtask descriptions, priorities,
        and suggested investigation approaches.

        Args:
            objective: The investigation objective

        Returns:
            List of subtask dictionaries with id, description, priority
        """
        if not self.gemini_client:
            self.logger.warning("Gemini client not available, using fallback decomposition")
            return self._fallback_decompose_objective(objective)

        try:
            model = self.gemini_client.GenerativeModel("gemini-1.5-pro")

            prompt = f"""You are an expert OSINT researcher. Decompose the following investigation objective into actionable subtasks.

Objective: {objective}

Respond with a JSON array of subtasks. Each subtask should have:
- "id": unique identifier (e.g., "ST-001")
- "description": specific, verifiable investigation task
- "priority": 1-10 priority score (10 = critical, 1 = optional)
- "suggested_sources": list of recommended source types (news, social_media, documents, etc.)

Focus on concrete, testable investigations that can be verified against evidence.

Example format:
[
  {{"id": "ST-001", "description": "Find reports of X happening on date Y", "priority": 9, "suggested_sources": ["news", "documents"]}},
  {{"id": "ST-002", "description": "Identify key figures involved in X event", "priority": 8, "suggested_sources": ["social_media", "news"]}}
]

Respond with ONLY the JSON array, no other text."""

            response = model.generate_content(prompt)
            response_text = response.text.strip()

            # Extract JSON from response
            subtasks = json.loads(response_text)

            # Ensure all required fields exist
            for subtask in subtasks:
                if "id" not in subtask:
                    subtask["id"] = f"ST-{uuid.uuid4().hex[:8].upper()}"
                if "suggested_sources" not in subtask:
                    subtask["suggested_sources"] = []
                subtask["status"] = "pending"

            self.logger.info(f"Gemini decomposed objective into {len(subtasks)} subtasks")
            return subtasks

        except json.JSONDecodeError:
            self.logger.error("Failed to parse Gemini JSON response")
            return self._fallback_decompose_objective(objective)
        except Exception as e:
            self.logger.error(f"Gemini decomposition error: {e}")
            return self._fallback_decompose_objective(objective)

    def _fallback_decompose_objective(self, objective: str) -> list[dict]:
        """
        Fallback decomposition when Gemini is unavailable.

        Uses simple keyword-based splitting to create basic subtasks.

        Args:
            objective: The investigation objective

        Returns:
            List of basic subtask dictionaries
        """
        # Simple decomposition: treat key questions as subtasks
        keywords = ["who", "what", "where", "when", "why", "how"]
        subtasks = []

        for i, keyword in enumerate(keywords):
            if keyword in objective.lower():
                subtasks.append(
                    {
                        "id": f"ST-{i:03d}",
                        "description": f"Investigate {keyword} aspects of: {objective[:60]}...",
                        "priority": 8 - (i % 3),  # Stagger priorities
                        "suggested_sources": ["news", "documents"],
                        "status": "pending",
                    }
                )

        # If no keywords matched, create a single general task
        if not subtasks:
            subtasks = [
                {
                    "id": "ST-001",
                    "description": f"Comprehensive investigation of: {objective}",
                    "priority": 9,
                    "suggested_sources": ["news", "social_media", "documents"],
                    "status": "pending",
                }
            ]

        return subtasks

    async def assign_agents(self, state: OrchestratorState) -> OrchestratorState:
        """
        Assign subtasks to available agents using TaskQueue for priority-based distribution.

        Uses the agent registry to find agents capable of handling each subtask,
        considering suggested sources and agent availability. Tasks are added to
        queue with priority scoring.

        Args:
            state: Current orchestrator state

        Returns:
            Updated state with agent assignments
        """
        subtasks = state.get("subtasks", [])

        if not subtasks:
            self.logger.warning("No subtasks to assign")
            return {
                **state,
                "agent_assignments": {},
                "messages": state.get("messages", []) + ["No subtasks available for assignment"],
            }

        # Initialize coverage metrics if first run
        if self.coverage_metrics is None:
            objective = state.get("objective", "")
            keywords = objective.lower().split()
            self.task_queue.set_investigation_context(keywords)
            self.coverage_metrics = CoverageMetrics()

        assignments = {}

        # Add subtasks to queue with priority
        for subtask in subtasks:
            if subtask.get("status") == "pending":
                # Extract metadata for priority scoring
                metadata = {
                    "keywords": subtask.get("description", "").split(),
                    "source_type": subtask.get("suggested_sources", [None])[0] if subtask.get("suggested_sources") else None,
                    "urgency": "high" if subtask.get("priority", 5) >= 8 else "normal",
                }

                # Add to queue
                task_id = self.task_queue.add_task(
                    objective=subtask["description"],
                    metadata=metadata,
                    task_id=subtask["id"]
                )

        # Distribute tasks to agents based on capabilities
        await self.distribute_tasks()

        # Get current task assignments from queue
        for task_id, task in self.task_queue._tasks.items():
            if task.assigned_agent:
                assignments[task_id] = task.assigned_agent

        assignment_summary = "\n".join(
            [f"  {st['id']}: {assignments.get(st['id'], 'queued')}" for st in subtasks]
        )
        reasoning = f"Agent assignments (priority-based):\n{assignment_summary}"

        self.logger.info(f"Agent assignment complete: {len(assignments)} subtasks assigned/queued")

        return {
            **state,
            "agent_assignments": assignments,
            "messages": state.get("messages", []) + [reasoning],
        }

    async def distribute_tasks(self):
        """
        Distribute tasks from queue to available agents based on capabilities.

        Matches tasks to agents using registry capabilities and updates queue.
        """
        if not self.registry:
            # No registry, assign to general_worker
            pending_tasks = self.task_queue.get_pending_tasks()
            for task in pending_tasks:
                self.task_queue.update_task_status(
                    task.id,
                    status="assigned",
                    assigned_agent="general_worker"
                )
            return

        try:
            # Get available agents
            active_agents = await self.registry.get_active_agents()

            # Process pending tasks
            for agent_info in active_agents:
                # Try to get a task matching this agent's capabilities
                task = self.task_queue.get_next_task(agent_capabilities=agent_info.capabilities)

                if task:
                    # Assign task to agent
                    self.task_queue.update_task_status(
                        task.id,
                        status="assigned",
                        assigned_agent=agent_info.name
                    )

                    self.logger.info(
                        f"Distributed {task.id} to {agent_info.name}",
                        priority=f"{task.priority:.3f}"
                    )

        except Exception as e:
            self.logger.error(f"Task distribution failed: {e}")
            # Fallback: assign to general_worker
            pending_tasks = self.task_queue.get_pending_tasks()
            for task in pending_tasks:
                self.task_queue.update_task_status(
                    task.id,
                    status="assigned",
                    assigned_agent="general_worker"
                )

    async def coordinate_execution(self, state: OrchestratorState) -> OrchestratorState:
        """
        Coordinate execution of assigned subtasks across agents.

        In production, this would dispatch tasks to agents via the message bus.
        Currently simulates execution and collects findings.

        Args:
            state: Current orchestrator state

        Returns:
            Updated state with initial findings
        """
        assignments = state.get("agent_assignments", {})

        if not assignments:
            self.logger.warning("No agent assignments to coordinate")
            return {
                **state,
                "findings": [],
                "messages": state.get("messages", []) + ["No agents assigned to coordinate"],
            }

        self.logger.info(f"Coordinating execution for {len(assignments)} agents")

        findings = []

        # Simulate/execute agent assignments
        if self.message_bus:
            try:
                for subtask_id, agent_name in assignments.items():
                    # Create execution message
                    message = {
                        "type": "execute_subtask",
                        "subtask_id": subtask_id,
                        "objective": state.get("objective", ""),
                        "timestamp": datetime.utcnow().isoformat(),
                    }

                    # Dispatch via message bus (non-blocking)
                    await self.message_bus.publish(
                        channel=f"execution.{agent_name}",
                        message=message,
                    )

                    self.logger.info(f"Dispatched {subtask_id} to {agent_name}")

            except Exception as e:
                self.logger.error(f"Coordination dispatch failed: {e}")

        # Simulate findings for now (would be replaced with actual agent results)
        findings = [
            Finding(
                source="simulation",
                content="Initial findings simulation for demonstration",
                agent_id="coordinator",
                confidence=0.7,
                metadata={"type": "simulation"},
            )
        ]

        findings_summary = f"Initiated execution for {len(assignments)} subtasks, collected initial findings"
        messages = state.get("messages", []) + [findings_summary]

        return {
            **state,
            "findings": [vars(f) | {"timestamp": f.timestamp.isoformat()} for f in findings],
            "messages": messages,
        }

    async def evaluate_findings(self, state: OrchestratorState) -> OrchestratorState:
        """
        Evaluate findings using signal analysis and coverage metrics for adaptive routing.

        Analyzes signal strength, coverage metrics, and diminishing returns to decide
        whether to explore, refine, synthesize, or end the investigation.

        Args:
            state: Current orchestrator state

        Returns:
            Updated state with next_action routing decision
        """
        findings = state.get("findings", [])
        refinement_count = state.get("refinement_count", 0)
        max_refinements = state.get("max_refinements", self.max_refinements)
        objective = state.get("objective", "")

        self.logger.info(
            "Evaluating findings",
            finding_count=len(findings),
            refinement_count=refinement_count,
        )

        # Calculate signal strength using new analysis module
        keywords = objective.lower().split()
        signal_strength = calculate_signal_strength(findings, investigation_keywords=keywords)

        # Update coverage metrics
        if self.coverage_metrics:
            for finding in findings:
                self.coverage_metrics.update_from_finding(finding)

            coverage = self.coverage_metrics.get_overall_coverage()
        else:
            coverage = state.get("coverage_metrics", {})

        # Check coverage targets
        coverage_met = all(
            coverage.get(key, 0) >= target
            for key, target in self.coverage_target.items()
        )

        # Diminishing returns analysis using new check function
        diminishing_returns = False
        if refinement_count > 2 and len(findings) > 2:
            # Get new findings (since last refinement)
            new_findings = findings[-2:] if len(findings) > 2 else []
            novelty_score = check_diminishing_returns(
                new_findings,
                self.previous_findings,
                novelty_threshold=self.diminishing_returns_threshold
            )
            diminishing_returns = novelty_score < self.diminishing_returns_threshold

            # Update previous findings for next iteration
            self.previous_findings = findings.copy()

        # Adaptive routing logic - CRITICAL: Must always terminate
        next_action = "synthesize"  # Default to synthesizing

        # Decision tree - evaluate from most to least important
        if refinement_count > max_refinements:
            # Safety: hard limit exceeded
            next_action = "synthesize"
            reasoning = f"HARD LIMIT: Refinements exceeded {max_refinements}, synthesizing"

        elif refinement_count >= max_refinements:
            # Hit refinement limit
            next_action = "synthesize"
            reasoning = f"Max refinements {max_refinements} reached, synthesizing results"

        elif diminishing_returns or refinement_count > 5:
            # Diminishing returns or approaching limit
            next_action = "synthesize"
            reasoning = "Diminishing returns or approaching limit, synthesizing"

        elif signal_strength > self.signal_strength_threshold and not coverage_met:
            # Strong signal but need more coverage - only allow refinement if under limit
            if refinement_count < max_refinements - 1:
                next_action = "refine"
                reasoning = f"Signal strength {signal_strength:.2f} but coverage incomplete"
            else:
                next_action = "synthesize"
                reasoning = "Strong signal but at refinement limit, synthesizing"

        elif coverage_met:
            # Goals met
            next_action = "synthesize"
            reasoning = "Coverage targets met, synthesizing results"

        elif refinement_count < 2:
            # Allow limited exploration for very early stages
            next_action = "refine"
            reasoning = f"Early stage, continuing refinement (count: {refinement_count}/{max_refinements})"

        else:
            # Default to synthesizing for safety
            next_action = "synthesize"
            reasoning = "Default to synthesis for safety"

        evaluation_summary = f"Routing decision: {next_action}\n  {reasoning}\n  Signal: {signal_strength:.2f}, Coverage: {coverage}"
        messages = state.get("messages", []) + [evaluation_summary]

        self.logger.info("Evaluation complete", next_action=next_action, reasoning=reasoning)

        return {
            **state,
            "signal_strength": signal_strength,
            "coverage_metrics": coverage,
            "next_action": next_action,
            "messages": messages,
        }

    def _calculate_signal_strength(self, findings: list) -> float:
        """
        Calculate overall signal strength from findings.

        Considers finding count, confidence levels, and consistency.

        Args:
            findings: List of findings dictionaries

        Returns:
            Signal strength score 0.0-1.0
        """
        if not findings:
            return 0.0

        # Normalize by expected finding count
        finding_score = min(len(findings) / 10.0, 1.0)

        # Average confidence
        confidences = [f.get("confidence", 0.5) for f in findings if isinstance(f, dict)]
        confidence_score = sum(confidences) / len(confidences) if confidences else 0.0

        # Weighted combination
        signal_strength = (finding_score * 0.4) + (confidence_score * 0.6)

        return min(signal_strength, 1.0)

    def _check_diminishing_returns(self, findings: list, refinement_count: int) -> bool:
        """
        Check if refinement is showing diminishing returns.

        Compares recent findings to previous ones to detect lack of new information.

        Args:
            findings: List of findings collected so far
            refinement_count: Number of refinements performed

        Returns:
            True if diminishing returns detected
        """
        if refinement_count < 2 or len(findings) < 4:
            return False

        # Simple heuristic: if findings haven't grown much in last refinement
        recent_findings = findings[-2:] if len(findings) > 2 else []
        if not recent_findings:
            return False

        # Check if new information ratio is below threshold
        new_info_ratio = len(recent_findings) / max(len(findings) - len(recent_findings), 1)
        returns_diminished = new_info_ratio < self.diminishing_returns_threshold

        self.logger.debug(
            "Diminishing returns check",
            new_info_ratio=new_info_ratio,
            diminished=returns_diminished,
        )

        return returns_diminished

    async def refine_approach(self, state: OrchestratorState) -> OrchestratorState:
        """
        Refine the investigation approach based on findings so far.

        Updates subtasks, reassigns agents, and prepares for next iteration.

        Args:
            state: Current orchestrator state

        Returns:
            Updated state with refined approach
        """
        refinement_count = state.get("refinement_count", 0) + 1
        findings = state.get("findings", [])

        self.logger.info(f"Refining approach (iteration {refinement_count})")

        # Generate refinement strategy
        refinement_summary = (
            f"Refinement iteration {refinement_count}: Analyzing {len(findings)} findings, "
            f"adapting approach based on discoveries"
        )

        messages = state.get("messages", []) + [refinement_summary]

        return {
            **state,
            "refinement_count": refinement_count,
            "messages": messages,
        }

    async def synthesize_results(self, state: OrchestratorState) -> OrchestratorState:
        """
        Synthesize collected findings into coherent intelligence product.

        Consolidates findings, identifies patterns, and prepares final output.

        Args:
            state: Current orchestrator state

        Returns:
            Updated state with synthesis results
        """
        findings = state.get("findings", [])
        conflicts = state.get("conflicts", [])

        self.logger.info(f"Synthesizing results from {len(findings)} findings and {len(conflicts)} conflicts")

        synthesis_summary = (
            f"Investigation complete. Synthesized {len(findings)} findings and {len(conflicts)} conflicts. "
            f"Ready for analysis and reporting."
        )

        messages = state.get("messages", []) + [synthesis_summary]

        return {
            **state,
            "messages": messages,
            "next_action": "end",
        }

    def get_status(self) -> dict:
        """
        Get current orchestration status and reasoning.

        Returns:
            Dictionary with current state, routing decisions, and reasoning
        """
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "status": "ready",
            "max_refinements": self.max_refinements,
            "routing_thresholds": {
                "signal_strength": self.signal_strength_threshold,
                "coverage_targets": self.coverage_target,
                "diminishing_returns": self.diminishing_returns_threshold,
            },
        }

    def explain_routing(self, findings_count: int, refinement_count: int, signal_strength: float) -> str:
        """
        Explain why certain routing decisions were made.

        Provides transparent reasoning about agent selection and refinement logic.

        Args:
            findings_count: Number of findings collected
            refinement_count: Current refinement iteration
            signal_strength: Current signal strength score

        Returns:
            Human-readable explanation of routing logic
        """
        lines = ["Routing Decision Explanation:"]
        lines.append(f"  Signal strength: {signal_strength:.2f} (threshold: {self.signal_strength_threshold})")
        lines.append(f"  Refinements: {refinement_count}/{self.max_refinements}")
        lines.append(f"  Findings collected: {findings_count}")

        if signal_strength > self.signal_strength_threshold:
            lines.append("  -> Strong signal detected, pursuing deeper investigation")
        elif signal_strength < 0.3:
            lines.append("  -> Weak signal, attempting alternative approaches")
        else:
            lines.append("  -> Moderate signal, continuing investigation")

        if refinement_count >= self.max_refinements:
            lines.append("  -> Max refinements reached, will synthesize results")
        elif refinement_count > 2:
            lines.append("  -> Multiple refinements done, checking for diminishing returns")

        return "\n".join(lines)

    async def process(self, input_data: dict) -> dict:
        """
        Execute the planning and orchestration workflow.

        Args:
            input_data: Dictionary with 'objective' key

        Returns:
            Results dictionary with findings, routing history, and status
        """
        objective = input_data.get("objective", "")

        if not objective:
            return {
                "success": False,
                "error": "No objective provided",
                "findings": [],
            }

        self.logger.info(f"Starting orchestration for: {objective[:100]}...")

        try:
            # Build initial state
            initial_state: OrchestratorState = {
                "objective": objective,
                "messages": [f"Starting investigation: {objective}"],
                "subtasks": [],
                "agent_assignments": {},
                "findings": [],
                "refinement_count": 0,
                "max_refinements": self.max_refinements,
                "coverage_metrics": {
                    "source_diversity": 0.0,
                    "geographic_coverage": 0.0,
                    "topical_coverage": 0.0,
                },
                "signal_strength": 0.0,
                "conflicts": [],
                "next_action": "explore",
            }

            # Execute the graph asynchronously with thread ID for checkpointing
            final_state = await self.graph.ainvoke(
                initial_state,
                config={"configurable": {"thread_id": self.agent_id}},
            )

            return {
                "success": True,
                "objective": objective,
                "subtasks_created": len(final_state.get("subtasks", [])),
                "findings_collected": len(final_state.get("findings", [])),
                "refinements_performed": final_state.get("refinement_count", 0),
                "final_signal_strength": final_state.get("signal_strength", 0.0),
                "final_action": final_state.get("next_action", "end"),
                "messages": final_state.get("messages", []),
            }

        except Exception as e:
            self.logger.error(f"Orchestration failed: {e}", exc_info=True)
            return {
                "success": False,
                "objective": objective,
                "error": str(e),
                "findings": [],
            }

    def get_capabilities(self) -> list[str]:
        """
        Return agent capabilities.

        Returns:
            List of capabilities this agent provides
        """
        return [
            "orchestration",
            "planning",
            "objective_decomposition",
            "task_distribution",
            "adaptive_routing",
        ]
