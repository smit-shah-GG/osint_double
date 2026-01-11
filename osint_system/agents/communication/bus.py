"""Message bus implementation using aiopubsub for agent broadcasting and discovery."""

import asyncio
from typing import Optional, Any, Callable, Dict, Set
from datetime import datetime
import uuid
from aiopubsub import Hub, Subscriber, Key
from loguru import logger


class MessageBus:
    """
    Singleton message bus for agent communication using aiopubsub.

    Provides pub/sub messaging patterns for:
    - Agent discovery broadcasts
    - Service requests and responses
    - Capability announcements
    - General inter-agent messaging

    Key patterns:
    - "discovery.*" - Agent discovery messages
    - "agent.{name}.*" - Direct messages to specific agents
    - "broadcast.*" - System-wide broadcasts
    - "service.{capability}" - Service request routing
    """

    _instance: Optional['MessageBus'] = None
    _lock = asyncio.Lock()

    def __new__(cls) -> 'MessageBus':
        """Ensure singleton instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize the message bus (only once for singleton)."""
        if not self._initialized:
            self.hub = Hub()
            self._subscribers: Dict[str, Subscriber] = {}
            self._active_subscriptions: Dict[str, Set[Key]] = {}
            self.logger = logger.bind(component="MessageBus")
            self._initialized = True
            self._shutdown = False
            self.logger.info("MessageBus singleton initialized")

    async def publish(self, key: str, message: Any) -> None:
        """
        Publish a message to a specific key pattern.

        Args:
            key: The routing key (e.g., "discovery.announce", "agent.crawler.status")
            message: The message payload (will be passed to all matching subscribers)
        """
        if self._shutdown:
            self.logger.warning(f"Cannot publish to {key} - bus is shutting down")
            return

        try:
            # Add metadata to all messages
            wrapped_message = {
                "id": str(uuid.uuid4()),
                "timestamp": datetime.utcnow().isoformat(),
                "key": key,
                "payload": message
            }

            self.hub.publish(Key(key), wrapped_message)
            self.logger.debug(f"Published message to {key}", message_id=wrapped_message["id"])

        except Exception as e:
            self.logger.error(f"Failed to publish to {key}: {e}")
            raise

    async def broadcast_capability(self, agent_name: str, capabilities: list[str]) -> None:
        """
        Broadcast agent capabilities for discovery.

        Args:
            agent_name: Name of the broadcasting agent
            capabilities: List of capability strings
        """
        message = {
            "agent_name": agent_name,
            "capabilities": capabilities,
            "timestamp": datetime.utcnow().isoformat()
        }

        await self.publish("discovery.announce", message)
        self.logger.info(f"Broadcasted capabilities for {agent_name}", capabilities=capabilities)

    async def request_service(self, capability: str, payload: dict, requester: str) -> None:
        """
        Request a service from any agent with the specified capability.

        Args:
            capability: The required capability
            payload: Request data
            requester: Name of the requesting agent
        """
        message = {
            "capability": capability,
            "payload": payload,
            "requester": requester,
            "request_id": str(uuid.uuid4())
        }

        await self.publish(f"service.{capability}", message)
        self.logger.info(f"Service requested: {capability}", requester=requester)

        return message["request_id"]

    async def send_response(self, target_agent: str, request_id: str, response: Any) -> None:
        """
        Send a response to a specific agent.

        Args:
            target_agent: Name of the target agent
            request_id: ID of the original request
            response: Response data
        """
        message = {
            "request_id": request_id,
            "response": response,
            "timestamp": datetime.utcnow().isoformat()
        }

        await self.publish(f"agent.{target_agent}.response", message)
        self.logger.debug(f"Response sent to {target_agent}", request_id=request_id)

    def subscribe_to_pattern(self, subscriber_name: str, pattern: str,
                           callback: Callable[[Any], None]) -> Subscriber:
        """
        Subscribe to messages matching a key pattern.

        Args:
            subscriber_name: Unique name for this subscriber
            pattern: Key pattern to match (e.g., "discovery.*", "service.crawler")
            callback: Async function to call when message received

        Returns:
            Subscriber instance for management
        """
        if self._shutdown:
            raise RuntimeError("Cannot subscribe - bus is shutting down")

        # Create or get subscriber
        if subscriber_name not in self._subscribers:
            subscriber = Subscriber(self.hub, subscriber_name)
            self._subscribers[subscriber_name] = subscriber
            self._active_subscriptions[subscriber_name] = set()
            self.logger.debug(f"Created subscriber: {subscriber_name}")
        else:
            subscriber = self._subscribers[subscriber_name]

        # Subscribe to pattern
        key = Key(pattern)
        subscriber.subscribe(key)

        # Track subscription
        if subscriber_name not in self._active_subscriptions:
            self._active_subscriptions[subscriber_name] = set()
        self._active_subscriptions[subscriber_name].add(key)

        # Register callback
        @subscriber.on(key)
        async def message_handler(key_received, message):
            """Handle incoming messages."""
            try:
                await callback(message)
            except Exception as e:
                self.logger.error(f"Subscriber {subscriber_name} callback error: {e}",
                                exc_info=True)

        self.logger.info(f"Subscriber {subscriber_name} subscribed to pattern: {pattern}")
        return subscriber

    def unsubscribe(self, subscriber_name: str, pattern: Optional[str] = None) -> None:
        """
        Unsubscribe from message patterns.

        Args:
            subscriber_name: Name of the subscriber
            pattern: Specific pattern to unsubscribe from (or None for all)
        """
        if subscriber_name not in self._subscribers:
            self.logger.warning(f"Subscriber {subscriber_name} not found")
            return

        subscriber = self._subscribers[subscriber_name]

        if pattern:
            # Unsubscribe from specific pattern
            key = Key(pattern)
            subscriber.unsubscribe(key)

            if subscriber_name in self._active_subscriptions:
                self._active_subscriptions[subscriber_name].discard(key)

            self.logger.info(f"Unsubscribed {subscriber_name} from {pattern}")
        else:
            # Unsubscribe from all patterns
            if subscriber_name in self._active_subscriptions:
                for key in self._active_subscriptions[subscriber_name]:
                    subscriber.unsubscribe(key)
                del self._active_subscriptions[subscriber_name]

            del self._subscribers[subscriber_name]
            self.logger.info(f"Unsubscribed {subscriber_name} from all patterns")

    def get_active_subscriptions(self) -> Dict[str, Set[str]]:
        """
        Get all active subscriptions for monitoring.

        Returns:
            Dictionary mapping subscriber names to their key patterns
        """
        return {
            name: {str(key) for key in keys}
            for name, keys in self._active_subscriptions.items()
        }

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - clean shutdown."""
        await self.shutdown()

    async def shutdown(self):
        """
        Gracefully shutdown the message bus.

        Unsubscribes all subscribers and cleans up resources.
        """
        if self._shutdown:
            return

        self._shutdown = True
        self.logger.info("Shutting down MessageBus")

        # Unsubscribe all
        for subscriber_name in list(self._subscribers.keys()):
            self.unsubscribe(subscriber_name)

        self.logger.info("MessageBus shutdown complete")

    @classmethod
    def reset_singleton(cls):
        """Reset the singleton instance (mainly for testing)."""
        cls._instance = None