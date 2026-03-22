"""Smoke tests for OpenAI-compatible LLM providers.

Test Coverage:
- OpenAI/Azure/DeepSeek provider instantiation
- Configuration validation
- Factory registration
- Mock API calls (no actual API requests)
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from src.libs.llm.azure_llm import AzureLLM
from src.libs.llm.deepseek_llm import DeepSeekLLM
from src.libs.llm.llm_factory import LLMFactory
from src.libs.llm.openai_llm import OpenAILLM


class TestOpenAILLM:
    """Tests for OpenAI LLM provider."""

    def test_init_success(self):
        """OpenAI provider should initialize with valid config."""
        settings = MagicMock()
        settings.llm.api_key = "sk-test-key"
        settings.llm.model = "gpt-4o"

        with patch("src.libs.llm.openai_llm.OpenAI"):
            llm = OpenAILLM(settings)

            assert llm.api_key == "sk-test-key"
            assert llm.model == "gpt-4o"

    def test_init_missing_api_key(self):
        """OpenAI provider should raise error when API key is missing."""
        settings = MagicMock()
        settings.llm.api_key = None

        with pytest.raises(ValueError, match="OpenAI API key is required"):
            OpenAILLM(settings)

    def test_init_with_overrides(self):
        """OpenAI provider should accept override kwargs."""
        settings = MagicMock()
        settings.llm.api_key = "sk-default"
        settings.llm.model = "gpt-4o"

        with patch("src.libs.llm.openai_llm.OpenAI"):
            llm = OpenAILLM(settings, api_key="sk-override", model="gpt-3.5-turbo")

            assert llm.api_key == "sk-override"
            assert llm.model == "gpt-3.5-turbo"

    def test_chat_success(self):
        """chat() should call OpenAI API and return response."""
        settings = MagicMock()
        settings.llm.api_key = "sk-test-key"
        settings.llm.model = "gpt-4o"

        mock_client = Mock()
        mock_choice = Mock()
        mock_choice.message.content = "Hello from OpenAI!"
        mock_response = Mock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        with patch("src.libs.llm.openai_llm.OpenAI", return_value=mock_client):
            llm = OpenAILLM(settings)
            result = llm.chat([{"role": "user", "content": "Hello"}])

            assert result == "Hello from OpenAI!"
            mock_client.chat.completions.create.assert_called_once()

    def test_chat_validates_messages(self):
        """chat() should validate messages before API call."""
        settings = MagicMock()
        settings.llm.api_key = "sk-test-key"

        with patch("src.libs.llm.openai_llm.OpenAI"):
            llm = OpenAILLM(settings)

            with pytest.raises(ValueError, match="cannot be empty"):
                llm.chat([])

    def test_chat_api_failure(self):
        """chat() should raise RuntimeError on API failure."""
        settings = MagicMock()
        settings.llm.api_key = "sk-test-key"

        mock_client = Mock()
        mock_client.chat.completions.create.side_effect = Exception("API error")

        with patch("src.libs.llm.openai_llm.OpenAI", return_value=mock_client):
            llm = OpenAILLM(settings)

            with pytest.raises(RuntimeError, match="OpenAI API call failed"):
                llm.chat([{"role": "user", "content": "test"}])

    def test_get_model_name(self):
        """get_model_name() should return configured model."""
        settings = MagicMock()
        settings.llm.api_key = "sk-test-key"
        settings.llm.model = "gpt-4o"

        with patch("src.libs.llm.openai_llm.OpenAI"):
            llm = OpenAILLM(settings)
            assert llm.get_model_name() == "gpt-4o"


class TestAzureLLM:
    """Tests for Azure OpenAI LLM provider."""

    def test_init_success(self):
        """Azure provider should initialize with valid config."""
        settings = MagicMock()
        settings.llm.api_key = "azure-key"
        settings.llm.azure_endpoint = "https://test.openai.azure.com/"
        settings.llm.model = "gpt-4o"

        with patch("src.libs.llm.azure_llm.AzureOpenAI"):
            llm = AzureLLM(settings)

            assert llm.api_key == "azure-key"
            assert llm.azure_endpoint == "https://test.openai.azure.com/"
            assert llm.model == "gpt-4o"

    def test_init_missing_api_key(self):
        """Azure provider should raise error when API key is missing."""
        settings = MagicMock()
        settings.llm.api_key = None
        settings.llm.azure_endpoint = "https://test.openai.azure.com/"

        with pytest.raises(ValueError, match="Azure OpenAI API key is required"):
            AzureLLM(settings)

    def test_init_missing_endpoint(self):
        """Azure provider should raise error when endpoint is missing."""
        settings = MagicMock()
        settings.llm.api_key = "azure-key"
        settings.llm.azure_endpoint = None

        with pytest.raises(ValueError, match="Azure OpenAI endpoint is required"):
            AzureLLM(settings)

    def test_chat_success(self):
        """chat() should call Azure OpenAI API and return response."""
        settings = MagicMock()
        settings.llm.api_key = "azure-key"
        settings.llm.azure_endpoint = "https://test.openai.azure.com/"
        settings.llm.model = "gpt-4o"

        mock_client = Mock()
        mock_choice = Mock()
        mock_choice.message.content = "Hello from Azure!"
        mock_response = Mock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        with patch("src.libs.llm.azure_llm.AzureOpenAI", return_value=mock_client):
            llm = AzureLLM(settings)
            result = llm.chat([{"role": "user", "content": "Hello"}])

            assert result == "Hello from Azure!"

    def test_get_model_name(self):
        """get_model_name() should return configured model."""
        settings = MagicMock()
        settings.llm.api_key = "azure-key"
        settings.llm.azure_endpoint = "https://test.openai.azure.com/"
        settings.llm.model = "gpt-4o"

        with patch("src.libs.llm.azure_llm.AzureOpenAI"):
            llm = AzureLLM(settings)
            assert llm.get_model_name() == "gpt-4o"


class TestDeepSeekLLM:
    """Tests for DeepSeek LLM provider."""

    def test_init_success(self):
        """DeepSeek provider should initialize with valid config."""
        settings = MagicMock()
        settings.llm.api_key = "deepseek-key"
        settings.llm.model = "deepseek-chat"

        with patch("src.libs.llm.deepseek_llm.OpenAI"):
            llm = DeepSeekLLM(settings)

            assert llm.api_key == "deepseek-key"
            assert llm.model == "deepseek-chat"
            assert llm.base_url == DeepSeekLLM.DEEPSEEK_BASE_URL

    def test_init_missing_api_key(self):
        """DeepSeek provider should raise error when API key is missing."""
        settings = MagicMock()
        settings.llm.api_key = None

        with pytest.raises(ValueError, match="DeepSeek API key is required"):
            DeepSeekLLM(settings)

    def test_init_custom_base_url(self):
        """DeepSeek provider should accept custom base URL."""
        settings = MagicMock()
        settings.llm.api_key = "deepseek-key"
        settings.llm.model = "deepseek-chat"

        with patch("src.libs.llm.deepseek_llm.OpenAI"):
            llm = DeepSeekLLM(settings, base_url="https://custom.deepseek.com")
            assert llm.base_url == "https://custom.deepseek.com"

    def test_chat_success(self):
        """chat() should call DeepSeek API and return response."""
        settings = MagicMock()
        settings.llm.api_key = "deepseek-key"
        settings.llm.model = "deepseek-chat"

        mock_client = Mock()
        mock_choice = Mock()
        mock_choice.message.content = "Hello from DeepSeek!"
        mock_response = Mock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        with patch("src.libs.llm.deepseek_llm.OpenAI", return_value=mock_client):
            llm = DeepSeekLLM(settings)
            result = llm.chat([{"role": "user", "content": "Hello"}])

            assert result == "Hello from DeepSeek!"

    def test_get_model_name(self):
        """get_model_name() should return configured model."""
        settings = MagicMock()
        settings.llm.api_key = "deepseek-key"
        settings.llm.model = "deepseek-coder"

        with patch("src.libs.llm.deepseek_llm.OpenAI"):
            llm = DeepSeekLLM(settings)
            assert llm.get_model_name() == "deepseek-coder"


class TestLLMFactoryIntegration:
    """Integration tests for LLM Factory with new providers."""

    def setup_method(self):
        """Ensure providers are registered before each test."""
        # Re-register providers in case other tests cleared the registry
        from src.libs.llm.llm_factory import _register_builtin_providers
        _register_builtin_providers()

    def test_factory_registers_openai(self):
        """Factory should auto-register OpenAI provider."""
        providers = LLMFactory.list_providers()
        assert "openai" in providers

    def test_factory_registers_azure(self):
        """Factory should auto-register Azure provider."""
        providers = LLMFactory.list_providers()
        assert "azure" in providers

    def test_factory_registers_deepseek(self):
        """Factory should auto-register DeepSeek provider."""
        providers = LLMFactory.list_providers()
        assert "deepseek" in providers
        """Factory should create OpenAI provider from settings."""
        settings = MagicMock()
        settings.llm.provider = "openai"
        settings.llm.api_key = "sk-test"
        settings.llm.model = "gpt-4o"

        with patch("src.libs.llm.openai_llm.OpenAI"):
            llm = LLMFactory.create(settings)
            assert isinstance(llm, OpenAILLM)

    def test_factory_create_azure(self):
        """Factory should create Azure provider from settings."""
        settings = MagicMock()
        settings.llm.provider = "azure"
        settings.llm.api_key = "azure-key"
        settings.llm.azure_endpoint = "https://test.openai.azure.com/"
        settings.llm.model = "gpt-4o"

        with patch("src.libs.llm.azure_llm.AzureOpenAI"):
            llm = LLMFactory.create(settings)
            assert isinstance(llm, AzureLLM)

    def test_factory_create_deepseek(self):
        """Factory should create DeepSeek provider from settings."""
        settings = MagicMock()
        settings.llm.provider = "deepseek"
        settings.llm.api_key = "deepseek-key"
        settings.llm.model = "deepseek-chat"

        with patch("src.libs.llm.deepseek_llm.OpenAI"):
            llm = LLMFactory.create(settings)
            assert isinstance(llm, DeepSeekLLM)
