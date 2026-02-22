"""Unit tests for Ollama Embedding provider.

Test Coverage:
- Provider initialization with configuration
- Batch text embedding
- Empty input handling
- Connection failure scenarios
- Timeout handling
- Factory integration
"""

from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest
import requests

from src.libs.embedding.ollama_embedding import OllamaEmbedding


@pytest.mark.unit
class TestOllamaEmbedding:
    """Tests for OllamaEmbedding provider."""

    def test_ollama_embedding_creation(self):
        """Should create OllamaEmbedding with default settings."""
        settings = MagicMock()
        settings.embedding.base_url = "http://localhost:11434"
        settings.embedding.model = "nomic-embed-text"

        embedding = OllamaEmbedding(settings)

        assert embedding.base_url == "http://localhost:11434"
        assert embedding.model == "nomic-embed-text"
        assert embedding.timeout == 30
        assert embedding.api_endpoint == "http://localhost:11434/api/embeddings"

    def test_ollama_embedding_with_kwargs(self):
        """Should override settings with kwargs."""
        settings = MagicMock()
        settings.embedding.base_url = "http://localhost:11434"
        settings.embedding.model = "default-model"

        embedding = OllamaEmbedding(
            settings,
            base_url="http://custom:8080",
            model="custom-model",
            timeout=60,
        )

        assert embedding.base_url == "http://custom:8080"
        assert embedding.model == "custom-model"
        assert embedding.timeout == 60

    def test_base_url_trailing_slash_removed(self):
        """Should remove trailing slash from base_url."""
        settings = MagicMock()
        settings.embedding.base_url = "http://localhost:11434/"
        settings.embedding.model = "nomic-embed-text"

        embedding = OllamaEmbedding(settings)

        assert embedding.base_url == "http://localhost:11434"
        assert embedding.api_endpoint == "http://localhost:11434/api/embeddings"

    @patch("requests.post")
    def test_embed_single_text(self, mock_post):
        """Should embed single text successfully."""
        settings = MagicMock()
        settings.embedding.base_url = "http://localhost:11434"
        settings.embedding.model = "nomic-embed-text"

        # Mock API response
        mock_response = Mock()
        mock_response.json.return_value = {"embedding": [0.1, 0.2, 0.3]}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        embedding = OllamaEmbedding(settings)
        vectors = embedding.embed(["Hello world"])

        assert len(vectors) == 1
        assert vectors[0] == [0.1, 0.2, 0.3]

        # Verify API call
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[1]["json"] == {
            "model": "nomic-embed-text",
            "prompt": "Hello world",
        }
        assert call_args[1]["timeout"] == 30

    @patch("requests.post")
    def test_embed_batch_texts(self, mock_post):
        """Should embed multiple texts successfully."""
        settings = MagicMock()
        settings.embedding.base_url = "http://localhost:11434"
        settings.embedding.model = "nomic-embed-text"

        # Mock API responses for batch
        mock_responses = [
            Mock(
                json=Mock(return_value={"embedding": [0.1, 0.2, 0.3]}),
                raise_for_status=Mock(),
            ),
            Mock(
                json=Mock(return_value={"embedding": [0.4, 0.5, 0.6]}),
                raise_for_status=Mock(),
            ),
            Mock(
                json=Mock(return_value={"embedding": [0.7, 0.8, 0.9]}),
                raise_for_status=Mock(),
            ),
        ]
        mock_post.side_effect = mock_responses

        embedding = OllamaEmbedding(settings)
        vectors = embedding.embed(["Text 1", "Text 2", "Text 3"])

        assert len(vectors) == 3
        assert vectors[0] == [0.1, 0.2, 0.3]
        assert vectors[1] == [0.4, 0.5, 0.6]
        assert vectors[2] == [0.7, 0.8, 0.9]

        # Verify 3 API calls
        assert mock_post.call_count == 3

    def test_embed_empty_input(self):
        """Should raise ValueError for empty input."""
        settings = MagicMock()
        settings.embedding.base_url = "http://localhost:11434"
        settings.embedding.model = "nomic-embed-text"

        embedding = OllamaEmbedding(settings)

        with pytest.raises(ValueError, match="cannot be empty"):
            embedding.embed([])

    def test_embed_non_string_input(self):
        """Should raise ValueError for non-string input."""
        settings = MagicMock()
        settings.embedding.base_url = "http://localhost:11434"
        settings.embedding.model = "nomic-embed-text"

        embedding = OllamaEmbedding(settings)

        with pytest.raises(ValueError, match="not a string"):
            embedding.embed([123])  # type: ignore

    @patch("requests.post")
    def test_connection_failure(self, mock_post):
        """Should raise RuntimeError on connection failure."""
        settings = MagicMock()
        settings.embedding.base_url = "http://localhost:11434"
        settings.embedding.model = "nomic-embed-text"

        # Mock connection error
        mock_post.side_effect = requests.exceptions.ConnectionError(
            "Connection refused"
        )

        embedding = OllamaEmbedding(settings)

        with pytest.raises(
            RuntimeError,
            match="Failed to connect to Ollama service",
        ):
            embedding.embed(["Test"])

    @patch("requests.post")
    def test_timeout_handling(self, mock_post):
        """Should raise RuntimeError on timeout."""
        settings = MagicMock()
        settings.embedding.base_url = "http://localhost:11434"
        settings.embedding.model = "nomic-embed-text"

        # Mock timeout error
        mock_post.side_effect = requests.exceptions.Timeout("Request timeout")

        embedding = OllamaEmbedding(settings)

        with pytest.raises(RuntimeError, match="timed out after"):
            embedding.embed(["Test"])

    @patch("requests.post")
    def test_http_error_handling(self, mock_post):
        """Should raise RuntimeError on HTTP error."""
        settings = MagicMock()
        settings.embedding.base_url = "http://localhost:11434"
        settings.embedding.model = "nomic-embed-text"

        # Mock HTTP error
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = (
            requests.exceptions.HTTPError("404 Not Found")
        )
        mock_post.return_value = mock_response

        embedding = OllamaEmbedding(settings)

        with pytest.raises(RuntimeError, match="HTTP error"):
            embedding.embed(["Test"])

    @patch("requests.post")
    def test_missing_embedding_in_response(self, mock_post):
        """Should raise RuntimeError if response missing embedding."""
        settings = MagicMock()
        settings.embedding.base_url = "http://localhost:11434"
        settings.embedding.model = "nomic-embed-text"

        # Mock response without embedding field
        mock_response = Mock()
        mock_response.json.return_value = {"error": "Model not found"}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        embedding = OllamaEmbedding(settings)

        with pytest.raises(RuntimeError, match="No embedding returned"):
            embedding.embed(["Test"])

    @patch("requests.post")
    def test_embed_with_trace(self, mock_post):
        """Should record trace when trace context provided."""
        settings = MagicMock()
        settings.embedding.base_url = "http://localhost:11434"
        settings.embedding.model = "nomic-embed-text"

        # Mock API response
        mock_response = Mock()
        mock_response.json.return_value = {"embedding": [0.1, 0.2, 0.3]}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        # Mock trace context
        trace = MagicMock()

        embedding = OllamaEmbedding(settings)
        embedding.embed(["Test"], trace=trace)

        # Verify trace was recorded
        trace.record_stage.assert_called_once()
        call_args = trace.record_stage.call_args
        assert call_args[1]["stage_name"] == "ollama_embedding"
        assert call_args[1]["data"]["provider"] == "ollama"
        assert call_args[1]["data"]["model"] == "nomic-embed-text"

    def test_get_model_name(self):
        """Should return configured model name."""
        settings = MagicMock()
        settings.embedding.base_url = "http://localhost:11434"
        settings.embedding.model = "custom-model"

        embedding = OllamaEmbedding(settings)

        assert embedding.get_model_name() == "custom-model"

    def test_get_dimension_known_model(self):
        """Should return correct dimension for known models."""
        settings = MagicMock()
        settings.embedding.base_url = "http://localhost:11434"

        # Test nomic-embed-text
        settings.embedding.model = "nomic-embed-text"
        embedding = OllamaEmbedding(settings)
        assert embedding.get_dimension() == 768

        # Test mxbai-embed-large
        settings.embedding.model = "mxbai-embed-large"
        embedding = OllamaEmbedding(settings)
        assert embedding.get_dimension() == 1024

        # Test all-minilm
        settings.embedding.model = "all-minilm"
        embedding = OllamaEmbedding(settings)
        assert embedding.get_dimension() == 384

    def test_get_dimension_unknown_model(self):
        """Should return default dimension for unknown models."""
        settings = MagicMock()
        settings.embedding.base_url = "http://localhost:11434"
        settings.embedding.model = "unknown-model"

        embedding = OllamaEmbedding(settings)

        # Default to nomic-embed-text dimension
        assert embedding.get_dimension() == 768

    def test_factory_integration(self):
        """Should be creatable via EmbeddingFactory."""
        from src.libs.embedding.embedding_factory import EmbeddingFactory

        settings = MagicMock()
        settings.embedding.provider = "ollama"
        settings.embedding.base_url = "http://localhost:11434"
        settings.embedding.model = "nomic-embed-text"

        embedding = EmbeddingFactory.create(settings)

        assert isinstance(embedding, OllamaEmbedding)
        assert embedding.model == "nomic-embed-text"
