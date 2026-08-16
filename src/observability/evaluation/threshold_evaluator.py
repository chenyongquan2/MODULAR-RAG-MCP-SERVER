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
from typing import TYPE_CHECKING, Optional

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

    DEGRADATION_FAILURE_KEY = "degradation_ratio"
    """降级率不达标时在 ``get_failed_metrics()`` 里使用的伪 metric key。

    它不是聚合指标,但要出现在同一个「哪里没过」的清单里 —— 否则读者会看到
    ``acceptance_status=fail`` 却在 8 项指标里找不到任何一项不达标。
    """

    def __init__(
        self,
        thresholds: "AcceptanceThresholds",
        max_degradation_ratio: Optional[float] = None,
    ) -> None:
        """记录阈值清单(浅引用即可,本类不修改)。

        Args:
            thresholds: 8 项主聚合指标的阈值。
            max_degradation_ratio: (change evaluation-degradation-governance)
                降级率门槛。为 ``None`` 时不判降级 —— 保持本能力落地之前的行为,
                让只关心指标阈值的调用方(如历史报告重算)不受影响。
        """
        self._thresholds = thresholds
        # 阈值 dict 化以避免每次 evaluate() 重新调用 to_dict
        self._threshold_map: dict[str, float] = thresholds.to_dict()
        self._max_degradation_ratio = max_degradation_ratio

    def evaluate(
        self,
        aggregate_metrics: dict[str, float],
        degradation_ratio: Optional[float] = None,
    ) -> AcceptanceStatus:
        """根据 aggregate_metrics、阈值与降级率计算 pass/fail。

        **为什么降级率也要判**:8 项指标全过、而其中一半是在收缩后的分母上算出
        来的 —— 这种 ``pass`` 是假的。实测 run 80a82405 的 faithfulness 0.8887
        只是 27/42 条的均值。指标达标与样本完整是两个独立的合格条件。

        Args:
            aggregate_metrics: 评估报告的 8 项主聚合指标快照,key 必须含
                ``ragas__*`` 与 ``custom__*`` 共 8 项。
            degradation_ratio: 本次运行的降级率(降级 case 数 / 总 case 数)。
                与构造时的 ``max_degradation_ratio`` 任一为 ``None`` 则不判此项。

        Returns:
            AcceptanceStatus.PASS:全部 8 项均 ≥ 各自阈值,且降级率未超门槛。
            AcceptanceStatus.FAIL:任一项 < 阈值、缺失 key、值为 NaN,或降级率超标。
        """
        if self._is_degradation_over_threshold(degradation_ratio):
            return AcceptanceStatus.FAIL

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

    def _is_degradation_over_threshold(self, degradation_ratio: Optional[float]) -> bool:
        """降级率是否超过门槛。

        两个值任一为 ``None`` 就不判 —— 「没配门槛」与「没提供降级率」都不是
        失败,只是本项不参与判定。
        """
        if self._max_degradation_ratio is None or degradation_ratio is None:
            return False
        try:
            return float(degradation_ratio) > float(self._max_degradation_ratio)
        except (TypeError, ValueError):  # pragma: no cover - 防御性
            return False

    def get_failed_metrics(
        self,
        aggregate_metrics: dict[str, float],
        degradation_ratio: Optional[float] = None,
    ) -> list[str]:
        """返回未达标项的清单(供面板诊断、日志使用)。

        Args:
            aggregate_metrics: 8 项主聚合指标快照。
            degradation_ratio: 本次运行的降级率;超标时清单里会含
                ``DEGRADATION_FAILURE_KEY``。

        Returns:
            未达标项;全部达标时返回空列表。降级率超标排在最前 —— 它一旦成立,
            后面那些指标值本身就是在不完整样本上算的,先看它才对。
        """
        failed: list[str] = []
        if self._is_degradation_over_threshold(degradation_ratio):
            failed.append(self.DEGRADATION_FAILURE_KEY)
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
