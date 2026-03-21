"""SQLAlchemy declarative base and common mixins for all ORM models.

Every model in this package must inherit from ``Base``. This ensures
all tables are registered in ``Base.metadata``, which Alembic uses
for autogenerate migrations.

``TimestampMixin`` provides ``created_at`` and ``updated_at`` columns
with server-side defaults, suitable for all domain models.

Usage:
    from osint_system.data_management.models.base import Base, TimestampMixin

    class MyModel(TimestampMixin, Base):
        __tablename__ = "my_table"
        ...
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Root declarative base class for all ORM models.

    Provides the ``metadata`` object that Alembic reads for schema diffs.
    Do NOT create additional DeclarativeBase subclasses -- all models
    must share this single metadata registry.
    """

    pass


class TimestampMixin:
    """Mixin providing created_at and updated_at timestamp columns.

    ``created_at`` defaults to ``now()`` at the database level via
    ``server_default``. ``updated_at`` is nullable and set on update
    via ``onupdate``.

    Must appear BEFORE ``Base`` in MRO (``class Foo(TimestampMixin, Base):``)
    so its column definitions are picked up by the declarative metaclass.
    """

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        onupdate=func.now(),
        nullable=True,
        default=None,
    )
