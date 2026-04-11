"""Ragas evaluator implementation.

This module wraps the Ragas framework behind the project's pluggable
``BaseEvaluator`` interface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from src.libs.evaluator.base_evaluator import BaseEvaluator

if TYPE_CHECKING:
    from src.core.settings import Settings
    from src.core.trace.trace_context import TraceContext


class RagasEvaluator(BaseEvaluator):
    """Ragas-based evaluator for retrieval and answer quality.

    Supported metrics:
    - faithfulness
    - answer_relevancy
    - context_precision

    The evaluator supports two execution modes:
    1. ``mock_metrics`` mode for deterministic unit tests without external deps.
    2. Real Ragas execution mode, requiring ``ragas`` and ``datasets``.
    """

    def __init__(self, settings: "Settings", **override_kwargs: Any) -> None:
        """Initialize the evaluator.

        Args:
            settings: Application settings.
            **override_kwargs: Provider-level overrides (reserved).
        """
        self.settings = settings
        self._override_kwargs = override_kwargs

    def evaluate(
        self,
        query: str,
        retrieved_ids: list[str],
        golden_ids: list[str],
        trace: Optional["TraceContext"] = None,
        **kwargs: Any,
    ) -> dict[str, float]:
        """Evaluate with Ragas metrics.

        Args:
            query: The input question.
            retrieved_ids: Ranked retrieved chunk IDs.
            golden_ids: Expected golden chunk IDs.
            trace: Optional tracing context.
            **kwargs: Provider-specific arguments.
                - mock_metrics: Optional precomputed metrics used in tests.
                - answer: Model answer text used by ragas.
                - contexts: List of retrieved context strings.
                - ground_truth: Reference answer text.
                - llm: Optional ragas-compatible llm instance.
                - embeddings: Optional ragas-compatible embeddings instance.

        Returns:
            A dict containing faithfulness, answer_relevancy, context_precision.

        Raises:
            ValueError: If required input lists are empty.
            ImportError: If ragas dependencies are missing.
            RuntimeError: If ragas execution fails.
        """
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

        if trace:
            trace.add_metadata("evaluator_type", "ragas")
            trace.add_metadata("query", query)

        mock_metrics = kwargs.get("mock_metrics")
        if isinstance(mock_metrics, dict):
            metrics = self._normalize_metrics(mock_metrics)
            if trace:
                trace.add_metadata("metrics", metrics)
            return metrics

        metrics = self._evaluate_with_ragas(
            query=query,
            retrieved_ids=retrieved_ids,
            golden_ids=golden_ids,
            **kwargs,
        )

        if trace:
            trace.add_metadata("metrics", metrics)
        return metrics

    def _evaluate_with_ragas(
        self,
        query: str,
        retrieved_ids: list[str],
        golden_ids: list[str],
        **kwargs: Any,
    ) -> dict[str, float]:
        """Run real Ragas evaluation and map outputs to stable metric keys."""
        try:
            from datasets import Dataset
            from ragas import evaluate as ragas_evaluate
            from ragas.metrics import (
                answer_relevancy,
                context_precision,
                faithfulness,
            )
        except ImportError as exc:
            raise ImportError(
                "Ragas evaluator requires optional dependencies 'ragas' and "
                "'datasets'. Install them first, e.g. `pip install ragas datasets`."
            ) from exc

        answer = str(kwargs.get("answer", ""))
        ground_truth = str(kwargs.get("ground_truth", " ".join(golden_ids)))
        contexts = kwargs.get("contexts")
        if not contexts:
            # 使用检索 ID 作为最小上下文占位，确保评估输入结构完整。
            contexts = retrieved_ids

        dataset = Dataset.from_dict(
            {
                "question": [query],
                "answer": [answer],
                "contexts": [list(contexts)],
                "ground_truth": [ground_truth],
            }
        )

        try:
            result = ragas_evaluate(
                dataset=dataset,
                metrics=[faithfulness, answer_relevancy, context_precision],
                llm=kwargs.get("llm"),
                embeddings=kwargs.get("embeddings"),
            )
        except Exception as exc:
            raise RuntimeError(f"Ragas evaluation failed: {exc}") from exc

        raw_metrics: dict[str, Any]
        if hasattr(result, "to_dict"):
            raw_metrics = result.to_dict()  # type: ignore[assignment]
        elif isinstance(result, dict):
            raw_metrics = result
        else:
            raw_metrics = dict(result)

        return self._normalize_metrics(raw_metrics)

    def _normalize_metrics(self, raw_metrics: dict[str, Any]) -> dict[str, float]:
        """Normalize provider output into stable float metrics."""
        def _pick(*names: str) -> float:
            for name in names:
                value = raw_metrics.get(name)
                if value is not None:
                    return float(value)
            return 0.0

        return {
            "faithfulness": _pick("faithfulness"),
            "answer_relevancy": _pick("answer_relevancy", "answer_relevance"),
            "context_precision": _pick("context_precision"),
        }
