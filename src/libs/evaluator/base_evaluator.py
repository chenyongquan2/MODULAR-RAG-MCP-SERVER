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

    # ------------------------------------------------------------------
    # 可选能力：只凭「有序的检索结果 id」就能算出的指标
    # ------------------------------------------------------------------
    #
    # 为什么需要把它单列出来:分路径指标要对 dense / sparse 每一路**各打一次分**,
    # 而这时只有该路的有序 chunk_id,没有答案、没有上下文文本。LLM 判定类后端
    # (faithfulness / answer_relevancy 之类)在这种输入下无从谈起,纯计算类后端
    # (hit_rate / mrr / ndcg / recall)则完全够用。
    #
    # 用「可选能力 + 显式探测」而不是给所有后端加抽象方法,是因为「能不能只凭
    # id 打分」本就是后端之间的真实差异,强行统一只会逼出一堆假实现。

    def supports_retrieval_only(self) -> bool:
        """本后端能否只凭有序的检索结果 id 打分。

        默认 ``False``。纯计算类后端覆盖为 ``True``。

        ⚠️ **调用方探测时必须用 ``is True`` 严格判断**。测试里常用 ``Mock()``,
        而 ``Mock()`` 的任何方法调用都返回真值 Mock —— 普通真值判断会把它误判成
        「支持该能力」,接着在下游炸成降级。本项目为此让 6 个既有用例全红过一次。
        """
        return False

    def evaluate_retrieval_only(
        self,
        query: str,
        retrieved_ids: list[str],
        golden_ids: list[str],
    ) -> dict[str, float]:
        """只凭有序的检索结果 id 打分,返回纯计算类指标。

        实现**必须与 :meth:`evaluate` 共用同一套公式**,不得另写一份 ——
        两套公式必然漂移,而漂移是静默的(数对不上但谁都不报错)。

        Args:
            query: 查询文本(仅用于日志与追踪,不参与打分)。
            retrieved_ids: 检索结果的 chunk_id,**顺序即名次**。
            golden_ids: 金标的期望 chunk_id。

        Returns:
            指标名 → 值。key 集合必须与 :meth:`zero_metrics` 中纯计算类的那部分一致。

        Raises:
            NotImplementedError: 本后端不支持该能力(见 :meth:`supports_retrieval_only`)。
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support retrieval-only scoring; "
            "check supports_retrieval_only() before calling."
        )
