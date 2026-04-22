"""Unit tests for RagasEvaluator."""

from __future__ import annotations

import pytest

from src.core.settings import EvaluationSettings, Settings
from src.observability.evaluation.ragas_evaluator import RagasEvaluator


@pytest.fixture
def mock_settings_ragas() -> Settings:
    """Create a minimal Settings object for ragas evaluator tests."""
    return Settings(
        llm=None,
        embedding=None,
        vision_llm=None,
        vector_store=None,
        evaluation=EvaluationSettings(backends=["ragas"]),
    )


class TestRagasEvaluator:
    """Test suite for RagasEvaluator."""

    def test_evaluate_returns_mock_metrics(self, mock_settings_ragas: Settings) -> None:
        """Evaluator should return normalized metrics in mock mode."""
        evaluator = RagasEvaluator(settings=mock_settings_ragas)

        metrics = evaluator.evaluate(
            query="what is rag?",
            retrieved_ids=["chunk_1", "chunk_2"],
            golden_ids=["chunk_2"],
            mock_metrics={
                "faithfulness": 0.91,
                "answer_relevancy": 0.87,
                "context_precision": 0.93,
            },
        )

        assert metrics["faithfulness"] == 0.91
        assert metrics["answer_relevancy"] == 0.87
        assert metrics["context_precision"] == 0.93

    def test_evaluate_supports_answer_relevance_alias(
        self, mock_settings_ragas: Settings
    ) -> None:
        """`answer_relevance` key should be normalized to answer_relevancy."""
        evaluator = RagasEvaluator(settings=mock_settings_ragas)

        metrics = evaluator.evaluate(
            query="what is rag?",
            retrieved_ids=["chunk_1", "chunk_2"],
            golden_ids=["chunk_2"],
            mock_metrics={
                "faithfulness": 0.9,
                "answer_relevance": 0.8,
                "context_precision": 0.7,
            },
        )

        assert metrics["answer_relevancy"] == 0.8

    def test_empty_retrieved_ids_raises_error(
        self, mock_settings_ragas: Settings
    ) -> None:
        """Empty retrieved_ids should raise ValueError."""
        evaluator = RagasEvaluator(settings=mock_settings_ragas)

        with pytest.raises(ValueError) as exc_info:
            evaluator.evaluate(
                query="test",
                retrieved_ids=[],
                golden_ids=["chunk_1"],
                mock_metrics={},
            )

        assert "retrieved_ids cannot be empty" in str(exc_info.value)

    def test_empty_golden_ids_raises_error(self, mock_settings_ragas: Settings) -> None:
        """Empty golden_ids should raise ValueError."""
        evaluator = RagasEvaluator(settings=mock_settings_ragas)

        with pytest.raises(ValueError) as exc_info:
            evaluator.evaluate(
                query="test",
                retrieved_ids=["chunk_1"],
                golden_ids=[],
                mock_metrics={},
            )

        assert "golden_ids cannot be empty" in str(exc_info.value)

    def test_missing_ragas_dependency_raises_import_error(
        self, mock_settings_ragas: Settings
    ) -> None:
        """Real mode should raise clear ImportError when ragas is not installed.

        注意：必须传入真实文本 contexts / ground_truth / answer 才能到达 import
        路径；空值会在校验阶段先抛 ValueError，这是最佳实践要求的显式报错。
        """
        evaluator = RagasEvaluator(settings=mock_settings_ragas)

        with pytest.raises(ImportError) as exc_info:
            evaluator.evaluate(
                query="what is rag?",
                retrieved_ids=["chunk_1"],
                golden_ids=["chunk_1"],
                answer="RAG stands for Retrieval-Augmented Generation.",
                contexts=["RAG combines retrieval with generation to ground LLM outputs."],
                ground_truth="RAG = Retrieval-Augmented Generation.",
            )

        assert "pip install ragas datasets" in str(exc_info.value)

    def test_missing_contexts_raises_value_error(
        self, mock_settings_ragas: Settings
    ) -> None:
        """真实模式下缺失 contexts 应抛 ValueError，而不是悄悄用 chunk ID 顶替。"""
        evaluator = RagasEvaluator(settings=mock_settings_ragas)

        with pytest.raises(ValueError) as exc_info:
            evaluator.evaluate(
                query="what is rag?",
                retrieved_ids=["chunk_1"],
                golden_ids=["chunk_1"],
                answer="irrelevant",
                ground_truth="irrelevant",
                # contexts 缺失
            )

        assert "contexts" in str(exc_info.value).lower()

    def test_missing_ground_truth_raises_value_error(
        self, mock_settings_ragas: Settings
    ) -> None:
        """真实模式下缺失 ground_truth 应抛 ValueError。"""
        evaluator = RagasEvaluator(settings=mock_settings_ragas)

        with pytest.raises(ValueError) as exc_info:
            evaluator.evaluate(
                query="what is rag?",
                retrieved_ids=["chunk_1"],
                golden_ids=["chunk_1"],
                answer="irrelevant",
                contexts=["some real retrieved text"],
                # ground_truth 缺失
            )

        assert "ground_truth" in str(exc_info.value)

    def test_contexts_must_be_strings_not_ids(
        self, mock_settings_ragas: Settings
    ) -> None:
        """contexts 中包含非字符串或空串应报错，防止传 chunk ID。"""
        evaluator = RagasEvaluator(settings=mock_settings_ragas)

        with pytest.raises(ValueError) as exc_info:
            evaluator.evaluate(
                query="what is rag?",
                retrieved_ids=["chunk_1"],
                golden_ids=["chunk_1"],
                answer="irrelevant",
                contexts=["", "   "],  # 空串不合法
                ground_truth="irrelevant",
            )

        assert "non-empty" in str(exc_info.value).lower()

    def test_mock_mode_normalizes_context_recall(
        self, mock_settings_ragas: Settings
    ) -> None:
        """mock 模式应返回包含 context_recall 的完整四指标。"""
        evaluator = RagasEvaluator(settings=mock_settings_ragas)

        metrics = evaluator.evaluate(
            query="what is rag?",
            retrieved_ids=["chunk_1"],
            golden_ids=["chunk_1"],
            mock_metrics={
                "faithfulness": 0.9,
                "answer_relevancy": 0.85,
                "context_precision": 0.8,
                "context_recall": 0.75,
            },
        )

        assert metrics["context_recall"] == 0.75
        assert set(metrics.keys()) == {
            "faithfulness",
            "answer_relevancy",
            "context_precision",
            "context_recall",
        }

    def test_normalize_metrics_defaults_context_recall_to_zero(
        self, mock_settings_ragas: Settings
    ) -> None:
        """mock_metrics 不含 context_recall 时，_normalize_metrics 应返回 0.0。"""
        evaluator = RagasEvaluator(settings=mock_settings_ragas)
        metrics = evaluator.evaluate(
            query="q",
            retrieved_ids=["c1"],
            golden_ids=["c1"],
            mock_metrics={"faithfulness": 0.9, "answer_relevancy": 0.8, "context_precision": 0.7},
        )
        assert "context_recall" in metrics
        assert metrics["context_recall"] == pytest.approx(0.0)

    def test_zero_metrics_returns_all_four_keys(
        self, mock_settings_ragas: Settings
    ) -> None:
        """zero_metrics() 应返回 Ragas 四指标的零值模板。"""
        evaluator = RagasEvaluator(settings=mock_settings_ragas)
        zero = evaluator.zero_metrics()
        assert set(zero.keys()) == {
            "faithfulness", "answer_relevancy", "context_precision", "context_recall"
        }
        assert all(v == 0.0 for v in zero.values())
