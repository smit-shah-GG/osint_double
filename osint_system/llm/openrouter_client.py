"""OpenRouter API client with google.genai-compatible interface.

Drop-in replacement for google.genai.Client when OPENROUTER_API_KEY is set.
Uses the OpenAI SDK pointed at OpenRouter's base URL, but exposes the same
`client.aio.models.generate_content()` and `client.models.generate_content()`
interface that the rest of the codebase expects.

Supports model fallback chains: if the primary model returns a 429 or 5xx,
automatically retries with the next model in the fallback chain.

Usage:
    from osint_system.llm.openrouter_client import OpenRouterClient

    client = OpenRouterClient(api_key="sk-or-...")
    response = await client.aio.models.generate_content(
        model="gemini-3-pro-preview",
        contents=["Analyze this..."],
        config={"temperature": 0.2},
    )
    print(response.text)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import openai
import structlog

logger = structlog.get_logger().bind(component="OpenRouterClient")

# Map short model names to OpenRouter model IDs
MODEL_MAP: dict[str, str] = {
    # Pro tier (synthesis)
    "gemini-3-pro-preview": "google/gemini-2.5-pro-preview-06-05",
    "gemini-3-pro": "google/gemini-2.5-pro-preview-06-05",
    "gemini-2.5-pro": "google/gemini-2.5-pro-preview-06-05",
    # Flash tier (extraction)
    "qwen-3.5-flash": "qwen/qwen3.5-flash-02-23",
    "gemini-3-flash": "google/gemini-3-flash-preview",
    "gemini-3-flash-preview": "google/gemini-3-flash-preview",
    "gemini-3.1-flash-lite-preview": "google/gemini-3.1-flash-lite-preview",
    "gemini-2.5-flash": "google/gemini-2.5-flash",
    "gemini-2.0-flash": "google/gemini-2.0-flash-001",
    # Reasoning tier (synthesis fallback)
    "deepseek-r1": "deepseek/deepseek-r1-0528",
    "deepseek-r1-0528": "deepseek/deepseek-r1-0528",
    "deepseek-v3.2": "deepseek/deepseek-v3.2",
    # Free tier (fallback)
    "nemotron-super-120b": "nvidia/nemotron-3-super-120b-a12b:free",
    "hermes-405b": "nousresearch/hermes-3-llama-3.1-405b:free",
}

# Fallback chains: if primary model fails (429/5xx), try next in chain
FALLBACK_CHAINS: dict[str, list[str]] = {
    # Extraction: Flash Lite → Nemotron 120B (free) → Hermes 405B (free)
    "google/gemini-3.1-flash-lite-preview": [
        "nvidia/nemotron-3-super-120b-a12b:free",
        "nousresearch/hermes-3-llama-3.1-405b:free",
    ],
    "qwen/qwen3.5-flash-02-23": [
        "nvidia/nemotron-3-super-120b-a12b:free",
        "nousresearch/hermes-3-llama-3.1-405b:free",
    ],
    # Synthesis: Gemini 2.5 Pro → DeepSeek V3.2 → Hermes 405B (free)
    "google/gemini-2.5-pro-preview": [
        "deepseek/deepseek-v3.2",
        "nousresearch/hermes-3-llama-3.1-405b:free",
    ],
    "google/gemini-2.5-pro-preview-06-05": [
        "deepseek/deepseek-v3.2",
        "nousresearch/hermes-3-llama-3.1-405b:free",
    ],
    "deepseek/deepseek-r1-0528": [
        "deepseek/deepseek-v3.2",
        "nousresearch/hermes-3-llama-3.1-405b:free",
    ],
}

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Status codes that trigger fallback
_RETRIABLE_STATUSES = {429, 500, 502, 503, 529}

# Warn-once for fallback transitions: set of (primary, fallback) tuples.
# Logs each unique model transition only once per investigation run to
# eliminate fallback chain log spam.
_warned_transitions: set[tuple[str, str]] = set()


def reset_fallback_warnings() -> None:
    """Reset warn-once state. Call at start of each investigation run."""
    _warned_transitions.clear()


@dataclass
class _Response:
    """Minimal response object matching google.genai response.text interface."""
    text: str


class _SyncModels:
    """Synchronous models interface matching google.genai.Client.models."""

    def __init__(self, sync_client: openai.OpenAI) -> None:
        self._client = sync_client

    def generate_content(
        self,
        *,
        model: str,
        contents: list[str] | str,
        config: dict[str, Any] | None = None,
    ) -> _Response:
        config = config or {}
        or_model = MODEL_MAP.get(model, model)
        models_to_try = [or_model] + FALLBACK_CHAINS.get(or_model, [])

        messages = self._build_messages(contents, config)
        kwargs = self._build_kwargs(config)

        last_error: Exception | None = None
        for attempt_model in models_to_try:
            try:
                completion = self._client.chat.completions.create(
                    model=attempt_model,
                    messages=messages,
                    **kwargs,
                )
                if not completion.choices or not completion.choices[0].message:
                    text = ""
                else:
                    text = completion.choices[0].message.content or ""
                if attempt_model != or_model:
                    logger.info("fallback_used", primary=or_model, used=attempt_model)
                return _Response(text=text)
            except openai.APIStatusError as e:
                if e.status_code in _RETRIABLE_STATUSES and attempt_model != models_to_try[-1]:
                    next_model = models_to_try[models_to_try.index(attempt_model) + 1]
                    transition = (attempt_model, next_model)
                    if transition not in _warned_transitions:
                        _warned_transitions.add(transition)
                        logger.warning(
                            "model_fallback",
                            model=attempt_model,
                            status=e.status_code,
                            next=next_model,
                        )
                    last_error = e
                    continue
                raise
            except Exception:
                raise

        raise last_error  # type: ignore[misc]

    @staticmethod
    def _build_messages(
        contents: list[str] | str,
        config: dict[str, Any],
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        system = config.get("system_instruction")
        if system:
            messages.append({"role": "system", "content": system})
        if isinstance(contents, str):
            messages.append({"role": "user", "content": contents})
        elif isinstance(contents, list):
            messages.append({"role": "user", "content": "\n".join(contents)})
        return messages

    @staticmethod
    def _build_kwargs(config: dict[str, Any]) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if "temperature" in config:
            kwargs["temperature"] = config["temperature"]
        if "max_output_tokens" in config:
            kwargs["max_tokens"] = config["max_output_tokens"]
        # Force valid JSON output when system prompt requests structured data
        if config.get("response_format") == "json":
            kwargs["response_format"] = {"type": "json_object"}
        return kwargs


class _AsyncModels:
    """Async models interface matching google.genai.Client.aio.models."""

    def __init__(self, async_client: openai.AsyncOpenAI) -> None:
        self._client = async_client

    async def generate_content(
        self,
        *,
        model: str,
        contents: list[str] | str,
        config: dict[str, Any] | None = None,
    ) -> _Response:
        config = config or {}
        or_model = MODEL_MAP.get(model, model)
        models_to_try = [or_model] + FALLBACK_CHAINS.get(or_model, [])

        messages = _SyncModels._build_messages(contents, config)
        kwargs = _SyncModels._build_kwargs(config)

        last_error: Exception | None = None
        for attempt_model in models_to_try:
            try:
                completion = await self._client.chat.completions.create(
                    model=attempt_model,
                    messages=messages,
                    **kwargs,
                )
                if not completion.choices or not completion.choices[0].message:
                    text = ""
                else:
                    text = completion.choices[0].message.content or ""
                if attempt_model != or_model:
                    logger.info("fallback_used", primary=or_model, used=attempt_model)
                return _Response(text=text)
            except openai.APIStatusError as e:
                if e.status_code in _RETRIABLE_STATUSES and attempt_model != models_to_try[-1]:
                    next_model = models_to_try[models_to_try.index(attempt_model) + 1]
                    transition = (attempt_model, next_model)
                    if transition not in _warned_transitions:
                        _warned_transitions.add(transition)
                        logger.warning(
                            "model_fallback",
                            model=attempt_model,
                            status=e.status_code,
                            next=next_model,
                        )
                    last_error = e
                    continue
                raise
            except Exception:
                raise

        raise last_error  # type: ignore[misc]


class _AsyncNamespace:
    """Namespace matching google.genai.Client.aio."""

    def __init__(self, async_client: openai.AsyncOpenAI) -> None:
        self.models = _AsyncModels(async_client)


class OpenRouterClient:
    """OpenRouter client with google.genai-compatible interface.

    Exposes:
        client.models.generate_content(...)      # sync
        client.aio.models.generate_content(...)   # async

    Fallback chains:
        Extraction: Qwen 3.5 Flash → Hermes 405B (free)
        Synthesis:  Gemini Pro → DeepSeek R1 → Hermes 405B (free)
    """

    def __init__(self, api_key: str) -> None:
        self._sync = openai.OpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=api_key,
        )
        self._async = openai.AsyncOpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=api_key,
        )
        self.models = _SyncModels(self._sync)
        self.aio = _AsyncNamespace(self._async)

        logger.info("openrouter_client_initialized")
