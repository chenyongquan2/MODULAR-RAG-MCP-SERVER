"""Unit tests for DenseRetriever."""

from unittest.mock import MagicMock, patch
import pytest

from src.core.query_engine.dense_retriever import DenseRetriever
from src.core.types import RetrievalResult


class MockSettings:
    """Mock settings for testing."""

    def __init__(self):
        self.embedding = MagicMock()
        self.embedding.provider = "openai"
        self.embedding.model = "text-embedding-3-small"
        self.retrieval = MagicMock()
        self.retrieval.top_k_dense = 20
        self.vector_store = MagicMock()
        self.vector_store.backend = "chroma"
        self.vector_store.persist_path = "./data/db/chroma"


class TestDenseRetriever:
    """Test cases for DenseRetriever class."""

    def test_init_with_dependency_injection(self):
        """Test initialization with dependency injection."""
        settings = MockSettings()
        mock_embedding = MagicMock()
        mock_vector_store = MagicMock()

        retriever = DenseRetriever(
            settings=settings,
            embedding_client=mock_embedding,
            vector_store=mock_vector_store,
            top_k=10,
        )

        assert retriever._embedding_client is mock_embedding
        assert retriever._vector_store is mock_vector_store
        assert retriever._top_k == 10

    def test_init_with_factory_creation(self):
        """Test initialization with factory creation."""
        settings = MockSettings()

        with patch("src.libs.embedding.embedding_factory.EmbeddingFactory.create") as mock_emb, \
             patch("src.libs.vector_store.vector_store_factory.VectorStoreFactory.create") as mock_vs:

            mock_emb.return_value = MagicMock()
            mock_vs.return_value = MagicMock()

            retriever = DenseRetriever(settings=settings)

            mock_emb.assert_called_once_with(settings)
            mock_vs.assert_called_once_with(settings)

    def test_init_with_default_top_k(self):
        """Test initialization uses default top_k from settings."""
        settings = MockSettings()
        settings.retrieval.top_k_dense = 30

        retriever = DenseRetriever(
            settings=settings,
            embedding_client=MagicMock(),
            vector_store=MagicMock(),
        )

        assert retriever._top_k == 30

    def test_init_with_none_settings_raises_error(self):
        """Test that None settings raises ValueError."""
        with pytest.raises(ValueError, match="Settings cannot be None"):
            DenseRetriever(settings=None)

    def test_retrieve_empty_query_raises_error(self):
        """Test that empty query raises ValueError."""
        settings = MockSettings()
        retriever = DenseRetriever(
            settings=settings,
            embedding_client=MagicMock(),
            vector_store=MagicMock(),
        )

        with pytest.raises(ValueError, match="Query cannot be empty"):
            retriever.retrieve("")

        with pytest.raises(ValueError, match="Query cannot be empty"):
            retriever.retrieve("   ")

        with pytest.raises(ValueError, match="Query cannot be empty"):
            retriever.retrieve(None)  # type: ignore

    def test_retrieve_invalid_top_k_raises_error(self):
        """Test that invalid top_k raises ValueError."""
        settings = MockSettings()
        retriever = DenseRetriever(
            settings=settings,
            embedding_client=MagicMock(),
            vector_store=MagicMock(),
            top_k=5,
        )

        with pytest.raises(ValueError, match="top_k must be a positive integer"):
            retriever.retrieve("test query", top_k=0)

        with pytest.raises(ValueError, match="top_k must be a positive integer"):
            retriever.retrieve("test query", top_k=-1)

    def test_retrieve_success(self):
        """Test successful retrieval."""
        settings = MockSettings()
        mock_embedding = MagicMock()
        mock_vector_store = MagicMock()

        # Mock embedding response
        mock_embedding.embed.return_value = [[0.1, 0.2, 0.3]]
        mock_embedding.get_model_name.return_value = "test-model"

        # Mock vector store response
        mock_vector_store.query.return_value = [
            {
                "id": "chunk_1",
                "score": 0.95,
                "text": "This is the first chunk",
                "metadata": {"source": "doc1"},
            },
            {
                "id": "chunk_2",
                "score": 0.85,
                "text": "This is the second chunk",
                "metadata": {"source": "doc2"},
            },
        ]

        retriever = DenseRetriever(
            settings=settings,
            embedding_client=mock_embedding,
            vector_store=mock_vector_store,
            top_k=10,
        )

        results = retriever.retrieve("test query", top_k=5, filters={"source": "doc1"})

        # Verify embedding was called
        mock_embedding.embed.assert_called_once()

        # Verify vector store was called
        mock_vector_store.query.assert_called_once()

        # Verify results
        assert len(results) == 2
        assert isinstance(results[0], RetrievalResult)
        assert results[0].chunk_id == "chunk_1"
        assert results[0].score == 0.95
        assert results[0].text == "This is the first chunk"
        assert results[0].metadata == {"source": "doc1"}
        assert results[1].chunk_id == "chunk_2"

    def test_retrieve_uses_instance_top_k_when_not_specified(self):
        """Test that instance top_k is used when not specified in retrieve."""
        settings = MockSettings()
        mock_embedding = MagicMock()
        mock_vector_store = MagicMock()

        mock_embedding.embed.return_value = [[0.1, 0.2, 0.3]]
        mock_vector_store.query.return_value = []

        retriever = DenseRetriever(
            settings=settings,
            embedding_client=mock_embedding,
            vector_store=mock_vector_store,
            top_k=15,
        )

        retriever.retrieve("test query")

        # Verify vector store was called with instance top_k
        call_args = mock_vector_store.query.call_args
        assert call_args.kwargs["top_k"] == 15

    def test_retrieve_override_top_k(self):
        """Test that top_k can be overridden in retrieve call."""
        settings = MockSettings()
        mock_embedding = MagicMock()
        mock_vector_store = MagicMock()

        mock_embedding.embed.return_value = [[0.1, 0.2, 0.3]]
        mock_vector_store.query.return_value = []

        retriever = DenseRetriever(
            settings=settings,
            embedding_client=mock_embedding,
            vector_store=mock_vector_store,
            top_k=15,
        )

        retriever.retrieve("test query", top_k=5)

        # Verify vector store was called with overridden top_k
        call_args = mock_vector_store.query.call_args
        assert call_args.kwargs["top_k"] == 5

    def test_retrieve_empty_results(self):
        """Test retrieval returns empty list when no results."""
        settings = MockSettings()
        mock_embedding = MagicMock()
        mock_vector_store = MagicMock()

        mock_embedding.embed.return_value = [[0.1, 0.2, 0.3]]
        mock_vector_store.query.return_value = []

        retriever = DenseRetriever(
            settings=settings,
            embedding_client=mock_embedding,
            vector_store=mock_vector_store,
        )

        results = retriever.retrieve("test query")

        assert results == []

    def test_retrieve_embedding_failure(self):
        """Test handling of embedding failure."""
        settings = MockSettings()
        mock_embedding = MagicMock()
        mock_vector_store = MagicMock()

        mock_embedding.embed.side_effect = RuntimeError("Embedding API failed")

        retriever = DenseRetriever(
            settings=settings,
            embedding_client=mock_embedding,
            vector_store=mock_vector_store,
        )

        with pytest.raises(RuntimeError, match="Dense retrieval failed"):
            retriever.retrieve("test query")

    def test_retrieve_empty_embedding_result(self):
        """Test handling of empty embedding result."""
        settings = MockSettings()
        mock_embedding = MagicMock()
        mock_vector_store = MagicMock()

        mock_embedding.embed.return_value = []

        retriever = DenseRetriever(
            settings=settings,
            embedding_client=mock_embedding,
            vector_store=mock_vector_store,
        )

        with pytest.raises(RuntimeError, match="Embedding client returned empty result"):
            retriever.retrieve("test query")

    def test_get_backend_name(self):
        """Test getting vector store backend name."""
        settings = MockSettings()
        mock_vector_store = MagicMock()
        mock_vector_store.get_backend_name.return_value = "chromadb"

        retriever = DenseRetriever(
            settings=settings,
            embedding_client=MagicMock(),
            vector_store=mock_vector_store,
        )

        assert retriever.get_backend_name() == "chromadb"

    def test_get_backend_name_fallback(self):
        """Test fallback when get_backend_name raises."""
        settings = MockSettings()
        mock_vector_store = MagicMock()
        mock_vector_store.get_backend_name.side_effect = Exception("Backend error")

        retriever = DenseRetriever(
            settings=settings,
            embedding_client=MagicMock(),
            vector_store=mock_vector_store,
        )

        assert retriever.get_backend_name() == "unknown"

    def test_get_embedding_model(self):
        """Test getting embedding model name."""
        settings = MockSettings()
        mock_embedding = MagicMock()
        mock_embedding.get_model_name.return_value = "text-embedding-3-small"

        retriever = DenseRetriever(
            settings=settings,
            embedding_client=mock_embedding,
            vector_store=MagicMock(),
        )

        assert retriever.get_embedding_model() == "text-embedding-3-small"

    def test_retrieve_with_trace(self):
        """Test that trace parameter is passed to embedding."""
        settings = MockSettings()
        mock_embedding = MagicMock()
        mock_vector_store = MagicMock()

        mock_embedding.embed.return_value = [[0.1, 0.2, 0.3]]
        mock_vector_store.query.return_value = []

        mock_trace = MagicMock()

        retriever = DenseRetriever(
            settings=settings,
            embedding_client=mock_embedding,
            vector_store=mock_vector_store,
        )

        retriever.retrieve("test query", trace=mock_trace)

        # Verify trace was passed to embed
        mock_embedding.embed.assert_called_once_with(["test query"], trace=mock_trace)

    def test_retrieve_query_stripped(self):
        """Test that query is stripped before embedding."""
        settings = MockSettings()
        mock_embedding = MagicMock()
        mock_vector_store = MagicMock()

        mock_embedding.embed.return_value = [[0.1, 0.2, 0.3]]
        mock_vector_store.query.return_value = []

        retriever = DenseRetriever(
            settings=settings,
            embedding_client=mock_embedding,
            vector_store=mock_vector_store,
        )

        retriever.retrieve("  test query  ")

        # Verify query was stripped
        mock_embedding.embed.assert_called_once_with(["test query"], trace=None)
