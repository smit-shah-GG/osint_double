"""OSINT Dashboard: FastAPI + Jinja2 + HTMX web interface.

Provides investigation monitoring and results exploration through a
local web dashboard. HTMX enables interactivity without a JavaScript
build step — partial page updates, auto-refresh polling, and inline
expansion of fact details.

Key exports:
- create_app: FastAPI application factory with store dependency injection
- run_dashboard: CLI entry point for starting the dashboard server
"""

from osint_system.dashboard.app import create_app, run_dashboard

__all__ = [
    "create_app",
    "run_dashboard",
]
