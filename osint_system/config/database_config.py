"""PostgreSQL database configuration.

Provides DatabaseConfig for PostgreSQL connection settings and pool tuning.
Loads from environment variables with sensible defaults for local development.

This module has zero dependency on SQLAlchemy or asyncpg -- it is pure
configuration. The actual engine is only created by database.py.

Environment variables:
    POSTGRES_HOST: PostgreSQL hostname (default: localhost)
    POSTGRES_PORT: PostgreSQL port (default: 5432)
    POSTGRES_USER: PostgreSQL username (default: osint)
    POSTGRES_PASSWORD: PostgreSQL password (default: osint_dev_password)
    POSTGRES_DB: PostgreSQL database name (default: osint)
    POSTGRES_POOL_SIZE: Connection pool size (default: 10)
    POSTGRES_MAX_OVERFLOW: Max overflow connections beyond pool_size (default: 20)

Usage:
    from osint_system.config.database_config import DatabaseConfig

    config = DatabaseConfig.from_env()
    print(config.database_url)  # postgresql+asyncpg://osint:...@localhost:5432/osint
"""

import os
from pathlib import Path

from pydantic import BaseModel, Field


class DatabaseConfig(BaseModel):
    """PostgreSQL connection and pool configuration.

    All fields have sensible defaults matching the docker-compose.yml
    development environment. Use ``from_env()`` to load overrides from
    environment variables.

    Attributes:
        postgres_host: PostgreSQL server hostname.
        postgres_port: PostgreSQL server port.
        postgres_user: PostgreSQL authentication username.
        postgres_password: PostgreSQL authentication password.
        postgres_db: PostgreSQL database name.
        pool_size: SQLAlchemy connection pool size. Controls the number
            of persistent connections held open. Range: 1-50.
        max_overflow: Maximum temporary connections beyond pool_size
            during load spikes. Range: 0-100.
    """

    postgres_host: str = Field(
        default="localhost",
        description="PostgreSQL server hostname",
    )
    postgres_port: int = Field(
        default=5432,
        description="PostgreSQL server port",
    )
    postgres_user: str = Field(
        default="osint",
        description="PostgreSQL authentication username",
    )
    postgres_password: str = Field(
        default="osint_dev_password",
        description="PostgreSQL authentication password",
    )
    postgres_db: str = Field(
        default="osint",
        description="PostgreSQL database name",
    )
    pool_size: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Connection pool size",
    )
    max_overflow: int = Field(
        default=20,
        ge=0,
        le=100,
        description="Max overflow connections beyond pool_size",
    )

    @property
    def database_url(self) -> str:
        """Async connection URL for SQLAlchemy + asyncpg.

        Returns:
            URL in the format ``postgresql+asyncpg://user:pass@host:port/db``.
        """
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sync_database_url(self) -> str:
        """Synchronous connection URL for Alembic migrations (psycopg driver).

        Returns:
            URL in the format ``postgresql+psycopg://user:pass@host:port/db``.
        """
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        """Load configuration from environment variables.

        Reads POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD,
        POSTGRES_DB, POSTGRES_POOL_SIZE, POSTGRES_MAX_OVERFLOW from the
        environment. Falls back to field defaults when variables are not set.

        Attempts to load a ``.env`` file from the project root using
        python-dotenv if available. Fails silently if python-dotenv is
        not installed or ``.env`` does not exist.

        Returns:
            DatabaseConfig populated from environment variables.
        """
        # Attempt .env loading (best-effort, same pattern as GraphConfig)
        try:
            from dotenv import load_dotenv

            project_root = Path(__file__).resolve().parent.parent.parent
            env_path = project_root / ".env"
            if env_path.exists():
                load_dotenv(env_path)
        except ImportError:
            pass

        kwargs: dict = {}

        host = os.getenv("POSTGRES_HOST")
        if host:
            kwargs["postgres_host"] = host

        port = os.getenv("POSTGRES_PORT")
        if port is not None:
            try:
                kwargs["postgres_port"] = int(port)
            except ValueError:
                pass

        user = os.getenv("POSTGRES_USER")
        if user:
            kwargs["postgres_user"] = user

        password = os.getenv("POSTGRES_PASSWORD")
        if password:
            kwargs["postgres_password"] = password

        db = os.getenv("POSTGRES_DB")
        if db:
            kwargs["postgres_db"] = db

        pool = os.getenv("POSTGRES_POOL_SIZE")
        if pool is not None:
            try:
                kwargs["pool_size"] = int(pool)
            except ValueError:
                pass

        overflow = os.getenv("POSTGRES_MAX_OVERFLOW")
        if overflow is not None:
            try:
                kwargs["max_overflow"] = int(overflow)
            except ValueError:
                pass

        return cls(**kwargs)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "postgres_host": "localhost",
                    "postgres_port": 5432,
                    "postgres_user": "osint",
                    "postgres_password": "osint_dev_password",
                    "postgres_db": "osint",
                    "pool_size": 10,
                    "max_overflow": 20,
                }
            ]
        }
    }
