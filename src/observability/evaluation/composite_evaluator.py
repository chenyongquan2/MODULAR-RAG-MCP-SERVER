"""Composite evaluator that orchestrates multiple evaluator backends."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any, Optional

from src.libs.evaluator.base_evaluator import BaseEvaluator

if TYPE_CHECKING:
    from src.core.trace.trace_context import TraceContext


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

        # 使用线程池并行评估，加速多后端组合场景。
        with ThreadPoolExecutor(max_workers=len(self._evaluators)) as executor:
            futures = {
                executor.submit(
                    evaluator.evaluate,
                    query,
                    retrieved_ids,
                    golden_ids,
                    trace=trace,
                    **kwargs,
                ): evaluator.__class__.__name__
                for evaluator in self._evaluators
            }

            for future in as_completed(futures):
                evaluator_name = futures[future]
                try:
                    metrics = future.result()
                except Exception as exc:
                    raise RuntimeError(
                        f"Composite evaluator failed on {evaluator_name}: {exc}"
                    ) from exc

                for metric_name, value in metrics.items():
                    merged_metrics[metric_name] = float(value)

        if trace:
            trace.add_metadata("evaluator_type", "composite")
            trace.add_metadata("composite_metrics", merged_metrics)

        return merged_metrics
