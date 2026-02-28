"""Azure Vision LLM provider implementation.

This module provides integration with Azure OpenAI Service for multimodal
(text + image) inference, supporting GPT-4o and GPT-4-Vision-Preview models.
"""

from __future__ import annotations

import base64
import os
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

from openai import AzureOpenAI
from PIL import Image

from src.libs.llm.base_vision_llm import BaseVisionLLM
from src.observability.logger import get_logger

if TYPE_CHECKING:
    from src.core.settings import Settings

logger = get_logger(__name__)


class AzureVisionLLM(BaseVisionLLM):
    """Azure OpenAI Vision LLM provider implementation.

    Supports Azure OpenAI Service with GPT-4o and GPT-4-Vision-Preview models
    for multimodal (text + image) understanding.

    Design Principles Applied:
    - Pluggable: Implements BaseVisionLLM interface for seamless swapping.
    - Config-Driven: Endpoint, API key, and deployment from settings.
    - Fail-Fast: Validates configuration and image inputs.
    - Observable: Logs API calls and image preprocessing steps.
    - Graceful Degradation: Auto-resizes large images to fit API limits.
    """

    # Default max image size (Azure Vision API limit: 2048px)
    DEFAULT_MAX_IMAGE_SIZE = 2048

    def __init__(self, settings: Settings, **kwargs: Any):
        """Initialize Azure Vision LLM provider.

        Args:
            settings: Application settings containing Vision LLM configuration.
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
        self.model = kwargs.get("model") or getattr(
            settings.vision_llm, "model", "gpt-4o"
        )

        # Azure uses api_version for API compatibility
        self.api_version = kwargs.get("api_version", "2024-02-15-preview")

        # Max image size for resizing (px)
        self.max_image_size = kwargs.get(
            "max_image_size", self.DEFAULT_MAX_IMAGE_SIZE
        )

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
                f"Initialized Azure Vision LLM: endpoint={self.azure_endpoint}, "
                f"model={self.model}, api_version={self.api_version}, "
                f"max_image_size={self.max_image_size}px"
            )
        except Exception as e:
            raise RuntimeError(
                f"Failed to initialize Azure OpenAI client: {e}"
            ) from e

    def chat_with_image(
        self,
        text: str,
        image: Union[str, bytes],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> str:
        """Send text and image to Azure Vision LLM and return the response.

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
            RuntimeError: If the Azure Vision API call fails.
            FileNotFoundError: If image path doesn't exist.

        Example:
            >>> response = azure_vision_llm.chat_with_image(
            ...     text="Describe this diagram in detail",
            ...     image="data/images/architecture.png"
            ... )
            >>> isinstance(response, str)
            True
        """
        # Validate inputs
        self.validate_text(text)
        self.validate_image(image)

        # Load and encode image
        try:
            image_base64 = self._prepare_image(image)
        except Exception as e:
            error_msg = f"Failed to prepare image: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

        # Extract optional parameters
        temperature = kwargs.get("temperature", 0.7)
        max_tokens = kwargs.get("max_tokens", 1024)

        try:
            # Build multimodal messages
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": text},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_base64}"
                            },
                        },
                    ],
                }
            ]

            logger.debug(
                f"Calling Azure Vision API: model={self.model}, "
                f"temperature={temperature}, max_tokens={max_tokens}"
            )

            # Call Azure OpenAI Vision API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            # Extract response text
            content = response.choices[0].message.content

            if content is None:
                raise RuntimeError("Azure Vision API returned empty response content")

            logger.debug(
                f"Azure Vision API response received: {len(content)} chars"
            )
            return content

        except Exception as e:
            # Check for common Azure-specific errors
            error_msg = f"Azure Vision API call failed: {e}"
            if "401" in str(e) or "Unauthorized" in str(e):
                error_msg = (
                    "Azure Vision API authentication failed. "
                    "Check your API key and endpoint configuration."
                )
            elif "400" in str(e) or "Bad Request" in str(e):
                error_msg = (
                    f"Azure Vision API bad request: {e}. "
                    "Check image format and prompt."
                )
            elif "429" in str(e) or "Rate limit" in str(e):
                error_msg = (
                    f"Azure Vision API rate limit exceeded: {e}. "
                    "Consider reducing request frequency."
                )

            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    def _prepare_image(self, image: Union[str, bytes]) -> str:
        """Prepare image for Azure Vision API by loading and encoding.

        Args:
            image: Image path (str) or raw bytes.

        Returns:
            Base64-encoded image string.

        Raises:
            FileNotFoundError: If image path doesn't exist.
            ValueError: If image format is unsupported.
            RuntimeError: If image processing fails.
        """
        # Load image
        if isinstance(image, str):
            # Load from file path
            image_path = Path(image)
            if not image_path.exists():
                raise FileNotFoundError(
                    f"Image file not found: {image_path.absolute()}"
                )

            logger.debug(f"Loading image from path: {image_path}")
            try:
                with Image.open(image_path) as img:
                    image_bytes = self._resize_if_needed(img)
            except Exception as e:
                raise RuntimeError(
                    f"Failed to load image from {image_path}: {e}"
                ) from e

        elif isinstance(image, bytes):
            # Load from bytes
            logger.debug(f"Loading image from bytes: {len(image)} bytes")
            try:
                with Image.open(BytesIO(image)) as img:
                    image_bytes = self._resize_if_needed(img)
            except Exception as e:
                raise RuntimeError(f"Failed to load image from bytes: {e}") from e

        else:
            raise ValueError(
                f"Image must be str (path) or bytes, got {type(image).__name__}"
            )

        # Encode to base64
        return base64.b64encode(image_bytes).decode("utf-8")

    def _resize_if_needed(self, img: Image.Image) -> bytes:
        """Resize image if it exceeds max_image_size, then convert to bytes.

        Args:
            img: PIL Image object.

        Returns:
            Image bytes in PNG format.

        Note:
            Azure Vision API has a 2048px limit on image dimensions.
            Images exceeding this limit are automatically resized.
        """
        width, height = img.size
        max_dim = max(width, height)

        if max_dim > self.max_image_size:
            # Calculate resize ratio
            ratio = self.max_image_size / max_dim
            new_width = int(width * ratio)
            new_height = int(height * ratio)

            logger.info(
                f"Resizing image from {width}x{height} to {new_width}x{new_height} "
                f"(max_dim: {self.max_image_size}px)"
            )

            # Resize with high-quality resampling
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # Convert to bytes
        buffer = BytesIO()
        # Convert RGBA to RGB if needed (PNG supports both)
        if img.mode == "RGBA":
            # Create white background for transparency
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])  # Use alpha channel as mask
            img = background

        img.save(buffer, format="PNG")
        return buffer.getvalue()

    def get_model_name(self) -> str:
        """Get the Azure Vision model name.

        Returns:
            The configured model identifier (e.g., 'gpt-4o').
        """
        return self.model

    def get_backend_name(self) -> str:
        """Get the backend provider name.

        Returns:
            The provider identifier string ('azure').
        """
        return "azure"
