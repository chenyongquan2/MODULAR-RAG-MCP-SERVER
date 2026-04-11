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
    """单条黄金测试用例。"""

    query: str
    expected_chunk_ids: list[str]
    expected_sources: list[str] = field(default_factory=list)


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
    ) -> None:
        """初始化评估运行器。

        Args:
            settings: 全局配置。
            hybrid_search: 已初始化的检索引擎，需提供 ``search()`` 方法。
            evaluator: 评估器实例（custom/ragas/composite）。

        Raises:
            ValueError: 任一依赖为空时抛出。
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

            if not isinstance(query, str) or not query.strip():
                raise ValueError(f"test_cases[{index}].query must be a non-empty string")
            if not isinstance(expected_chunk_ids, list) or not expected_chunk_ids:
                raise ValueError(
                    f"test_cases[{index}].expected_chunk_ids must be a non-empty list"
                )
            if not isinstance(expected_sources, list):
                raise ValueError(f"test_cases[{index}].expected_sources must be a list")

            cases.append(
                EvalCase(
                    query=query,
                    expected_chunk_ids=[str(chunk_id) for chunk_id in expected_chunk_ids],
                    expected_sources=[str(source) for source in expected_sources],
                )
            )

        return cases

    def _evaluate_case(
        self,
        case: EvalCase,
        retrieval_results: list[RetrievalResult],
    ) -> EvalCaseResult:
        """评估单条测试用例并返回结果对象。"""
        retrieved_chunk_ids = [result.chunk_id for result in retrieval_results]
        retrieved_sources = self._extract_sources(retrieval_results)

        hit, reciprocal_rank = self._compute_hit_and_rr(
            retrieved_chunk_ids=retrieved_chunk_ids,
            expected_chunk_ids=case.expected_chunk_ids,
        )
        source_hit = self._compute_source_hit(
            retrieved_sources=retrieved_sources,
            expected_sources=case.expected_sources,
        )

        # 这里兼容 evaluator 的“非空输入”约束：无召回时返回 0 指标，避免整体中断。
        if retrieved_chunk_ids:
            try:
                metrics = self._evaluator.evaluate(
                    query=case.query,
                    retrieved_ids=retrieved_chunk_ids,
                    golden_ids=case.expected_chunk_ids,
                    expected_sources=case.expected_sources,
                    retrieved_sources=retrieved_sources,
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
