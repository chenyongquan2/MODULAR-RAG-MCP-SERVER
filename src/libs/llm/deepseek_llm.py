"""DeepSeek LLM provider implementation.

This module provides integration with DeepSeek API,
which is OpenAI-compatible and supports models like deepseek-chat, deepseek-coder.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional

from openai import OpenAI

from src.libs.llm.base_llm import BaseLLM
from src.observability.logger import get_logger

if TYPE_CHECKING:
    from src.core.settings import Settings

logger = get_logger(__name__)


class DeepSeekLLM(BaseLLM):
    """DeepSeek LLM provider implementation.

    Supports DeepSeek API (OpenAI-compatible) with models like deepseek-chat, deepseek-coder.
    Configuration is driven by settings.yaml.

    Design Principles Applied:
    - Pluggable: Implements BaseLLM interface for seamless swapping.
    - Config-Driven: API key and model from settings.
    - Fail-Fast: Validates configuration on initialization.
    - Observable: Logs API calls and errors.
    """

    # DeepSeek API endpoint
    DEEPSEEK_BASE_URL = "https://api.deepseek.com"

    def __init__(self, settings: Settings, **kwargs: Any):
        """Initialize DeepSeek LLM provider.

        Args:
            settings: Application settings containing LLM configuration.
            **kwargs: Optional overrides (model, api_key, base_url, etc.).

        Raises:
            ValueError: If required configuration is missing.
        """
        self.settings = settings

        # Extract configuration with fallback to kwargs
        self.api_key = kwargs.get("api_key") or getattr(
            settings.llm, "api_key", None
        )
        self.model = kwargs.get("model") or getattr(
            settings.llm, "model", "deepseek-chat"
        )
        self.base_url = kwargs.get("base_url", self.DEEPSEEK_BASE_URL)

        # Validate required configuration
        if not self.api_key:
            raise ValueError(
                "DeepSeek API key is required. "
                "Set 'llm.api_key' in settings.yaml or set DEEPSEEK_API_KEY env var."
            )

        # Initialize OpenAI client with DeepSeek base URL
        try:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )
            logger.info(
                f"Initialized DeepSeek LLM: base_url={self.base_url}, model={self.model}"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to initialize DeepSeek client: {e}") from e

    def chat(
        self,
        messages: List[dict[str, str]],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> str:
        """Send messages to DeepSeek and return the response.

        Args:
            messages: List of message dicts following OpenAI format.
            trace: Optional TraceContext for observability (reserved).
            **kwargs: Optional parameters (temperature, max_tokens, etc.).

        Returns:
            The assistant's response text.

        Raises:
            ValueError: If messages are invalid.
            RuntimeError: If DeepSeek API call fails.
        """
        # Validate input
        self.validate_messages(messages)

        # Extract optional parameters
        temperature = kwargs.get("temperature", 0.7)
        max_tokens = kwargs.get("max_tokens")

        try:
            # Call DeepSeek Chat Completion API (OpenAI-compatible)
            logger.debug(
                f"Calling DeepSeek API: model={self.model}, "
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
                raise RuntimeError("DeepSeek returned empty response content")

            logger.debug(f"DeepSeek response received: {len(content)} chars")
            return content

        except Exception as e:
            error_msg = f"DeepSeek API call failed: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    def get_model_name(self) -> str:
        """Get the DeepSeek model name.

        Returns:
            The configured model identifier (e.g., 'deepseek-chat').
        """
        return self.model
