"""Custom evaluator implementation for lightweight IR metrics.

This module implements a custom evaluator that calculates common information
retrieval metrics (Hit Rate, MRR, Recall@K, NDCG@K) without external dependencies.
"""

from __future__ import annotations

import math as _math
from typing import TYPE_CHECKING, Any, Optional

from src.libs.evaluator.base_evaluator import BaseEvaluator


def _log2(x: float) -> float:
    """计算以 2 为底的对数，x <= 1 时返回 1.0 防止除零。

    NDCG 公式中分母为 log2(rank + 1)，rank 从 1 开始时最小值为 log2(2) = 1.0，
    此处守卫保证即使调用者传入异常值也不会产生 ZeroDivisionError。
    """
    return _math.log2(x) if x > 1.0 else 1.0

if TYPE_CHECKING:
    from src.core.settings import Settings
    from src.core.trace.trace_context import TraceContext


class CustomEvaluator(BaseEvaluator):
    """Custom evaluator implementing Hit Rate, MRR, Recall@K, NDCG@K metrics.

    This evaluator provides lightweight retrieval quality metrics:
    - Hit Rate: Proportion of queries where at least one relevant document
      appears in the top-K retrieved results.
    - MRR (Mean Reciprocal Rank): Average of 1/rank for the first relevant
      document in the retrieved results.
    - Recall@K: |retrieved ∩ golden| / |golden|，衡量 golden IDs 的召回比例。
    - NDCG@K (Normalized Discounted Cumulative Gain): 位置加权排名质量分，
      考虑相关文档出现的位置，靠前得分越高。

    Design Principles Applied:
    - Deterministic: Same inputs always produce same outputs (stable for testing).
    - Input Validation: Raises clear errors for invalid inputs.
    - Configurable: Supports customization via settings.
    """

    def __init__(self, settings: Settings, **override_kwargs: Any):
        """Initialize the custom evaluator.

        Args:
            settings: Application settings containing evaluation configuration.
            **override_kwargs: Optional parameters to override settings.
        """
        self.settings = settings

    def evaluate(
        self,
        query: str,
        retrieved_ids: list[str],
        golden_ids: list[str],
        trace: Optional["TraceContext"] = None,
        **kwargs: Any,
    ) -> dict[str, float]:
        """Evaluate retrieval quality using Hit Rate and MRR metrics.

        Args:
            query: The search query text.
            retrieved_ids: List of retrieved chunk IDs (in ranked order).
            golden_ids: List of golden/ground-truth chunk IDs.
            trace: Optional TraceContext for observability.
            **kwargs: Additional parameters (unused).

        Returns:
            Dictionary containing:
            - "hit_rate": 1.0 if any golden ID is in retrieved_ids, else 0.0
            - "mrr": Reciprocal rank of first golden ID, or 0.0 if none found
            - "recall": |retrieved ∩ golden| / |golden|，golden 召回比例
            - "ndcg": Normalized DCG，综合排名位置的质量分

        Raises:
            ValueError: If query/retrieved_ids/golden_ids are invalid.

        Example:
            >>> evaluator = CustomEvaluator(settings)
            >>> metrics = evaluator.evaluate(
            ...     query="test",
            ...     retrieved_ids=["chunk_1", "chunk_2", "chunk_3"],
            ...     golden_ids=["chunk_2", "chunk_5"]
            ... )
            >>> print(metrics)
            {"hit_rate": 1.0, "mrr": 0.5}
        """
        # Input validation
        if not isinstance(query, str) or not query.strip():
            raise ValueError(
                "Missing required field: query must be a non-empty string. "
                "Please provide a valid query text."
            )
        if not retrieved_ids:
            raise ValueError(
                "Missing required field: retrieved_ids cannot be empty. "
                "Please provide at least one retrieved chunk ID."
            )
        if not golden_ids:
            raise ValueError(
                "Missing required field: golden_ids cannot be empty. "
                "Please provide at least one golden chunk ID."
            )

        # Add trace metadata if available
        if trace:
            self._add_trace_metadata(trace, "evaluator_type", "custom")
            self._add_trace_metadata(trace, "query", query)

        # Calculate metrics
        golden_set = set(golden_ids)
        retrieved_set = set(retrieved_ids)

        # Hit Rate: 1.0 if any overlap, 0.0 otherwise
        hit_rate = 1.0 if (golden_set & retrieved_set) else 0.0

        # MRR: Find first golden ID in retrieved list
        mrr = 0.0
        for rank, chunk_id in enumerate(retrieved_ids, start=1):
            if chunk_id in golden_set:
                mrr = 1.0 / rank
                break

        # Recall@K：命中的 golden IDs 占全部 golden IDs 的比例
        # 衡量"应该召回的是否都召回了"，是 RAG 最核心的检索指标之一
        recall = len(golden_set & retrieved_set) / len(golden_set)

        # NDCG@K：Normalized Discounted Cumulative Gain
        # 在 Hit Rate 基础上进一步考虑相关文档的排名位置：排名越靠前得分越高
        # DCG = Σ rel_i / log2(rank_i + 1)，其中 rel_i=1 表示该位置为相关文档
        dcg = sum(
            1.0 / _log2(rank + 1)
            for rank, chunk_id in enumerate(retrieved_ids, start=1)
            if chunk_id in golden_set
        )
        # Ideal DCG：假设所有 golden IDs 都在最靠前的位置
        ideal_hits = min(len(golden_set), len(retrieved_ids))
        ideal_dcg = sum(1.0 / _log2(rank + 1) for rank in range(1, ideal_hits + 1))
        ndcg = (dcg / ideal_dcg) if ideal_dcg > 0.0 else 0.0

        metrics = {"hit_rate": hit_rate, "mrr": mrr, "recall": recall, "ndcg": ndcg}

        # Add trace metadata for results
        if trace:
            self._add_trace_metadata(trace, "metrics", metrics)

        return metrics

    def zero_metrics(self) -> dict[str, float]:
        """返回空检索时的零值模板，保证所有 case_results 的 metric key 保持一致。

        当 EvalRunner 检索到空结果时，会调用此方法获取一致的零值字典，
        避免不同 case 之间 metric key 不一致导致 aggregate_metrics 聚合异常。
        """
        return {"hit_rate": 0.0, "mrr": 0.0, "recall": 0.0, "ndcg": 0.0}

    def _add_trace_metadata(
        self,
        trace: "TraceContext",
        key: str,
        value: Any,
    ) -> None:
        """Write trace metadata with backward-compatible behavior.

        优先调用 TraceContext.add_metadata（若实现），否则直接回写到
        trace.metadata 字典，保证在不同 TraceContext 实现下都能工作。
        """
        add_metadata = getattr(trace, "add_metadata", None)
        if callable(add_metadata):
            add_metadata(key, value)
            return

        metadata = getattr(trace, "metadata", None)
        if isinstance(metadata, dict):
            metadata[key] = value
