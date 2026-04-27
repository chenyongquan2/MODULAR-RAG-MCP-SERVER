"""ThresholdEvaluator — 评估报告 pass/fail 判定 (Feature-001 T009)。

实现 spec § FR-013 与 data-model § 2.4 中的 AcceptanceStatus 计算逻辑:
当且仅当 8 个主聚合指标全部 ≥ 各自的 acceptance_thresholds 中阈值时,
评估结果输出 ``AcceptanceStatus.PASS``;否则输出 ``AcceptanceStatus.FAIL``。

设计准则:
- **无状态**:只读阈值与指标快照,无副作用,可重复调用
- **不参与 by-tag**:spec § Clarifications Q2 已明确 by-tag 切片**不**参与
  pass/fail 判定;本类只看 8 个主聚合指标
- **缺指标即视为 fail**:若 aggregate_metrics 缺少某 metric key,该 metric
  视为不达标;这种情况通常意味着 backend 配置错误,fail 是正确的安全默认
- **NaN 视为 fail**:metric 值为 NaN(显式降级,FR-001)时该 metric 视为
  不达标;NaN 不与浮点数 ``>=`` 比较产出 True

由 :class:`src.observability.evaluation.eval_runner.EvalRunner` 在 ``run()``
尾部调用,把 ``AcceptanceStatus`` 嵌入 EvalReport 输出。
"""

from __future__ import annotations

import math as _math
from typing import TYPE_CHECKING

from src.core.types import AcceptanceStatus

if TYPE_CHECKING:
    from src.core.settings import AcceptanceThresholds


class ThresholdEvaluator:
    """读 acceptance_thresholds + 给 8 项主聚合指标打 pass/fail。

    Args:
        thresholds: 当次评估生效的阈值清单(来自 settings.evaluation.acceptance_thresholds
            或用户在 settings.yaml 中覆盖的子集)。

    Example:
        >>> from src.core.settings import AcceptanceThresholds
        >>> evaluator = ThresholdEvaluator(AcceptanceThresholds())
        >>> status = evaluator.evaluate({
        ...     "ragas__context_recall": 0.75, "ragas__context_precision": 0.70,
        ...     "ragas__faithfulness": 0.90, "ragas__answer_relevancy": 0.80,
        ...     "custom__hit_rate": 0.65, "custom__mrr": 0.60,
        ...     "custom__recall": 0.75, "custom__ndcg": 0.60,
        ... })
        >>> status == AcceptanceStatus.PASS
        True
    """

    # 8 项主聚合指标的固定 key 列表(顺序无关,但用于失败时的稳定输出)
    _METRIC_KEYS: tuple[str, ...] = (
        "ragas__context_recall",
        "ragas__context_precision",
        "ragas__faithfulness",
        "ragas__answer_relevancy",
        "custom__hit_rate",
        "custom__mrr",
        "custom__recall",
        "custom__ndcg",
    )

    def __init__(self, thresholds: "AcceptanceThresholds") -> None:
        """记录阈值清单(浅引用即可,本类不修改)。"""
        self._thresholds = thresholds
        # 阈值 dict 化以避免每次 evaluate() 重新调用 to_dict
        self._threshold_map: dict[str, float] = thresholds.to_dict()

    def evaluate(self, aggregate_metrics: dict[str, float]) -> AcceptanceStatus:
        """根据 aggregate_metrics 与阈值计算 pass/fail。

        Args:
            aggregate_metrics: 评估报告的 8 项主聚合指标快照,key 必须含
                ``ragas__*`` 与 ``custom__*`` 共 8 项。

        Returns:
            AcceptanceStatus.PASS:全部 8 项均 ≥ 各自阈值。
            AcceptanceStatus.FAIL:任一项 < 阈值、缺失 key、或值为 NaN。
        """
        for metric_key in self._METRIC_KEYS:
            threshold = self._threshold_map.get(metric_key)
            if threshold is None:
                # 阈值清单缺失 key 不应发生(settings 校验时已强制 8 项齐全),
                # 但若发生则保守判 fail
                return AcceptanceStatus.FAIL

            value = aggregate_metrics.get(metric_key)
            if value is None or self._is_nan(value):
                # 缺指标 / NaN 视为不达标
                return AcceptanceStatus.FAIL

            if float(value) < threshold:
                return AcceptanceStatus.FAIL

        return AcceptanceStatus.PASS

    def get_failed_metrics(
        self, aggregate_metrics: dict[str, float]
    ) -> list[str]:
        """返回未达标的 metric key 列表(供面板诊断、日志使用)。

        Args:
            aggregate_metrics: 8 项主聚合指标快照。

        Returns:
            按 ``_METRIC_KEYS`` 顺序排列的未达标 metric key;全部达标时返回空列表。
        """
        failed: list[str] = []
        for metric_key in self._METRIC_KEYS:
            threshold = self._threshold_map.get(metric_key)
            if threshold is None:
                failed.append(metric_key)
                continue

            value = aggregate_metrics.get(metric_key)
            if value is None or self._is_nan(value) or float(value) < threshold:
                failed.append(metric_key)

        return failed

    @staticmethod
    def _is_nan(value: float | int) -> bool:
        """检测 NaN 不依赖外部库,跨 Python 版本统一行为。"""
        try:
            return _math.isnan(float(value))
        except (TypeError, ValueError):
            return True

    @property
    def thresholds_snapshot(self) -> dict[str, float]:
        """返回阈值快照(用于 EvaluationReport.acceptance_thresholds_snapshot)。"""
        return dict(self._threshold_map)
