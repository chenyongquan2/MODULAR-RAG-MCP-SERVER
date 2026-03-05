"""HybridSearch 集成测试。"""

import pytest
from unittest.mock import Mock, MagicMock

from src.core.query_engine.fusion import Fusion, HybridSearch
from src.core.query_engine.query_processor import QueryProcessor
from src.core.types import RetrievalResult


class MockDenseRetriever:
    """Mock DenseRetriever for testing."""

    def __init__(self, results=None, error=None):
        self._results = results or []
        self._error = error

    def retrieve(self, query, top_k=20, filters=None, trace=None):
        if self._error:
            raise self._error
        return self._results


class MockSparseRetriever:
    """Mock SparseRetriever for testing."""

    def __init__(self, results=None, error=None):
        self._results = results or []
        self._error = error

    def retrieve(self, keywords, top_k=20, trace=None):
        if self._error:
            raise self._error
        return self._results


class MockReranker:
    """Mock Reranker for testing."""

    def __init__(self, results=None):
        self._results = results

    def rerank(self, query, candidates, trace=None):
        if self._results is None:
            return candidates
        return self._results


class TestHybridSearch:
    """HybridSearch 集成测试。"""

    def test_search_basic(self):
        """测试基本搜索功能。"""
        dense_results = [
            RetrievalResult(chunk_id="1", score=0.9, text="text1", metadata={"source": "dense"}),
            RetrievalResult(chunk_id="2", score=0.8, text="text2", metadata={"source": "dense"}),
        ]
        sparse_results = [
            RetrievalResult(chunk_id="2", score=0.7, text="text2", metadata={"source": "sparse"}),
            RetrievalResult(chunk_id="3", score=0.6, text="text3", metadata={"source": "sparse"}),
        ]

        dense_retriever = MockDenseRetriever(dense_results)
        sparse_retriever = MockSparseRetriever(sparse_results)
        fusion = Fusion()
        reranker = MockReranker()

        hybrid = HybridSearch(
            settings=None,
            dense_retriever=dense_retriever,
            sparse_retriever=sparse_retriever,
            fusion=fusion,
            reranker=reranker,
        )

        results = hybrid.search("test query", top_k=3)

        assert len(results) > 0

    def test_search_with_filters(self):
        """测试带过滤条件的搜索。"""
        dense_results = [
            RetrievalResult(chunk_id="1", score=0.9, text="text1", metadata={"collection": "docs"}),
            RetrievalResult(chunk_id="2", score=0.8, text="text2", metadata={"collection": "other"}),
        ]

        dense_retriever = MockDenseRetriever(dense_results)
        sparse_retriever = MockSparseRetriever([])
        fusion = Fusion()
        reranker = MockReranker()

        hybrid = HybridSearch(
            settings=None,
            dense_retriever=dense_retriever,
            sparse_retriever=sparse_retriever,
            fusion=fusion,
            reranker=reranker,
        )

        results = hybrid.search("test query", top_k=10, filters={"collection": "docs"})

        assert all(r.metadata.get("collection") == "docs" for r in results)

    def test_search_dense_fallback(self):
        """测试 Dense 失败时的回退。"""
        dense_retriever = MockDenseRetriever(error=RuntimeError("Dense failed"))
        sparse_results = [
            RetrievalResult(chunk_id="1", score=0.9, text="text1", metadata={}),
        ]
        sparse_retriever = MockSparseRetriever(sparse_results)
        fusion = Fusion()
        reranker = MockReranker()

        hybrid = HybridSearch(
            settings=None,
            dense_retriever=dense_retriever,
            sparse_retriever=sparse_retriever,
            fusion=fusion,
            reranker=reranker,
        )

        results = hybrid.search("test query", top_k=5)

        assert len(results) > 0
        assert results[0].chunk_id == "1"

    def test_search_sparse_fallback(self):
        """测试 Sparse 失败时的回退。"""
        dense_results = [
            RetrievalResult(chunk_id="1", score=0.9, text="text1", metadata={}),
        ]
        dense_retriever = MockDenseRetriever(dense_results)
        sparse_retriever = MockSparseRetriever(error=RuntimeError("Sparse failed"))
        fusion = Fusion()
        reranker = MockReranker()

        hybrid = HybridSearch(
            settings=None,
            dense_retriever=dense_retriever,
            sparse_retriever=sparse_retriever,
            fusion=fusion,
            reranker=reranker,
        )

        results = hybrid.search("test query", top_k=5)

        assert len(results) > 0
        assert results[0].chunk_id == "1"

    def test_search_both_fail(self):
        """测试两路都失败时返回空列表。"""
        dense_retriever = MockDenseRetriever(error=RuntimeError("Dense failed"))
        sparse_retriever = MockSparseRetriever(error=RuntimeError("Sparse failed"))
        fusion = Fusion()
        reranker = MockReranker()

        hybrid = HybridSearch(
            settings=None,
            dense_retriever=dense_retriever,
            sparse_retriever=sparse_retriever,
            fusion=fusion,
            reranker=reranker,
        )

        results = hybrid.search("test query", top_k=5)

        assert results == []

    def test_search_empty_query(self):
        """测试空查询抛出异常。"""
        hybrid = HybridSearch(
            settings=None,
            dense_retriever=MockDenseRetriever(),
            sparse_retriever=MockSparseRetriever(),
            reranker=MockReranker(),
        )

        with pytest.raises(ValueError, match="Query cannot be empty"):
            hybrid.search("")

    def test_search_invalid_top_k(self):
        """测试无效的 top_k。"""
        hybrid = HybridSearch(
            settings=None,
            dense_retriever=MockDenseRetriever(),
            sparse_retriever=MockSparseRetriever(),
            reranker=MockReranker(),
        )

        with pytest.raises(ValueError, match="top_k must be a positive integer"):
            hybrid.search("test", top_k=0)
