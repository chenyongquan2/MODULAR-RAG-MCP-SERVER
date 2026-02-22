"""Ollama local LLM provider implementation.

This module provides integration with Ollama's local HTTP endpoint,
supporting local models like llama2, mistral, codellama, etc.
Ollama uses an OpenAI-compatible API.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional

from openai import OpenAI

from src.libs.llm.base_llm import BaseLLM
from src.observability.logger import get_logger

if TYPE_CHECKING:
    from src.core.settings import Settings

logger = get_logger(__name__)


class OllamaLLM(BaseLLM):
    """Ollama local LLM provider implementation.

    Supports Ollama's local HTTP API with OpenAI-compatible interface.
    Default endpoint: http://localhost:11434/v1

    Design Principles Applied:
    - Pluggable: Implements BaseLLM interface for seamless swapping.
    - Config-Driven: Base URL and model from settings.
    - Fail-Fast: Validates configuration on initialization.
    - Observable: Logs API calls and errors with clear messages.
    - Privacy: Does not log sensitive connection details.
    """

    def __init__(self, settings: Settings, **kwargs: Any):
        """Initialize Ollama LLM provider.

        Args:
            settings: Application settings containing LLM configuration.
            **kwargs: Optional overrides (model, base_url, etc.).

        Raises:
            ValueError: If required configuration is missing.
        """
        self.settings = settings

        # Extract configuration with fallback to kwargs
        self.base_url = kwargs.get("base_url") or getattr(
            settings.llm, "base_url", "http://localhost:11434/v1"
        )
        self.model = kwargs.get("model") or getattr(
            settings.llm, "model", "llama2"
        )

        # Ollama doesn't require API key, but OpenAI client needs one
        # Use a placeholder to satisfy the client initialization
        api_key = kwargs.get("api_key") or "ollama"

        # Initialize OpenAI client with custom base_url for Ollama
        try:
            self.client = OpenAI(
                base_url=self.base_url,
                api_key=api_key,
            )
            logger.info(
                f"Initialized Ollama LLM with model: {self.model}, "
                f"endpoint: {self._sanitize_url(self.base_url)}"
            )
        except Exception as e:
            raise RuntimeError(
                f"Failed to initialize Ollama client. "
                f"Ensure Ollama is running at {self._sanitize_url(self.base_url)}. "
                f"Error: {e}"
            ) from e

    def _sanitize_url(self, url: str) -> str:
        """Sanitize URL for logging (remove credentials if any).

        Args:
            url: The URL to sanitize.

        Returns:
            Sanitized URL string.
        """
        # Basic sanitization - remove userinfo if present
        if "@" in url:
            parts = url.split("@")
            return f"***@{parts[-1]}"
        return url

    def chat(
        self,
        messages: List[dict[str, str]],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> str:
        """Send messages to Ollama and return the response.

        Args:
            messages: List of message dicts following OpenAI format.
            trace: Optional TraceContext for observability (reserved).
            **kwargs: Optional parameters (temperature, max_tokens, etc.).

        Returns:
            The assistant's response text.

        Raises:
            ValueError: If messages are invalid.
            RuntimeError: If Ollama API call fails (connection error, timeout, etc.).
        """
        # Validate input
        self.validate_messages(messages)

        # Extract optional parameters
        temperature = kwargs.get("temperature", 0.7)
        max_tokens = kwargs.get("max_tokens")

        try:
            # Call Ollama Chat Completion API (OpenAI-compatible)
            logger.debug(
                f"Calling Ollama API: model={self.model}, "
                f"messages_count={len(messages)}, temperature={temperature}"
            )

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            # Extract response text
            content = response.choices[0].message.content

            if content is None:
                raise RuntimeError("Ollama returned empty response content")

            logger.debug(f"Ollama response received: {len(content)} chars")
            return content

        except Exception as e:
            error_msg = (
                f"Ollama API call failed for model '{self.model}'. "
                f"Ensure Ollama is running and the model is available. "
                f"Error: {e}"
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    def get_model_name(self) -> str:
        """Get the Ollama model name.

        Returns:
            The configured model identifier (e.g., 'llama2', 'mistral').
        """
        return self.model
