"""Evaluator 抽象基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.trace.trace_context import TraceContext


class BaseEvaluator(ABC):
    """评估器抽象基类。
    
    评估器用于评估检索质量，通过比较检索结果与黄金标准答案，计算各种评估指标。
    """

    @abstractmethod
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
            评估指标字典，例如：
            {
                "hit_rate@5": 0.8,
                "hit_rate@10": 0.9,
                "mrr": 0.75
            }
        """
        pass
