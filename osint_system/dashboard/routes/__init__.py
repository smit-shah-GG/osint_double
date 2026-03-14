"""Dashboard route modules.

Each module provides an APIRouter instance that is included by the
main app factory with appropriate prefixes:

- investigations: / and /investigation/{investigation_id}
- facts: /facts/{investigation_id}
- reports: /reports/{investigation_id}
- monitoring: /monitoring/status
- api: /api/investigation/{investigation_id}/*
"""

from osint_system.dashboard.routes import (
    api,
    facts,
    investigations,
    monitoring,
    reports,
)

__all__ = [
    "api",
    "facts",
    "investigations",
    "monitoring",
    "reports",
]
