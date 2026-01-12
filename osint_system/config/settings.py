"""Application settings using Pydantic BaseSettings for environment variable management."""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """
    Global application settings loaded from environment variables.

    Attributes:
        gemini_api_key: Google Gemini API key (required)
        gemini_model: Default Gemini model to use
        max_rpm: Maximum requests per minute (free tier default)
        max_tpm: Maximum tokens per minute
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_format: Log output format (json for production, console for dev)
        interactive_mode: Enable interactive CLI features
        news_api_key: NewsAPI.org API key (optional)
        reddit_client_id: Reddit application client ID
        reddit_client_secret: Reddit application client secret
        reddit_user_agent: Reddit user agent string
    """

    gemini_api_key: str = Field(..., description="Google Gemini API key")
    gemini_model: str = Field(
        default="gemini-3-pro-preview",
        description="Default Gemini model identifier"
    )
    max_rpm: int = Field(
        default=15,
        description="Maximum requests per minute (free tier limit)"
    )
    max_tpm: int = Field(
        default=1_000_000,
        description="Maximum tokens per minute"
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level"
    )
    log_format: str = Field(
        default="json",
        description="Log output format: json or console"
    )
    interactive_mode: bool = Field(
        default=True,
        description="Enable interactive CLI features"
    )
    news_api_key: str | None = Field(
        default=None,
        description="NewsAPI.org API key for news fetching"
    )
    reddit_client_id: str = Field(
        default="",
        description="Reddit application client ID"
    )
    reddit_client_secret: str = Field(
        default="",
        description="Reddit application client secret"
    )
    reddit_user_agent: str = Field(
        default="osint_system:v0.1.0",
        description="Reddit user agent (format: app:version (by /u/username))"
    )

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


# Singleton instance - import this throughout the application
settings = Settings()
