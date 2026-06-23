from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel, ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..config import LLMConfig
from .models import CommitOutput, StandupOutput, PROutput, ExplainOutput, CatchupOutput  # noqa: F401
from .prompts import get_json_schema_prompt  # noqa: F401

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LLMError(Exception):
    """Raised when the LLM call fails after all retries."""


class LLMValidationError(LLMError):
    """Raised when the LLM response cannot be validated against the output model."""


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class BaseLLMClient(ABC):
    """Common interface for all LLM backend clients."""

    @abstractmethod
    def complete(self, system: str, user: str, output_model: type[T]) -> T:
        """Send a completion request and return a validated *output_model* instance."""
        ...


# ---------------------------------------------------------------------------
# Anthropic client
# ---------------------------------------------------------------------------

class AnthropicClient(BaseLLMClient):
    """Uses the Anthropic Python SDK with native structured output.

    Requires: anthropic>=0.28.0
    """

    def __init__(self, config: LLMConfig) -> None:
        try:
            import anthropic as _anthropic  # noqa: F401
        except ImportError as exc:
            raise LLMError(
                "anthropic package is not installed. Run: pip install anthropic>=0.28.0"
            ) from exc

        self._config = config
        import anthropic as _anthropic
        self._client = _anthropic.Anthropic(api_key=config.api_key)

    @retry(
        retry=retry_if_exception_type(LLMError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def complete(self, system: str, user: str, output_model: type[T]) -> T:
        """Call Anthropic and parse structured JSON response."""
        import anthropic as _anthropic

        # Embed schema so the model knows the exact shape expected
        schema_str = get_json_schema_prompt(output_model)
        augmented_system = (
            system
            + "\n\n---\nYou MUST respond with a single JSON object matching the schema below. "
            + "No prose, no markdown fences.\n"
            + schema_str
        )

        try:
            response = self._client.messages.create(
                model=self._config.model,
                max_tokens=4096,
                system=augmented_system,
                messages=[{"role": "user", "content": user}],
            )
            text = "".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            return _parse_json_response(text, output_model)

        except _anthropic.APIStatusError as exc:
            raise LLMError(
                f"Anthropic API error {exc.status_code}: {exc.message}"
            ) from exc
        except _anthropic.APIConnectionError as exc:
            raise LLMError(f"Anthropic connection error: {exc}") from exc
        except _anthropic.RateLimitError as exc:
            raise LLMError(f"Anthropic rate limit exceeded: {exc}") from exc
        except LLMValidationError:
            raise
        except Exception as exc:
            raise LLMError(f"Unexpected error calling Anthropic: {exc}") from exc


# ---------------------------------------------------------------------------
# OpenAI-compatible client (DeepSeek, OpenAI, Ollama)
# ---------------------------------------------------------------------------

class OpenAICompatibleClient(BaseLLMClient):
    """Works with DeepSeek, OpenAI, and Ollama via the openai SDK.

    Uses response_format={"type": "json_object"} and appends the JSON schema
    to the system prompt so the model knows what shape to produce.

    Requires: openai>=1.30.0
    """

    def __init__(self, config: LLMConfig) -> None:
        try:
            import openai as _openai  # noqa: F401
        except ImportError as exc:
            raise LLMError(
                "openai package is not installed. Run: pip install openai>=1.30.0"
            ) from exc

        self._config = config
        import openai as _openai
        kwargs: dict = {"api_key": config.api_key or "placeholder"}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        self._client = _openai.OpenAI(**kwargs)

    @retry(
        retry=retry_if_exception_type(LLMError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def complete(self, system: str, user: str, output_model: type[T]) -> T:
        """Call OpenAI-compatible endpoint with JSON mode."""
        import openai as _openai

        # Embed schema in the system prompt so the model knows the shape
        schema_str = get_json_schema_prompt(output_model)
        augmented_system = (
            system
            + "\n\n---\nYou MUST respond with a single JSON object that strictly matches "
            + "the following JSON Schema. Do NOT include any prose or markdown fences.\n"
            + schema_str
        )

        try:
            response = self._client.chat.completions.create(
                model=self._config.model,
                messages=[
                    {"role": "system", "content": augmented_system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                max_tokens=4096,
                temperature=0.3,
            )
            text = response.choices[0].message.content or ""
            return _parse_json_response(text, output_model)

        except _openai.APIStatusError as exc:
            raise LLMError(
                f"OpenAI-compatible API error {exc.status_code}: {exc.message}"
            ) from exc
        except _openai.APIConnectionError as exc:
            raise LLMError(f"API connection error: {exc}") from exc
        except _openai.RateLimitError as exc:
            raise LLMError(f"Rate limit exceeded: {exc}") from exc
        except LLMValidationError:
            raise
        except Exception as exc:
            raise LLMError(f"Unexpected error calling LLM: {exc}") from exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_json_response(text: str, output_model: type[T]) -> T:
    """Parse *text* as JSON and validate against *output_model*.

    Strips markdown fences if the model wrapped its response in them.
    Raises LLMValidationError with a helpful message on failure.
    """
    stripped = text.strip()
    # Strip markdown code fences if present
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        inner_lines = lines[1:]
        if inner_lines and inner_lines[-1].strip() == "```":
            inner_lines = inner_lines[:-1]
        stripped = "\n".join(inner_lines).strip()

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise LLMValidationError(
            f"LLM response is not valid JSON.\n"
            f"Parse error: {exc}\n"
            f"Raw response (first 500 chars):\n{text[:500]}"
        ) from exc

    try:
        return output_model.model_validate(data)
    except ValidationError as exc:
        errors = exc.errors()
        error_lines = [
            f"  - {str(e['loc'])}: {e['msg']}" for e in errors[:5]
        ]
        raise LLMValidationError(
            f"LLM response does not match expected schema for {output_model.__name__}.\n"
            f"Validation errors:\n" + "\n".join(error_lines) + "\n"
            f"Received JSON:\n{json.dumps(data, indent=2)[:800]}"
        ) from exc


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_llm_client(config: LLMConfig) -> BaseLLMClient:
    """Return the appropriate LLM client for *config*."""
    if config.uses_anthropic_sdk:
        return AnthropicClient(config)
    return OpenAICompatibleClient(config)
