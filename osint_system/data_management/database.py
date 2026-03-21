"""Async SQLAlchemy engine and session factory for PostgreSQL.

Provides module-level engine/session lifecycle management. All database
access flows through ``init_db()`` at application startup and
``close_db()`` at shutdown.

CRITICAL design decision: ``expire_on_commit=False`` on the session factory.
Without this, accessing any ORM attribute after ``session.commit()`` triggers
a lazy load -- which raises ``MissingGreenlet`` in async contexts because
SQLAlchemy cannot implicitly spawn an IO coroutine from synchronous attribute
access. See: https://docs.sqlalchemy.org/en/20/errors.html#error-xd2s

Usage:
    from osint_system.data_management.database import init_db, get_session_factory, close_db

    # At startup
    session_factory = init_db()

    # During request handling
    async with get_session_factory()() as session:
        result = await session.execute(select(SomeModel))
        ...

    # At shutdown
    await close_db()
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from osint_system.config.database_config import DatabaseConfig

logger = logging.getLogger(__name__)

# Module-level singletons. Initialized by ``init_db()``, cleared by ``close_db()``.
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_engine(config: DatabaseConfig) -> AsyncEngine:
    """Create an ``AsyncEngine`` from the given configuration.

    Uses asyncpg as the underlying driver. Enables ``pool_pre_ping`` to
    discard stale connections before checkout (guards against PostgreSQL
    idle connection timeouts and container restarts).

    Args:
        config: Database connection and pool configuration.

    Returns:
        Configured ``AsyncEngine`` instance. Caller owns lifecycle
        (must call ``engine.dispose()`` on shutdown).
    """
    return create_async_engine(
        config.database_url,
        pool_size=config.pool_size,
        max_overflow=config.max_overflow,
        pool_pre_ping=True,
        echo=False,
    )


def create_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Create an ``async_sessionmaker`` bound to the given engine.

    ``expire_on_commit=False`` is CRITICAL for async usage. Without it,
    any post-commit attribute access on an ORM instance triggers an
    implicit lazy load which raises ``MissingGreenlet`` because the
    async event loop cannot be re-entered synchronously.

    Args:
        engine: The ``AsyncEngine`` to bind sessions to.

    Returns:
        Session factory. Call it (``factory()``) to get an ``AsyncSession``.
    """
    return async_sessionmaker(engine, expire_on_commit=False)


def init_db(
    config: DatabaseConfig | None = None,
) -> async_sessionmaker[AsyncSession]:
    """Initialize the module-level engine and session factory.

    Idempotent: if already initialized, returns the existing session
    factory without creating a new engine. This prevents accidental
    double-initialization from multiple call sites.

    Args:
        config: Database configuration. Defaults to
            ``DatabaseConfig.from_env()`` if not provided.

    Returns:
        The module-level ``async_sessionmaker`` instance.
    """
    global _engine, _session_factory  # noqa: PLW0603

    if _session_factory is not None:
        logger.debug("Database already initialized, returning existing session factory")
        return _session_factory

    if config is None:
        from osint_system.config.database_config import DatabaseConfig

        config = DatabaseConfig.from_env()

    _engine = create_engine(config)
    _session_factory = create_session_factory(_engine)

    logger.info(
        "Database initialized: %s:%d/%s (pool=%d, overflow=%d)",
        config.postgres_host,
        config.postgres_port,
        config.postgres_db,
        config.pool_size,
        config.max_overflow,
    )
    return _session_factory


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the module-level session factory.

    Raises:
        RuntimeError: If ``init_db()`` has not been called.

    Returns:
        The ``async_sessionmaker`` instance.
    """
    if _session_factory is None:
        raise RuntimeError(
            "Database not initialized. Call init_db() before get_session_factory()."
        )
    return _session_factory


def get_engine() -> AsyncEngine:
    """Return the module-level async engine.

    Raises:
        RuntimeError: If ``init_db()`` has not been called.

    Returns:
        The ``AsyncEngine`` instance.
    """
    if _engine is None:
        raise RuntimeError(
            "Database not initialized. Call init_db() before get_engine()."
        )
    return _engine


async def close_db() -> None:
    """Dispose the engine and reset module-level state.

    Safe to call even if ``init_db()`` was never called (no-op).
    After this call, ``get_engine()`` and ``get_session_factory()``
    will raise ``RuntimeError`` until ``init_db()`` is called again.
    """
    global _engine, _session_factory  # noqa: PLW0603

    if _engine is not None:
        await _engine.dispose()
        logger.info("Database engine disposed")

    _engine = None
    _session_factory = None
