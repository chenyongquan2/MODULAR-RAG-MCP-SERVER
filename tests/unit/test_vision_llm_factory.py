"""Unit tests for Vision LLM Factory.

Tests the factory pattern for Vision LLM provider creation, including:
- Provider registration mechanism
- Factory routing based on configuration
- Error handling for unknown/invalid providers
- Fake Vision LLM implementation for testing isolation
"""

from __future__ import annotations

from typing import Any, Optional, Union
from unittest.mock import MagicMock, PropertyMock

import pytest

from src.core.settings import (
    EmbeddingSettings,
    LLMSettings,
    Settings,
    VectorStoreSettings,
    VisionLLMSettings,
)
from src.libs.llm.base_vision_llm import BaseVisionLLM
from src.libs.llm.llm_factory import LLMFactory


# --- Helper function to create minimal Settings ---


def create_test_settings(llm_provider: str = "fake_vision") -> Settings:
    """Create minimal Settings for testing.

    Args:
        llm_provider: LLM provider name.

    Returns:
        Settings instance with minimal required fields.
    """
    return Settings(
        llm=LLMSettings(provider=llm_provider, model="fake-model", api_key="fake"),
        embedding=EmbeddingSettings(provider="fake", model="fake"),
        vision_llm=VisionLLMSettings(provider=llm_provider, model="fake"),
        vector_store=VectorStoreSettings(backend="fake"),
    )


class FakeVisionLLM(BaseVisionLLM):
    """Fake Vision LLM implementation for testing.

    Returns deterministic responses based on input patterns,
    enabling isolated unit tests without real API calls.
    """

    def __init__(self, settings: Settings, **kwargs: Any):
        """Initialize Fake Vision LLM.

        Args:
            settings: Application settings (stored for inspection).
            **kwargs: Additional parameters (stored for inspection).
        """
        self.settings = settings
        self.override_kwargs = kwargs

    def chat_with_image(
        self,
        text: str,
        image: Union[str, bytes],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> str:
        """Return fake response based on input patterns.

        Args:
            text: The text prompt.
            image: Image path or bytes.
            trace: Optional trace context.
            **kwargs: Additional parameters.

        Returns:
            Deterministic fake response for testing.
        """
        self.validate_text(text)
        self.validate_image(image)

        # Deterministic response patterns for test assertions
        if "error" in text.lower():
            raise RuntimeError("Simulated Vision LLM error")

        if isinstance(image, str):
            return f"Fake Vision LLM analyzed image at path: {image}"
        else:
            return f"Fake Vision LLM analyzed {len(image)} bytes of image data"

    def get_model_name(self) -> str:
        """Return fake model name."""
        return "fake-vision-model"

    def get_backend_name(self) -> str:
        """Return fake backend name."""
        return "fake"


# --- Test Cases ---


def test_register_vision_provider():
    """Test registering a custom Vision LLM provider."""
    # Register fake provider
    LLMFactory.register_vision_provider("fake_vision", FakeVisionLLM)

    # Verify it's in the registry
    providers = LLMFactory.list_vision_providers()
    assert "fake_vision" in providers


def test_register_vision_provider_invalid_class():
    """Test registering a non-BaseVisionLLM class raises error."""

    class InvalidClass:
        pass

    with pytest.raises(ValueError, match="must inherit from BaseVisionLLM"):
        LLMFactory.register_vision_provider("invalid", InvalidClass)  # type: ignore


def test_create_vision_llm_from_settings():
    """Test creating Vision LLM instance from settings."""
    # Register fake provider first
    LLMFactory.register_vision_provider("fake_vision", FakeVisionLLM)

    settings = create_test_settings("fake_vision")
    vision_llm = LLMFactory.create_vision_llm(settings)

    # Verify correct type
    assert isinstance(vision_llm, FakeVisionLLM)
    assert vision_llm.get_model_name() == "fake-vision-model"
    assert vision_llm.get_backend_name() == "fake"


def test_create_vision_llm_with_override_kwargs():
    """Test creating Vision LLM with override parameters."""
    LLMFactory.register_vision_provider("fake_vision", FakeVisionLLM)

    settings = create_test_settings("fake_vision")
    vision_llm = LLMFactory.create_vision_llm(settings, custom_param="test_value")

    # Verify override kwargs were passed
    assert isinstance(vision_llm, FakeVisionLLM)
    assert vision_llm.override_kwargs.get("custom_param") == "test_value"


def test_create_vision_llm_unsupported_provider():
    """Test creating Vision LLM with unknown provider raises error."""
    settings = create_test_settings("unknown_vision_provider")

    with pytest.raises(ValueError, match="Unsupported Vision LLM provider"):
        LLMFactory.create_vision_llm(settings)


def test_create_vision_llm_missing_provider_config():
    """Test creating Vision LLM without provider config raises error."""
    # Create Settings without llm field (bypass validation for test)
    mock_settings = MagicMock(spec=Settings)
    # Simulate missing llm.provider by raising AttributeError
    type(mock_settings).llm = PropertyMock(side_effect=AttributeError("no llm"))

    # Missing provider field
    with pytest.raises(
        ValueError, match="Missing required configuration.*llm.provider"
    ):
        LLMFactory.create_vision_llm(mock_settings)


def test_list_vision_providers():
    """Test listing all registered Vision LLM providers."""
    # Register multiple fake providers
    LLMFactory.register_vision_provider("provider_a", FakeVisionLLM)
    LLMFactory.register_vision_provider("provider_b", FakeVisionLLM)

    providers = LLMFactory.list_vision_providers()

    # Verify list is sorted and contains our providers
    assert isinstance(providers, list)
    assert "provider_a" in providers
    assert "provider_b" in providers
    assert providers == sorted(providers)  # Verify sorted


def test_vision_llm_chat_with_image_path():
    """Test Vision LLM with image file path."""
    LLMFactory.register_vision_provider("fake_vision", FakeVisionLLM)

    settings = create_test_settings("fake_vision")
    vision_llm = LLMFactory.create_vision_llm(settings)

    # Test with file path
    response = vision_llm.chat_with_image(
        text="Describe this image", image="test/path/image.png"
    )

    assert "test/path/image.png" in response
    assert "Fake Vision LLM analyzed" in response


def test_vision_llm_chat_with_image_bytes():
    """Test Vision LLM with image bytes."""
    LLMFactory.register_vision_provider("fake_vision", FakeVisionLLM)

    settings = create_test_settings("fake_vision")
    vision_llm = LLMFactory.create_vision_llm(settings)

    # Test with bytes
    fake_image_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    response = vision_llm.chat_with_image(text="Analyze this", image=fake_image_bytes)

    assert str(len(fake_image_bytes)) in response
    assert "bytes" in response


def test_vision_llm_validate_text():
    """Test Vision LLM text validation."""
    LLMFactory.register_vision_provider("fake_vision", FakeVisionLLM)

    settings = create_test_settings("fake_vision")
    vision_llm = FakeVisionLLM(settings)

    # Valid text should pass
    vision_llm.validate_text("Valid prompt")

    # Empty text should fail
    with pytest.raises(ValueError, match="Text prompt cannot be empty"):
        vision_llm.validate_text("")

    # Whitespace-only should fail
    with pytest.raises(ValueError, match="Text prompt cannot be empty"):
        vision_llm.validate_text("   ")


def test_vision_llm_validate_image():
    """Test Vision LLM image validation."""
    settings = create_test_settings("fake_vision")
    vision_llm = FakeVisionLLM(settings)

    # Valid path should pass
    vision_llm.validate_image("path/to/image.png")

    # Valid bytes should pass
    vision_llm.validate_image(b"\x89PNG")

    # Empty bytes should fail
    with pytest.raises(ValueError, match="Image input cannot be empty"):
        vision_llm.validate_image(b"")

    # Invalid type should fail
    with pytest.raises(ValueError, match="Image must be str .* or bytes"):
        vision_llm.validate_image(123)  # type: ignore


def test_vision_llm_error_handling():
    """Test Vision LLM error handling."""
    LLMFactory.register_vision_provider("fake_vision", FakeVisionLLM)

    settings = create_test_settings("fake_vision")
    vision_llm = LLMFactory.create_vision_llm(settings)

    # Test error trigger pattern
    with pytest.raises(RuntimeError, match="Simulated Vision LLM error"):
        vision_llm.chat_with_image(text="trigger error", image="test.png")
