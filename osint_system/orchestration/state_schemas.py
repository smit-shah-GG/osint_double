"""State schemas for Planning & Orchestration Agent using LangGraph."""

from typing import TypedDict, Literal, Sequence, Any
from dataclasses import dataclass, field
from datetime import datetime


class OrchestratorState(TypedDict, total=False):
    """
    Central state schema for the Planning & Orchestration Agent.

    Manages the objective decomposition, task assignments, findings collection,
    and adaptive routing decisions. Supports iterative refinement with
    coverage metrics and conflict tracking.

    Fields:
        objective: The original investigation objective
        messages: Message history for context preservation
        subtasks: Decomposed objectives into actionable subtasks
        agent_assignments: Mapping of subtasks to assigned agents
        findings: Collected findings from agents (list of dicts)
        refinement_count: Number of refinement iterations performed
        coverage_metrics: Coverage analysis (source diversity, geographic, topical)
        conflicts: Conflicting information discovered
        next_action: Next routing decision (explore, refine, synthesize, end)
    """

    # Core objective and context
    objective: str
    messages: Sequence[Any]

    # Task decomposition
    subtasks: list[dict]  # [{id, description, priority, assigned_agent, status}]
    agent_assignments: dict[str, str]  # subtask_id -> agent_name

    # Findings and results
    findings: list[dict]  # [{source, content, confidence, agent_id, timestamp}]

    # Refinement tracking
    refinement_count: int
    max_refinements: int

    # Coverage and quality metrics
    coverage_metrics: dict[str, float]  # {source_diversity, geographic_coverage, topical_coverage}
    signal_strength: float  # 0.0-1.0 based on findings consistency

    # Conflict tracking
    conflicts: list[dict]  # [{topic, versions: [{source, content, confidence}], status}]

    # Routing decision
    next_action: Literal["explore", "refine", "synthesize", "end"]


@dataclass
class Subtask:
    """Represents a decomposed subtask from objective analysis."""

    id: str
    description: str
    priority: int  # 1-10, higher is more important
    assigned_agent: str = ""
    status: Literal["pending", "in_progress", "completed", "failed"] = "pending"
    findings: list[dict] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Finding:
    """Represents a finding from agent discovery."""

    source: str
    content: str
    agent_id: str
    confidence: float  # 0.0-1.0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: dict = field(default_factory=dict)


@dataclass
class Conflict:
    """Represents conflicting information discovered."""

    topic: str
    versions: list[dict]  # [{source, content, confidence}]
    status: Literal["unresolved", "under_investigation", "resolved"] = "unresolved"
    resolution_notes: str = ""
