"""EvalRunner: 基于 golden test set 执行检索评估并生成报告 (Feature-001 后扩展)。

Feature-001 改造点 (T010, refs spec FR-007 / FR-013 / FR-015 / FR-016 / FR-017):
- ``EvalCase`` 加 ``tags`` 字段(Optional,US1 占位允许 None,US2 后必填)
- ``EvalReport`` 大扩展:加 ``run_id`` / ``collection`` / ``test_set_version`` /
  ``created_at`` / ``acceptance_thresholds_snapshot`` / ``acceptance_status`` /
  ``judge_llm_identifier`` / ``embedding_identifier`` / ``degraded_case_count`` /
  ``aggregate_metrics_by_tag`` 字段
- ``_load_test_cases()`` 解析 tags 与 ``_schema_version`` 校验
- ``run()`` 入口 FR-007 chunk_id 存在性校验
- 新增 ``_aggregate_by_tag(...)`` helper(FR-015 by-tag 切片,< min 样本跳过)
- 新增 ``_archive_report(...)`` helper(写 ``logs/evaluation_reports/<run_id>.json``
  + 追加 ``index.jsonl`` 一行精简元数据)
- 收集 NaN metrics → ``degraded_case_count++``,不计入分母(避免污染均值)
- 调用 ``ThresholdEvaluator`` 计算 ``acceptance_status``;从 evaluator 取
  ``judge_llm_identifier`` / ``embedding_identifier``(若 evaluator 不支持则 None)
"""

from __future__ import annotations

import json
import math as _math
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.core.settings import Settings
from src.core.types import AcceptanceStatus, RetrievalResult, TestCaseTags
from src.libs.evaluator.base_evaluator import BaseEvaluator
from src.observability.evaluation.threshold_evaluator import ThresholdEvaluator
from src.observability.logger import get_logger

logger = get_logger(__name__)


@dataclass
class EvalCase:
    """单条黄金测试用例。

    字段说明：
        - ``query``：用户查询文本。
        - ``expected_chunk_ids``：参考检索 ID,供检索类指标(Hit/MRR)使用。
        - ``expected_sources``：参考来源文档(可选)。
        - ``ground_truth``：参考答案文本,供 RAGAS 生成类指标
          (context_precision / context_recall)使用;无此字段时相关指标无意义。
        - ``tags``：(Feature-001 新增)测试用例标签,用于 by-tag 切片聚合
          (FR-014 / FR-015)。US1 占位阶段允许 ``None``;US2 后必填。
    """

    query: str
    expected_chunk_ids: list[str]
    expected_sources: list[str] = field(default_factory=list)
    ground_truth: str = ""
    tags: Optional[TestCaseTags] = None


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
    # RAGAS 所需的文本字段(非检索类场景可为空字符串 / 空列表)
    answer: str = ""
    contexts: list[str] = field(default_factory=list)
    ground_truth: str = ""
    # Feature-001:用例标签(从 EvalCase 透传,供 by-tag 聚合使用)
    tags: Optional[TestCaseTags] = None

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典(tags 为 None 时不输出该字段)。"""
        result = asdict(self)
        # tags=None 时去掉该字段,保持 JSON 紧凑
        if result.get("tags") is None:
            result.pop("tags", None)
        return result


@dataclass
class EvalReport:
    """评估报告 (Feature-001 后扩展)。

    字段命名遵循 specs/001-rag-acceptance/contracts/evaluation_report.schema.md。
    """

    total_cases: int
    hit_rate: float
    mrr: float
    source_hit_rate: float
    aggregate_metrics: dict[str, float]
    case_results: list[EvalCaseResult]
    # 基线对比字段(由 EvaluationService.compare_with_baseline() 或 US3
    # BaselineManager 填充;US1 阶段保持 None)
    baseline_id: Optional[str] = None
    delta_hit_rate: Optional[float] = None
    delta_mrr: Optional[float] = None
    delta_aggregate_metrics: Optional[dict[str, float]] = None
    # ──────── Feature-001 新增字段 ────────
    run_id: str = ""
    collection: str = ""
    test_set_path: str = ""
    test_set_version: str = ""
    created_at: str = ""
    judge_llm_identifier: Optional[str] = None
    embedding_identifier: Optional[str] = None
    acceptance_thresholds_snapshot: dict[str, float] = field(default_factory=dict)
    acceptance_status: Optional[AcceptanceStatus] = None
    degraded_case_count: int = 0
    aggregate_metrics_by_tag: dict[str, dict[str, dict[str, Optional[float]]]] = field(
        default_factory=dict
    )
    per_tag_delta: Optional[dict[str, dict[str, Optional[dict[str, float]]]]] = None

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。

        - 顶层默认含 hit_rate/mrr/source_hit_rate/aggregate_metrics/case_results,
          以及 Feature-001 加入的 run_id/collection 等字段(非空时输出)。
        - delta 类字段仅当 baseline_id 非空时输出,保持向后兼容。
        - acceptance_status 是 ``AcceptanceStatus`` 枚举,序列化为字符串值。
        """
        result: dict[str, Any] = {
            "total_cases": self.total_cases,
            "hit_rate": self.hit_rate,
            "mrr": self.mrr,
            "source_hit_rate": self.source_hit_rate,
            "aggregate_metrics": self.aggregate_metrics,
            "case_results": [r.to_dict() for r in self.case_results],
        }
        # Feature-001 字段(非空时输出,保持 JSON 紧凑)
        if self.run_id:
            result["run_id"] = self.run_id
        if self.collection:
            result["collection"] = self.collection
        if self.test_set_path:
            result["test_set_path"] = self.test_set_path
        if self.test_set_version:
            result["test_set_version"] = self.test_set_version
        if self.created_at:
            result["created_at"] = self.created_at
        if self.judge_llm_identifier is not None:
            result["judge_llm_identifier"] = self.judge_llm_identifier
        if self.embedding_identifier is not None:
            result["embedding_identifier"] = self.embedding_identifier
        if self.acceptance_thresholds_snapshot:
            result["acceptance_thresholds_snapshot"] = dict(self.acceptance_thresholds_snapshot)
        if self.acceptance_status is not None:
            result["acceptance_status"] = self.acceptance_status.value
        # degraded_case_count 总是输出(0 也有意义,表示无降级)
        result["degraded_case_count"] = self.degraded_case_count
        if self.aggregate_metrics_by_tag:
            result["aggregate_metrics_by_tag"] = self.aggregate_metrics_by_tag
        # 仅在 baseline 信息存在时才输出 delta 字段,保持向后兼容
        if self.baseline_id is not None:
            result["baseline_id"] = self.baseline_id
            result["delta_hit_rate"] = self.delta_hit_rate
            result["delta_mrr"] = self.delta_mrr
            result["delta_aggregate_metrics"] = self.delta_aggregate_metrics
            if self.per_tag_delta is not None:
                result["per_tag_delta"] = self.per_tag_delta
        return result


class EvalRunner:
    """评估运行器。

    读取 golden test set,逐条执行 HybridSearch,调用 evaluator 计算指标,
    最终输出聚合报告 (Feature-001 后含 acceptance_status / by-tag 聚合 / 归档)。
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
            hybrid_search: 已初始化的检索引擎,需提供 ``search()`` 方法。
            evaluator: 评估器实例(custom/ragas/composite)。
            response_builder: 可选的响应构建器(提供 ``build(query, results)`` 方法)。
                RAGAS 的 ``faithfulness`` / ``answer_relevancy`` 等指标依赖 LLM 生成的
                answer;若不注入则这些指标无法计算。仅做检索类评估时可留空。

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
        # FR-007 chunk_id 校验需要 vector store;延迟构建避免无 chunk_id 校验时
        # 也要为创建 store 付出代价(LangChain client init 可能涉及 IO)
        self._vector_store: Any = None

    def run(
        self,
        test_set_path: str,
        top_k: Optional[int] = None,
        filters: Optional[dict[str, Any]] = None,
        archive: bool = True,
    ) -> EvalReport:
        """运行评估并返回报告。

        Args:
            test_set_path: golden test set 文件路径。
            top_k: 每条 query 的召回数量,默认取配置 ``retrieval.top_k_final``。
            filters: 可选过滤器(例如 ``{"collection": "default"}``)。
            archive: 是否把报告归档到 ``settings.evaluation.report_archive_dir``
                (默认 True,写 ``<run_id>.json`` + 追加 ``index.jsonl``);
                CLI 通过 ``--no-archive`` 设为 False。

        Returns:
            EvalReport: 聚合后的评估报告(Feature-001 后含 acceptance_status 等)。

        Raises:
            ValueError: 输入参数不合法或测试集格式错误,或 FR-007 校验失败时抛出。
            RuntimeError: 检索/评估过程执行失败。
        """
        run_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        cases, test_set_meta = self._load_test_cases(test_set_path)
        if not cases:
            raise ValueError("golden test set contains no test cases")

        effective_top_k = top_k or getattr(self._settings.retrieval, "top_k_final", 10)
        if effective_top_k <= 0:
            raise ValueError("top_k must be a positive integer")

        # FR-007: 评估开始前校验所有 expected_chunk_ids 在 vector store 中存在
        # (configurable via settings.evaluation.chunk_id_validation,默认开启)
        self._validate_chunk_ids_exist(cases, filters)

        results: list[EvalCaseResult] = []
        # 维护三组聚合状态:
        # 1. all_metric_keys:所有 case 中出现过的 metric key 全集
        #    (即使该 metric 在所有 case 中都是 NaN,key 仍要保留 — 否则
        #    SC-001 的"8 项指标全部产出"会因为某项全降级而误判)
        # 2. metric_value_lists:每个 metric 的有效值列表(已剔除 NaN)
        #    用于按 case 数取均值(避免 NaN 拉低分母)
        # 3. degraded_case_count:任一 metric NaN 即视为该 case 降级(SC-006)
        all_metric_keys: set[str] = set()
        metric_value_lists: dict[str, list[float]] = {}
        hit_count = 0
        rr_sum = 0.0
        source_hit_count = 0
        degraded_case_count = 0

        for case in cases:
            try:
                retrieval_results = self._hybrid_search.search(
                    query=case.query,
                    top_k=effective_top_k,
                    filters=filters,
                )
            except Exception as exc:
                raise RuntimeError(
                    f"failed to run retrieval for query '{case.query}': {exc}"
                ) from exc

            case_result = self._evaluate_case(case, retrieval_results)
            results.append(case_result)

            if case_result.hit:
                hit_count += 1
            rr_sum += case_result.reciprocal_rank
            if case_result.source_hit:
                source_hit_count += 1

            # FR-001:NaN 仅允许在显式降级场景。本 case 任一 metric NaN 即计入
            # degraded_case_count(SC-006:占比 ≤ 5% 才算合格基线质量)
            case_has_nan = False
            for metric_name, value in case_result.metrics.items():
                # 先记录 metric key 出现过(无论是否 NaN),保证 aggregate 含完整 key 集
                all_metric_keys.add(metric_name)
                if self._is_nan(value):
                    case_has_nan = True
                    continue  # 不计入分母,避免污染均值
                metric_value_lists.setdefault(metric_name, []).append(float(value))
            if case_has_nan:
                degraded_case_count += 1

        total = len(results)
        # 按"有效值数量"取均值;若某 metric 在所有 case 中全 NaN,聚合层
        # 输出 NaN(JSON 序列化时为 "NaN" 字面量)而非丢 key,这样 SC-001
        # "8 项指标全部产出"判据可以稳定判断,ThresholdEvaluator 也能区分
        # "缺失 key"(配置错误,不应发生)与"NaN"(显式降级)。
        aggregate_metrics: dict[str, float] = {}
        for metric_name in all_metric_keys:
            values = metric_value_lists.get(metric_name, [])
            aggregate_metrics[metric_name] = (
                (sum(values) / len(values)) if values else float("nan")
            )

        # FR-015: by-tag 切片聚合 (content_type / difficulty 两维)
        aggregate_metrics_by_tag = self._aggregate_by_tag(
            results, dimensions=self._settings.evaluation.by_tag_dimensions,
            min_samples=self._settings.evaluation.tag_slice_min_samples,
        )

        # FR-013: 用 ThresholdEvaluator 计算 acceptance_status
        threshold_evaluator = ThresholdEvaluator(
            self._settings.evaluation.acceptance_thresholds
        )
        acceptance_status = threshold_evaluator.evaluate(aggregate_metrics)
        thresholds_snapshot = threshold_evaluator.thresholds_snapshot

        # FR-016 / FR-017: judge_llm_identifier / embedding_identifier
        # 从 evaluator 上取(若 evaluator 不支持这些方法则 None,作为 custom-only
        # 评估场景下的合理默认)
        judge_id = self._safe_call(self._evaluator, "get_judge_identifier")
        embedding_id = self._safe_call(self._evaluator, "get_embedding_identifier")

        report = EvalReport(
            total_cases=total,
            hit_rate=hit_count / total if total else 0.0,
            mrr=rr_sum / total if total else 0.0,
            source_hit_rate=source_hit_count / total if total else 0.0,
            aggregate_metrics=aggregate_metrics,
            case_results=results,
            run_id=run_id,
            collection=str((filters or {}).get("collection", self._settings.vector_store.collection_name)),
            test_set_path=test_set_path,
            test_set_version=test_set_meta.get("version", ""),
            created_at=created_at,
            judge_llm_identifier=judge_id,
            embedding_identifier=embedding_id,
            acceptance_thresholds_snapshot=thresholds_snapshot,
            acceptance_status=acceptance_status,
            degraded_case_count=degraded_case_count,
            aggregate_metrics_by_tag=aggregate_metrics_by_tag,
        )

        # T032 (FR-009):若该 collection 已有当前基线,自动算 delta 嵌入 report
        # (baseline_id / delta_aggregate_metrics / delta_hit_rate / delta_mrr /
        # per_tag_delta);无基线时这些字段保持 None,JSON 输出向后兼容
        self._attach_baseline_delta(report)

        # 默认归档到 settings.evaluation.report_archive_dir;CLI 通过
        # --no-archive 关闭。失败仅警告不抛错(不阻断 stdout 输出报告)。
        if archive:
            try:
                self._archive_report(report)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Failed to archive evaluation report: %s", exc)

        return report

    # ------------------------------------------------------------------
    # FR-007: chunk_id 存在性校验
    # ------------------------------------------------------------------

    def _validate_chunk_ids_exist(
        self,
        cases: list[EvalCase],
        filters: Optional[dict[str, Any]],
    ) -> None:
        """评估开始前校验所有 expected_chunk_ids 在 vector store 中存在 (FR-007)。

        失败时抛 ``ValueError`` 含 case index + 缺失 chunk_id,可定位修复点。

        Args:
            cases: 已加载的测试用例列表。
            filters: 评估 filters,用于读取 collection 名(可能覆盖 settings 默认)。

        Raises:
            ValueError: 任一 chunk_id 在 collection 中不存在。
        """
        if not self._settings.evaluation.chunk_id_validation:
            logger.info("chunk_id_validation disabled — skipping FR-007 check")
            return

        # 收集所有 expected_chunk_ids 去重
        all_expected: set[str] = set()
        for case in cases:
            all_expected.update(case.expected_chunk_ids)
        if not all_expected:
            return

        collection_name = str(
            (filters or {}).get("collection")
            or self._settings.vector_store.collection_name
        )

        # 通过 VectorStoreFactory 创建 (lazy);沿用项目现有 vector_store 抽象层
        try:
            vector_store = self._get_vector_store()
            # base_vector_store.get_by_ids 返回的 dict[id, ...] 仅含存在的 ID;
            # 对 chroma 后端实现,内部默认查 settings.vector_store.collection_name。
            # 若 filters 指定了不同 collection,需要通过 store 实例的查询接口指定;
            # 但本项目的 base_vector_store.get_by_ids 不直接支持 collection 参数,
            # 默认就走 settings.vector_store.collection_name。这里做 best-effort:
            # 若 filters 指定的 collection ≠ settings 默认,降级为警告 + 继续。
            if collection_name != self._settings.vector_store.collection_name:
                logger.warning(
                    "chunk_id_validation: filters.collection=%s differs from "
                    "settings.vector_store.collection_name=%s; validation "
                    "performed against settings default (best-effort)",
                    collection_name,
                    self._settings.vector_store.collection_name,
                )

            existing_records = vector_store.get_by_ids(list(all_expected))
            existing_ids = {rec.get("id") for rec in existing_records if isinstance(rec, dict)}
        except ValueError:
            # 输入合法性问题(如空 list)直接重抛
            raise
        except Exception as exc:
            raise ValueError(
                f"chunk_id_validation failed: cannot query vector store '{collection_name}': {exc} "
                f"(set evaluation.chunk_id_validation=false to skip this check)"
            ) from exc

        # 逐 case 找出第一个不存在的 chunk_id,产出可定位错误
        for idx, case in enumerate(cases):
            for chunk_id in case.expected_chunk_ids:
                if chunk_id not in existing_ids:
                    short_query = case.query[:50] + ("..." if len(case.query) > 50 else "")
                    raise ValueError(
                        f"golden_test_set chunk_id missing: case[{idx}] "
                        f"'{short_query}' references chunk_id '{chunk_id}' "
                        f"not in collection '{collection_name}' "
                        f"(set evaluation.chunk_id_validation=false to skip this check)"
                    )

        logger.info(
            "FR-007 chunk_id validation passed: %d unique IDs across %d cases",
            len(all_expected),
            len(cases),
        )

    def _get_vector_store(self) -> Any:
        """Lazy 构建 vector store(FR-007 校验时按需触发)。"""
        if self._vector_store is None:
            from src.libs.vector_store.vector_store_factory import VectorStoreFactory

            self._vector_store = VectorStoreFactory.create(self._settings)
        return self._vector_store

    # ------------------------------------------------------------------
    # 测试集加载
    # ------------------------------------------------------------------

    def _load_test_cases(self, test_set_path: str) -> tuple[list[EvalCase], dict[str, Any]]:
        """加载并校验 golden test set。

        Returns:
            (cases, meta) 二元组。meta 含 ``version`` / ``language`` /
            ``source_corpus_collection`` 等顶层字段,供 EvalReport 填充。
        """
        file_path = Path(test_set_path)
        if not file_path.exists():
            raise ValueError(f"golden test set file not found: {test_set_path}")

        try:
            raw_data = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"golden test set is not valid JSON: {exc}") from exc

        # _schema_version 校验(Feature-001 引入,缺失时按 1 处理向后兼容)
        schema_version = raw_data.get("_schema_version", 1)
        if schema_version != 1:
            raise ValueError(
                f"unsupported golden_test_set _schema_version={schema_version} "
                "(this build supports version 1)"
            )

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
            tags_raw = item.get("tags")

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

            tags: Optional[TestCaseTags] = None
            if isinstance(tags_raw, dict):
                try:
                    tags = TestCaseTags(
                        content_type=tags_raw["content_type"],
                        difficulty=tags_raw["difficulty"],
                        language=tags_raw["language"],
                        doc_version=tags_raw.get("doc_version", "v1"),
                    )
                except KeyError as exc:
                    raise ValueError(
                        f"test_cases[{index}].tags missing required field: {exc}"
                    ) from exc

            cases.append(
                EvalCase(
                    query=query,
                    expected_chunk_ids=[str(chunk_id) for chunk_id in expected_chunk_ids],
                    expected_sources=[str(source) for source in expected_sources],
                    ground_truth=ground_truth,
                    tags=tags,
                )
            )

        meta = {
            "version": str(raw_data.get("version", "")),
            "language": str(raw_data.get("language", "")),
            "source_corpus_collection": str(raw_data.get("source_corpus_collection", "")),
        }
        return cases, meta

    # ------------------------------------------------------------------
    # 单 case 评估
    # ------------------------------------------------------------------

    def _evaluate_case(
        self,
        case: EvalCase,
        retrieval_results: list[RetrievalResult],
    ) -> EvalCaseResult:
        """评估单条测试用例并返回结果对象。

        关键行为:
            - 抽取检索结果的真实文本作为 ``contexts``(供 RAGAS 类指标使用)。
            - 若注入了 ``response_builder``,走完整 RAG 链路生成 ``answer``。
            - 将 ``answer`` / ``contexts`` / ``ground_truth`` 以显式 kwargs
              方式传给 evaluator,避免"传 ID 当文本"的错误语义。
            - 透传 ``tags`` 到 EvalCaseResult,供后续 by-tag 聚合使用。
        """
        retrieved_chunk_ids = [result.chunk_id for result in retrieval_results]
        retrieved_sources = self._extract_sources(retrieval_results)
        contexts_text = [result.text for result in retrieval_results]

        hit, reciprocal_rank = self._compute_hit_and_rr(
            retrieved_chunk_ids=retrieved_chunk_ids,
            expected_chunk_ids=case.expected_chunk_ids,
        )
        source_hit = self._compute_source_hit(
            retrieved_sources=retrieved_sources,
            expected_sources=case.expected_sources,
        )

        answer_text = ""
        if self._response_builder is not None and retrieval_results:
            try:
                structured = self._response_builder.build(
                    query=case.query,
                    results=retrieval_results,
                )
                answer_text = getattr(structured, "markdown", "") or str(structured)
            except Exception as exc:
                raise RuntimeError(
                    f"failed to build answer for query '{case.query}': {exc}"
                ) from exc

        if retrieved_chunk_ids:
            try:
                metrics = self._evaluator.evaluate(
                    query=case.query,
                    retrieved_ids=retrieved_chunk_ids,
                    golden_ids=case.expected_chunk_ids,
                    expected_sources=case.expected_sources,
                    retrieved_sources=retrieved_sources,
                    answer=answer_text,
                    contexts=contexts_text,
                    ground_truth=case.ground_truth,
                )
            except Exception as exc:
                raise RuntimeError(f"failed to evaluate query '{case.query}': {exc}") from exc
        else:
            metrics = self._evaluator.zero_metrics()

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
            tags=case.tags,
        )

    # ------------------------------------------------------------------
    # FR-015: by-tag 切片聚合
    # ------------------------------------------------------------------

    def _aggregate_by_tag(
        self,
        case_results: list[EvalCaseResult],
        dimensions: list[str],
        min_samples: int,
    ) -> dict[str, dict[str, dict[str, Optional[float]]]]:
        """按 ``tags`` 维度对 case_results 做切片聚合。

        命名规则: ``aggregate_metrics_by_<dim>.<value>.<metric>``
        跳过策略: 切片样本量 < ``min_samples`` 时全 metric 为 None,且 entry 含
        ``_skipped_reason: "n_samples=<n><N>"``(spec § FR-015)。

        Args:
            case_results: 已评估完的 case 列表。
            dimensions: 切片维度白名单(MVP 仅支持 content_type / difficulty)。
            min_samples: 切片样本量下限(默认 5)。

        Returns:
            形如 ``{dimension: {value: {metric: float | None}}}`` 的嵌套字典。
            被 skipped 的切片在该 entry 内含 ``_skipped_reason`` key。
        """
        result: dict[str, dict[str, dict[str, Optional[float]]]] = {}

        for dimension in dimensions:
            # 收集该维度下每个 value 对应的 case_result 列表
            buckets: dict[str, list[EvalCaseResult]] = {}
            for cr in case_results:
                if cr.tags is None:
                    continue
                value = getattr(cr.tags, dimension, None)
                if value is None:
                    continue
                buckets.setdefault(str(value), []).append(cr)

            dim_result: dict[str, dict[str, Optional[float]]] = {}
            for value, group in buckets.items():
                if len(group) < min_samples:
                    # 跳过该切片;输出 null + _skipped_reason
                    skip_entry: dict[str, Optional[float]] = {
                        "_skipped_reason": f"n_samples={len(group)}<{min_samples}",  # type: ignore[dict-item]
                    }
                    # 把 union 中所有 metric key 全填 None,保持 schema 一致
                    metric_keys: set[str] = set()
                    for cr in group:
                        metric_keys.update(cr.metrics.keys())
                    for mk in metric_keys:
                        skip_entry[mk] = None
                    dim_result[value] = skip_entry
                    continue

                # 聚合 (跳过 NaN,与主聚合一致)
                value_lists: dict[str, list[float]] = {}
                for cr in group:
                    for metric_name, metric_value in cr.metrics.items():
                        if self._is_nan(metric_value):
                            continue
                        value_lists.setdefault(metric_name, []).append(float(metric_value))
                slice_metrics: dict[str, Optional[float]] = {
                    mk: (sum(vs) / len(vs)) if vs else None
                    for mk, vs in value_lists.items()
                }
                dim_result[value] = slice_metrics

            if dim_result:
                result[dimension] = dim_result

        return result

    # ------------------------------------------------------------------
    # FR-009: Baseline + Delta 集成 (T032)
    # ------------------------------------------------------------------

    def _attach_baseline_delta(self, report: EvalReport) -> None:
        """若该 collection 已有当前基线,在 report 上附 delta 字段(FR-009)。

        失败/无基线时静默不动(report.baseline_id 保持 None,delta_* 也是 None,
        JSON 序列化时 to_dict() 自动跳过这些字段,向后兼容)。

        Args:
            report: 即将归档/输出的 EvalReport(in-place 修改 baseline 相关字段)。
        """
        try:
            from src.observability.evaluation.baseline_manager import BaselineManager
            manager = BaselineManager(self._settings)
            current_baseline = manager.get_current_baseline(report.collection)
            if current_baseline is None:
                return
            baseline_report_dict = manager.load_report(current_baseline.report_id)
            current_report_dict = report.to_dict()
            delta = manager.compute_delta(current_report_dict, baseline_report_dict)
        except Exception as exc:
            # 任何失败都降级为"无 delta"(不阻断主评估输出)
            logger.warning("Failed to compute baseline delta: %s", exc)
            return

        report.baseline_id = current_baseline.report_id
        report.delta_aggregate_metrics = dict(delta.per_metric_delta)
        report.per_tag_delta = dict(delta.per_tag_delta) if delta.per_tag_delta else None
        # 顶层 hit_rate / mrr 的 delta(从 baseline_report 直接读取顶层字段)
        try:
            report.delta_hit_rate = report.hit_rate - float(
                baseline_report_dict.get("hit_rate", 0.0)
            )
            report.delta_mrr = report.mrr - float(baseline_report_dict.get("mrr", 0.0))
        except (TypeError, ValueError):
            pass
        logger.info(
            "Attached baseline delta: baseline_id=%s,主聚合 delta keys=%s",
            current_baseline.report_id,
            sorted(delta.per_metric_delta.keys()),
        )

    # ------------------------------------------------------------------
    # 归档:logs/evaluation_reports/<run_id>.json + index.jsonl
    # ------------------------------------------------------------------

    def _archive_report(self, report: EvalReport) -> None:
        """把完整报告 + 精简元数据落盘 (research § Decision 3)。"""
        archive_dir = Path(self._settings.evaluation.report_archive_dir)
        archive_dir.mkdir(parents=True, exist_ok=True)

        # 完整报告
        report_path = archive_dir / f"{report.run_id}.json"
        report_path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 索引(append-only JSONL)
        index_path = archive_dir / "index.jsonl"
        index_entry = {
            "run_id": report.run_id,
            "collection": report.collection,
            "created_at": report.created_at,
            "acceptance_status": (
                report.acceptance_status.value if report.acceptance_status else None
            ),
            "judge_llm_identifier": report.judge_llm_identifier,
            "embedding_identifier": report.embedding_identifier,
            "total_cases": report.total_cases,
            "is_baseline": False,  # 由 BaselineManager 在 US3 阶段维护
            "report_path": str(report_path),
        }
        with index_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(index_entry, ensure_ascii=False) + "\n")

        logger.info(
            "Archived evaluation report: run_id=%s acceptance_status=%s",
            report.run_id,
            report.acceptance_status.value if report.acceptance_status else "n/a",
        )

    # ------------------------------------------------------------------
    # 工具函数
    # ------------------------------------------------------------------

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
        """计算 source 级命中(命中任一 source 即视为命中)。"""
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

    @staticmethod
    def _is_nan(value: Any) -> bool:
        """检测 NaN(None / 非数也视为 NaN,保持保守判定)。"""
        if value is None:
            return True
        try:
            return _math.isnan(float(value))
        except (TypeError, ValueError):
            return True

    @staticmethod
    def _safe_call(obj: Any, method_name: str) -> Optional[str]:
        """安全调用 obj.method_name() — 没有该方法或失败时返回 None。

        用于 evaluator 上的 get_judge_identifier / get_embedding_identifier
        — custom-only 场景下 evaluator 没这些方法,合理返回 None。
        """
        method = getattr(obj, method_name, None)
        if not callable(method):
            return None
        try:
            value = method()
            return str(value) if value else None
        except Exception:
            return None
