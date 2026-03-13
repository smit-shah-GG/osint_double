"""Gemini API client with exponential backoff and rate limiting."""

import time
import random
import functools
from typing import Callable, Any

from google import genai
from loguru import logger

from osint_system.config.settings import settings


def _exponential_backoff(func: Callable) -> Callable:
    """
    Decorator implementing exponential backoff with jitter for API calls.

    Retries failed requests up to 5 times with exponentially increasing delays.
    Base delay: 1.0s, exponential factor: 2, jitter: 0-10% of delay.

    Args:
        func: Function to wrap with retry logic

    Returns:
        Wrapped function with exponential backoff
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        max_retries = 5
        base_delay = 1.0

        for retry in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if retry == max_retries - 1:
                    logger.error(f"Max retries exceeded for {func.__name__}: {e}")
                    raise

                # Calculate delay with exponential backoff
                delay = base_delay * (2 ** retry)
                # Add jitter (0-10% of delay)
                jitter = random.uniform(0, delay * 0.1)
                total_delay = delay + jitter

                logger.warning(
                    f"Retry {retry + 1}/{max_retries} for {func.__name__} "
                    f"after {total_delay:.2f}s: {e}"
                )
                time.sleep(total_delay)

        # Should never reach here due to the raise in the loop
        raise RuntimeError(f"Unexpected retry loop exit in {func.__name__}")

    return wrapper


class GeminiClient:
    """
    Google Gemini API client with rate limiting and error handling.

    Provides a robust interface to Gemini models with exponential backoff
    for transient failures, token counting for cost monitoring, and
    proper error handling for blocked prompts.

    Attributes:
        client: google.genai.Client instance
        model_name: Model identifier string for API calls
    """

    def __init__(self):
        """
        Initialize Gemini client with API key from settings.

        Raises:
            ValueError: If API key is not configured
        """
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY not configured in environment")

        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.model_name = settings.gemini_model

        logger.info(
            f"Gemini client initialized with model {self.model_name}"
        )

    @_exponential_backoff
    def generate_content(self, prompt: str, temperature: float = 0.7) -> str:
        """
        Generate content from Gemini API with exponential backoff.

        Args:
            prompt: Input prompt for content generation
            temperature: Sampling temperature (0.0-1.0). Lower = more deterministic

        Returns:
            Generated text content

        Raises:
            Exception: For API errors after retries exhausted (including safety blocks)
        """
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=[prompt],
            config={"temperature": temperature},
        )
        return response.text

    def count_tokens(self, text: str) -> int:
        """
        Count tokens in text for cost estimation.

        Args:
            text: Text to count tokens in

        Returns:
            Total token count
        """
        result = self.client.models.count_tokens(
            model=self.model_name,
            contents=[text],
        )
        return result.total_tokens


# Singleton instance - import this throughout the application
client = GeminiClient()
