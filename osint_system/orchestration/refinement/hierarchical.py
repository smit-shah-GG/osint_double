"""Hierarchical sub-coordinator support for complex multi-aspect investigations."""

import uuid
from typing import Dict, List, Optional, Any
from datetime import datetime
from loguru import logger
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from osint_system.orchestration.state_schemas import OrchestratorState, Finding


class SubCoordinator:
    """
    Sub-coordinator for managing a subset of agents for specific source types.

    Handles delegation of specialized tasks to agent cohorts based on
    source type (news, social, document) and aggregates their results
    back to the main orchestrator.
    """

    def __init__(
        self,
        coordinator_id: str,
        source_type: str,
        parent_objective: str,
        agents: list[str]
    ):
        """
        Initialize a sub-coordinator for a specific source type.

        Args:
            coordinator_id: Unique identifier for this sub-coordinator
            source_type: Type of sources this coordinator handles
            parent_objective: Parent investigation objective
            agents: List of agent names/IDs to coordinate
        """
        self.coordinator_id = coordinator_id
        self.source_type = source_type
        self.parent_objective = parent_objective
        self.agents = agents
        self.findings = []
        self.start_time = datetime.utcnow()

        self.logger = logger.bind(
            component="SubCoordinator",
            coordinator_id=coordinator_id,
            source_type=source_type
        )

        # Build sub-graph for this coordinator
        self.graph = self._build_subgraph()

        self.logger.info(
            "SubCoordinator initialized",
            agent_count=len(agents)
        )

    def _build_subgraph(self) -> Any:
        """
        Build a LangGraph StateGraph for the sub-coordinator workflow.

        Returns:
            Compiled subgraph for source-specific investigation
        """
        graph = StateGraph(dict)  # Simple state for sub-coordinators

        # Define nodes
        graph.add_node("distribute_tasks", self.distribute_tasks)
        graph.add_node("collect_findings", self.collect_findings)
        graph.add_node("aggregate_results", self.aggregate_results)

        # Set flow
        graph.set_entry_point("distribute_tasks")
        graph.add_edge("distribute_tasks", "collect_findings")
        graph.add_edge("collect_findings", "aggregate_results")
        graph.add_edge("aggregate_results", END)

        # Compile with memory checkpoint
        checkpointer = MemorySaver()
        compiled_graph = graph.compile(checkpointer=checkpointer)

        return compiled_graph

    async def distribute_tasks(self, state: dict) -> dict:
        """
        Distribute tasks to agents in this sub-coordinator's cohort.

        Args:
            state: Current subgraph state

        Returns:
            Updated state with task distributions
        """
        tasks = state.get("tasks", [])

        self.logger.info(f"Distributing {len(tasks)} tasks to {len(self.agents)} agents")

        # Simple round-robin distribution
        distributions = {}
        for i, task in enumerate(tasks):
            agent_idx = i % len(self.agents)
            agent_name = self.agents[agent_idx]

            if agent_name not in distributions:
                distributions[agent_name] = []

            distributions[agent_name].append(task)

        return {
            **state,
            "distributions": distributions,
            "distribution_time": datetime.utcnow().isoformat()
        }

    async def collect_findings(self, state: dict) -> dict:
        """
        Collect findings from agents in this cohort.

        Args:
            state: Current subgraph state

        Returns:
            Updated state with collected findings
        """
        distributions = state.get("distributions", {})

        # Simulate finding collection (would be replaced with actual agent results)
        findings = []
        for agent_name, tasks in distributions.items():
            for task in tasks:
                finding = {
                    "source": self.source_type,
                    "content": f"Finding from {agent_name} for {self.source_type} investigation",
                    "agent_id": agent_name,
                    "sub_coordinator": self.coordinator_id,
                    "confidence": 0.75,
                    "timestamp": datetime.utcnow().isoformat(),
                    "metadata": {
                        "source_type": self.source_type,
                        "task_id": task.get("id") if isinstance(task, dict) else str(task)
                    }
                }
                findings.append(finding)

        self.findings.extend(findings)

        self.logger.info(f"Collected {len(findings)} findings from agents")

        return {
            **state,
            "findings": findings,
            "collection_time": datetime.utcnow().isoformat()
        }

    async def aggregate_results(self, state: dict) -> dict:
        """
        Aggregate findings from this sub-coordinator's agents.

        Preserves source attribution and adds sub-coordinator metadata.

        Args:
            state: Current subgraph state

        Returns:
            Final state with aggregated results
        """
        findings = state.get("findings", [])

        # Add aggregation metadata
        aggregated_results = {
            "sub_coordinator_id": self.coordinator_id,
            "source_type": self.source_type,
            "parent_objective": self.parent_objective,
            "agents_involved": self.agents,
            "findings_count": len(findings),
            "findings": findings,
            "start_time": self.start_time.isoformat(),
            "end_time": datetime.utcnow().isoformat(),
            "summary": f"Investigated {self.source_type} sources with {len(self.agents)} agents, found {len(findings)} items"
        }

        self.logger.info(
            "Results aggregated",
            findings=len(findings),
            duration=(datetime.utcnow() - self.start_time).total_seconds()
        )

        return {
            **state,
            "aggregated_results": aggregated_results
        }

    async def execute(self, tasks: list[dict]) -> dict:
        """
        Execute the sub-coordinator workflow for given tasks.

        Args:
            tasks: List of tasks to distribute and execute

        Returns:
            Aggregated results from all agents in this cohort
        """
        initial_state = {
            "tasks": tasks,
            "coordinator_id": self.coordinator_id,
            "source_type": self.source_type
        }

        # Execute the subgraph
        final_state = await self.graph.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": self.coordinator_id}}
        )

        return final_state.get("aggregated_results", {})

    def get_status(self) -> dict:
        """
        Get current status of this sub-coordinator.

        Returns:
            Status dictionary with coordinator details
        """
        return {
            "coordinator_id": self.coordinator_id,
            "source_type": self.source_type,
            "agents": self.agents,
            "findings_collected": len(self.findings),
            "runtime": (datetime.utcnow() - self.start_time).total_seconds()
        }


class SubCoordinatorFactory:
    """
    Factory for creating sub-coordinators based on source types and capabilities.
    """

    # Default agent groupings by source type
    SOURCE_TYPE_AGENTS = {
        "news": ["newsfeed_crawler", "news_aggregator", "article_parser"],
        "social": ["social_media_crawler", "twitter_agent", "reddit_agent"],
        "document": ["document_scraper", "pdf_parser", "archive_searcher"],
        "specialized": ["academic_crawler", "expert_finder", "database_searcher"]
    }

    @classmethod
    def create_by_source_type(
        cls,
        source_type: str,
        parent_objective: str,
        available_agents: Optional[list[str]] = None
    ) -> SubCoordinator:
        """
        Create a sub-coordinator for a specific source type.

        Args:
            source_type: Type of sources to investigate
            parent_objective: Parent investigation objective
            available_agents: Optional list of available agents to filter from

        Returns:
            SubCoordinator instance configured for the source type
        """
        coordinator_id = f"SUB-{source_type.upper()}-{uuid.uuid4().hex[:8]}"

        # Get agents for this source type
        default_agents = cls.SOURCE_TYPE_AGENTS.get(source_type, ["general_agent"])

        # Filter by available agents if provided
        if available_agents:
            agents = [a for a in default_agents if a in available_agents]
            if not agents:
                # Fallback to available agents if no specific match
                agents = available_agents[:3]  # Limit to 3 agents per sub-coordinator
        else:
            agents = default_agents

        logger.info(
            f"Creating sub-coordinator",
            coordinator_id=coordinator_id,
            source_type=source_type,
            agents=agents
        )

        return SubCoordinator(
            coordinator_id=coordinator_id,
            source_type=source_type,
            parent_objective=parent_objective,
            agents=agents
        )

    @classmethod
    def create_parallel_coordinators(
        cls,
        objective: str,
        aspects: list[str],
        available_agents: Optional[list[str]] = None
    ) -> Dict[str, SubCoordinator]:
        """
        Create multiple sub-coordinators for parallel exploration of different aspects.

        Args:
            objective: Parent investigation objective
            aspects: List of aspects/source types to investigate
            available_agents: Optional list of available agents

        Returns:
            Dictionary mapping aspect to SubCoordinator instance
        """
        coordinators = {}

        for aspect in aspects:
            # Determine source type from aspect
            source_type = cls._aspect_to_source_type(aspect)

            coordinator = cls.create_by_source_type(
                source_type=source_type,
                parent_objective=f"{objective} - {aspect}",
                available_agents=available_agents
            )

            coordinators[aspect] = coordinator

        logger.info(
            f"Created {len(coordinators)} parallel sub-coordinators",
            aspects=aspects
        )

        return coordinators

    @staticmethod
    def _aspect_to_source_type(aspect: str) -> str:
        """
        Map investigation aspect to appropriate source type.

        Args:
            aspect: Investigation aspect

        Returns:
            Corresponding source type
        """
        aspect_lower = aspect.lower()

        if any(term in aspect_lower for term in ["news", "media", "press", "article"]):
            return "news"
        elif any(term in aspect_lower for term in ["social", "twitter", "reddit", "forum"]):
            return "social"
        elif any(term in aspect_lower for term in ["document", "pdf", "report", "paper"]):
            return "document"
        elif any(term in aspect_lower for term in ["academic", "expert", "research", "technical"]):
            return "specialized"
        else:
            return "news"  # Default to news sources


def combine_sub_coordinator_results(results: List[dict]) -> dict:
    """
    Combine results from multiple sub-coordinators while preserving attribution.

    Args:
        results: List of aggregated results from sub-coordinators

    Returns:
        Combined results with source attribution preserved
    """
    combined = {
        "total_findings": 0,
        "sub_coordinators": [],
        "findings_by_source": {},
        "all_findings": [],
        "agents_involved": set(),
        "summary": ""
    }

    for result in results:
        coordinator_id = result.get("sub_coordinator_id", "unknown")
        source_type = result.get("source_type", "unknown")
        findings = result.get("findings", [])

        # Track sub-coordinator
        combined["sub_coordinators"].append({
            "id": coordinator_id,
            "source_type": source_type,
            "findings_count": len(findings)
        })

        # Group findings by source type
        if source_type not in combined["findings_by_source"]:
            combined["findings_by_source"][source_type] = []

        combined["findings_by_source"][source_type].extend(findings)

        # Collect all findings
        combined["all_findings"].extend(findings)
        combined["total_findings"] += len(findings)

        # Track agents
        agents = result.get("agents_involved", [])
        combined["agents_involved"].update(agents)

    # Convert set to list for JSON serialization
    combined["agents_involved"] = list(combined["agents_involved"])

    # Build summary
    source_summaries = []
    for source_type, findings in combined["findings_by_source"].items():
        source_summaries.append(f"{source_type}: {len(findings)} findings")

    combined["summary"] = (
        f"Combined results from {len(results)} sub-coordinators. "
        f"Total findings: {combined['total_findings']}. "
        f"By source: {', '.join(source_summaries)}"
    )

    logger.info(
        "Combined sub-coordinator results",
        coordinators=len(results),
        total_findings=combined["total_findings"]
    )

    return combined