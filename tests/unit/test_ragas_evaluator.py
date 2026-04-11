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
        """Real mode should raise clear ImportError when ragas is not installed."""
        evaluator = RagasEvaluator(settings=mock_settings_ragas)

        with pytest.raises(ImportError) as exc_info:
            evaluator.evaluate(
                query="what is rag?",
                retrieved_ids=["chunk_1"],
                golden_ids=["chunk_1"],
            )

        assert "pip install ragas datasets" in str(exc_info.value)
