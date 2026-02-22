"""Abstract base class for LLM providers.

This module defines the pluggable interface for LLM service providers,
enabling seamless switching between different backends (Azure OpenAI, OpenAI,
Ollama, DeepSeek, etc.) through configuration-driven instantiation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List, Optional


class BaseLLM(ABC):
    """Abstract base class for LLM providers.

    All LLM implementations must inherit from this class and implement
    the chat() method. This ensures consistent interface across different
    providers (Azure OpenAI, OpenAI, Ollama, DeepSeek, etc.).

    Design Principles Applied:
    - Pluggable: Subclasses can be swapped without changing upstream code.
    - Observable: Accepts optional TraceContext for observability integration.
    - Config-Driven: Instances are created via factory based on settings.
    """

    @abstractmethod
    def chat(
        self,
        messages: List[dict[str, str]],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> str:
        """Send messages to the LLM and return the response text.

        Args:
            messages: List of message dicts with 'role' and 'content' keys.
                Follows the OpenAI chat completion format, e.g.:
                [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
            trace: Optional TraceContext for observability (reserved for Stage F).
            **kwargs: Provider-specific parameters (temperature, max_tokens, etc.).

        Returns:
            The assistant's response text as a string.

        Raises:
            ValueError: If messages list is empty or contains invalid entries.
            RuntimeError: If the LLM provider call fails.

        Example:
            >>> response = llm.chat([{"role": "user", "content": "Hello"}])
            >>> isinstance(response, str)
            True
        """
        pass

    def validate_messages(self, messages: List[dict[str, str]]) -> None:
        """Validate input message list.

        Args:
            messages: List of message dicts to validate.

        Raises:
            ValueError: If messages list is empty or contains invalid entries.
        """
        if not messages:
            raise ValueError("Messages list cannot be empty")

        for i, msg in enumerate(messages):
            if not isinstance(msg, dict):
                raise ValueError(
                    f"Message at index {i} is not a dict "
                    f"(type: {type(msg).__name__})"
                )
            if "role" not in msg:
                raise ValueError(
                    f"Message at index {i} is missing required key 'role'"
                )
            if "content" not in msg:
                raise ValueError(
                    f"Message at index {i} is missing required key 'content'"
                )

    def get_model_name(self) -> str:
        """Get the model name used by this provider.

        Returns:
            The model identifier string.

        Raises:
            NotImplementedError: If the subclass doesn't override this method.

        Note:
            Subclasses should override this method to return their specific model.
            This is useful for logging and observability.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement get_model_name() method"
        )
