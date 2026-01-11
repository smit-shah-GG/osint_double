"""Structured logging utilities using structlog for agent context and tracing."""

import os
import sys
import uuid
from typing import Any, Optional
import structlog
from structlog.processors import JSONRenderer, KeyValueRenderer
from structlog.contextvars import merge_contextvars

# Check if we're in development mode (TTY and LOG_FORMAT=console)
IS_TTY = sys.stderr.isatty()
LOG_FORMAT = os.getenv("LOG_FORMAT", "console").lower()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


def configure_structured_logging() -> None:
    """
    Configure structured logging with appropriate processors and renderers.

    Uses:
    - Console renderer for development (colorized, human-readable)
    - JSON renderer for production (structured, machine-readable)
    - Context binding for agent_id and correlation_id
    """
    # Common processors for all environments
    processors = [
        merge_contextvars,  # Merge context variables
        structlog.processors.add_log_level,  # Add log level name
        structlog.processors.TimeStamper(fmt="iso"),  # ISO timestamp
        structlog.processors.StackInfoRenderer(),  # Stack trace for errors
        structlog.processors.format_exc_info,  # Exception formatting
    ]

    # Choose renderer based on environment
    if IS_TTY and LOG_FORMAT == "console":
        # Development mode: colorized console output
        processors.append(
            structlog.dev.ConsoleRenderer(
                colors=True,
                exception_formatter=structlog.dev.plain_traceback,
            )
        )
    else:
        # Production mode: JSON output
        processors.append(JSONRenderer())

    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(LOG_LEVEL),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_structured_logger(
    name: str,
    agent_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    **additional_context: Any,
) -> structlog.BoundLogger:
    """
    Get a structured logger with bound context.

    Args:
        name: Logger name (typically module name)
        agent_id: Optional agent ID to bind
        agent_name: Optional agent name to bind
        **additional_context: Additional context to bind

    Returns:
        Configured BoundLogger instance with context

    Example:
        >>> logger = get_structured_logger("crawler.news", agent_id="abc-123")
        >>> logger.info("fetching articles", source="reuters", count=10)
    """
    logger = structlog.get_logger(name)

    # Bind agent context if provided
    if agent_id:
        logger = logger.bind(agent_id=agent_id)
    if agent_name:
        logger = logger.bind(agent_name=agent_name)

    # Bind additional context
    if additional_context:
        logger = logger.bind(**additional_context)

    return logger


def get_correlation_id() -> str:
    """
    Generate a correlation ID for tracing agent interactions.

    Returns:
        UUID string for correlation

    Example:
        >>> correlation_id = get_correlation_id()
        >>> logger = get_structured_logger("agent").bind(correlation_id=correlation_id)
    """
    return str(uuid.uuid4())


def bind_agent_context(
    logger: structlog.BoundLogger,
    agent_id: str,
    agent_name: str,
    correlation_id: Optional[str] = None,
) -> structlog.BoundLogger:
    """
    Bind agent context to an existing logger.

    Args:
        logger: Existing logger instance
        agent_id: Agent ID to bind
        agent_name: Agent name to bind
        correlation_id: Optional correlation ID for tracing

    Returns:
        Logger with bound agent context

    Example:
        >>> base_logger = get_structured_logger("system")
        >>> agent_logger = bind_agent_context(base_logger, "abc-123", "NewsAgent")
    """
    bound_logger = logger.bind(agent_id=agent_id, agent_name=agent_name)

    if correlation_id:
        bound_logger = bound_logger.bind(correlation_id=correlation_id)

    return bound_logger


# Configure on module import
configure_structured_logging()


# Export for convenience
__all__ = [
    "get_structured_logger",
    "get_correlation_id",
    "bind_agent_context",
    "configure_structured_logging",
]