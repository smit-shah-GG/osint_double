"""Neo4j graph database configuration.

Provides GraphConfig for Neo4j connection settings and graph layer behavior.
Loads from environment variables with sensible defaults for local development.

This module has zero dependency on the neo4j driver -- it is pure configuration.
The actual driver is only imported by the adapter implementations (neo4j_adapter.py).

Environment variables:
    NEO4J_URI: Bolt URI for Neo4j connection (default: bolt://localhost:7687)
    NEO4J_USER: Neo4j username (default: neo4j)
    NEO4J_PASSWORD: Neo4j password (default: osint_dev_password)
    NEO4J_DATABASE: Neo4j database name (default: neo4j)
    GRAPH_USE_NETWORKX: Force NetworkX backend even if Neo4j is available (default: false)
    GRAPH_LLM_EXTRACTION: Enable LLM-based relationship extraction (default: false)

Usage:
    from osint_system.config.graph_config import GraphConfig

    config = GraphConfig.from_env()
    print(config.neo4j_uri)  # bolt://localhost:7687
"""

import os
from pathlib import Path

from pydantic import BaseModel, Field


def _parse_bool(value: str | None, default: bool = False) -> bool:
    """Parse a boolean from an environment variable string.

    Handles common truthy/falsy representations. Returns ``default`` if
    the value is None or empty.

    Args:
        value: Raw env var string (e.g., "true", "1", "yes", "false", "0", "no").
        default: Value to return if ``value`` is None or empty.

    Returns:
        Parsed boolean.
    """
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("true", "1", "yes")


class GraphConfig(BaseModel):
    """Neo4j connection and graph layer configuration.

    All fields have sensible defaults for local development with Docker Compose.
    Use ``from_env()`` to load from environment variables.

    Attributes:
        neo4j_uri: Bolt protocol URI for Neo4j. Docker default: bolt://localhost:7687.
        neo4j_user: Neo4j authentication username.
        neo4j_password: Neo4j authentication password. Override for production.
        neo4j_database: Neo4j database name. Community Edition always uses "neo4j".
        use_networkx_fallback: Force NetworkX in-memory backend instead of Neo4j.
            Useful for tests and CI where Docker is unavailable. Production
            hard-requires Neo4j per CONTEXT.md.
        batch_size: UNWIND batch size for bulk node/edge ingestion. Higher values
            improve throughput but increase transaction memory. Range: 100-50000.
        max_hops: Default maximum traversal depth for path queries. Bounded to
            prevent unbounded traversal (Pitfall 4 from RESEARCH.md). Range: 1-10.
        llm_relationship_extraction: Gate for LLM-based semantic relationship
            extraction (CAUSES, PRECEDES, ATTRIBUTED_TO). When False, only
            rule-based extraction runs. Per RESEARCH.md open question 4:
            LLM cost per fact is unclear at scale, so this defaults to off.
        cross_investigation_matching: Enable automatic cross-investigation entity
            matching. When True, entities with matching canonical names across
            investigations are linked with ``cross_investigation=True`` edges.
    """

    neo4j_uri: str = Field(
        default="bolt://localhost:7687",
        description="Bolt URI for Neo4j connection",
    )
    neo4j_user: str = Field(
        default="neo4j",
        description="Neo4j authentication username",
    )
    neo4j_password: str = Field(
        default="osint_dev_password",
        description="Neo4j authentication password",
    )
    neo4j_database: str = Field(
        default="neo4j",
        description="Neo4j database name (Community Edition: always 'neo4j')",
    )
    use_networkx_fallback: bool = Field(
        default=False,
        description="Force NetworkX backend instead of Neo4j",
    )
    batch_size: int = Field(
        default=5000,
        ge=100,
        le=50000,
        description="UNWIND batch size for bulk ingestion",
    )
    max_hops: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Default max hops for path queries",
    )
    llm_relationship_extraction: bool = Field(
        default=False,
        description="Enable LLM-based semantic relationship extraction",
    )
    cross_investigation_matching: bool = Field(
        default=True,
        description="Enable cross-investigation entity matching",
    )

    @classmethod
    def from_env(cls) -> "GraphConfig":
        """Load configuration from environment variables.

        Reads NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_DATABASE,
        GRAPH_USE_NETWORKX, and GRAPH_LLM_EXTRACTION from the environment.
        Falls back to field defaults when variables are not set.

        Attempts to load a ``.env`` file from the project root using
        python-dotenv if available. Fails silently if python-dotenv is
        not installed or ``.env`` does not exist.

        Returns:
            GraphConfig populated from environment variables.
        """
        # Attempt .env loading (best-effort, no hard dependency on dotenv)
        try:
            from dotenv import load_dotenv

            # Walk up from this file to find project root .env
            project_root = Path(__file__).resolve().parent.parent.parent
            env_path = project_root / ".env"
            if env_path.exists():
                load_dotenv(env_path)
        except ImportError:
            pass

        kwargs: dict = {}

        uri = os.getenv("NEO4J_URI")
        if uri:
            kwargs["neo4j_uri"] = uri

        user = os.getenv("NEO4J_USER")
        if user:
            kwargs["neo4j_user"] = user

        password = os.getenv("NEO4J_PASSWORD")
        if password:
            kwargs["neo4j_password"] = password

        database = os.getenv("NEO4J_DATABASE")
        if database:
            kwargs["neo4j_database"] = database

        use_nx = os.getenv("GRAPH_USE_NETWORKX")
        if use_nx is not None:
            kwargs["use_networkx_fallback"] = _parse_bool(use_nx, default=False)

        llm_extract = os.getenv("GRAPH_LLM_EXTRACTION")
        if llm_extract is not None:
            kwargs["llm_relationship_extraction"] = _parse_bool(
                llm_extract, default=False
            )

        batch = os.getenv("GRAPH_BATCH_SIZE")
        if batch is not None:
            try:
                kwargs["batch_size"] = int(batch)
            except ValueError:
                pass  # Fall through to default; Pydantic validates bounds

        max_hops_env = os.getenv("GRAPH_MAX_HOPS")
        if max_hops_env is not None:
            try:
                kwargs["max_hops"] = int(max_hops_env)
            except ValueError:
                pass

        cross_inv = os.getenv("GRAPH_CROSS_INVESTIGATION")
        if cross_inv is not None:
            kwargs["cross_investigation_matching"] = _parse_bool(
                cross_inv, default=True
            )

        return cls(**kwargs)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "neo4j_uri": "bolt://localhost:7687",
                    "neo4j_user": "neo4j",
                    "neo4j_password": "osint_dev_password",
                    "neo4j_database": "neo4j",
                    "use_networkx_fallback": False,
                    "batch_size": 5000,
                    "max_hops": 3,
                    "llm_relationship_extraction": False,
                    "cross_investigation_matching": True,
                }
            ]
        }
    }
