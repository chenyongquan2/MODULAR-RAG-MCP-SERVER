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

Feature-001 改造 (T008, refs spec FR-016 / FR-017):
    Judge LLM 与 embedding **不再**靠调用方从 kwargs 传 ``llm``/``embeddings``,
    而是在首次评估调用时通过 ``_ragas_wrappers`` 模块经 LLMFactory /
    EmbeddingFactory 自动注入(provider-agnostic、配置驱动)。kwargs 保留覆盖
    通道供单元测试 mock 使用。
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
    2. Real Ragas execution mode, requiring ``ragas`` and ``datasets``;Judge
       与 embedding 通过 LLMFactory / EmbeddingFactory 注入(spec § FR-016 / FR-017)。
    """

    def __init__(self, settings: "Settings", **override_kwargs: Any) -> None:
        """Initialize the evaluator.

        Args:
            settings: Application settings.
            **override_kwargs: Provider-level overrides (reserved).
        """
        self.settings = settings
        self._override_kwargs = override_kwargs
        # 延迟构建 RAGAS Judge / embedding 包装(在首次 evaluate 时按需触发);
        # 避免 RagasEvaluator 实例化时立刻发起 LLM 客户端连接,以及让仅做
        # 配置/类型校验的 import 路径不依赖 LLM 网络可达性。
        self._judge_wrapper: Any = None
        self._embedding_wrapper: Any = None
        self._wrappers_built: bool = False
        # change evaluation-degradation-governance T-2.2:judge 调用结果采集器。
        # RAGAS 把 judge 的原始响应吞掉了,只留一个 NaN —— 采集器挂在项目
        # 自己的适配层上,是唯一还能看到「为什么判不出来」的位置。
        # 显式持有并注入(非全局状态,硬约束 4),生命周期与单次 evaluate() 对齐。
        from src.observability.evaluation.judge_call_collector import JudgeCallCollector

        self._call_collector = JudgeCallCollector()
        # 最近一次 evaluate() 中各 metric 的降级原因;由 EvalRunner 读取。
        self._last_degradation_reasons: dict[str, str] = {}

    def _ensure_wrappers(self) -> None:
        """首次评估时构建 Judge / embedding 包装,后续重用。

        通过 ``src.observability.evaluation._ragas_wrappers`` 中的工厂调用
        ``LLMFactory.create`` 与 ``EmbeddingFactory.create``,把项目实例适配为
        RAGAS 期待的 ``BaseRagasLLM`` / ``BaseRagasEmbeddings``。

        Raises:
            ImportError: ragas / langchain-core 缺失时(实际上 T001 已固定依赖,
                此处仅作 defensive)。
        """
        if self._wrappers_built:
            return
        from src.observability.evaluation._ragas_wrappers import (
            build_ragas_embedding,
            build_ragas_judge,
        )

        # collector 注入 judge 包装:RAGAS 每次回调项目 BaseLLM 时,调用结果
        # (空响应 / 超时 / 上游拒绝)都会被记下来,供 evaluate() 归约成原因。
        self._judge_wrapper = build_ragas_judge(self.settings, collector=self._call_collector)
        self._embedding_wrapper = build_ragas_embedding(self.settings)
        self._wrappers_built = True

    def get_judge_identifier(self) -> str:
        """返回 Judge LLM 的 ``"<provider>:<model>"`` 标识 (FR-016)。

        Used by EvalRunner 写入 EvaluationReport.judge_llm_identifier 字段,
        让跨 Judge 跑出的报告可追溯、可对比。
        """
        from src.observability.evaluation._ragas_wrappers import (
            get_judge_identifier as _get_judge_id,
        )

        return _get_judge_id(self.settings)

    def get_embedding_identifier(self) -> str:
        """返回评估期 embedding 的 ``"<provider>:<model>"`` 标识 (FR-017)。

        默认为顶层 embedding 复用(spec § FR-017 避免 train-eval skew)。
        """
        from src.observability.evaluation._ragas_wrappers import (
            get_embedding_identifier as _get_embedding_id,
        )

        return _get_embedding_id(self.settings)

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
            self._last_degradation_reasons = self._reduce_degradation_reasons(metrics)
            if trace:
                trace.add_metadata("metrics", metrics)
            return metrics

        # 每条 case 独立采集 —— 不 reset 会让上一条的失败串味到这一条
        self._call_collector.reset()

        metrics = self._evaluate_with_ragas(
            query=query,
            **kwargs,
        )

        self._last_degradation_reasons = self._reduce_degradation_reasons(metrics)

        if trace:
            trace.add_metadata("metrics", metrics)
            if self._last_degradation_reasons:
                trace.add_metadata("degradation_reasons", self._last_degradation_reasons)
        return metrics

    def get_last_degradation_reasons(self) -> dict[str, str]:
        """返回最近一次 ``evaluate()`` 中各降级 metric 的原因。

        由 ``EvalRunner`` 在每条 case 评估后读取,写入 ``EvalCaseResult``。
        用「拉」而不是「返回值里带」,是为了不改 ``BaseEvaluator.evaluate()``
        的签名 —— 那是所有 evaluator 共用的契约,而降级归因只有 LLM 判定类
        后端才有意义。

        Returns:
            metric 名 -> ``DegradationReason`` 值;无降级时为空字典。
        """
        return dict(self._last_degradation_reasons)

    def _reduce_degradation_reasons(self, metrics: dict[str, float]) -> dict[str, str]:
        """把本次调用记录归约成各降级 metric 的原因。

        当前实现给同一条 case 内所有降级 metric **同一个**原因 —— 因为 RAGAS
        的四个指标共用一批 judge 调用,调用与指标之间没有可靠的归属关系。
        这是 design § Risks 里显式记录的已知局限:宁可粗一点也不臆造归属,
        兜底占比(``unknown_reason_warn``)就是用来暴露归约能力不足的。

        Args:
            metrics: 本次评估产出的 metric 字典(可能含 NaN)。

        Returns:
            metric 名 -> 原因;无降级时为空字典。
        """
        degraded = [name for name, value in metrics.items() if self._is_nan_value(value)]
        if not degraded:
            return {}
        reason = self._call_collector.dominant_reason()
        return {name: reason for name in degraded}

    @staticmethod
    def _is_nan_value(value: Any) -> bool:
        """判断 metric 值是否为 NaN(降级标志)。"""
        import math as _math

        try:
            return _math.isnan(float(value))
        except (TypeError, ValueError):
            return False

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

        # FR-016 / FR-017:Judge 与 embedding 通过 _ragas_wrappers 经 LLMFactory /
        # EmbeddingFactory 注入;kwargs 仅保留作为单元测试 mock 通道
        # (kwargs.get("llm") / .get("embeddings") 非空时优先使用,便于测试隔离)。
        kwarg_llm = kwargs.get("llm")
        kwarg_embeddings = kwargs.get("embeddings")
        if kwarg_llm is None or kwarg_embeddings is None:
            self._ensure_wrappers()
        ragas_llm = kwarg_llm if kwarg_llm is not None else self._judge_wrapper
        ragas_embeddings = (
            kwarg_embeddings if kwarg_embeddings is not None else self._embedding_wrapper
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
                llm=ragas_llm,
                embeddings=ragas_embeddings,
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

    def zero_metrics(self) -> dict[str, float]:
        """返回 Ragas 标准四指标的零值模板，供空检索 fallback 使用。"""
        return {
            "faithfulness": 0.0,
            "answer_relevancy": 0.0,
            "context_precision": 0.0,
            "context_recall": 0.0,
        }
