"""Analysis and reporting configuration.

Provides AnalysisConfig for LLM synthesis settings, token budgets, model
selection, and output directory paths. Loads from environment variables
with an ``ANALYSIS_`` prefix, following the same from_env() pattern as
GraphConfig.

Environment variables:
    ANALYSIS_SYNTHESIS_MODEL: Gemini model for synthesis (default: gemini-1.5-pro)
    ANALYSIS_TEMPERATURE: LLM temperature for synthesis (default: 0.3)
    ANALYSIS_MAX_TOKENS_PER_SECTION: Token budget per prompt section (default: 15000)
    ANALYSIS_MAX_KEY_JUDGMENTS: Max key judgments per report (default: 10)
    ANALYSIS_MAX_ALT_HYPOTHESES: Max alternative hypotheses per judgment (default: 5)
    ANALYSIS_REPORT_OUTPUT_DIR: Report output directory (default: reports/)
    ANALYSIS_DATABASE_OUTPUT_DIR: Database export directory (default: exports/)
    ANALYSIS_DASHBOARD_HOST: Dashboard bind host (default: 127.0.0.1)
    ANALYSIS_DASHBOARD_PORT: Dashboard bind port (default: 8080)
    ANALYSIS_AUTO_GENERATE: Auto-generate report on pipeline complete (default: true)

Usage:
    from osint_system.config.analysis_config import AnalysisConfig

    config = AnalysisConfig.from_env()
    print(config.synthesis_model)  # gemini-1.5-pro
    print(config.temperature)     # 0.3
"""

import os
from pathlib import Path

from pydantic import BaseModel, Field


def _parse_bool(value: str | None, default: bool = False) -> bool:
    """Parse a boolean from an environment variable string.

    Args:
        value: Raw env var string.
        default: Value to return if value is None or empty.

    Returns:
        Parsed boolean.
    """
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("true", "1", "yes")


class AnalysisConfig(BaseModel):
    """Analysis and reporting engine configuration.

    Controls LLM model selection, token budgets, output limits,
    file paths, and dashboard network settings.

    Attributes:
        synthesis_model: Gemini model identifier for synthesis tasks.
        max_tokens_per_section: Token budget per synthesis prompt section.
            Per RESEARCH.md: quality degrades beyond ~100K tokens;
            target 10K-30K per section.
        temperature: LLM temperature. Low values (0.2-0.4) for factual
            analysis; higher risks hallucination/casual language drift.
        max_key_judgments: Cap on key judgments per report.
        max_alternative_hypotheses: Cap on alternative hypotheses per judgment.
        report_output_dir: Directory for rendered reports (Markdown, PDF).
        database_output_dir: Directory for SQLite/JSON database exports.
        dashboard_host: Dashboard web server bind address.
        dashboard_port: Dashboard web server bind port.
        auto_generate_on_complete: Auto-generate report when verification
            pipeline completes.
    """

    synthesis_model: str = Field(
        default="gemini-1.5-pro",
        description="Gemini model for synthesis tasks",
    )
    max_tokens_per_section: int = Field(
        default=15000,
        ge=1000,
        le=100000,
        description="Token budget per synthesis prompt section",
    )
    temperature: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="LLM temperature for synthesis",
    )
    max_key_judgments: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Max key judgments per report",
    )
    max_alternative_hypotheses: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Max alternative hypotheses per judgment",
    )
    report_output_dir: str = Field(
        default="reports/",
        description="Directory for rendered reports",
    )
    database_output_dir: str = Field(
        default="exports/",
        description="Directory for database exports",
    )
    dashboard_host: str = Field(
        default="127.0.0.1",
        description="Dashboard bind address",
    )
    dashboard_port: int = Field(
        default=8080,
        ge=1,
        le=65535,
        description="Dashboard bind port",
    )
    auto_generate_on_complete: bool = Field(
        default=True,
        description="Auto-generate report on pipeline complete",
    )

    @classmethod
    def from_env(cls) -> "AnalysisConfig":
        """Load configuration from environment variables with ANALYSIS_ prefix.

        Attempts to load a .env file from the project root using python-dotenv
        if available. Falls back to field defaults when variables are not set.

        Returns:
            AnalysisConfig populated from environment variables.
        """
        try:
            from dotenv import load_dotenv

            project_root = Path(__file__).resolve().parent.parent.parent
            env_path = project_root / ".env"
            if env_path.exists():
                load_dotenv(env_path)
        except ImportError:
            pass

        kwargs: dict = {}

        model = os.getenv("ANALYSIS_SYNTHESIS_MODEL")
        if model:
            kwargs["synthesis_model"] = model

        temp = os.getenv("ANALYSIS_TEMPERATURE")
        if temp is not None:
            try:
                kwargs["temperature"] = float(temp)
            except ValueError:
                pass

        max_tokens = os.getenv("ANALYSIS_MAX_TOKENS_PER_SECTION")
        if max_tokens is not None:
            try:
                kwargs["max_tokens_per_section"] = int(max_tokens)
            except ValueError:
                pass

        max_judgments = os.getenv("ANALYSIS_MAX_KEY_JUDGMENTS")
        if max_judgments is not None:
            try:
                kwargs["max_key_judgments"] = int(max_judgments)
            except ValueError:
                pass

        max_alt = os.getenv("ANALYSIS_MAX_ALT_HYPOTHESES")
        if max_alt is not None:
            try:
                kwargs["max_alternative_hypotheses"] = int(max_alt)
            except ValueError:
                pass

        report_dir = os.getenv("ANALYSIS_REPORT_OUTPUT_DIR")
        if report_dir:
            kwargs["report_output_dir"] = report_dir

        db_dir = os.getenv("ANALYSIS_DATABASE_OUTPUT_DIR")
        if db_dir:
            kwargs["database_output_dir"] = db_dir

        host = os.getenv("ANALYSIS_DASHBOARD_HOST")
        if host:
            kwargs["dashboard_host"] = host

        port = os.getenv("ANALYSIS_DASHBOARD_PORT")
        if port is not None:
            try:
                kwargs["dashboard_port"] = int(port)
            except ValueError:
                pass

        auto_gen = os.getenv("ANALYSIS_AUTO_GENERATE")
        if auto_gen is not None:
            kwargs["auto_generate_on_complete"] = _parse_bool(
                auto_gen, default=True
            )

        return cls(**kwargs)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "synthesis_model": "gemini-1.5-pro",
                    "max_tokens_per_section": 15000,
                    "temperature": 0.3,
                    "max_key_judgments": 10,
                    "max_alternative_hypotheses": 5,
                    "report_output_dir": "reports/",
                    "database_output_dir": "exports/",
                    "dashboard_host": "127.0.0.1",
                    "dashboard_port": 8080,
                    "auto_generate_on_complete": True,
                }
            ]
        }
    }
