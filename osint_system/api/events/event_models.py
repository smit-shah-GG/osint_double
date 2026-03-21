"""Typed event structures for pipeline phase notifications.

Events flow from the pipeline runner through ``PipelineEventBus`` to SSE
subscribers.  All ``data`` values MUST be JSON-serializable primitives
(str, int, float, bool, None, list, dict) -- no datetime objects, Pydantic
models, or enums.  Serialization is NOT enforced at emit time (too expensive
for ~20-30 events per run) but WILL cause ``json.dumps`` failures in the
SSE generator if violated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EventType(str, Enum):
    """Pipeline event types.

    Values are the SSE ``event:`` field strings.
    """

    PHASE_STARTED = "phase_started"
    PHASE_PROGRESS = "phase_progress"
    PHASE_COMPLETED = "phase_completed"
    PIPELINE_COMPLETED = "pipeline_completed"
    PIPELINE_ERROR = "pipeline_error"


@dataclass
class PipelineEvent:
    """Structured pipeline event.

    Attributes:
        id: Auto-incrementing integer per investigation, used as SSE ``id:``
            field for ``Last-Event-ID`` reconnection.
        event_type: One of ``EventType.value`` strings (e.g. ``"phase_started"``).
        data: Event payload.  MUST contain only JSON-serializable primitives.
        timestamp: UTC timestamp of event creation.
    """

    id: int
    event_type: str
    data: dict[str, Any]
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
