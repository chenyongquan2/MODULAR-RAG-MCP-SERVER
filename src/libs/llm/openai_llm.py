"""OpenAI LLM provider implementation.

This module provides integration with OpenAI's Chat Completion API,
supporting models like GPT-4, GPT-4o, GPT-3.5-turbo, etc.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional

from openai import OpenAI

from src.libs.llm.base_llm import BaseLLM
from src.observability.logger import get_logger

if TYPE_CHECKING:
    from src.core.settings import Settings

logger = get_logger(__name__)


class OpenAILLM(BaseLLM):
    """OpenAI LLM provider implementation.

    Supports OpenAI Chat Completion API with standard models (GPT-4, GPT-3.5-turbo, etc.).
    Configuration is driven by settings.yaml.

    Design Principles Applied:
    - Pluggable: Implements BaseLLM interface for seamless swapping.
    - Config-Driven: API key and model from settings.
    - Fail-Fast: Validates configuration on initialization.
    - Observable: Logs API calls and errors.
    """

    def __init__(self, settings: Settings, **kwargs: Any):
        """Initialize OpenAI LLM provider.

        Args:
            settings: Application settings containing LLM configuration.
            **kwargs: Optional overrides (model, api_key, etc.).

        Raises:
            ValueError: If required configuration is missing.
        """
        self.settings = settings

        # Extract configuration with fallback to kwargs
        self.api_key = kwargs.get("api_key") or getattr(
            settings.llm, "api_key", None
        )
        self.model = kwargs.get("model") or getattr(settings.llm, "model", "gpt-4o")

        # Validate required configuration
        if not self.api_key:
            raise ValueError(
                "OpenAI API key is required. "
                "Set 'llm.api_key' in settings.yaml or set OPENAI_API_KEY env var."
            )

        # Initialize OpenAI client
        try:
            self.client = OpenAI(api_key=self.api_key)
            logger.info(f"Initialized OpenAI LLM with model: {self.model}")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize OpenAI client: {e}") from e

    def chat(
        self,
        messages: List[dict[str, str]],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> str:
        """Send messages to OpenAI and return the response.

        Args:
            messages: List of message dicts following OpenAI format.
            trace: Optional TraceContext for observability (reserved).
            **kwargs: Optional parameters (temperature, max_tokens, etc.).

        Returns:
            The assistant's response text.

        Raises:
            ValueError: If messages are invalid.
            RuntimeError: If OpenAI API call fails.
        """
        # Validate input
        self.validate_messages(messages)

        # Extract optional parameters
        temperature = kwargs.get("temperature", 0.7)
        max_tokens = kwargs.get("max_tokens")

        try:
            # Call OpenAI Chat Completion API
            logger.debug(
                f"Calling OpenAI API: model={self.model}, "
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
                raise RuntimeError("OpenAI returned empty response content")

            logger.debug(f"OpenAI response received: {len(content)} chars")
            return content

        except Exception as e:
            error_msg = f"OpenAI API call failed: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    def get_model_name(self) -> str:
        """Get the OpenAI model name.

        Returns:
            The configured model identifier (e.g., 'gpt-4o').
        """
        return self.model
