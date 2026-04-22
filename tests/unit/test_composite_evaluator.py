"""Unit tests for CompositeEvaluator."""

from __future__ import annotations

import pytest

from src.libs.evaluator.base_evaluator import BaseEvaluator
from src.observability.evaluation.composite_evaluator import (
    CompositeEvaluator,
    _class_name_to_prefix,
)


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

    def zero_metrics(self) -> dict[str, float]:
        return {"hit_rate": 0.0}


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

    def zero_metrics(self) -> dict[str, float]:
        return {"faithfulness": 0.0}


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


def test_evaluate_merges_metrics_with_namespace_prefix() -> None:
    """CompositeEvaluator 合并指标时应添加评估器名称前缀，防止 key 冲突。"""
    evaluator = CompositeEvaluator([_StubEvaluatorA(), _StubEvaluatorB()])

    result = evaluator.evaluate(
        query="q",
        retrieved_ids=["chunk_1"],
        golden_ids=["chunk_1"],
    )

    # key 格式为 <snake_prefix>__<metric_name>
    assert result["_stub_evaluator_a__hit_rate"] == pytest.approx(1.0)
    assert result["_stub_evaluator_b__faithfulness"] == pytest.approx(0.92)
    assert len(result) == 2


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


def test_collision_keys_preserved_via_prefix() -> None:
    """两个评估器返回相同 metric name 时，前缀保证两者都保留。"""

    class _AlphaEvaluator(BaseEvaluator):
        def evaluate(self, query, retrieved_ids, golden_ids, trace=None, **kw):
            return {"hit_rate": 0.9}

    class _BetaEvaluator(BaseEvaluator):
        def evaluate(self, query, retrieved_ids, golden_ids, trace=None, **kw):
            return {"hit_rate": 0.7}

    result = CompositeEvaluator([_AlphaEvaluator(), _BetaEvaluator()]).evaluate(
        query="q", retrieved_ids=["c1"], golden_ids=["c1"]
    )
    # 类名含前导 _ 时前缀也含 _（snake_case 转换保留原始字符）
    assert "_alpha__hit_rate" in result
    assert "_beta__hit_rate" in result
    assert result["_alpha__hit_rate"] == pytest.approx(0.9)
    assert result["_beta__hit_rate"] == pytest.approx(0.7)


def test_class_name_to_prefix_strips_evaluator_suffix() -> None:
    """_class_name_to_prefix 应去掉 Evaluator 后缀并转为 snake_case。"""
    assert _class_name_to_prefix("CustomEvaluator") == "custom"
    assert _class_name_to_prefix("RagasEvaluator") == "ragas"
    assert _class_name_to_prefix("MyFancyEvaluator") == "my_fancy"


def test_zero_metrics_delegates_to_children_with_prefix() -> None:
    """zero_metrics() 应将各子评估器的零值模板合并并加前缀。"""
    evaluator = CompositeEvaluator([_StubEvaluatorA(), _StubEvaluatorB()])
    zero = evaluator.zero_metrics()
    assert "_stub_evaluator_a__hit_rate" in zero
    assert "_stub_evaluator_b__faithfulness" in zero
    assert all(v == 0.0 for v in zero.values())


def test_single_evaluator_keeps_bare_metric_keys() -> None:
    """仅一个子评估器时不加 prefix，保持与历史 baseline（无前缀）向后兼容。"""
    evaluator = CompositeEvaluator([_StubEvaluatorA()])
    result = evaluator.evaluate(
        query="q", retrieved_ids=["c1"], golden_ids=["c1"]
    )
    # 应使用裸 key，而非 _stub_evaluator_a__hit_rate
    assert "hit_rate" in result
    assert "_stub_evaluator_a__hit_rate" not in result
    # zero_metrics 同样遵循单评估器不加前缀的规则
    assert "hit_rate" in evaluator.zero_metrics()
