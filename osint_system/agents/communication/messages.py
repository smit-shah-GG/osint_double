"""Pydantic message schemas for type-safe agent communication."""

from typing import Any, Optional, List, Dict, Literal, Union
from datetime import datetime
import uuid
from pydantic import BaseModel, Field, field_validator


class BaseMessage(BaseModel):
    """
    Base message schema for all agent communication.

    All messages include standard metadata fields for tracking
    and routing within the message bus.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()),
                   description="Unique message identifier")
    timestamp: datetime = Field(default_factory=datetime.utcnow,
                               description="Message creation timestamp")
    from_agent: str = Field(description="Name/ID of the sending agent")
    to_agent: Optional[str] = Field(None,
                                   description="Target agent name/ID (None for broadcast)")
    message_type: str = Field(description="Message type discriminator")

    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        use_enum_values = True
        validate_assignment = True


class CapabilityAnnouncement(BaseMessage):
    """
    Message for broadcasting agent capabilities.

    Used for agent discovery - agents announce their capabilities
    to the registry and other interested agents.
    """

    message_type: Literal["capability_announcement"] = "capability_announcement"
    agent_name: str = Field(description="Human-readable agent name")
    capabilities: List[str] = Field(description="List of capability strings")
    metadata: Dict[str, Any] = Field(default_factory=dict,
                                    description="Additional agent metadata")

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, v):
        """Ensure capabilities list is not empty."""
        if not v:
            raise ValueError("Capabilities list cannot be empty")
        # Ensure all capabilities are non-empty strings
        if not all(isinstance(cap, str) and cap.strip() for cap in v):
            raise ValueError("All capabilities must be non-empty strings")
        return v


class ServiceRequest(BaseMessage):
    """
    Request for a service from agents with specific capabilities.

    Agents can request services without knowing which specific
    agent will handle the request - routing is capability-based.
    """

    message_type: Literal["service_request"] = "service_request"
    capability_needed: str = Field(description="Required capability for this service")
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()),
                          description="Unique request identifier for tracking responses")
    payload: Dict[str, Any] = Field(description="Request data/parameters")
    timeout_seconds: Optional[int] = Field(30,
                                          description="Request timeout in seconds")
    priority: int = Field(default=5, ge=1, le=10,
                        description="Request priority (1=lowest, 10=highest)")

    @field_validator("capability_needed")
    @classmethod
    def validate_capability(cls, v):
        """Ensure capability is non-empty."""
        if not v or not v.strip():
            raise ValueError("Capability needed must be specified")
        return v.strip()


class ServiceResponse(BaseMessage):
    """
    Response to a service request.

    Contains the result of the service execution or error information
    if the service could not be completed.
    """

    message_type: Literal["service_response"] = "service_response"
    request_id: str = Field(description="ID of the original request")
    success: bool = Field(description="Whether the service completed successfully")
    result: Optional[Any] = Field(None,
                                 description="Service execution result (if successful)")
    error: Optional[str] = Field(None,
                                description="Error message (if unsuccessful)")
    error_details: Optional[Dict[str, Any]] = Field(None,
                                                   description="Additional error context")
    execution_time_ms: Optional[int] = Field(None,
                                            description="Service execution time in milliseconds")

    @field_validator("error")
    @classmethod
    def validate_error_consistency(cls, v, values):
        """Ensure error field is consistent with success flag."""
        success = values.get("success", True)
        if not success and not v:
            raise ValueError("Error message required when success=False")
        if success and v:
            raise ValueError("Error message should be None when success=True")
        return v


class HeartbeatMessage(BaseMessage):
    """
    Heartbeat message for agent health monitoring.

    Agents periodically send heartbeats to indicate they are
    still active and responsive.
    """

    message_type: Literal["heartbeat"] = "heartbeat"
    agent_name: str = Field(description="Name of the agent sending heartbeat")
    status: Literal["active", "busy", "idle"] = Field("active",
                                                     description="Current agent status")
    capabilities: Optional[List[str]] = Field(None,
                                             description="Current capabilities (may change)")
    metrics: Optional[Dict[str, Any]] = Field(None,
                                             description="Agent performance metrics")


class TaskAssignment(BaseMessage):
    """
    Task assignment from orchestrator to worker agent.

    Used by planning/orchestration agents to delegate
    specific tasks to worker agents.
    """

    message_type: Literal["task_assignment"] = "task_assignment"
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()),
                       description="Unique task identifier")
    task_type: str = Field(description="Type of task to execute")
    task_description: str = Field(description="Human-readable task description")
    parameters: Dict[str, Any] = Field(default_factory=dict,
                                      description="Task parameters and configuration")
    deadline: Optional[datetime] = Field(None,
                                        description="Task deadline (if applicable)")
    dependencies: List[str] = Field(default_factory=list,
                                   description="IDs of tasks this depends on")


class TaskResult(BaseMessage):
    """
    Result of task execution.

    Sent by worker agents back to orchestrator upon
    task completion or failure.
    """

    message_type: Literal["task_result"] = "task_result"
    task_id: str = Field(description="ID of the completed task")
    status: Literal["completed", "failed", "cancelled"] = Field(
        description="Task completion status")
    result: Optional[Any] = Field(None,
                                description="Task execution result")
    error: Optional[str] = Field(None,
                               description="Error message if task failed")
    execution_time_ms: int = Field(description="Task execution time in milliseconds")
    resources_used: Optional[Dict[str, Any]] = Field(None,
                                                    description="Resources consumed during execution")


class BroadcastMessage(BaseMessage):
    """
    General broadcast message to all agents.

    Used for system-wide announcements, alerts, or
    configuration updates.
    """

    message_type: Literal["broadcast"] = "broadcast"
    broadcast_type: str = Field(description="Type of broadcast (alert, config, info, etc.)")
    subject: str = Field(description="Broadcast subject/title")
    content: Any = Field(description="Broadcast content")
    priority: int = Field(default=5, ge=1, le=10,
                        description="Broadcast priority")
    expires_at: Optional[datetime] = Field(None,
                                          description="When this broadcast expires")


# Union type for all message types
MessageType = Union[
    CapabilityAnnouncement,
    ServiceRequest,
    ServiceResponse,
    HeartbeatMessage,
    TaskAssignment,
    TaskResult,
    BroadcastMessage
]


def parse_message(data: dict) -> MessageType:
    """
    Parse a dictionary into the appropriate message type.

    Args:
        data: Dictionary containing message data

    Returns:
        Parsed message object of the appropriate type

    Raises:
        ValueError: If message_type is unknown or data is invalid
    """
    message_type = data.get("message_type")

    type_map = {
        "capability_announcement": CapabilityAnnouncement,
        "service_request": ServiceRequest,
        "service_response": ServiceResponse,
        "heartbeat": HeartbeatMessage,
        "task_assignment": TaskAssignment,
        "task_result": TaskResult,
        "broadcast": BroadcastMessage
    }

    if message_type not in type_map:
        raise ValueError(f"Unknown message type: {message_type}")

    message_class = type_map[message_type]
    return message_class(**data)


def create_capability_announcement(agent_name: str, capabilities: List[str],
                                  from_agent: str, **kwargs) -> CapabilityAnnouncement:
    """
    Helper to create a capability announcement message.

    Args:
        agent_name: Name of the announcing agent
        capabilities: List of capabilities
        from_agent: ID of the sending agent
        **kwargs: Additional message fields

    Returns:
        CapabilityAnnouncement message
    """
    return CapabilityAnnouncement(
        agent_name=agent_name,
        capabilities=capabilities,
        from_agent=from_agent,
        **kwargs
    )


def create_service_request(capability: str, payload: dict,
                         from_agent: str, **kwargs) -> ServiceRequest:
    """
    Helper to create a service request message.

    Args:
        capability: Required capability
        payload: Request data
        from_agent: ID of the requesting agent
        **kwargs: Additional message fields

    Returns:
        ServiceRequest message
    """
    return ServiceRequest(
        capability_needed=capability,
        payload=payload,
        from_agent=from_agent,
        **kwargs
    )


def create_service_response(request_id: str, success: bool,
                          from_agent: str, result: Any = None,
                          error: str = None, **kwargs) -> ServiceResponse:
    """
    Helper to create a service response message.

    Args:
        request_id: ID of the original request
        success: Whether the service succeeded
        from_agent: ID of the responding agent
        result: Service result (if successful)
        error: Error message (if unsuccessful)
        **kwargs: Additional message fields

    Returns:
        ServiceResponse message
    """
    return ServiceResponse(
        request_id=request_id,
        success=success,
        from_agent=from_agent,
        result=result,
        error=error,
        **kwargs
    )