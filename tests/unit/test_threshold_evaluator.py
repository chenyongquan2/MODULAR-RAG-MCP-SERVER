"""Unit tests for ThresholdEvaluator (T014, refs spec FR-013).

测试范围:
- 全 8 项 ≥ 阈值 → PASS
- 任一项 < 阈值 → FAIL
- 阈值边界(等于阈值视作 PASS,略低 → FAIL)
- 缺指标 key → FAIL(保守判定,通常是 backend 配置错误)
- NaN 值 → FAIL
- get_failed_metrics 返回未达标列表
- thresholds_snapshot 返回字典副本
"""

from __future__ import annotations

import math

import pytest

from src.core.settings import AcceptanceThresholds
from src.core.types import AcceptanceStatus
from src.observability.evaluation.threshold_evaluator import ThresholdEvaluator


pytestmark = pytest.mark.unit


def _all_pass_metrics() -> dict[str, float]:
    """生成全部满足业界参考阈值的指标快照。"""
    return {
        "ragas__context_recall": 0.80,
        "ragas__context_precision": 0.75,
        "ragas__faithfulness": 0.90,
        "ragas__answer_relevancy": 0.85,
        "custom__hit_rate": 0.70,
        "custom__mrr": 0.65,
        "custom__recall": 0.80,
        "custom__ndcg": 0.65,
    }


def _all_at_threshold_metrics() -> dict[str, float]:
    """全部恰好等于业界参考阈值(边界条件)。"""
    return {
        "ragas__context_recall": 0.70,
        "ragas__context_precision": 0.65,
        "ragas__faithfulness": 0.85,
        "ragas__answer_relevancy": 0.75,
        "custom__hit_rate": 0.60,
        "custom__mrr": 0.55,
        "custom__recall": 0.70,
        "custom__ndcg": 0.55,
    }


# ---------------------------------------------------------------------------
# 主路径
# ---------------------------------------------------------------------------


class TestThresholdEvaluatorMainPath:
    """全 8 项达标 → PASS;任一不达标 → FAIL。"""

    def test_all_pass_returns_pass(self) -> None:
        evaluator = ThresholdEvaluator(AcceptanceThresholds())
        assert evaluator.evaluate(_all_pass_metrics()) == AcceptanceStatus.PASS

    def test_all_at_threshold_boundary_returns_pass(self) -> None:
        """指标值恰好等于阈值时,>= 比较应返回 PASS(包含边界)。"""
        evaluator = ThresholdEvaluator(AcceptanceThresholds())
        assert evaluator.evaluate(_all_at_threshold_metrics()) == AcceptanceStatus.PASS

    def test_one_metric_below_threshold_returns_fail(self) -> None:
        evaluator = ThresholdEvaluator(AcceptanceThresholds())
        metrics = _all_pass_metrics()
        metrics["ragas__faithfulness"] = 0.84  # 略低于默认 0.85
        assert evaluator.evaluate(metrics) == AcceptanceStatus.FAIL

    def test_just_below_boundary_returns_fail(self) -> None:
        """边界精度:0.69999 < 0.70 应返 FAIL(浮点严格比较)。"""
        evaluator = ThresholdEvaluator(AcceptanceThresholds())
        metrics = _all_at_threshold_metrics()
        metrics["ragas__context_recall"] = 0.69999
        assert evaluator.evaluate(metrics) == AcceptanceStatus.FAIL

    def test_user_overridden_thresholds_apply(self) -> None:
        """用户覆盖某项阈值后,该阈值生效。"""
        thresholds = AcceptanceThresholds(ragas__faithfulness=0.95)
        evaluator = ThresholdEvaluator(thresholds)
        metrics = _all_pass_metrics()
        metrics["ragas__faithfulness"] = 0.90  # 默认 0.85 通过,但覆盖到 0.95 不通过
        assert evaluator.evaluate(metrics) == AcceptanceStatus.FAIL


# ---------------------------------------------------------------------------
# 异常输入处理
# ---------------------------------------------------------------------------


class TestThresholdEvaluatorEdgeCases:
    """缺 key / NaN / 空 dict 等异常输入。"""

    def test_missing_metric_key_returns_fail(self) -> None:
        """aggregate_metrics 缺某个 metric → FAIL(通常是 backend 配置错误)。"""
        evaluator = ThresholdEvaluator(AcceptanceThresholds())
        metrics = _all_pass_metrics()
        del metrics["custom__ndcg"]
        assert evaluator.evaluate(metrics) == AcceptanceStatus.FAIL

    def test_nan_metric_returns_fail(self) -> None:
        """NaN 不与浮点 >= 比较产出 True → FAIL(显式降级场景)。"""
        evaluator = ThresholdEvaluator(AcceptanceThresholds())
        metrics = _all_pass_metrics()
        metrics["ragas__answer_relevancy"] = float("nan")
        assert evaluator.evaluate(metrics) == AcceptanceStatus.FAIL

    def test_none_metric_returns_fail(self) -> None:
        """None metric 视作降级。"""
        evaluator = ThresholdEvaluator(AcceptanceThresholds())
        metrics = _all_pass_metrics()
        metrics["custom__mrr"] = None  # type: ignore[assignment]
        assert evaluator.evaluate(metrics) == AcceptanceStatus.FAIL

    def test_empty_metrics_returns_fail(self) -> None:
        evaluator = ThresholdEvaluator(AcceptanceThresholds())
        assert evaluator.evaluate({}) == AcceptanceStatus.FAIL


# ---------------------------------------------------------------------------
# get_failed_metrics & thresholds_snapshot
# ---------------------------------------------------------------------------


class TestFailedMetricsAndSnapshot:
    """诊断辅助方法。"""

    def test_get_failed_metrics_empty_when_all_pass(self) -> None:
        evaluator = ThresholdEvaluator(AcceptanceThresholds())
        assert evaluator.get_failed_metrics(_all_pass_metrics()) == []

    def test_get_failed_metrics_lists_specific_failures(self) -> None:
        evaluator = ThresholdEvaluator(AcceptanceThresholds())
        metrics = _all_pass_metrics()
        metrics["ragas__faithfulness"] = 0.50
        metrics["custom__hit_rate"] = 0.40
        failed = evaluator.get_failed_metrics(metrics)
        assert "ragas__faithfulness" in failed
        assert "custom__hit_rate" in failed
        assert len(failed) == 2

    def test_get_failed_metrics_includes_nan(self) -> None:
        evaluator = ThresholdEvaluator(AcceptanceThresholds())
        metrics = _all_pass_metrics()
        metrics["ragas__context_precision"] = float("nan")
        failed = evaluator.get_failed_metrics(metrics)
        assert "ragas__context_precision" in failed

    def test_thresholds_snapshot_is_independent_copy(self) -> None:
        """snapshot 返回的 dict 应是副本,外部修改不影响内部状态。"""
        thresholds = AcceptanceThresholds()
        evaluator = ThresholdEvaluator(thresholds)
        snap1 = evaluator.thresholds_snapshot
        snap1["ragas__faithfulness"] = 0.0  # 外部篡改
        snap2 = evaluator.thresholds_snapshot
        assert snap2["ragas__faithfulness"] == 0.85  # 内部未受影响

    def test_thresholds_snapshot_keys(self) -> None:
        """snapshot 含完整 8 个 metric key。"""
        evaluator = ThresholdEvaluator(AcceptanceThresholds())
        snap = evaluator.thresholds_snapshot
        assert set(snap.keys()) == {
            "ragas__context_recall",
            "ragas__context_precision",
            "ragas__faithfulness",
            "ragas__answer_relevancy",
            "custom__hit_rate",
            "custom__mrr",
            "custom__recall",
            "custom__ndcg",
        }
