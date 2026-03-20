"""Production-grade logging configuration using loguru with automatic dev/prod detection."""

import sys
from loguru import logger

from osint_system.config.settings import settings


def _patch_component_label(record: dict) -> None:
    """Normalize the display label for log records.

    Some modules bind ``component``, others bind ``agent_name``.
    This patcher ensures a consistent ``_label`` key is always
    available for the format string.
    """
    extra = record["extra"]
    extra["_label"] = extra.get("component") or extra.get("agent_name", "unknown")


def configure_logging() -> None:
    """
    Configure loguru based on environment settings.

    Behavior:
    - Development (TTY + console format): Colorized, human-readable output
    - Production (non-TTY or json format): JSON-structured logs to stdout
    - Respects LOG_LEVEL from settings
    """
    # Remove default handler
    logger.remove()

    # Normalize component/agent_name into _label for format strings
    logger.configure(patcher=_patch_component_label)

    # Determine if we're in a TTY environment (interactive terminal)
    is_tty = sys.stderr.isatty()
    use_console_format = settings.log_format.lower() == "console"

    if is_tty and use_console_format:
        # Development mode: colorized, human-readable
        logger.add(
            sys.stderr,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{extra[_label]}</cyan> | <level>{message}</level>",
            level=settings.log_level,
            colorize=True,
        )
    else:
        # Production mode: JSON-structured logs
        logger.add(
            sys.stdout,
            format="{message}",
            level=settings.log_level,
            serialize=True,  # Output as JSON
            diagnose=False,  # Disable variable inspection for security
        )


def get_logger(component: str):
    """
    Get a logger instance bound to a specific component name.

    Args:
        component: Component/module name for log context

    Returns:
        Logger instance with component context

    Example:
        >>> log = get_logger("crawler.newsfeed")
        >>> log.info("Fetching articles")
    """
    return logger.bind(component=component)


# Configure logging on module import
configure_logging()

# Export the configured logger for direct use
__all__ = ["logger", "get_logger", "configure_logging"]
