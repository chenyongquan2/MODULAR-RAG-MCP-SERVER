"""Ragas evaluator implementation.

This module wraps the Ragas framework behind the project's pluggable
``BaseEvaluator`` interface.

设计说明（最佳实践）：
    RAGAS 的四个核心指标都依赖**真实文本**而非 chunk ID：
        - faithfulness         : 需要 question + answer + contexts
        - answer_relevancy     : 需要 question + answer + contexts
        - context_precision    : 需要 question + contexts + ground_truth
        - context_recall       : 需要 contexts + ground_truth

    因此本实现对真实 ragas 模式强制要求以下字段（通过 kwargs 传入）：
        - ``contexts``      (list[str])：检索到的 **文本片段**，严禁传 chunk ID。
        - ``ground_truth``  (str)      ：参考答案文本。
        - ``answer``        (str)      ：完整 RAG 链路生成的回答（可为空，但会
                                         导致 faithfulness/answer_relevancy 失真）。

    单元测试可通过 ``mock_metrics`` 旁路真实执行。
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
    - context_recall

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
            retrieved_ids: Ranked retrieved chunk IDs（仅用于与检索类指标接口统一，
                RAGAS 本身不使用 ID）。
            golden_ids: Expected golden chunk IDs（同上）。
            trace: Optional tracing context.
            **kwargs: Provider-specific arguments.
                - mock_metrics: Optional precomputed metrics used in tests.
                - answer: Model answer text used by ragas（faithfulness/relevancy 必需）。
                - contexts: List of retrieved context **strings**（严禁传 chunk ID）。
                - ground_truth: Reference answer text（precision/recall 必需）。
                - llm: Optional ragas-compatible llm instance.
                - embeddings: Optional ragas-compatible embeddings instance.

        Returns:
            A dict containing faithfulness, answer_relevancy, context_precision,
            context_recall.

        Raises:
            ValueError: If required input lists are empty, or if real-mode
                required fields (contexts / ground_truth) are missing.
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
            **kwargs,
        )

        if trace:
            trace.add_metadata("metrics", metrics)
        return metrics

    def _evaluate_with_ragas(
        self,
        query: str,
        **kwargs: Any,
    ) -> dict[str, float]:
        """Run real Ragas evaluation and map outputs to stable metric keys."""
        # —— 严格校验：RAGAS 必需的文本字段（必须先于 import，避免被
        # ImportError 遮盖，确保配置错误产生清晰 ValueError 信号）——
        # 旧实现会在缺失时把 chunk ID 当成 context/ground_truth，导致指标无意义。
        # 这里改为显式报错，迫使调用方（EvalRunner）传入真实文本。
        contexts = kwargs.get("contexts")
        if not contexts or not isinstance(contexts, list):
            raise ValueError(
                "RagasEvaluator requires 'contexts' (list[str] of retrieved "
                "text chunks). Passing chunk IDs is not supported — the metric "
                "would be meaningless. EvalRunner should extract "
                "RetrievalResult.text for each result."
            )
        if any(not isinstance(item, str) or not item.strip() for item in contexts):
            raise ValueError(
                "RagasEvaluator 'contexts' must be a list of non-empty strings."
            )

        ground_truth = kwargs.get("ground_truth")
        if not isinstance(ground_truth, str) or not ground_truth.strip():
            raise ValueError(
                "RagasEvaluator requires non-empty 'ground_truth' (reference "
                "answer text). This is needed by context_precision and "
                "context_recall metrics. Populate the 'ground_truth' field of "
                "each test case in the golden test set."
            )

        answer = kwargs.get("answer", "")
        if not isinstance(answer, str):
            raise ValueError("RagasEvaluator 'answer' must be a string.")
        # answer 为空仍允许执行（context_precision/recall 不依赖 answer），
        # 但会在 faithfulness/answer_relevancy 上产出 0 或 NaN，由 ragas 自行处理。

        try:
            from datasets import Dataset
            from ragas import evaluate as ragas_evaluate
            from ragas.metrics import (
                answer_relevancy,
                context_precision,
                context_recall,
                faithfulness,
            )
        except ImportError as exc:
            raise ImportError(
                "Ragas evaluator requires optional dependencies 'ragas' and "
                "'datasets'. Install them first, e.g. `pip install ragas datasets`."
            ) from exc

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
                metrics=[
                    faithfulness,
                    answer_relevancy,
                    context_precision,
                    context_recall,
                ],
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
        """Normalize provider output into stable float metrics.

        覆盖 RAGAS 4 个核心指标；对常见别名（answer_relevance）做归一化。
        """
        def _pick(*names: str) -> float:
            for name in names:
                value = raw_metrics.get(name)
                if value is not None:
                    try:
                        return float(value)
                    except (TypeError, ValueError):
                        continue
            return 0.0

        return {
            "faithfulness": _pick("faithfulness"),
            "answer_relevancy": _pick("answer_relevancy", "answer_relevance"),
            "context_precision": _pick("context_precision"),
            "context_recall": _pick("context_recall"),
        }
