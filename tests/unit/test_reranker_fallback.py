"""Reranker 单元测试。"""

import pytest
from unittest.mock import Mock, MagicMock

from src.core.query_engine.reranker import Reranker
from src.core.settings import RerankSettings
from src.core.types import RetrievalResult


class MockSettings:
    """Mock settings for testing.

    ``rerank`` 用真实的 ``RerankSettings`` dataclass 而非 ``Mock()``:Core 层
    的 ``Reranker`` 现在真的会读 ``top_m`` / ``timeout_sec`` / ``batch_size``
    (此前 ``top_m`` 是个从未被消费的死配置),裸 Mock 会让这些字段返回 Mock
    对象。用真实 dataclass 还有个额外好处 —— 测试再也无法与真实配置结构
    漂移,而「测试与真实装配脱节」正是本变更要修的那类问题。

    本次只替换这个 stub 的构造方式,**不改任何断言**。
    """
    rerank = RerankSettings(backend="none")


class TestReranker:
    """Reranker 类的单元测试。"""

    def setup_method(self):
        """Ensure providers are registered before each test."""
        # Re-register providers in case other tests cleared the registry
        from src.libs.reranker.reranker_factory import _register_builtin_providers
        _register_builtin_providers()

    def test_reranker_with_none_backend(self):
        """测试 None reranker (passthrough)。"""
        settings = MockSettings()
        reranker = Reranker(settings)

        candidates = [
            RetrievalResult(chunk_id="1", score=0.9, text="text1", metadata={}),
            RetrievalResult(chunk_id="2", score=0.8, text="text2", metadata={}),
        ]

        results = reranker.rerank("query", candidates)

        assert len(results) == 2
        assert results[0].chunk_id == "1"
        assert results[0].metadata.get("reranked") is True

    def test_reranker_empty_candidates(self):
        """测试空候选列表。"""
        settings = MockSettings()
        reranker = Reranker(settings)

        results = reranker.rerank("query", [])

        assert results == []

    def test_reranker_empty_query(self):
        """测试空查询返回原始顺序。"""
        settings = MockSettings()
        reranker = Reranker(settings)

        candidates = [
            RetrievalResult(chunk_id="1", score=0.9, text="text1", metadata={}),
            RetrievalResult(chunk_id="2", score=0.8, text="text2", metadata={}),
        ]

        results = reranker.rerank("", candidates)

        assert len(results) == 2

    def test_reranker_fallback_on_error(self):
        """测试错误时的回退行为。"""
        settings = MockSettings()

        mock_backend = Mock()
        mock_backend.rerank.side_effect = RuntimeError("Reranker failed")

        reranker = Reranker(settings, reranker_backend=mock_backend)

        candidates = [
            RetrievalResult(chunk_id="1", score=0.9, text="text1", metadata={}),
            RetrievalResult(chunk_id="2", score=0.8, text="text2", metadata={}),
        ]

        results = reranker.rerank("query", candidates)

        assert len(results) == 2
        assert results[0].metadata.get("rerank_fallback") is True
        assert results[1].metadata.get("rerank_fallback") is True

    def test_reranker_success(self):
        """测试成功的重排序。"""
        settings = MockSettings()

        mock_backend = Mock()
        mock_backend.rerank.return_value = [
            {"id": "2", "text": "text2", "score": 0.9, "_retrieval_result": None},
            {"id": "1", "text": "text1", "score": 0.8, "_retrieval_result": None},
        ]

        reranker = Reranker(settings, reranker_backend=mock_backend)

        candidates = [
            RetrievalResult(chunk_id="1", score=0.9, text="text1", metadata={}),
            RetrievalResult(chunk_id="2", score=0.8, text="text2", metadata={}),
        ]

        results = reranker.rerank("query", candidates)

        assert len(results) == 2
        assert results[0].metadata.get("reranked") is True

    def test_reranker_with_retrieval_result_reference(self):
        """测试保留原始 RetrievalResult 引用。"""
        settings = MockSettings()

        candidates = [
            RetrievalResult(chunk_id="1", score=0.9, text="text1", metadata={}),
            RetrievalResult(chunk_id="2", score=0.8, text="text2", metadata={}),
        ]

        mock_backend = Mock()
        mock_backend.rerank.return_value = [
            {"id": "1", "text": "text1", "score": 0.9, "_retrieval_result": candidates[0]},
            {"id": "2", "text": "text2", "score": 0.8, "_retrieval_result": candidates[1]},
        ]

        reranker = Reranker(settings, reranker_backend=mock_backend)

        results = reranker.rerank("query", candidates)

        assert len(results) == 2
        assert results[0].metadata.get("reranked") is True
        assert results[0].metadata.get("rerank_fallback") is None
