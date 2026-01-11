"""Task queue with priority-based task management and distribution."""

import heapq
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Literal, Dict, List, Any
from loguru import logger


@dataclass
class Task:
    """
    Represents a task in the queue with priority scoring.

    Fields:
        id: Unique task identifier
        objective: Task description/objective
        priority: Priority score 0.0-1.0 (higher is more important)
        created_at: Timestamp when task was created
        assigned_agent: Agent assigned to this task (empty if unassigned)
        status: Task execution status
        metadata: Additional task metadata (keywords, sources, etc.)
        retry_count: Number of times task has been retried
    """

    id: str
    objective: str
    priority: float  # 0.0-1.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    assigned_agent: str = ""
    status: Literal["pending", "assigned", "in_progress", "completed", "failed"] = "pending"
    metadata: Dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0

    def __lt__(self, other: "Task") -> bool:
        """
        Compare tasks for priority queue ordering.

        Higher priority tasks come first. For equal priority, older tasks come first.
        """
        if self.priority != other.priority:
            # Higher priority comes first (negate for max-heap behavior)
            return self.priority > other.priority
        return self.created_at < other.created_at


class TaskQueue:
    """
    Priority-based task queue with automatic priority scoring.

    Features:
    - Heap-based priority queue for efficient task retrieval
    - Automatic priority calculation using heuristics
    - Task status tracking and updates
    - Metadata-driven priority scoring

    Priority Scoring Components:
    - Keyword relevance (0.4 weight): Matches with investigation keywords
    - Recency (0.2 weight): Time-based urgency factor
    - Retry penalty (0.2 weight): Decreases priority for repeated failures
    - Source diversity bonus (0.2 weight): Rewards exploring new sources
    """

    def __init__(self):
        """Initialize the task queue."""
        self._heap: List[Task] = []
        self._tasks: Dict[str, Task] = {}  # task_id -> Task for O(1) lookup
        self._seen_sources: set = set()  # Track sources for diversity scoring
        self._investigation_keywords: set = set()  # Keywords from objective
        self.logger = logger.bind(component="TaskQueue")

        self.logger.info("TaskQueue initialized")

    def set_investigation_context(self, keywords: List[str], priority_sources: List[str] = None):
        """
        Set investigation context for priority scoring.

        Args:
            keywords: Key terms from the investigation objective
            priority_sources: Optional list of high-priority source types
        """
        self._investigation_keywords = set(k.lower() for k in keywords)
        if priority_sources:
            self.metadata = {"priority_sources": priority_sources}

        self.logger.info(
            "Investigation context set",
            keywords=len(self._investigation_keywords),
            priority_sources=priority_sources or []
        )

    def add_task(
        self,
        objective: str,
        priority: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
        task_id: Optional[str] = None
    ) -> str:
        """
        Add a task to the queue with auto-calculated priority.

        Args:
            objective: Task description
            priority: Manual priority override (0.0-1.0), auto-calculated if None
            metadata: Additional task information for priority scoring
            task_id: Optional task ID (generated if not provided)

        Returns:
            Task ID
        """
        if not task_id:
            task_id = f"TASK-{uuid.uuid4().hex[:8].upper()}"

        # Calculate priority if not provided
        if priority is None:
            priority = self._calculate_priority(objective, metadata or {})
        else:
            # Clamp manual priority to valid range
            priority = max(0.0, min(1.0, priority))

        task = Task(
            id=task_id,
            objective=objective,
            priority=priority,
            metadata=metadata or {},
            status="pending"
        )

        # Add to heap and lookup dict
        heapq.heappush(self._heap, task)
        self._tasks[task_id] = task

        # Update source diversity tracking
        source = metadata.get("source_type") if metadata else None
        if source:
            self._seen_sources.add(source)

        self.logger.info(
            f"Task added: {task_id}",
            priority=f"{priority:.3f}",
            objective=objective[:50]
        )

        return task_id

    def _calculate_priority(self, objective: str, metadata: Dict[str, Any]) -> float:
        """
        Calculate task priority using heuristic scoring.

        Components:
        - Keyword relevance: 0.4 weight
        - Recency: 0.2 weight
        - Retry penalty: 0.2 weight
        - Source diversity bonus: 0.2 weight

        Args:
            objective: Task description
            metadata: Task metadata with optional keywords, timestamp, source_type

        Returns:
            Priority score 0.0-1.0
        """
        # Component 1: Keyword relevance (0.4 weight)
        keyword_score = self._calculate_keyword_relevance(objective, metadata)

        # Component 2: Recency (0.2 weight)
        recency_score = self._calculate_recency_score(metadata)

        # Component 3: Retry penalty (0.2 weight)
        retry_count = metadata.get("retry_count", 0)
        retry_penalty = max(0.0, 1.0 - (retry_count * 0.2))  # -20% per retry

        # Component 4: Source diversity bonus (0.2 weight)
        diversity_score = self._calculate_diversity_score(metadata)

        # Weighted combination
        priority = (
            keyword_score * 0.4 +
            recency_score * 0.2 +
            retry_penalty * 0.2 +
            diversity_score * 0.2
        )

        self.logger.debug(
            "Priority calculated",
            keyword=f"{keyword_score:.2f}",
            recency=f"{recency_score:.2f}",
            retry=f"{retry_penalty:.2f}",
            diversity=f"{diversity_score:.2f}",
            final=f"{priority:.2f}"
        )

        return max(0.0, min(1.0, priority))

    def _calculate_keyword_relevance(self, objective: str, metadata: Dict[str, Any]) -> float:
        """
        Calculate keyword relevance score.

        Args:
            objective: Task description
            metadata: Task metadata with optional 'keywords' field

        Returns:
            Relevance score 0.0-1.0
        """
        if not self._investigation_keywords:
            return 0.5  # Neutral score if no context

        # Combine objective text and metadata keywords
        task_keywords = set(objective.lower().split())
        if "keywords" in metadata:
            task_keywords.update(k.lower() for k in metadata["keywords"])

        # Calculate overlap
        matches = self._investigation_keywords.intersection(task_keywords)
        relevance = len(matches) / len(self._investigation_keywords) if self._investigation_keywords else 0.0

        return min(relevance * 1.5, 1.0)  # Boost and cap at 1.0

    def _calculate_recency_score(self, metadata: Dict[str, Any]) -> float:
        """
        Calculate recency/urgency score.

        More recent or time-sensitive tasks get higher scores.

        Args:
            metadata: Task metadata with optional 'timestamp' or 'urgency' field

        Returns:
            Recency score 0.0-1.0
        """
        # Check for explicit urgency flag
        if metadata.get("urgency") == "high":
            return 1.0
        elif metadata.get("urgency") == "low":
            return 0.3

        # Check for timestamp-based recency
        if "timestamp" in metadata:
            try:
                timestamp = metadata["timestamp"]
                if isinstance(timestamp, str):
                    timestamp = datetime.fromisoformat(timestamp)

                age_hours = (datetime.utcnow() - timestamp).total_seconds() / 3600
                # Decay over 72 hours (3 days)
                recency = max(0.0, 1.0 - (age_hours / 72.0))
                return recency
            except (ValueError, TypeError):
                pass

        # Default: assume moderate recency
        return 0.5

    def _calculate_diversity_score(self, metadata: Dict[str, Any]) -> float:
        """
        Calculate source diversity bonus.

        Tasks exploring new sources get higher scores.

        Args:
            metadata: Task metadata with optional 'source_type' field

        Returns:
            Diversity score 0.0-1.0
        """
        source_type = metadata.get("source_type")

        if not source_type:
            return 0.5  # Neutral if no source specified

        # Bonus for new source types
        if source_type not in self._seen_sources:
            return 1.0

        # Penalty for heavily used sources
        # (Would need more sophisticated tracking in production)
        return 0.4

    def get_next_task(self, agent_capabilities: Optional[List[str]] = None) -> Optional[Task]:
        """
        Get the highest priority pending task.

        Args:
            agent_capabilities: Optional list of agent capabilities for matching

        Returns:
            Task object if available, None if queue is empty
        """
        while self._heap:
            task = heapq.heappop(self._heap)

            # Check if task still valid (not removed externally)
            if task.id not in self._tasks:
                continue

            # Check if task still pending
            if task.status != "pending":
                continue

            # Check capability matching if specified
            if agent_capabilities:
                required_capability = task.metadata.get("required_capability")
                if required_capability and required_capability not in agent_capabilities:
                    # Re-add to heap and continue
                    heapq.heappush(self._heap, task)
                    continue

            # Update status
            task.status = "assigned"

            self.logger.info(f"Task retrieved: {task.id}", priority=f"{task.priority:.3f}")
            return task

        return None

    def update_task_status(
        self,
        task_id: str,
        status: Literal["pending", "assigned", "in_progress", "completed", "failed"],
        assigned_agent: Optional[str] = None
    ) -> bool:
        """
        Update task status and optionally assign agent.

        Args:
            task_id: Task identifier
            status: New status
            assigned_agent: Agent assigned to task

        Returns:
            True if updated, False if task not found
        """
        if task_id not in self._tasks:
            self.logger.warning(f"Task not found for status update: {task_id}")
            return False

        task = self._tasks[task_id]
        old_status = task.status
        task.status = status

        if assigned_agent:
            task.assigned_agent = assigned_agent

        # If task failed, increment retry count
        if status == "failed":
            task.retry_count += 1

        self.logger.info(
            f"Task status updated: {task_id}",
            old_status=old_status,
            new_status=status,
            agent=assigned_agent or "none"
        )

        return True

    def get_pending_tasks(self, limit: Optional[int] = None) -> List[Task]:
        """
        Get all pending tasks sorted by priority.

        Args:
            limit: Optional maximum number of tasks to return

        Returns:
            List of pending tasks
        """
        pending = [
            task for task in self._tasks.values()
            if task.status == "pending"
        ]

        # Sort by priority (descending)
        pending.sort(reverse=True)

        if limit:
            pending = pending[:limit]

        self.logger.debug(f"Retrieved {len(pending)} pending tasks")
        return pending

    def get_task(self, task_id: str) -> Optional[Task]:
        """
        Get a specific task by ID.

        Args:
            task_id: Task identifier

        Returns:
            Task if found, None otherwise
        """
        return self._tasks.get(task_id)

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get queue statistics.

        Returns:
            Dictionary with queue metrics
        """
        status_counts = {}
        for task in self._tasks.values():
            status_counts[task.status] = status_counts.get(task.status, 0) + 1

        return {
            "total_tasks": len(self._tasks),
            "pending_tasks": status_counts.get("pending", 0),
            "assigned_tasks": status_counts.get("assigned", 0),
            "in_progress_tasks": status_counts.get("in_progress", 0),
            "completed_tasks": status_counts.get("completed", 0),
            "failed_tasks": status_counts.get("failed", 0),
            "unique_sources": len(self._seen_sources),
            "investigation_keywords": len(self._investigation_keywords)
        }

    def clear(self):
        """Clear all tasks from the queue."""
        self._heap.clear()
        self._tasks.clear()
        self._seen_sources.clear()
        self.logger.info("Task queue cleared")

    def __len__(self) -> int:
        """Return the number of tasks in the queue."""
        return len(self._tasks)
