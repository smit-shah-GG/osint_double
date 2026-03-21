"""SQLAlchemy declarative base for all ORM models.

Every model in this package must inherit from ``Base``. This ensures
all tables are registered in ``Base.metadata``, which Alembic uses
for autogenerate migrations.

Usage:
    from osint_system.data_management.models.base import Base

    class MyModel(Base):
        __tablename__ = "my_table"
        ...
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Root declarative base class for all ORM models.

    Provides the ``metadata`` object that Alembic reads for schema diffs.
    Do NOT create additional DeclarativeBase subclasses -- all models
    must share this single metadata registry.
    """

    pass
