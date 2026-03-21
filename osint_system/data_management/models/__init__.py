"""SQLAlchemy ORM models for the OSINT system.

All model classes must be imported here so that ``Base.metadata``
contains the full schema when Alembic autogenerate runs.

Model classes will be added in Plan 02 (ORM models + Alembic migration).
"""

from osint_system.data_management.models.base import Base

__all__ = ["Base"]
