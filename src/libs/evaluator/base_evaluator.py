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
