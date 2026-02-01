"""Context coordinator for crawler collaboration through shared entity tracking.

Enables crawlers to share discovered entities and topics, allowing for
coordinated investigation expansion and cross-referencing.
"""

from typing import Dict, List, Set, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
import logging
import asyncio

from osint_system.agents.communication.bus import MessageBus


logger = logging.getLogger(__name__)


@dataclass
class EntityDiscovery:
    """Record of an entity discovery by a crawler."""
    entity: str
    entity_type: str  # person, organization, location, event, etc.
    source_url: str
    source_crawler: str
    investigation_id: str
    context: str  # Surrounding text or context
    discovered_at: datetime = field(default_factory=datetime.utcnow)
    confidence: float = 1.0


class ContextCoordinator:
    """
    Coordinator for sharing context between crawlers during investigation.

    Tracks discovered entities across crawlers, enabling:
    - Entity cross-referencing (find which sources mentioned the same entity)
    - Topic expansion (discover related topics from crawler findings)
    - Context sharing via message bus

    Uses message bus to broadcast context updates to all interested crawlers.
    """

    def __init__(
        self,
        message_bus: Optional[MessageBus] = None,
        enable_broadcast: bool = True,
    ):
        """
        Initialize context coordinator.

        Args:
            message_bus: Optional MessageBus instance for broadcasting
            enable_broadcast: Whether to broadcast discoveries via message bus
        """
        self.message_bus = message_bus
        self.enable_broadcast = enable_broadcast and message_bus is not None

        # Entity tracking: entity -> list of discoveries
        self._discovered_entities: Dict[str, List[EntityDiscovery]] = {}

        # Topic expansion: initial topics -> discovered related topics
        self._related_topics: Dict[str, Set[str]] = {}

        # Investigation-scoped tracking
        self._investigation_entities: Dict[str, Set[str]] = {}

        logger.info(
            "ContextCoordinator initialized",
            extra={"broadcast_enabled": self.enable_broadcast},
        )

    async def share_discovery(
        self,
        entity: str,
        entity_type: str,
        source_url: str,
        source_crawler: str,
        investigation_id: str,
        context: str = "",
        confidence: float = 1.0,
    ) -> None:
        """
        Share a discovered entity with other crawlers.

        Records the discovery and optionally broadcasts via message bus.

        Args:
            entity: The discovered entity (name, term, etc.)
            entity_type: Type of entity (person, organization, location, event)
            source_url: URL where entity was discovered
            source_crawler: Name of crawler that discovered it
            investigation_id: Investigation this discovery belongs to
            context: Surrounding text or context
            confidence: Confidence score for this discovery
        """
        # Normalize entity for comparison
        normalized_entity = entity.lower().strip()

        discovery = EntityDiscovery(
            entity=entity,
            entity_type=entity_type,
            source_url=source_url,
            source_crawler=source_crawler,
            investigation_id=investigation_id,
            context=context,
            confidence=confidence,
        )

        # Track discovery
        if normalized_entity not in self._discovered_entities:
            self._discovered_entities[normalized_entity] = []
        self._discovered_entities[normalized_entity].append(discovery)

        # Track investigation-scoped entities
        if investigation_id not in self._investigation_entities:
            self._investigation_entities[investigation_id] = set()
        self._investigation_entities[investigation_id].add(normalized_entity)

        logger.info(
            f"Entity discovered: {entity} ({entity_type})",
            extra={
                "entity": entity,
                "type": entity_type,
                "source": source_crawler,
                "investigation_id": investigation_id,
            },
        )

        # Broadcast via message bus if enabled
        if self.enable_broadcast and self.message_bus:
            await self._broadcast_discovery(discovery)

    async def _broadcast_discovery(self, discovery: EntityDiscovery) -> None:
        """Broadcast entity discovery via message bus."""
        try:
            await self.message_bus.publish(
                "context.update",
                {
                    "type": "entity_discovered",
                    "entity": discovery.entity,
                    "entity_type": discovery.entity_type,
                    "source_url": discovery.source_url,
                    "source_crawler": discovery.source_crawler,
                    "investigation_id": discovery.investigation_id,
                    "context": discovery.context,
                    "confidence": discovery.confidence,
                    "timestamp": discovery.discovered_at.isoformat(),
                },
            )
        except Exception as e:
            logger.warning(f"Failed to broadcast discovery: {e}")

    def get_related_sources(self, entity: str) -> List[str]:
        """
        Get URLs that mentioned a specific entity.

        Args:
            entity: Entity to look up

        Returns:
            List of source URLs where this entity was mentioned
        """
        normalized_entity = entity.lower().strip()
        discoveries = self._discovered_entities.get(normalized_entity, [])
        return [d.source_url for d in discoveries]

    def get_entity_discoveries(
        self,
        entity: str,
        investigation_id: Optional[str] = None,
    ) -> List[EntityDiscovery]:
        """
        Get all discoveries for an entity.

        Args:
            entity: Entity to look up
            investigation_id: Optional filter by investigation

        Returns:
            List of EntityDiscovery records
        """
        normalized_entity = entity.lower().strip()
        discoveries = self._discovered_entities.get(normalized_entity, [])

        if investigation_id:
            discoveries = [d for d in discoveries if d.investigation_id == investigation_id]

        return discoveries

    def cross_reference(
        self,
        content: str,
        known_entities: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Find known entities mentioned in content.

        Searches content for mentions of tracked entities.

        Args:
            content: Text content to search
            known_entities: Optional list of specific entities to check
                           (uses all tracked entities if not provided)

        Returns:
            List of entity names found in content
        """
        content_lower = content.lower()

        if known_entities:
            entities_to_check = [e.lower().strip() for e in known_entities]
        else:
            entities_to_check = list(self._discovered_entities.keys())

        found = []
        for entity in entities_to_check:
            if entity in content_lower:
                found.append(entity)

        return found

    def add_related_topic(
        self,
        original_topic: str,
        related_topic: str,
        investigation_id: str,
    ) -> None:
        """
        Track a related topic discovered during investigation.

        Args:
            original_topic: The initial investigation topic
            related_topic: A related topic discovered
            investigation_id: Investigation identifier
        """
        key = f"{investigation_id}:{original_topic.lower()}"

        if key not in self._related_topics:
            self._related_topics[key] = set()

        self._related_topics[key].add(related_topic.lower())

        logger.debug(
            f"Related topic added: {original_topic} -> {related_topic}",
            extra={"investigation_id": investigation_id},
        )

    def get_related_topics(
        self,
        original_topic: str,
        investigation_id: str,
    ) -> Set[str]:
        """
        Get related topics for an original topic.

        Args:
            original_topic: The initial topic
            investigation_id: Investigation identifier

        Returns:
            Set of related topic strings
        """
        key = f"{investigation_id}:{original_topic.lower()}"
        return self._related_topics.get(key, set()).copy()

    def get_investigation_entities(
        self,
        investigation_id: str,
    ) -> Set[str]:
        """
        Get all entities discovered for an investigation.

        Args:
            investigation_id: Investigation identifier

        Returns:
            Set of normalized entity strings
        """
        return self._investigation_entities.get(investigation_id, set()).copy()

    def get_stats(self) -> Dict[str, Any]:
        """
        Get coordinator statistics.

        Returns:
            Dictionary with counts and metrics
        """
        total_discoveries = sum(
            len(discoveries)
            for discoveries in self._discovered_entities.values()
        )

        return {
            "unique_entities": len(self._discovered_entities),
            "total_discoveries": total_discoveries,
            "investigations_tracked": len(self._investigation_entities),
            "related_topic_sets": len(self._related_topics),
        }

    def clear_investigation(self, investigation_id: str) -> int:
        """
        Clear all context for an investigation.

        Args:
            investigation_id: Investigation to clear

        Returns:
            Number of entities cleared
        """
        count = 0

        # Clear from investigation entities
        if investigation_id in self._investigation_entities:
            count = len(self._investigation_entities[investigation_id])
            del self._investigation_entities[investigation_id]

        # Clear from discovered entities
        for entity_key in list(self._discovered_entities.keys()):
            discoveries = self._discovered_entities[entity_key]
            remaining = [d for d in discoveries if d.investigation_id != investigation_id]
            if remaining:
                self._discovered_entities[entity_key] = remaining
            else:
                del self._discovered_entities[entity_key]

        # Clear related topics
        keys_to_remove = [
            k for k in self._related_topics
            if k.startswith(f"{investigation_id}:")
        ]
        for key in keys_to_remove:
            del self._related_topics[key]

        logger.info(
            f"Cleared context for investigation {investigation_id}",
            extra={"entities_cleared": count},
        )

        return count
