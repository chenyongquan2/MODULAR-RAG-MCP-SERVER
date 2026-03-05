"""Unit tests for SparseRetriever."""

import pytest
from unittest.mock import MagicMock, patch

from src.core.query_engine.sparse_retriever import SparseRetriever
from src.core.types import RetrievalResult


class MockSettings:
    """Mock settings for testing."""

    def __init__(self):
        self.vector_store = MagicMock()
        self.vector_store.collection_name = "test_collection"
        self.vector_store.bm25_index_path = "data/db/bm25"
        self.vector_store.persist_path = "data/db/chroma"
        self.retrieval = MagicMock()
        self.retrieval.top_k_sparse = 10


class MockBM25Indexer:
    """Mock BM25 indexer for testing."""

    def __init__(self, query_results=None):
        self._query_results = query_results or []
        self._stats = {"total_documents": 10, "total_terms": 100}
        self._last_top_k = None

    def query(self, keywords, top_k=10):
        self._last_top_k = top_k
        return self._query_results[:top_k]

    @property
    def stats(self):
        return self._stats


class MockVectorStore:
    """Mock vector store for testing."""

    def __init__(self, get_by_ids_results=None):
        self._get_by_ids_results = get_by_ids_results or []
        self._backend_name = "mock"

    def get_by_ids(self, ids, trace=None, **kwargs):
        return self._get_by_ids_results

    def get_backend_name(self):
        return self._backend_name


class TestSparseRetriever:
    """Tests for SparseRetriever class."""

    def test_init_with_dependencies(self):
        """Test initialization with injected dependencies."""
        settings = MockSettings()
        mock_bm25 = MockBM25Indexer()
        mock_store = MockVectorStore()

        retriever = SparseRetriever(
            settings=settings,
            bm25_indexer=mock_bm25,
            vector_store=mock_store,
            top_k=5,
        )

        assert retriever._top_k == 5
        assert retriever._bm25_indexer == mock_bm25
        assert retriever._vector_store == mock_store

    def test_init_with_custom_top_k(self):
        """Test initialization with custom top_k override."""
        settings = MockSettings()
        settings.retrieval.top_k_sparse = 20

        mock_bm25 = MockBM25Indexer()
        mock_store = MockVectorStore()

        retriever = SparseRetriever(
            settings=settings,
            bm25_indexer=mock_bm25,
            vector_store=mock_store,
        )

        assert retriever._top_k == 20

    def test_init_creates_bm25_indexer_if_not_provided(self):
        """Test that BM25 indexer is created if not provided."""
        settings = MockSettings()

        with patch("src.ingestion.storage.bm25_indexer.BM25Indexer") as MockIndexer:
            mock_indexer = MagicMock()
            mock_indexer.load.return_value = True
            MockIndexer.return_value = mock_indexer

            with patch("src.libs.vector_store.vector_store_factory.VectorStoreFactory"):
                retriever = SparseRetriever(settings=settings)

                MockIndexer.assert_called_once()
                mock_indexer.load.assert_called_once()

    def test_retrieve_empty_keywords_raises_error(self):
        """Test that empty keywords raises ValueError."""
        settings = MockSettings()
        mock_bm25 = MockBM25Indexer()
        mock_store = MockVectorStore()

        retriever = SparseRetriever(
            settings=settings,
            bm25_indexer=mock_bm25,
            vector_store=mock_store,
        )

        with pytest.raises(ValueError, match="Keywords list cannot be empty"):
            retriever.retrieve([])

    def test_retrieve_invalid_top_k_raises_error(self):
        """Test that invalid top_k raises ValueError."""
        settings = MockSettings()
        mock_bm25 = MockBM25Indexer()
        mock_store = MockVectorStore()

        retriever = SparseRetriever(
            settings=settings,
            bm25_indexer=mock_bm25,
            vector_store=mock_store,
        )

        with pytest.raises(ValueError, match="top_k must be a positive integer"):
            retriever.retrieve(["test"], top_k=0)

    def test_retrieve_no_bm25_results(self):
        """Test that empty BM25 results return empty list."""
        settings = MockSettings()
        mock_bm25 = MockBM25Indexer(query_results=[])
        mock_store = MockVectorStore()

        retriever = SparseRetriever(
            settings=settings,
            bm25_indexer=mock_bm25,
            vector_store=mock_store,
        )

        results = retriever.retrieve(["test"])
        assert results == []

    def test_retrieve_success(self):
        """Test successful sparse retrieval."""
        settings = MockSettings()
        bm25_results = [
            {"chunk_id": "chunk_1", "score": 1.5},
            {"chunk_id": "chunk_2", "score": 1.0},
        ]
        mock_bm25 = MockBM25Indexer(query_results=bm25_results)

        vector_store_results = [
            {"id": "chunk_1", "text": "Hello world", "metadata": {"source": "doc1"}},
            {"id": "chunk_2", "text": "Test text", "metadata": {"source": "doc2"}},
        ]
        mock_store = MockVectorStore(get_by_ids_results=vector_store_results)

        retriever = SparseRetriever(
            settings=settings,
            bm25_indexer=mock_bm25,
            vector_store=mock_store,
        )

        results = retriever.retrieve(["hello", "world"])

        assert len(results) == 2
        assert results[0].chunk_id == "chunk_1"
        assert results[0].score == 1.5
        assert results[0].text == "Hello world"
        assert results[1].chunk_id == "chunk_2"
        assert results[1].score == 1.0

    def test_retrieve_maintains_bm25_order(self):
        """Test that results maintain BM25 ranking order."""
        settings = MockSettings()
        bm25_results = [
            {"chunk_id": "chunk_a", "score": 3.0},
            {"chunk_id": "chunk_b", "score": 2.0},
            {"chunk_id": "chunk_c", "score": 1.0},
        ]
        mock_bm25 = MockBM25Indexer(query_results=bm25_results)

        vector_store_results = [
            {"id": "chunk_a", "text": "Text A", "metadata": {}},
            {"id": "chunk_b", "text": "Text B", "metadata": {}},
            {"id": "chunk_c", "text": "Text C", "metadata": {}},
        ]
        mock_store = MockVectorStore(get_by_ids_results=vector_store_results)

        retriever = SparseRetriever(
            settings=settings,
            bm25_indexer=mock_bm25,
            vector_store=mock_store,
        )

        results = retriever.retrieve(["test"])

        assert results[0].chunk_id == "chunk_a"
        assert results[0].score == 3.0
        assert results[1].chunk_id == "chunk_b"
        assert results[1].score == 2.0
        assert results[2].chunk_id == "chunk_c"
        assert results[1].score == 2.0

    def test_retrieve_handles_missing_ids(self):
        """Test that retrieval handles missing IDs from vector store."""
        settings = MockSettings()
        bm25_results = [
            {"chunk_id": "chunk_1", "score": 1.5},
            {"chunk_id": "chunk_2", "score": 1.0},
            {"chunk_id": "chunk_3", "score": 0.5},
        ]
        mock_bm25 = MockBM25Indexer(query_results=bm25_results)

        vector_store_results = [
            {"id": "chunk_1", "text": "Text 1", "metadata": {}},
        ]
        mock_store = MockVectorStore(get_by_ids_results=vector_store_results)

        retriever = SparseRetriever(
            settings=settings,
            bm25_indexer=mock_bm25,
            vector_store=mock_store,
        )

        results = retriever.retrieve(["test"])

        assert len(results) == 1
        assert results[0].chunk_id == "chunk_1"

    def test_retrieve_with_custom_top_k(self):
        """Test retrieval with custom top_k parameter."""
        settings = MockSettings()
        settings.retrieval.top_k_sparse = 50

        bm25_results = [
            {"chunk_id": f"chunk_{i}", "score": float(10 - i)}
            for i in range(10)
        ]
        mock_bm25 = MockBM25Indexer(query_results=bm25_results)

        vector_store_results = [
            {"id": f"chunk_{i}", "text": f"Text {i}", "metadata": {}}
            for i in range(10)
        ]
        mock_store = MockVectorStore(get_by_ids_results=vector_store_results)

        retriever = SparseRetriever(
            settings=settings,
            bm25_indexer=mock_bm25,
            vector_store=mock_store,
        )

        results = retriever.retrieve(["test"], top_k=3)

        assert len(results) == 3
        assert retriever._top_k == 50

    def test_get_backend_name(self):
        """Test getting backend name."""
        settings = MockSettings()
        mock_bm25 = MockBM25Indexer()
        mock_store = MockVectorStore()
        mock_store._backend_name = "chromadb"

        retriever = SparseRetriever(
            settings=settings,
            bm25_indexer=mock_bm25,
            vector_store=mock_store,
        )

        assert retriever.get_backend_name() == "chromadb"

    def test_get_index_stats(self):
        """Test getting index statistics."""
        settings = MockSettings()
        mock_bm25 = MockBM25Indexer()
        mock_store = MockVectorStore()

        retriever = SparseRetriever(
            settings=settings,
            bm25_indexer=mock_bm25,
            vector_store=mock_store,
        )

        stats = retriever.get_index_stats()
        assert stats == {"total_documents": 10, "total_terms": 100}

    def test_retrieve_returns_retrieval_result_type(self):
        """Test that retrieve returns correct type."""
        settings = MockSettings()
        bm25_results = [{"chunk_id": "chunk_1", "score": 1.0}]
        mock_bm25 = MockBM25Indexer(query_results=bm25_results)

        vector_store_results = [{"id": "chunk_1", "text": "Test", "metadata": {}}]
        mock_store = MockVectorStore(get_by_ids_results=vector_store_results)

        retriever = SparseRetriever(
            settings=settings,
            bm25_indexer=mock_bm25,
            vector_store=mock_store,
        )

        results = retriever.retrieve(["test"])

        assert len(results) > 0
        assert isinstance(results[0], RetrievalResult)
        assert hasattr(results[0], "chunk_id")
        assert hasattr(results[0], "score")
        assert hasattr(results[0], "text")
        assert hasattr(results[0], "metadata")
