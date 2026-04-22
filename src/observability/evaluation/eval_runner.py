"""EvalRunner: 基于 golden test set 执行检索评估并生成报告。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from src.core.settings import Settings
from src.core.types import RetrievalResult
from src.libs.evaluator.base_evaluator import BaseEvaluator


@dataclass
class EvalCase:
    """单条黄金测试用例。

    字段说明：
        - ``query``：用户查询文本。
        - ``expected_chunk_ids``：参考检索 ID，供检索类指标（Hit/MRR）使用。
        - ``expected_sources``：参考来源文档（可选）。
        - ``ground_truth``：参考答案文本，供 RAGAS 生成类指标
          （context_precision / context_recall）使用；无此字段时相关指标无意义。
    """

    query: str
    expected_chunk_ids: list[str]
    expected_sources: list[str] = field(default_factory=list)
    ground_truth: str = ""


@dataclass
class EvalCaseResult:
    """单条用例执行结果。"""

    query: str
    expected_chunk_ids: list[str]
    expected_sources: list[str]
    retrieved_chunk_ids: list[str]
    retrieved_sources: list[str]
    hit: bool
    reciprocal_rank: float
    source_hit: bool
    metrics: dict[str, float]
    # RAGAS 所需的文本字段（非检索类场景可为空字符串 / 空列表）
    answer: str = ""
    contexts: list[str] = field(default_factory=list)
    ground_truth: str = ""

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return asdict(self)


@dataclass
class EvalReport:
    """评估报告。"""

    total_cases: int
    hit_rate: float
    mrr: float
    source_hit_rate: float
    aggregate_metrics: dict[str, float]
    case_results: list[EvalCaseResult]

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "total_cases": self.total_cases,
            "hit_rate": self.hit_rate,
            "mrr": self.mrr,
            "source_hit_rate": self.source_hit_rate,
            "aggregate_metrics": self.aggregate_metrics,
            "case_results": [result.to_dict() for result in self.case_results],
        }


class EvalRunner:
    """评估运行器。

    读取 golden test set，逐条执行 HybridSearch，调用 evaluator 计算指标，
    最终输出聚合报告（hit_rate / mrr / 详细结果）。
    """

    def __init__(
        self,
        settings: Settings,
        hybrid_search: Any,
        evaluator: BaseEvaluator,
        response_builder: Optional[Any] = None,
    ) -> None:
        """初始化评估运行器。

        Args:
            settings: 全局配置。
            hybrid_search: 已初始化的检索引擎，需提供 ``search()`` 方法。
            evaluator: 评估器实例（custom/ragas/composite）。
            response_builder: 可选的响应构建器（提供 ``build(query, results)`` 方法）。
                RAGAS 的 ``faithfulness`` / ``answer_relevancy`` 等指标依赖 LLM 生成的
                answer；若不注入则这些指标无法计算。仅做检索类评估时可留空。

        Raises:
            ValueError: 任一必需依赖为空时抛出。
        """
        if settings is None:
            raise ValueError("settings cannot be None")
        if hybrid_search is None:
            raise ValueError("hybrid_search cannot be None")
        if evaluator is None:
            raise ValueError("evaluator cannot be None")

        self._settings = settings
        self._hybrid_search = hybrid_search
        self._evaluator = evaluator
        self._response_builder = response_builder

    def run(
        self,
        test_set_path: str,
        top_k: Optional[int] = None,
        filters: Optional[dict[str, Any]] = None,
    ) -> EvalReport:
        """运行评估并返回报告。

        Args:
            test_set_path: golden test set 文件路径。
            top_k: 每条 query 的召回数量，默认取配置 ``retrieval.top_k_final``。
            filters: 可选过滤器（例如 ``{"collection": "default"}``）。

        Returns:
            EvalReport: 聚合后的评估报告。

        Raises:
            ValueError: 输入参数不合法或测试集格式错误。
            RuntimeError: 检索/评估过程执行失败。
        """
        cases = self._load_test_cases(test_set_path)
        if not cases:
            raise ValueError("golden test set contains no test cases")

        effective_top_k = top_k or getattr(self._settings.retrieval, "top_k_final", 10)
        if effective_top_k <= 0:
            raise ValueError("top_k must be a positive integer")

        results: list[EvalCaseResult] = []
        metric_sums: dict[str, float] = {}
        hit_count = 0
        rr_sum = 0.0
        source_hit_count = 0

        for case in cases:
            try:
                retrieval_results = self._hybrid_search.search(
                    query=case.query,
                    top_k=effective_top_k,
                    filters=filters,
                )
            except Exception as exc:
                raise RuntimeError(f"failed to run retrieval for query '{case.query}': {exc}") from exc

            case_result = self._evaluate_case(case, retrieval_results)
            results.append(case_result)

            if case_result.hit:
                hit_count += 1
            rr_sum += case_result.reciprocal_rank
            if case_result.source_hit:
                source_hit_count += 1

            for metric_name, value in case_result.metrics.items():
                metric_sums[metric_name] = metric_sums.get(metric_name, 0.0) + float(value)

        total = len(results)
        aggregate_metrics = {
            metric_name: metric_total / total for metric_name, metric_total in metric_sums.items()
        }

        return EvalReport(
            total_cases=total,
            hit_rate=hit_count / total,
            mrr=rr_sum / total,
            source_hit_rate=source_hit_count / total,
            aggregate_metrics=aggregate_metrics,
            case_results=results,
        )

    def _load_test_cases(self, test_set_path: str) -> list[EvalCase]:
        """加载并校验 golden test set。"""
        file_path = Path(test_set_path)
        if not file_path.exists():
            raise ValueError(f"golden test set file not found: {test_set_path}")

        try:
            raw_data = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"golden test set is not valid JSON: {exc}") from exc

        test_cases_raw = raw_data.get("test_cases")
        if not isinstance(test_cases_raw, list):
            raise ValueError("golden test set must contain a 'test_cases' list")

        cases: list[EvalCase] = []
        for index, item in enumerate(test_cases_raw):
            if not isinstance(item, dict):
                raise ValueError(f"test_cases[{index}] must be an object")

            query = item.get("query")
            expected_chunk_ids = item.get("expected_chunk_ids")
            expected_sources = item.get("expected_sources", [])
            ground_truth = item.get("ground_truth", "")

            if not isinstance(query, str) or not query.strip():
                raise ValueError(f"test_cases[{index}].query must be a non-empty string")
            if not isinstance(expected_chunk_ids, list) or not expected_chunk_ids:
                raise ValueError(
                    f"test_cases[{index}].expected_chunk_ids must be a non-empty list"
                )
            if not isinstance(expected_sources, list):
                raise ValueError(f"test_cases[{index}].expected_sources must be a list")
            if not isinstance(ground_truth, str):
                raise ValueError(
                    f"test_cases[{index}].ground_truth must be a string if provided"
                )

            cases.append(
                EvalCase(
                    query=query,
                    expected_chunk_ids=[str(chunk_id) for chunk_id in expected_chunk_ids],
                    expected_sources=[str(source) for source in expected_sources],
                    ground_truth=ground_truth,
                )
            )

        return cases

    def _evaluate_case(
        self,
        case: EvalCase,
        retrieval_results: list[RetrievalResult],
    ) -> EvalCaseResult:
        """评估单条测试用例并返回结果对象。

        关键行为：
            - 抽取检索结果的真实文本作为 ``contexts``（供 RAGAS 类指标使用）。
            - 若注入了 ``response_builder``，走完整 RAG 链路生成 ``answer``。
            - 将 ``answer`` / ``contexts`` / ``ground_truth`` 以显式 kwargs
              方式传给 evaluator，避免"传 ID 当文本"的错误语义。
        """
        retrieved_chunk_ids = [result.chunk_id for result in retrieval_results]
        retrieved_sources = self._extract_sources(retrieval_results)
        # 关键修复：从检索结果抽取真实文本内容（chunk.text），而不是 ID。
        contexts_text = [result.text for result in retrieval_results]

        hit, reciprocal_rank = self._compute_hit_and_rr(
            retrieved_chunk_ids=retrieved_chunk_ids,
            expected_chunk_ids=case.expected_chunk_ids,
        )
        source_hit = self._compute_source_hit(
            retrieved_sources=retrieved_sources,
            expected_sources=case.expected_sources,
        )

        # 如果注入了 response_builder，走完整 RAG 链路生成 answer。
        # 这是 RAGAS faithfulness / answer_relevancy 指标的前提条件。
        answer_text = ""
        if self._response_builder is not None and retrieval_results:
            try:
                structured = self._response_builder.build(
                    query=case.query,
                    results=retrieval_results,
                )
                # ResponseBuilder 返回 StructuredContent(markdown=..., citations=...)
                answer_text = getattr(structured, "markdown", "") or str(structured)
            except Exception as exc:
                raise RuntimeError(
                    f"failed to build answer for query '{case.query}': {exc}"
                ) from exc

        # 兼容 evaluator 的"非空输入"约束：无召回时返回 0 指标，避免整体中断。
        if retrieved_chunk_ids:
            try:
                metrics = self._evaluator.evaluate(
                    query=case.query,
                    retrieved_ids=retrieved_chunk_ids,
                    golden_ids=case.expected_chunk_ids,
                    expected_sources=case.expected_sources,
                    retrieved_sources=retrieved_sources,
                    # —— RAGAS 所需的文本字段，显式传递 ——
                    answer=answer_text,
                    contexts=contexts_text,
                    ground_truth=case.ground_truth,
                )
            except Exception as exc:
                raise RuntimeError(f"failed to evaluate query '{case.query}': {exc}") from exc
        else:
            metrics = {"hit_rate": 0.0, "mrr": 0.0}

        return EvalCaseResult(
            query=case.query,
            expected_chunk_ids=case.expected_chunk_ids,
            expected_sources=case.expected_sources,
            retrieved_chunk_ids=retrieved_chunk_ids,
            retrieved_sources=retrieved_sources,
            hit=hit,
            reciprocal_rank=reciprocal_rank,
            source_hit=source_hit,
            metrics={key: float(value) for key, value in metrics.items()},
            answer=answer_text,
            contexts=contexts_text,
            ground_truth=case.ground_truth,
        )

    @staticmethod
    def _compute_hit_and_rr(
        retrieved_chunk_ids: list[str],
        expected_chunk_ids: list[str],
    ) -> tuple[bool, float]:
        """计算单条 query 的 hit 与 reciprocal rank。"""
        expected_set = set(expected_chunk_ids)
        for index, chunk_id in enumerate(retrieved_chunk_ids, start=1):
            if chunk_id in expected_set:
                return True, 1.0 / index
        return False, 0.0

    @staticmethod
    def _compute_source_hit(
        retrieved_sources: list[str],
        expected_sources: list[str],
    ) -> bool:
        """计算 source 级命中（命中任一 source 即视为命中）。"""
        if not expected_sources:
            return False
        return bool(set(retrieved_sources) & set(expected_sources))

    @staticmethod
    def _extract_sources(results: list[RetrievalResult]) -> list[str]:
        """从检索结果中抽取 source 标识。"""
        sources: list[str] = []
        for result in results:
            source = result.metadata.get("source") or result.metadata.get("source_path")
            if source:
                sources.append(str(source))
        return sources
