"""Azure OpenAI LLM provider implementation.

This module provides integration with Azure OpenAI Service,
supporting GPT-4, GPT-4o, and other models hosted on Azure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional

from openai import AzureOpenAI

from src.libs.llm.base_llm import BaseLLM
from src.observability.logger import get_logger

if TYPE_CHECKING:
    from src.core.settings import Settings

logger = get_logger(__name__)


class AzureLLM(BaseLLM):
    """Azure OpenAI LLM provider implementation.

    Supports Azure OpenAI Service with deployment-based model access.
    Configuration is driven by settings.yaml.

    Design Principles Applied:
    - Pluggable: Implements BaseLLM interface for seamless swapping.
    - Config-Driven: Endpoint, API key, and deployment from settings.
    - Fail-Fast: Validates configuration on initialization.
    - Observable: Logs API calls and errors.
    """

    def __init__(self, settings: Settings, **kwargs: Any):
        """Initialize Azure OpenAI LLM provider.

        Args:
            settings: Application settings containing LLM configuration.
            **kwargs: Optional overrides (model, api_key, azure_endpoint, etc.).

        Raises:
            ValueError: If required configuration is missing.
        """
        self.settings = settings

        # Extract configuration with fallback to kwargs
        self.api_key = kwargs.get("api_key") or getattr(
            settings.llm, "api_key", None
        )
        self.azure_endpoint = kwargs.get("azure_endpoint") or getattr(
            settings.llm, "azure_endpoint", None
        )
        self.model = kwargs.get("model") or getattr(settings.llm, "model", "gpt-4o")
        
        # Azure uses api_version for API compatibility
        self.api_version = kwargs.get("api_version", "2024-02-15-preview")

        # Validate required configuration
        if not self.api_key:
            raise ValueError(
                "Azure OpenAI API key is required. "
                "Set 'llm.api_key' in settings.yaml or set AZURE_OPENAI_API_KEY env var."
            )

        if not self.azure_endpoint:
            raise ValueError(
                "Azure OpenAI endpoint is required. "
                "Set 'llm.azure_endpoint' in settings.yaml (e.g., https://your-resource.openai.azure.com/)."
            )

        # Initialize Azure OpenAI client
        try:
            self.client = AzureOpenAI(
                api_key=self.api_key,
                azure_endpoint=self.azure_endpoint,
                api_version=self.api_version,
            )
            logger.info(
                f"Initialized Azure OpenAI LLM: endpoint={self.azure_endpoint}, "
                f"model={self.model}, api_version={self.api_version}"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Azure OpenAI client: {e}") from e

    def chat(
        self,
        messages: List[dict[str, str]],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> str:
        """Send messages to Azure OpenAI and return the response.

        Args:
            messages: List of message dicts following OpenAI format.
            trace: Optional TraceContext for observability (reserved).
            **kwargs: Optional parameters (temperature, max_tokens, etc.).

        Returns:
            The assistant's response text.

        Raises:
            ValueError: If messages are invalid.
            RuntimeError: If Azure OpenAI API call fails.
        """
        # Validate input
        self.validate_messages(messages)

        # Extract optional parameters
        temperature = kwargs.get("temperature", 0.7)
        max_tokens = kwargs.get("max_tokens")

        try:
            # Call Azure OpenAI Chat Completion API
            logger.debug(
                f"Calling Azure OpenAI API: model={self.model}, "
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
                raise RuntimeError("Azure OpenAI returned empty response content")

            logger.debug(f"Azure OpenAI response received: {len(content)} chars")
            return content

        except Exception as e:
            error_msg = f"Azure OpenAI API call failed: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    def get_model_name(self) -> str:
        """Get the Azure OpenAI deployment/model name.

        Returns:
            The configured model identifier (e.g., 'gpt-4o').
        """
        return self.model
