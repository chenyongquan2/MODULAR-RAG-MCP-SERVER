"""Abstract base class for Vision LLM providers.

This module defines the pluggable interface for Vision LLM service providers,
which can process both text and image inputs (multimodal). This enables
seamless switching between different backends (Azure GPT-4o, OpenAI GPT-4-Vision,
etc.) through configuration-driven instantiation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional, Union


class BaseVisionLLM(ABC):
    """Abstract base class for Vision LLM providers.

    All Vision LLM implementations must inherit from this class and implement
    the chat_with_image() method. This ensures consistent interface across
    different providers for multimodal (text + image) inference.

    Design Principles Applied:
    - Pluggable: Subclasses can be swapped without changing upstream code.
    - Observable: Accepts optional TraceContext for observability integration.
    - Config-Driven: Instances are created via factory based on settings.
    - Extensible: Supports image preprocessing through subclass extension.
    """

    @abstractmethod
    def chat_with_image(
        self,
        text: str,
        image: Union[str, bytes],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> str:
        """Send text and image to the Vision LLM and return the response text.

        Args:
            text: The text prompt/question to send to the model.
            image: Image input, either as:
                - str: File path to image (e.g., 'data/images/doc_001.png')
                - bytes: Raw image bytes (for in-memory processing)
            trace: Optional TraceContext for observability (reserved for Stage F).
            **kwargs: Provider-specific parameters (temperature, max_tokens, etc.).

        Returns:
            The assistant's response text as a string.

        Raises:
            ValueError: If text is empty or image input is invalid.
            RuntimeError: If the Vision LLM provider call fails.
            FileNotFoundError: If image path doesn't exist.

        Example:
            >>> response = vision_llm.chat_with_image(
            ...     text="Describe this image in detail",
            ...     image="data/images/diagram.png"
            ... )
            >>> isinstance(response, str)
            True

        Note:
            Implementations should handle:
            - Image format validation (PNG, JPEG, etc.)
            - Image size limits (auto-resize if needed)
            - Base64 encoding for API calls
            - Graceful error handling with clear messages
        """
        pass

    def validate_text(self, text: str) -> None:
        """Validate input text prompt.

        Args:
            text: The text prompt to validate.

        Raises:
            ValueError: If text is empty or invalid.
        """
        if not text or not text.strip():
            raise ValueError("Text prompt cannot be empty")

    def validate_image(self, image: Union[str, bytes]) -> None:
        """Validate input image.

        Args:
            image: Image path or bytes to validate.

        Raises:
            ValueError: If image input is invalid.
            FileNotFoundError: If image path doesn't exist (for str input).

        Note:
            Subclasses can override this to add format/size validation.
        """
        if not image:
            raise ValueError("Image input cannot be empty")

        if isinstance(image, str):
            # Will be validated by subclass implementation
            # (e.g., check file existence, validate extension)
            pass
        elif isinstance(image, bytes):
            if len(image) == 0:
                raise ValueError("Image bytes cannot be empty")
        else:
            raise ValueError(
                f"Image must be str (path) or bytes, got {type(image).__name__}"
            )

    def get_model_name(self) -> str:
        """Get the model name used by this Vision provider.

        Returns:
            The model identifier string (e.g., 'gpt-4o', 'gpt-4-vision-preview').

        Raises:
            NotImplementedError: If the subclass doesn't override this method.

        Note:
            Subclasses should override this method to return their specific model.
            This is useful for logging and observability.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement get_model_name() method"
        )

    def get_backend_name(self) -> str:
        """Get the backend provider name.

        Returns:
            The provider identifier string (e.g., 'azure', 'openai').

        Raises:
            NotImplementedError: If the subclass doesn't override this method.

        Note:
            This method helps differentiate between providers in traces and logs.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement get_backend_name() method"
        )
