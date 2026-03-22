"""Smoke tests for OpenAI and Azure Embedding providers.

These tests verify that the OpenAI and Azure Embedding implementations
correctly integrate with the factory and handle basic operations using
mocked HTTP responses.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.core.settings import Settings
from src.libs.embedding.azure_embedding import AzureEmbedding
from src.libs.embedding.embedding_factory import EmbeddingFactory
from src.libs.embedding.openai_embedding import OpenAIEmbedding


@pytest.fixture
def mock_openai_settings():
    """Create mock settings for OpenAI Embedding."""
    settings = MagicMock(spec=Settings)
    settings.embedding = MagicMock()
    settings.embedding.provider = "openai"
    settings.embedding.model = "text-embedding-3-small"
    settings.embedding.api_key = "test-openai-key"
    return settings


@pytest.fixture
def mock_azure_settings():
    """Create mock settings for Azure OpenAI Embedding."""
    settings = MagicMock(spec=Settings)
    settings.embedding = MagicMock()
    settings.embedding.provider = "azure"
    settings.embedding.model = "text-embedding-3-small"
    settings.embedding.api_key = "test-azure-key"
    settings.embedding.azure_endpoint = "https://test.openai.azure.com/"
    settings.embedding.api_version = "2024-02-01"
    return settings


@pytest.fixture
def mock_embedding_response():
    """Create a mock OpenAI embedding API response."""
    mock_response = MagicMock()
    mock_response.data = [
        MagicMock(embedding=[0.1] * 1536),
        MagicMock(embedding=[0.2] * 1536),
    ]
    return mock_response


class TestOpenAIEmbedding:
    """Test suite for OpenAI Embedding provider."""

    def setup_method(self):
        """Ensure providers are registered before each test."""
        # Re-register providers in case other tests cleared the registry
        from src.libs.embedding.embedding_factory import _register_builtin_providers
        _register_builtin_providers()

    def test_factory_creates_openai_embedding(self, mock_openai_settings):
        """Test that factory creates OpenAI Embedding instance."""
        with patch("src.libs.embedding.openai_embedding.OpenAI"):
            embedding = EmbeddingFactory.create(mock_openai_settings)
            assert isinstance(embedding, OpenAIEmbedding)
            assert embedding.model == "text-embedding-3-small"

    def test_initialization_validates_api_key(self, mock_openai_settings):
        """Test that initialization fails without API key."""
        mock_openai_settings.embedding.api_key = None

        with patch("src.libs.embedding.openai_embedding.OpenAI"):
            with pytest.raises(ValueError, match="OpenAI API key is required"):
                OpenAIEmbedding(mock_openai_settings)

    def test_embed_validates_empty_input(self, mock_openai_settings):
        """Test that embed() rejects empty text list."""
        with patch("src.libs.embedding.openai_embedding.OpenAI"):
            embedding = OpenAIEmbedding(mock_openai_settings)

            with pytest.raises(ValueError, match="Texts list cannot be empty"):
                embedding.embed([])

    def test_embed_validates_non_string_input(self, mock_openai_settings):
        """Test that embed() rejects non-string entries."""
        with patch("src.libs.embedding.openai_embedding.OpenAI"):
            embedding = OpenAIEmbedding(mock_openai_settings)

            with pytest.raises(ValueError, match="not a string"):
                embedding.embed(["valid text", 123, "another text"])

    def test_embed_success(
        self, mock_openai_settings, mock_embedding_response
    ):
        """Test successful embedding call."""
        with patch("src.libs.embedding.openai_embedding.OpenAI") as mock_client_class:
            mock_client = MagicMock()
            mock_client.embeddings.create.return_value = mock_embedding_response
            mock_client_class.return_value = mock_client

            embedding = OpenAIEmbedding(mock_openai_settings)
            texts = ["Hello world", "Foo bar"]
            vectors = embedding.embed(texts)

            # Verify response structure
            assert len(vectors) == 2
            assert len(vectors[0]) == 1536
            assert len(vectors[1]) == 1536
            assert vectors[0] == [0.1] * 1536
            assert vectors[1] == [0.2] * 1536

            # Verify API call
            mock_client.embeddings.create.assert_called_once_with(
                model="text-embedding-3-small",
                input=texts,
            )

    def test_embed_batch_processing(self, mock_openai_settings):
        """Test batch processing for large input."""
        with patch("src.libs.embedding.openai_embedding.OpenAI") as mock_client_class:
            mock_client = MagicMock()

            # Mock response for each batch
            def create_response(batch_size):
                response = MagicMock()
                response.data = [
                    MagicMock(embedding=[0.1] * 1536) for _ in range(batch_size)
                ]
                return response

            mock_client.embeddings.create.side_effect = lambda **kwargs: (
                create_response(len(kwargs["input"]))
            )
            mock_client_class.return_value = mock_client

            # Create embedding with small batch size
            embedding = OpenAIEmbedding(mock_openai_settings, batch_size=2)
            texts = ["text1", "text2", "text3", "text4", "text5"]
            vectors = embedding.embed(texts)

            # Verify result
            assert len(vectors) == 5

            # Verify batching (5 texts with batch_size=2 -> 3 calls)
            assert mock_client.embeddings.create.call_count == 3

    def test_embed_api_failure(self, mock_openai_settings):
        """Test handling of API call failure."""
        with patch("src.libs.embedding.openai_embedding.OpenAI") as mock_client_class:
            mock_client = MagicMock()
            mock_client.embeddings.create.side_effect = Exception(
                "API connection error"
            )
            mock_client_class.return_value = mock_client

            embedding = OpenAIEmbedding(mock_openai_settings)

            with pytest.raises(
                RuntimeError, match="OpenAI Embedding API call failed"
            ):
                embedding.embed(["test text"])

    def test_get_model_name(self, mock_openai_settings):
        """Test get_model_name() method."""
        with patch("src.libs.embedding.openai_embedding.OpenAI"):
            embedding = OpenAIEmbedding(mock_openai_settings)
            assert embedding.get_model_name() == "text-embedding-3-small"

    def test_get_dimension(self, mock_openai_settings):
        """Test get_dimension() method."""
        with patch("src.libs.embedding.openai_embedding.OpenAI"):
            embedding = OpenAIEmbedding(mock_openai_settings)
            assert embedding.get_dimension() == 1536


class TestAzureEmbedding:
    """Test suite for Azure OpenAI Embedding provider."""

    def setup_method(self):
        """Ensure providers are registered before each test."""
        # Re-register providers in case other tests cleared the registry
        from src.libs.embedding.embedding_factory import _register_builtin_providers
        _register_builtin_providers()

    def test_factory_creates_azure_embedding(self, mock_azure_settings):
        """Test that factory creates Azure Embedding instance."""
        with patch("src.libs.embedding.azure_embedding.AzureOpenAI"):
            embedding = EmbeddingFactory.create(mock_azure_settings)
            assert isinstance(embedding, AzureEmbedding)
            assert embedding.model == "text-embedding-3-small"

    def test_initialization_validates_endpoint(self, mock_azure_settings):
        """Test that initialization fails without Azure endpoint."""
        mock_azure_settings.embedding.azure_endpoint = None

        with patch("src.libs.embedding.azure_embedding.AzureOpenAI"):
            with pytest.raises(ValueError, match="Azure endpoint is required"):
                AzureEmbedding(mock_azure_settings)

    def test_initialization_validates_api_key(self, mock_azure_settings):
        """Test that initialization fails without API key."""
        mock_azure_settings.embedding.api_key = None

        with patch("src.libs.embedding.azure_embedding.AzureOpenAI"):
            with pytest.raises(ValueError, match="Azure API key is required"):
                AzureEmbedding(mock_azure_settings)

    def test_embed_success(self, mock_azure_settings, mock_embedding_response):
        """Test successful Azure embedding call."""
        with patch(
            "src.libs.embedding.azure_embedding.AzureOpenAI"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.embeddings.create.return_value = mock_embedding_response
            mock_client_class.return_value = mock_client

            embedding = AzureEmbedding(mock_azure_settings)
            texts = ["Hello world", "Foo bar"]
            vectors = embedding.embed(texts)

            # Verify response structure
            assert len(vectors) == 2
            assert len(vectors[0]) == 1536
            assert len(vectors[1]) == 1536

            # Verify Azure client initialization
            mock_client_class.assert_called_once_with(
                azure_endpoint="https://test.openai.azure.com/",
                api_key="test-azure-key",
                api_version="2024-02-01",
            )

            # Verify API call (Azure uses deployment name as model)
            mock_client.embeddings.create.assert_called_once_with(
                model="text-embedding-3-small",
                input=texts,
            )

    def test_embed_api_failure_includes_endpoint(self, mock_azure_settings):
        """Test that API failure error includes Azure endpoint info."""
        with patch(
            "src.libs.embedding.azure_embedding.AzureOpenAI"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.embeddings.create.side_effect = Exception(
                "Authentication failed"
            )
            mock_client_class.return_value = mock_client

            embedding = AzureEmbedding(mock_azure_settings)

            with pytest.raises(RuntimeError) as exc_info:
                embedding.embed(["test text"])

            # Verify error message includes Azure-specific details
            error_msg = str(exc_info.value)
            assert "Azure OpenAI Embedding API call failed" in error_msg
            assert "endpoint: https://test.openai.azure.com/" in error_msg
            assert "model: text-embedding-3-small" in error_msg

    def test_get_model_name(self, mock_azure_settings):
        """Test get_model_name() method."""
        with patch("src.libs.embedding.azure_embedding.AzureOpenAI"):
            embedding = AzureEmbedding(mock_azure_settings)
            assert embedding.get_model_name() == "text-embedding-3-small"

    def test_get_dimension(self, mock_azure_settings):
        """Test get_dimension() method."""
        with patch("src.libs.embedding.azure_embedding.AzureOpenAI"):
            embedding = AzureEmbedding(mock_azure_settings)
            assert embedding.get_dimension() == 1536


class TestProviderIntegration:
    """Test provider registration and factory integration."""

    def setup_method(self):
        """Ensure providers are registered before each test."""
        # Re-register providers in case other tests cleared the registry
        from src.libs.embedding.embedding_factory import _register_builtin_providers
        _register_builtin_providers()

    def test_openai_provider_registered(self):
        """Test that OpenAI provider is registered in factory."""
        providers = EmbeddingFactory.list_providers()
        assert "openai" in providers

    def test_azure_provider_registered(self):
        """Test that Azure provider is registered in factory."""
        providers = EmbeddingFactory.list_providers()
        assert "azure" in providers

    def test_unknown_provider_raises_error(self):
        """Test that unknown provider raises clear error."""
        settings = MagicMock(spec=Settings)
        settings.embedding = MagicMock()
        settings.embedding.provider = "unknown_provider"

        with pytest.raises(
            ValueError, match="Unsupported Embedding provider: 'unknown_provider'"
        ):
            EmbeddingFactory.create(settings)
