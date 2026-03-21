"""Pipeline event system and investigation lifecycle tracking.

Provides:
- ``PipelineEventBus``: In-memory pub/sub with per-investigation event storage
  and replay support for SSE reconnection.
- ``PipelineEvent`` / ``EventType``: Typed event structures for pipeline phases.
- ``InvestigationRegistry``: Investigation lifecycle tracking with atomic
  status transitions (compare-and-swap with asyncio.Lock).
"""

from osint_system.api.events.event_bus import PipelineEventBus
from osint_system.api.events.event_models import EventType, PipelineEvent
from osint_system.api.events.investigation_registry import (
    Investigation,
    InvestigationRegistry,
    InvestigationStatus,
)

__all__ = [
    "EventType",
    "Investigation",
    "InvestigationRegistry",
    "InvestigationStatus",
    "PipelineEvent",
    "PipelineEventBus",
]
