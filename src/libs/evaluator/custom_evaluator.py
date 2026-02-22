"""自定义评估器实现。"""

from __future__ import annotations

from typing import Dict, List, Optional, TYPE_CHECKING

from src.libs.evaluator.base_evaluator import BaseEvaluator
from src.observability.logger import get_logger

if TYPE_CHECKING:
    from src.core.trace.trace_context import TraceContext

logger = get_logger(__name__)


class CustomEvaluator(BaseEvaluator):
    """自定义评估器，实现 Hit Rate 和 MRR 指标。
    
    Metrics:
        - Hit Rate@K: 前 K 个检索结果中至少命中一个黄金标准的比例
        - MRR (Mean Reciprocal Rank): 第一个黄金标准出现位置的倒数
    """

    def __init__(self, k_values: Optional[List[int]] = None):
        """初始化评估器。
        
        Args:
            k_values: 计算 Hit Rate 的 K 值列表，默认为 [5, 10]
        """
        self.k_values = k_values or [5, 10]

    def evaluate(
        self,
        query: str,
        retrieved_chunk_ids: List[str],
        golden_chunk_ids: List[str],
        trace: Optional["TraceContext"] = None
    ) -> Dict[str, float]:
        """执行评估。
        
        Args:
            query: 查询文本
            retrieved_chunk_ids: 检索返回的 chunk ID 列表（已排序）
            golden_chunk_ids: 黄金标准 chunk ID 列表
            trace: 可选的追踪上下文
            
        Returns:
            评估指标字典，包含 hit_rate@K 和 mrr
        """
        if trace:
            trace.add_metadata("evaluator_type", "custom")
            trace.add_metadata("k_values", self.k_values)

        metrics = {}

        # 计算 Hit Rate@K
        for k in self.k_values:
            hit_rate = self._calculate_hit_rate(retrieved_chunk_ids, golden_chunk_ids, k)
            metrics[f"hit_rate@{k}"] = hit_rate

        # 计算 MRR
        mrr = self._calculate_mrr(retrieved_chunk_ids, golden_chunk_ids)
        metrics["mrr"] = mrr

        logger.info(f"Evaluation metrics: {metrics}")

        if trace:
            trace.add_metadata("metrics", metrics)

        return metrics

    def _calculate_hit_rate(
        self,
        retrieved_chunk_ids: List[str],
        golden_chunk_ids: List[str],
        k: int
    ) -> float:
        """计算 Hit Rate@K。
        
        Args:
            retrieved_chunk_ids: 检索返回的 chunk ID 列表
            golden_chunk_ids: 黄金标准 chunk ID 列表
            k: 只考虑前 K 个检索结果
            
        Returns:
            Hit Rate 值（0.0 或 1.0）
        """
        if not golden_chunk_ids:
            logger.warning("No golden chunk IDs provided for evaluation")
            return 0.0

        # 取前 K 个检索结果
        top_k_retrieved = set(retrieved_chunk_ids[:k])
        golden_set = set(golden_chunk_ids)

        # 检查是否有交集
        has_hit = len(top_k_retrieved & golden_set) > 0
        return 1.0 if has_hit else 0.0

    def _calculate_mrr(
        self,
        retrieved_chunk_ids: List[str],
        golden_chunk_ids: List[str]
    ) -> float:
        """计算 MRR (Mean Reciprocal Rank)。
        
        Args:
            retrieved_chunk_ids: 检索返回的 chunk ID 列表
            golden_chunk_ids: 黄金标准 chunk ID 列表
            
        Returns:
            MRR 值，范围 [0.0, 1.0]
        """
        if not golden_chunk_ids:
            logger.warning("No golden chunk IDs provided for evaluation")
            return 0.0

        golden_set = set(golden_chunk_ids)

        # 找到第一个命中的位置
        for rank, chunk_id in enumerate(retrieved_chunk_ids, start=1):
            if chunk_id in golden_set:
                return 1.0 / rank

        # 没有命中
        return 0.0
