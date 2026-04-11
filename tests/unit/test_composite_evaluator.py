"""Unit tests for CompositeEvaluator."""

from __future__ import annotations

import pytest

from src.libs.evaluator.base_evaluator import BaseEvaluator
from src.observability.evaluation.composite_evaluator import CompositeEvaluator


class _StubEvaluatorA(BaseEvaluator):
    """Stub evaluator A."""

    def evaluate(
        self,
        query: str,
        retrieved_ids: list[str],
        golden_ids: list[str],
        trace=None,
        **kwargs,
    ) -> dict[str, float]:
        return {"hit_rate": 1.0}


class _StubEvaluatorB(BaseEvaluator):
    """Stub evaluator B."""

    def evaluate(
        self,
        query: str,
        retrieved_ids: list[str],
        golden_ids: list[str],
        trace=None,
        **kwargs,
    ) -> dict[str, float]:
        return {"faithfulness": 0.92}


class _FailingEvaluator(BaseEvaluator):
    """Stub evaluator that raises an exception."""

    def evaluate(
        self,
        query: str,
        retrieved_ids: list[str],
        golden_ids: list[str],
        trace=None,
        **kwargs,
    ) -> dict[str, float]:
        raise RuntimeError("boom")


def test_evaluate_merges_metrics_from_all_evaluators() -> None:
    """Composite evaluator should merge all child metrics."""
    evaluator = CompositeEvaluator([_StubEvaluatorA(), _StubEvaluatorB()])

    result = evaluator.evaluate(
        query="q",
        retrieved_ids=["chunk_1"],
        golden_ids=["chunk_1"],
    )

    assert result == {"hit_rate": 1.0, "faithfulness": 0.92}


def test_evaluate_raises_runtime_error_on_child_failure() -> None:
    """Composite evaluator should wrap child failures as RuntimeError."""
    evaluator = CompositeEvaluator([_StubEvaluatorA(), _FailingEvaluator()])

    with pytest.raises(RuntimeError) as exc_info:
        evaluator.evaluate(
            query="q",
            retrieved_ids=["chunk_1"],
            golden_ids=["chunk_1"],
        )

    assert "Composite evaluator failed on" in str(exc_info.value)


def test_init_with_empty_evaluator_list_raises_value_error() -> None:
    """Composite evaluator requires at least one child evaluator."""
    with pytest.raises(ValueError) as exc_info:
        CompositeEvaluator([])

    assert "at least one evaluator instance" in str(exc_info.value)
