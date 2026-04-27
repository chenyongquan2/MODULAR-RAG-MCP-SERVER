"""Unit tests for backfill_chunk_ids semantic match logic (T025, refs FR-007).

测试范围:
- 阈值过滤(score < threshold 的 chunk 被 drop)
- 空 ground_truth 跳过(返回空 list)
- 多 case 的总匹配率统计
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# 加载 scripts/backfill_chunk_ids.py 作为模块
_spec = importlib.util.spec_from_file_location(
    "backfill_module",
    Path(__file__).parent.parent.parent / "scripts" / "backfill_chunk_ids.py",
)
backfill_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backfill_module)


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helper to mock the embed + query pipeline
# ---------------------------------------------------------------------------


def _make_factories(
    embed_return: list[list[float]],
    query_return: list[dict],
):
    embedding = MagicMock()
    embedding.embed.return_value = embed_return
    vector_store = MagicMock()
    vector_store.query.return_value = query_return
    return embedding, vector_store


# ---------------------------------------------------------------------------
# _backfill_one
# ---------------------------------------------------------------------------


class TestBackfillOne:
    def test_threshold_drops_low_score_chunks(self) -> None:
        """score < threshold 的 chunk 应被过滤。"""
        embedding, store = _make_factories(
            embed_return=[[0.1, 0.2, 0.3]],
            query_return=[
                {"id": "a", "score": 0.85, "text": "x", "metadata": {}},
                {"id": "b", "score": 0.55, "text": "y", "metadata": {}},  # 低于 0.6
                {"id": "c", "score": 0.62, "text": "z", "metadata": {}},
            ],
        )
        ids, scores = backfill_module._backfill_one(
            ground_truth="some text",
            embedding_factory_instance=embedding,
            vector_store=store,
            collection="default",
            top_k=3,
            threshold=0.6,
        )
        assert ids == ["a", "c"]
        assert scores == [0.85, 0.62]
        # 验证调用路径
        embedding.embed.assert_called_once_with(["some text"])
        store.query.assert_called_once()

    def test_empty_ground_truth_returns_empty(self) -> None:
        embedding, store = _make_factories(embed_return=[[0.1]], query_return=[])
        ids, scores = backfill_module._backfill_one(
            ground_truth="",
            embedding_factory_instance=embedding,
            vector_store=store,
            collection="default",
            top_k=5,
            threshold=0.6,
        )
        assert ids == []
        assert scores == []
        # 不应触发 embed
        embedding.embed.assert_not_called()

    def test_whitespace_only_ground_truth_returns_empty(self) -> None:
        embedding, store = _make_factories(embed_return=[[0.1]], query_return=[])
        ids, _ = backfill_module._backfill_one(
            ground_truth="   \n  ",
            embedding_factory_instance=embedding,
            vector_store=store,
            collection="default",
            top_k=5,
            threshold=0.6,
        )
        assert ids == []
        embedding.embed.assert_not_called()

    def test_chunk_id_alias_chunk_id(self) -> None:
        """支持 'chunk_id' 字段名(部分 vector store 后端用这个 key)。"""
        embedding, store = _make_factories(
            embed_return=[[0.0]],
            query_return=[
                {"chunk_id": "x1", "score": 0.95, "text": "x", "metadata": {}},
            ],
        )
        ids, _ = backfill_module._backfill_one(
            ground_truth="text",
            embedding_factory_instance=embedding,
            vector_store=store,
            collection="default",
            top_k=1,
            threshold=0.5,
        )
        assert ids == ["x1"]

    def test_all_chunks_below_threshold_returns_empty(self) -> None:
        """全部 chunk 都 < threshold → 空 list,不报错。"""
        embedding, store = _make_factories(
            embed_return=[[0.0]],
            query_return=[
                {"id": "a", "score": 0.30, "text": "x", "metadata": {}},
                {"id": "b", "score": 0.20, "text": "y", "metadata": {}},
            ],
        )
        ids, scores = backfill_module._backfill_one(
            ground_truth="text",
            embedding_factory_instance=embedding,
            vector_store=store,
            collection="default",
            top_k=2,
            threshold=0.5,
        )
        assert ids == []
        assert scores == []
