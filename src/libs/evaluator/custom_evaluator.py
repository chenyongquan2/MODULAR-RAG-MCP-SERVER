"""Custom evaluator implementation for lightweight IR metrics.

This module implements a custom evaluator that calculates common information
retrieval metrics (Hit Rate, MRR) without external dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from src.libs.evaluator.base_evaluator import BaseEvaluator

if TYPE_CHECKING:
    from src.core.settings import Settings
    from src.core.trace.trace_context import TraceContext


class CustomEvaluator(BaseEvaluator):
    """Custom evaluator implementing Hit Rate and MRR metrics.

    This evaluator provides lightweight retrieval quality metrics:
    - Hit Rate: Proportion of queries where at least one relevant document
      appears in the top-K retrieved results.
    - MRR (Mean Reciprocal Rank): Average of 1/rank for the first relevant
      document in the retrieved results.

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

        Raises:
            ValueError: If retrieved_ids or golden_ids are empty.

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
            trace.add_metadata("evaluator_type", "custom")
            trace.add_metadata("query", query)

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

        metrics = {"hit_rate": hit_rate, "mrr": mrr}

        # Add trace metadata for results
        if trace:
            trace.add_metadata("metrics", metrics)

        return metrics
