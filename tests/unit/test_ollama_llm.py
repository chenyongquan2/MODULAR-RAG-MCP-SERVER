"""Unit tests for Ollama LLM provider.

This module tests the OllamaLLM implementation with mocked HTTP calls.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from src.core.settings import Settings
from src.libs.llm.ollama_llm import OllamaLLM


@pytest.fixture
def mock_settings():
    """Create mock settings for Ollama LLM."""
    settings = Mock(spec=Settings)
    settings.llm = Mock()
    settings.llm.provider = "ollama"
    settings.llm.model = "llama2"
    settings.llm.base_url = "http://localhost:11434/v1"
    return settings


@pytest.fixture
def mock_ollama_response():
    """Create a properly structured mock response matching OpenAI format."""
    mock_choice = Mock()
    mock_choice.message.content = "Test response from Ollama"
    
    mock_response = Mock()
    mock_response.choices = [mock_choice]
    
    return mock_response


class TestOllamaLLMInitialization:
    """Test Ollama LLM initialization scenarios."""

    @patch("src.libs.llm.ollama_llm.OpenAI")
    def test_initialization_with_default_settings(self, mock_openai, mock_settings):
        """Test successful initialization with default settings."""
        # Act
        llm = OllamaLLM(mock_settings)

        # Assert
        assert llm.model == "llama2"
        assert llm.base_url == "http://localhost:11434/v1"
        mock_openai.assert_called_once_with(
            base_url="http://localhost:11434/v1",
            api_key="ollama"
        )

    @patch("src.libs.llm.ollama_llm.OpenAI")
    def test_initialization_with_custom_base_url(self, mock_openai, mock_settings):
        """Test initialization with custom base URL."""
        # Arrange
        custom_url = "http://192.168.1.100:11434/v1"
        mock_settings.llm.base_url = custom_url

        # Act
        llm = OllamaLLM(mock_settings)

        # Assert
        assert llm.base_url == custom_url
        mock_openai.assert_called_once_with(
            base_url=custom_url,
            api_key="ollama"
        )

    @patch("src.libs.llm.ollama_llm.OpenAI")
    def test_initialization_with_custom_model(self, mock_openai, mock_settings):
        """Test initialization with custom model."""
        # Arrange
        mock_settings.llm.model = "mistral"

        # Act
        llm = OllamaLLM(mock_settings)

        # Assert
        assert llm.model == "mistral"

    @patch("src.libs.llm.ollama_llm.OpenAI")
    def test_initialization_with_kwargs_override(self, mock_openai):
        """Test initialization with kwargs override."""
        # Arrange
        settings = Mock(spec=Settings)
        settings.llm = Mock()
        settings.llm.model = "llama2"
        settings.llm.base_url = "http://localhost:11434/v1"

        # Act
        llm = OllamaLLM(
            settings,
            model="codellama",
            base_url="http://custom:11434/v1"
        )

        # Assert
        assert llm.model == "codellama"
        assert llm.base_url == "http://custom:11434/v1"

    @patch("src.libs.llm.ollama_llm.OpenAI")
    def test_initialization_failure_shows_clear_error(self, mock_openai, mock_settings):
        """Test initialization failure shows clear error message."""
        # Arrange
        mock_openai.side_effect = Exception("Connection refused")

        # Act & Assert
        with pytest.raises(RuntimeError) as exc_info:
            OllamaLLM(mock_settings)
        
        assert "Failed to initialize Ollama client" in str(exc_info.value)
        assert "Ensure Ollama is running" in str(exc_info.value)
        assert "localhost:11434" in str(exc_info.value)


class TestOllamaLLMChat:
    """Test Ollama LLM chat functionality."""

    @patch("src.libs.llm.ollama_llm.OpenAI")
    def test_chat_success(self, mock_openai, mock_settings, mock_ollama_response):
        """Test successful chat completion."""
        # Arrange
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_ollama_response
        mock_openai.return_value = mock_client

        llm = OllamaLLM(mock_settings)
        messages = [{"role": "user", "content": "Hello"}]

        # Act
        response = llm.chat(messages)

        # Assert
        assert response == "Test response from Ollama"
        mock_client.chat.completions.create.assert_called_once_with(
            model="llama2",
            messages=messages,
            temperature=0.7,
            max_tokens=None
        )

    @patch("src.libs.llm.ollama_llm.OpenAI")
    def test_chat_with_custom_temperature(self, mock_openai, mock_settings, mock_ollama_response):
        """Test chat with custom temperature."""
        # Arrange
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_ollama_response
        mock_openai.return_value = mock_client

        llm = OllamaLLM(mock_settings)
        messages = [{"role": "user", "content": "Hello"}]

        # Act
        response = llm.chat(messages, temperature=0.9)

        # Assert
        assert response == "Test response from Ollama"
        mock_client.chat.completions.create.assert_called_once_with(
            model="llama2",
            messages=messages,
            temperature=0.9,
            max_tokens=None
        )

    @patch("src.libs.llm.ollama_llm.OpenAI")
    def test_chat_with_max_tokens(self, mock_openai, mock_settings, mock_ollama_response):
        """Test chat with max_tokens parameter."""
        # Arrange
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_ollama_response
        mock_openai.return_value = mock_client

        llm = OllamaLLM(mock_settings)
        messages = [{"role": "user", "content": "Hello"}]

        # Act
        response = llm.chat(messages, max_tokens=100)

        # Assert
        assert response == "Test response from Ollama"
        mock_client.chat.completions.create.assert_called_once_with(
            model="llama2",
            messages=messages,
            temperature=0.7,
            max_tokens=100
        )

    @patch("src.libs.llm.ollama_llm.OpenAI")
    def test_chat_with_empty_messages_raises_error(self, mock_openai, mock_settings):
        """Test chat with empty messages raises ValueError."""
        # Arrange
        llm = OllamaLLM(mock_settings)

        # Act & Assert
        with pytest.raises(ValueError) as exc_info:
            llm.chat([])
        
        assert "empty" in str(exc_info.value).lower()

    @patch("src.libs.llm.ollama_llm.OpenAI")
    def test_chat_with_invalid_message_format_raises_error(self, mock_openai, mock_settings):
        """Test chat with invalid message format raises ValueError."""
        # Arrange
        llm = OllamaLLM(mock_settings)
        invalid_messages = [{"invalid": "format"}]

        # Act & Assert
        with pytest.raises(ValueError):
            llm.chat(invalid_messages)

    @patch("src.libs.llm.ollama_llm.OpenAI")
    def test_chat_api_failure_shows_clear_error(self, mock_openai, mock_settings):
        """Test chat API failure shows clear error message."""
        # Arrange
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("Connection timeout")
        mock_openai.return_value = mock_client

        llm = OllamaLLM(mock_settings)
        messages = [{"role": "user", "content": "Hello"}]

        # Act & Assert
        with pytest.raises(RuntimeError) as exc_info:
            llm.chat(messages)
        
        error_msg = str(exc_info.value)
        assert "Ollama API call failed" in error_msg
        assert "llama2" in error_msg
        assert "Ensure Ollama is running" in error_msg

    @patch("src.libs.llm.ollama_llm.OpenAI")
    def test_chat_empty_response_raises_error(self, mock_openai, mock_settings):
        """Test chat with empty response content raises error."""
        # Arrange
        mock_choice = Mock()
        mock_choice.message.content = None
        mock_response = Mock()
        mock_response.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        llm = OllamaLLM(mock_settings)
        messages = [{"role": "user", "content": "Hello"}]

        # Act & Assert
        with pytest.raises(RuntimeError) as exc_info:
            llm.chat(messages)
        
        assert "Ollama returned empty response content" in str(exc_info.value)


class TestOllamaLLMModelName:
    """Test Ollama LLM model name retrieval."""

    @patch("src.libs.llm.ollama_llm.OpenAI")
    def test_get_model_name(self, mock_openai, mock_settings):
        """Test get_model_name returns correct model."""
        # Arrange
        llm = OllamaLLM(mock_settings)

        # Act
        model_name = llm.get_model_name()

        # Assert
        assert model_name == "llama2"

    @patch("src.libs.llm.ollama_llm.OpenAI")
    def test_get_model_name_with_custom_model(self, mock_openai, mock_settings):
        """Test get_model_name with custom model."""
        # Arrange
        mock_settings.llm.model = "mistral"
        llm = OllamaLLM(mock_settings)

        # Act
        model_name = llm.get_model_name()

        # Assert
        assert model_name == "mistral"


class TestOllamaLLMURLSanitization:
    """Test URL sanitization for logging."""

    @patch("src.libs.llm.ollama_llm.OpenAI")
    def test_sanitize_url_without_credentials(self, mock_openai, mock_settings):
        """Test URL sanitization without credentials."""
        # Arrange
        llm = OllamaLLM(mock_settings)

        # Act
        sanitized = llm._sanitize_url("http://localhost:11434/v1")

        # Assert
        assert sanitized == "http://localhost:11434/v1"

    @patch("src.libs.llm.ollama_llm.OpenAI")
    def test_sanitize_url_with_credentials(self, mock_openai, mock_settings):
        """Test URL sanitization with credentials."""
        # Arrange
        llm = OllamaLLM(mock_settings)

        # Act
        sanitized = llm._sanitize_url("http://user:password@localhost:11434/v1")

        # Assert
        assert "***@localhost:11434/v1" in sanitized
        assert "password" not in sanitized
        assert "user" not in sanitized
