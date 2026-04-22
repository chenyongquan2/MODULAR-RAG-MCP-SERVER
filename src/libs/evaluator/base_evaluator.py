"""Abstract base class for evaluator providers.

This module defines the pluggable interface for evaluation backends,
enabling seamless switching between different evaluation methods (custom metrics,
Ragas, DeepEval, etc.) through configuration-driven instantiation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from src.core.trace.trace_context import TraceContext


class BaseEvaluator(ABC):
    """Abstract base class for evaluator providers.

    All evaluator implementations must inherit from this class and implement
    the evaluate() method. This ensures consistent interface across different
    evaluation backends (custom metrics, Ragas, DeepEval, etc.).

    Design Principles Applied:
    - Pluggable: Subclasses can be swapped without changing upstream code.
    - Observable: Accepts optional TraceContext for observability integration.
    - Config-Driven: Instances are created via factory based on settings.
    """

    @abstractmethod
    def evaluate(
        self,
        query: str,
        retrieved_ids: list[str],
        golden_ids: list[str],
        trace: Optional["TraceContext"] = None,
        **kwargs: Any,
    ) -> dict[str, float]:
        """Evaluate retrieval quality by comparing retrieved results with golden set.

        Args:
            query: The search query text.
            retrieved_ids: List of retrieved chunk IDs (in ranked order).
            golden_ids: List of golden/ground-truth chunk IDs.
            trace: Optional TraceContext for observability (reserved for Stage F).
            **kwargs: Provider-specific parameters.

        Returns:
            Dictionary of evaluation metrics, e.g.:
            {
                "hit_rate": 0.8,
                "mrr": 0.75,
                "ndcg@10": 0.85
            }

        Raises:
            ValueError: If retrieved_ids or golden_ids are empty or invalid.
            RuntimeError: If the evaluation process fails.

        Example:
            >>> evaluator = CustomEvaluator()
            >>> metrics = evaluator.evaluate(
            ...     query="test",
            ...     retrieved_ids=["chunk_1", "chunk_2"],
            ...     golden_ids=["chunk_2"]
            ... )
            >>> print(metrics["hit_rate"])
            1.0
        """
        pass

    def zero_metrics(self) -> dict[str, float]:
        """返回与 evaluate() 输出 key 一致的零值字典。

        当 EvalRunner 检索结果为空时，会调用此方法获取零值占位，
        保证所有 case_results 的 metric key 保持一致，避免 aggregate_metrics 聚合异常。

        子类**必须**覆盖此方法，返回的 key 集合必须与 evaluate() 对齐；
        否则会因 key 缺失导致 aggregate_metrics 均值被系统性抬高。
        此处默认实现直接抛异常，让忘记覆盖的情况尽早失败。
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must override zero_metrics() to return a dict "
            "whose keys match evaluate() output. See BaseEvaluator.zero_metrics docstring."
        )
