"""Unit tests for Azure Vision LLM provider implementation.

This module tests the AzureVisionLLM class using mocked HTTP calls,
without requiring actual Azure API credentials.
"""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.core.settings import Settings


# Mock PIL.Image before importing azure_vision_llm
@pytest.fixture(autouse=True)
def mock_pil():
    """Mock PIL module for all tests."""
    with patch.dict("sys.modules", {"PIL": Mock(), "PIL.Image": Mock()}):
        yield


@pytest.fixture
def mock_settings():
    """Create mock settings with Azure Vision configuration."""
    settings = Mock(spec=Settings)
    settings.llm = Mock()
    settings.llm.api_key = "test-api-key"
    settings.llm.azure_endpoint = "https://test-resource.openai.azure.com/"
    settings.vision_llm = Mock()
    settings.vision_llm.model = "gpt-4o"
    return settings


@pytest.fixture
def azure_vision_llm(mock_settings):
    """Create AzureVisionLLM instance with mocked client."""
    with patch("src.libs.llm.azure_vision_llm.AzureOpenAI"), \
         patch("src.libs.llm.azure_vision_llm.Image"):
        from src.libs.llm.azure_vision_llm import AzureVisionLLM

        llm = AzureVisionLLM(settings=mock_settings)
        # Mock the client's chat.completions.create method
        llm.client.chat.completions.create = Mock()
        return llm


@pytest.fixture
def sample_image_bytes():
    """Create sample image bytes for testing."""
    # Simulate PNG header + minimal data
    return b"\x89PNG\r\n\x1a\n" + b"test_image_data"


@pytest.fixture
def sample_image_path(tmp_path, sample_image_bytes):
    """Create a temporary image file."""
    image_path = tmp_path / "test_image.png"
    image_path.write_bytes(sample_image_bytes)
    return str(image_path)


class TestAzureVisionLLMInit:
    """Test cases for AzureVisionLLM initialization."""

    def test_initialization_success(self, mock_settings):
        """Test successful initialization with valid settings."""
        with patch("src.libs.llm.azure_vision_llm.AzureOpenAI") as mock_client_class, \
             patch("src.libs.llm.azure_vision_llm.Image"):
            from src.libs.llm.azure_vision_llm import AzureVisionLLM

            mock_client = Mock()
            mock_client_class.return_value = mock_client

            llm = AzureVisionLLM(settings=mock_settings)

            assert llm.model == "gpt-4o"
            assert llm.api_key == "test-api-key"
            assert llm.azure_endpoint == "https://test-resource.openai.azure.com/"
            assert llm.api_version == "2024-02-15-preview"
            assert llm.max_image_size == 2048
            mock_client_class.assert_called_once()

    def test_initialization_missing_api_key(self, mock_settings):
        """Test initialization fails when API key is missing."""
        with patch("src.libs.llm.azure_vision_llm.Image"):
            from src.libs.llm.azure_vision_llm import AzureVisionLLM

            mock_settings.llm.api_key = None

            with pytest.raises(ValueError, match="Azure OpenAI API key is required"):
                AzureVisionLLM(settings=mock_settings)

    def test_initialization_missing_endpoint(self, mock_settings):
        """Test initialization fails when endpoint is missing."""
        with patch("src.libs.llm.azure_vision_llm.Image"):
            from src.libs.llm.azure_vision_llm import AzureVisionLLM

            mock_settings.llm.azure_endpoint = None

            with pytest.raises(ValueError, match="Azure OpenAI endpoint is required"):
                AzureVisionLLM(settings=mock_settings)

    def test_initialization_with_custom_params(self, mock_settings):
        """Test initialization with custom override parameters."""
        with patch("src.libs.llm.azure_vision_llm.AzureOpenAI"), \
             patch("src.libs.llm.azure_vision_llm.Image"):
            from src.libs.llm.azure_vision_llm import AzureVisionLLM

            llm = AzureVisionLLM(
                settings=mock_settings,
                model="gpt-4-vision-preview",
                api_version="2023-12-01",
                max_image_size=1024,
            )

            assert llm.model == "gpt-4-vision-preview"
            assert llm.api_version == "2023-12-01"
            assert llm.max_image_size == 1024


class TestChatWithImage:
    """Test cases for chat_with_image method."""

    def test_chat_with_image_path_success(
        self, azure_vision_llm, sample_image_path
    ):
        """Test successful chat with image path."""
        # Mock _prepare_image to return base64 string
        with patch.object(
            azure_vision_llm, "_prepare_image", return_value="base64_image_data"
        ):
            # Mock API response
            mock_response = Mock()
            mock_response.choices = [Mock()]
            mock_response.choices[0].message.content = "This is a red square image."
            azure_vision_llm.client.chat.completions.create.return_value = (
                mock_response
            )

            # Call method
            response = azure_vision_llm.chat_with_image(
                text="Describe this image", image=sample_image_path
            )

            # Assertions
            assert response == "This is a red square image."
            azure_vision_llm.client.chat.completions.create.assert_called_once()

            # Verify call arguments structure
            call_args = azure_vision_llm.client.chat.completions.create.call_args
            assert call_args.kwargs["model"] == "gpt-4o"
            assert call_args.kwargs["temperature"] == 0.7
            assert call_args.kwargs["max_tokens"] == 1024

            # Verify messages structure
            messages = call_args.kwargs["messages"]
            assert len(messages) == 1
            assert messages[0]["role"] == "user"
            assert len(messages[0]["content"]) == 2
            assert messages[0]["content"][0]["type"] == "text"
            assert messages[0]["content"][0]["text"] == "Describe this image"
            assert messages[0]["content"][1]["type"] == "image_url"
            assert "data:image/png;base64," in messages[0]["content"][1]["image_url"]["url"]

    def test_chat_with_image_bytes_success(
        self, azure_vision_llm, sample_image_bytes
    ):
        """Test successful chat with image bytes."""
        with patch.object(
            azure_vision_llm, "_prepare_image", return_value="base64_image_data"
        ):
            # Mock API response
            mock_response = Mock()
            mock_response.choices = [Mock()]
            mock_response.choices[0].message.content = "This is a test image."
            azure_vision_llm.client.chat.completions.create.return_value = (
                mock_response
            )

            # Call method
            response = azure_vision_llm.chat_with_image(
                text="What do you see?", image=sample_image_bytes
            )

            # Assertions
            assert response == "This is a test image."
            azure_vision_llm.client.chat.completions.create.assert_called_once()

    def test_chat_with_empty_text(self, azure_vision_llm, sample_image_path):
        """Test chat fails with empty text prompt."""
        with pytest.raises(ValueError, match="Text prompt cannot be empty"):
            azure_vision_llm.chat_with_image(text="", image=sample_image_path)

    def test_chat_with_empty_image_bytes(self, azure_vision_llm):
        """Test chat fails with empty image bytes."""
        with pytest.raises(ValueError, match="Image input cannot be empty"):
            azure_vision_llm.chat_with_image(text="Describe this", image=b"")

    def test_chat_with_invalid_image_type(self, azure_vision_llm):
        """Test chat fails with invalid image type."""
        with pytest.raises(
            ValueError, match="Image must be str \\(path\\) or bytes"
        ):
            azure_vision_llm.chat_with_image(
                text="Describe this", image=12345  # Invalid type
            )

    def test_chat_with_custom_temperature(
        self, azure_vision_llm, sample_image_path
    ):
        """Test chat with custom temperature parameter."""
        with patch.object(
            azure_vision_llm, "_prepare_image", return_value="base64_image_data"
        ):
            # Mock API response
            mock_response = Mock()
            mock_response.choices = [Mock()]
            mock_response.choices[0].message.content = "Response text."
            azure_vision_llm.client.chat.completions.create.return_value = (
                mock_response
            )

            # Call with custom temperature
            azure_vision_llm.chat_with_image(
                text="Describe", image=sample_image_path, temperature=0.2
            )

            # Verify temperature was passed correctly
            call_args = azure_vision_llm.client.chat.completions.create.call_args
            assert call_args.kwargs["temperature"] == 0.2

    def test_chat_api_returns_empty_content(
        self, azure_vision_llm, sample_image_path
    ):
        """Test chat handles empty API response content."""
        with patch.object(
            azure_vision_llm, "_prepare_image", return_value="base64_image_data"
        ):
            # Mock API response with None content
            mock_response = Mock()
            mock_response.choices = [Mock()]
            mock_response.choices[0].message.content = None
            azure_vision_llm.client.chat.completions.create.return_value = (
                mock_response
            )

            with pytest.raises(
                RuntimeError, match="Azure Vision API returned empty response content"
            ):
                azure_vision_llm.chat_with_image(
                    text="Describe", image=sample_image_path
                )


class TestErrorHandling:
    """Test cases for Azure-specific error handling."""

    def test_authentication_error(self, azure_vision_llm, sample_image_path):
        """Test handling of 401 authentication errors."""
        with patch.object(
            azure_vision_llm, "_prepare_image", return_value="base64_image_data"
        ):
            # Mock 401 error
            azure_vision_llm.client.chat.completions.create.side_effect = Exception(
                "401 Unauthorized"
            )

            with pytest.raises(
                RuntimeError, match="Azure Vision API authentication failed"
            ):
                azure_vision_llm.chat_with_image(
                    text="Describe", image=sample_image_path
                )

    def test_bad_request_error(self, azure_vision_llm, sample_image_path):
        """Test handling of 400 bad request errors."""
        with patch.object(
            azure_vision_llm, "_prepare_image", return_value="base64_image_data"
        ):
            # Mock 400 error
            azure_vision_llm.client.chat.completions.create.side_effect = Exception(
                "400 Bad Request: Invalid image format"
            )

            with pytest.raises(RuntimeError, match="Azure Vision API bad request"):
                azure_vision_llm.chat_with_image(
                    text="Describe", image=sample_image_path
                )

    def test_rate_limit_error(self, azure_vision_llm, sample_image_path):
        """Test handling of 429 rate limit errors."""
        with patch.object(
            azure_vision_llm, "_prepare_image", return_value="base64_image_data"
        ):
            # Mock 429 error
            azure_vision_llm.client.chat.completions.create.side_effect = Exception(
                "429 Rate limit exceeded"
            )

            with pytest.raises(
                RuntimeError, match="Azure Vision API rate limit exceeded"
            ):
                azure_vision_llm.chat_with_image(
                    text="Describe", image=sample_image_path
                )


class TestMetadataMethods:
    """Test cases for metadata retrieval methods."""

    def test_get_model_name(self, azure_vision_llm):
        """Test get_model_name returns correct model identifier."""
        assert azure_vision_llm.get_model_name() == "gpt-4o"

    def test_get_backend_name(self, azure_vision_llm):
        """Test get_backend_name returns 'azure'."""
        assert azure_vision_llm.get_backend_name() == "azure"

