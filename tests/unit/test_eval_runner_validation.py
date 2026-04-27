"""Unit tests for EvalRunner FR-007 chunk_id 存在性校验 (T015).

测试范围 (refs spec FR-007):
- 全部 expected_chunk_ids 在 vector store 中存在 → run() 通过
- 任一 chunk_id 缺失 → 抛 ValueError 含 case index + 缺失 ID
- ``chunk_id_validation=False`` 时跳过校验(允许占位 ID)
- vector store 查询失败时降级为友好错误(指明 chunk_id_validation 可关闭)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.settings import (
    EmbeddingSettings,
    EvaluationSettings,
    LLMSettings,
    Settings,
    VectorStoreSettings,
    VisionLLMSettings,
)
from src.core.types import RetrievalResult
from src.libs.evaluator.base_evaluator import BaseEvaluator
from src.observability.evaluation.eval_runner import EvalRunner


pytestmark = pytest.mark.unit


class _StubHybridSearch:
    def search(self, query, top_k, filters=None):
        return [RetrievalResult(chunk_id="real_id_1", score=0.9, text="ctx", metadata={})]


class _StubEvaluator(BaseEvaluator):
    def evaluate(self, query, retrieved_ids, golden_ids, trace=None, **kwargs):
        return {"hit_rate": 1.0, "mrr": 1.0, "recall": 1.0, "ndcg": 1.0}

    def zero_metrics(self):
        return {"hit_rate": 0.0, "mrr": 0.0, "recall": 0.0, "ndcg": 0.0}


def _settings(tmp_path: Path, chunk_id_validation: bool) -> Settings:
    return Settings(
        llm=LLMSettings(provider="ollama", model="llama3"),
        embedding=EmbeddingSettings(provider="openai", model="text-embedding-3-small"),
        vision_llm=VisionLLMSettings(provider="azure", model="gpt-4o"),
        vector_store=VectorStoreSettings(backend="chroma"),
        evaluation=EvaluationSettings(
            backends=["custom"],
            chunk_id_validation=chunk_id_validation,
            report_archive_dir=str(tmp_path / "reports"),
            baseline_store_path=str(tmp_path / "baselines.json"),
        ),
    )


def _write_test_set(tmp_path: Path, chunk_ids: list[str]) -> Path:
    """构造一份测试金标 JSON,所有 case 都用同一组 chunk_ids。"""
    cases = [
        {
            "query": f"q{i}",
            "expected_chunk_ids": chunk_ids,
            "expected_sources": [],
            "ground_truth": "",
        }
        for i in range(2)
    ]
    test_set_path = tmp_path / "golden.json"
    test_set_path.write_text(
        json.dumps({"_schema_version": 1, "test_cases": cases}, ensure_ascii=False),
        encoding="utf-8",
    )
    return test_set_path


# ---------------------------------------------------------------------------
# Validation 通过路径
# ---------------------------------------------------------------------------


class TestChunkIdValidationPasses:
    def test_all_existing_ids_pass(self, tmp_path: Path) -> None:
        """全部 expected_chunk_ids 都在 vector store 中 → 评估正常进行。"""
        settings = _settings(tmp_path, chunk_id_validation=True)
        test_set = _write_test_set(tmp_path, chunk_ids=["c1", "c2"])

        # mock vector store: get_by_ids 返回都存在
        mock_store = MagicMock()
        mock_store.get_by_ids.return_value = [
            {"id": "c1", "text": "x", "metadata": {}},
            {"id": "c2", "text": "y", "metadata": {}},
        ]

        with patch(
            "src.libs.vector_store.vector_store_factory.VectorStoreFactory.create",
            return_value=mock_store,
        ):
            runner = EvalRunner(
                settings=settings,
                hybrid_search=_StubHybridSearch(),
                evaluator=_StubEvaluator(),
            )
            report = runner.run(test_set_path=str(test_set), archive=False)

        assert report.total_cases == 2
        # 校验确实调用了 get_by_ids
        mock_store.get_by_ids.assert_called_once()


# ---------------------------------------------------------------------------
# Validation 失败路径
# ---------------------------------------------------------------------------


class TestChunkIdValidationFails:
    def test_missing_id_raises_value_error_with_locator(self, tmp_path: Path) -> None:
        """任一 chunk_id 缺失 → ValueError,信息含 case index + 缺失 ID + 提示。"""
        settings = _settings(tmp_path, chunk_id_validation=True)
        test_set = _write_test_set(tmp_path, chunk_ids=["c1", "c_missing"])

        mock_store = MagicMock()
        # 只返回 c1 (c_missing 不存在)
        mock_store.get_by_ids.return_value = [
            {"id": "c1", "text": "x", "metadata": {}}
        ]

        with patch(
            "src.libs.vector_store.vector_store_factory.VectorStoreFactory.create",
            return_value=mock_store,
        ):
            runner = EvalRunner(
                settings=settings,
                hybrid_search=_StubHybridSearch(),
                evaluator=_StubEvaluator(),
            )

            with pytest.raises(ValueError) as exc_info:
                runner.run(test_set_path=str(test_set), archive=False)

        error_msg = str(exc_info.value)
        # 错误消息应包含定位信息
        assert "chunk_id missing" in error_msg
        assert "case[0]" in error_msg  # 第一个 case 第一个不存在的 chunk_id
        assert "c_missing" in error_msg
        assert "chunk_id_validation=false" in error_msg  # 提示如何跳过

    def test_vector_store_failure_yields_friendly_error(self, tmp_path: Path) -> None:
        """vector store 不可用时,错误消息提示用户如何关闭校验。"""
        settings = _settings(tmp_path, chunk_id_validation=True)
        test_set = _write_test_set(tmp_path, chunk_ids=["c1"])

        mock_store = MagicMock()
        mock_store.get_by_ids.side_effect = RuntimeError("chroma db unreachable")

        with patch(
            "src.libs.vector_store.vector_store_factory.VectorStoreFactory.create",
            return_value=mock_store,
        ):
            runner = EvalRunner(
                settings=settings,
                hybrid_search=_StubHybridSearch(),
                evaluator=_StubEvaluator(),
            )

            with pytest.raises(ValueError) as exc_info:
                runner.run(test_set_path=str(test_set), archive=False)

        error_msg = str(exc_info.value)
        assert "chunk_id_validation failed" in error_msg
        assert "chunk_id_validation=false" in error_msg


# ---------------------------------------------------------------------------
# Validation 跳过路径
# ---------------------------------------------------------------------------


class TestChunkIdValidationSkipped:
    def test_chunk_id_validation_false_skips_vector_store_query(
        self, tmp_path: Path
    ) -> None:
        """chunk_id_validation=False 时不应触发 vector store 查询(占位 ID 也通过)。"""
        settings = _settings(tmp_path, chunk_id_validation=False)
        test_set = _write_test_set(tmp_path, chunk_ids=["chunk_placeholder_001"])

        with patch(
            "src.libs.vector_store.vector_store_factory.VectorStoreFactory.create"
        ) as mock_factory_create:
            runner = EvalRunner(
                settings=settings,
                hybrid_search=_StubHybridSearch(),
                evaluator=_StubEvaluator(),
            )
            report = runner.run(test_set_path=str(test_set), archive=False)

        assert report.total_cases == 2
        # VectorStoreFactory.create 不应被调用(完全跳过)
        assert mock_factory_create.call_count == 0
