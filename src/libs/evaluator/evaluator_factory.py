"""Evaluator 工厂。"""

from typing import List, Optional

from src.libs.evaluator.base_evaluator import BaseEvaluator
from src.libs.evaluator.custom_evaluator import CustomEvaluator
from src.observability.logger import get_logger

logger = get_logger(__name__)


def create_evaluator(
    backend: str = "custom",
    k_values: Optional[List[int]] = None,
    **kwargs
) -> BaseEvaluator:
    """创建评估器实例。
    
    Args:
        backend: 评估器后端类型，目前支持 "custom"
        k_values: Hit Rate 的 K 值列表，默认为 [5, 10]
        **kwargs: 其他评估器特定参数
        
    Returns:
        评估器实例
        
    Raises:
        ValueError: 不支持的评估器后端类型
        
    Examples:
        >>> evaluator = create_evaluator("custom", k_values=[5, 10])
        >>> metrics = evaluator.evaluate(
        ...     query="test query",
        ...     retrieved_chunk_ids=["chunk1", "chunk2", "chunk3"],
        ...     golden_chunk_ids=["chunk2"]
        ... )
    """
    logger.info(f"Creating evaluator with backend={backend}")

    if backend == "custom":
        return CustomEvaluator(k_values=k_values)
    else:
        raise ValueError(f"Unsupported evaluator backend: {backend}")
