"""Composite evaluator that orchestrates multiple evaluator backends."""

from __future__ import annotations

import re as _re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any, Optional

from src.libs.evaluator.base_evaluator import BaseEvaluator

if TYPE_CHECKING:
    from src.core.trace.trace_context import TraceContext


def _class_name_to_prefix(class_name: str) -> str:
    """将 CamelCase 评估器类名转换为 snake_case 前缀，并去掉 'Evaluator' 后缀。

    用于给各评估器的指标名添加命名空间，避免多评估器组合时指标 key 冲突。

    Examples:
        CustomEvaluator  → "custom"
        RagasEvaluator   → "ragas"
        MyFancyEvaluator → "my_fancy"
    """
    # 去掉末尾的 "Evaluator" 后缀
    name = _re.sub(r"Evaluator$", "", class_name)
    # CamelCase → snake_case：在小写/数字和大写字母之间插入下划线
    name = _re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return name.lower() or class_name.lower()


class CompositeEvaluator(BaseEvaluator):
    """Compose multiple evaluator backends and merge their metrics.

    This evaluator executes all delegated evaluators in parallel and then merges
    each evaluator's output metrics into one flat dictionary.
    """

    def __init__(self, evaluators: list[BaseEvaluator]) -> None:
        """Initialize with concrete evaluator instances.

        Args:
            evaluators: Ordered evaluator instances to execute.

        Raises:
            ValueError: If evaluator list is empty.
        """
        if not evaluators:
            raise ValueError(
                "CompositeEvaluator requires at least one evaluator instance."
            )
        self._evaluators = evaluators

    def evaluate(
        self,
        query: str,
        retrieved_ids: list[str],
        golden_ids: list[str],
        trace: Optional["TraceContext"] = None,
        **kwargs: Any,
    ) -> dict[str, float]:
        """Run all evaluators and merge metrics.

        Args:
            query: The search query text.
            retrieved_ids: Ranked retrieved chunk IDs.
            golden_ids: Golden/ground-truth chunk IDs.
            trace: Optional trace context.
            **kwargs: Forwarded to each evaluator.

        Returns:
            A merged metrics dict.

        Raises:
            RuntimeError: If any sub evaluator fails.
        """
        merged_metrics: dict[str, float] = {}
        # 仅当组合多个评估器时才添加 prefix，避免与历史 baseline 的无前缀 key 失配。
        # 单评估器场景保持 key 原貌（hit_rate 而非 custom__hit_rate），
        # 保证历史 JSONL 向后兼容且 compare_with_baseline 能正确对齐。
        apply_prefix = len(self._evaluators) > 1

        # 使用线程池并行评估，加速多后端组合场景。
        with ThreadPoolExecutor(max_workers=len(self._evaluators)) as executor:
            # 映射 future → evaluator 实例（用于获取类名生成前缀）
            futures = {
                executor.submit(
                    evaluator.evaluate,
                    query,
                    retrieved_ids,
                    golden_ids,
                    trace=trace,
                    **kwargs,
                ): evaluator
                for evaluator in self._evaluators
            }

            for future in as_completed(futures):
                evaluator_instance = futures[future]
                evaluator_name = evaluator_instance.__class__.__name__
                try:
                    metrics = future.result()
                except Exception as exc:
                    raise RuntimeError(
                        f"Composite evaluator failed on {evaluator_name}: {exc}"
                    ) from exc

                prefix = _class_name_to_prefix(evaluator_name) if apply_prefix else ""
                for metric_name, value in metrics.items():
                    key = f"{prefix}__{metric_name}" if prefix else metric_name
                    merged_metrics[key] = float(value)

        if trace:
            trace.add_metadata("evaluator_type", "composite")
            trace.add_metadata("composite_metrics", merged_metrics)

        return merged_metrics

    def zero_metrics(self) -> dict[str, float]:
        """返回所有子评估器零值模板的合并结果（命名规则与 evaluate 保持一致）。

        保证 CompositeEvaluator 在空检索场景下，metric key 与正常评估时完全一致：
        - 单评估器时不加 prefix；
        - 多评估器时加 prefix，避免 key 冲突。
        """
        apply_prefix = len(self._evaluators) > 1
        merged: dict[str, float] = {}
        for evaluator in self._evaluators:
            prefix = _class_name_to_prefix(evaluator.__class__.__name__) if apply_prefix else ""
            for metric_name in evaluator.zero_metrics():
                key = f"{prefix}__{metric_name}" if prefix else metric_name
                merged[key] = 0.0
        return merged

    def get_judge_identifier(self) -> Optional[str]:
        """透传第一个支持该方法的子评估器的 Judge identifier。

        Feature-001 FR-016:CompositeEvaluator 由 EvaluatorFactory 构造时
        通常含 RagasEvaluator(它有 get_judge_identifier);若 backends 仅
        含 custom 类(无 get_*_identifier 方法),则返回 None。
        EvalRunner 通过 _safe_call 调用本方法,把返回值写入
        EvaluationReport.judge_llm_identifier。
        """
        for evaluator in self._evaluators:
            method = getattr(evaluator, "get_judge_identifier", None)
            if callable(method):
                try:
                    value = method()
                except Exception:
                    continue
                if value:
                    return str(value)
        return None

    def get_embedding_identifier(self) -> Optional[str]:
        """透传第一个支持该方法的子评估器的 embedding identifier(FR-017)。"""
        for evaluator in self._evaluators:
            method = getattr(evaluator, "get_embedding_identifier", None)
            if callable(method):
                try:
                    value = method()
                except Exception:
                    continue
                if value:
                    return str(value)
        return None
