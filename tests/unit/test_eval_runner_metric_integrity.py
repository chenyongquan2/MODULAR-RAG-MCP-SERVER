"""EvalReport.metric_integrity 的单元测试。

refs change evaluation-degradation-governance T-1.1
spec: specs/evaluation/run-integrity/spec.md § 聚合指标必须披露有效分母

背景 —— 为什么这组测试存在:
    judge 判定失败时该 metric 记 NaN,``eval_runner`` 设计为不计入均值分母。
    这个策略是对的(NaN 参与平均会污染整列),但它让样本流失变得**静默**:
    实测 run 80a82405 公布的 faithfulness=0.8887 实为 27 条的均值而非 42 条,
    而报告里读不出这件事。metric_integrity 就是来补这个披露的。

    注意 ``degraded_case_count`` 与 ``metric_integrity`` 的分工:
      - 前者是 **case 级**:该 case 任一 metric NaN 就记一次
      - 后者是 **metric 级**:能回答「这个 metric 的均值到底除以了几」
    两者并存,前者向后兼容,后者是新的真相来源。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from src.core.settings import (
    EmbeddingSettings,
    EvaluationSettings,
    LLMSettings,
    Settings,
    VectorStoreSettings,
    VisionLLMSettings,
)
from src.core.types import DegradationReason, MetricIntegrity, RetrievalResult
from src.libs.evaluator.base_evaluator import BaseEvaluator
from src.observability.evaluation.eval_runner import EvalRunner


pytestmark = pytest.mark.unit


class _StubHybridSearch:
    def search(self, query, top_k, filters=None):
        return [RetrievalResult(chunk_id="c1", score=0.9, text="ctx", metadata={})]


class _StubEvaluatorPartialNan(BaseEvaluator):
    """前 ``nan_cases`` 条的 ragas__faithfulness 返回 NaN,其余正常。

    模拟真实情形:judge 在部分 case 上判不出来,而纯计算的 custom 指标不受影响。
    """

    def __init__(self, nan_cases: int) -> None:
        self._nan_cases = nan_cases
        self._counter = 0

    def evaluate(self, query, retrieved_ids, golden_ids, trace=None, **kwargs):
        self._counter += 1
        faithfulness = (
            float("nan") if self._counter <= self._nan_cases else 0.9
        )
        return {
            "ragas__faithfulness": faithfulness,
            "custom__hit_rate": 1.0,
        }

    def zero_metrics(self):
        return {"ragas__faithfulness": 0.0, "custom__hit_rate": 0.0}


class _StubEvaluatorNoNan(BaseEvaluator):
    """全部 case 判定成功。"""

    def evaluate(self, query, retrieved_ids, golden_ids, trace=None, **kwargs):
        return {"ragas__faithfulness": 0.8, "custom__hit_rate": 1.0}

    def zero_metrics(self):
        return {"ragas__faithfulness": 0.0, "custom__hit_rate": 0.0}


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        llm=LLMSettings(provider="ollama", model="llama3"),
        embedding=EmbeddingSettings(provider="openai", model="text-embedding-3-small"),
        vision_llm=VisionLLMSettings(provider="azure", model="gpt-4o"),
        vector_store=VectorStoreSettings(backend="chroma", collection_name="my_col"),
        evaluation=EvaluationSettings(
            backends=["custom"],
            chunk_id_validation=False,
            report_archive_dir=str(tmp_path / "reports"),
            baseline_store_path=str(tmp_path / "baselines.json"),
        ),
    )


def _write_test_set(tmp_path: Path, n_cases: int) -> Path:
    cases = [
        {
            "query": f"q{i}",
            "expected_chunk_ids": ["c1"],
            "expected_sources": [],
            "ground_truth": "",
        }
        for i in range(n_cases)
    ]
    p = tmp_path / "golden.json"
    p.write_text(
        json.dumps(
            {"_schema_version": 1, "test_cases": cases, "version": "v1.0"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return p


def _run(tmp_path: Path, evaluator: BaseEvaluator, n_cases: int):
    runner = EvalRunner(
        settings=_settings(tmp_path),
        hybrid_search=_StubHybridSearch(),
        evaluator=evaluator,
    )
    return runner.run(test_set_path=str(_write_test_set(tmp_path, n_cases)), archive=False)


# ---------------------------------------------------------------------------
# Scenario: 部分样本降级时披露分母
# ---------------------------------------------------------------------------


class TestDenominatorDisclosure:
    def test_partial_degradation_reports_split_denominator(self, tmp_path: Path) -> None:
        """10 条里 4 条降级 → 有效 6 / 降级 4,且聚合值是那 6 条的均值。"""
        report = _run(tmp_path, _StubEvaluatorPartialNan(nan_cases=4), n_cases=10)

        integrity = report.metric_integrity["ragas__faithfulness"]
        assert integrity.valid_count == 6
        assert integrity.degraded_count == 4
        assert integrity.total_count == 10

        # 聚合值必须等于有效样本的均值 —— 分母是 6 而不是 10
        assert report.aggregate_metrics["ragas__faithfulness"] == pytest.approx(0.9)

    def test_degradation_ratio_computed(self, tmp_path: Path) -> None:
        report = _run(tmp_path, _StubEvaluatorPartialNan(nan_cases=4), n_cases=10)
        assert report.metric_integrity["ragas__faithfulness"].degradation_ratio == pytest.approx(0.4)

    def test_case_level_count_and_metric_level_count_coexist(self, tmp_path: Path) -> None:
        """degraded_case_count(case 级)与 metric_integrity(metric 级)并存且各自正确。"""
        report = _run(tmp_path, _StubEvaluatorPartialNan(nan_cases=4), n_cases=10)
        # case 级:4 条 case 含 NaN
        assert report.degraded_case_count == 4
        # metric 级:faithfulness 降级 4,hit_rate 一条没降级
        assert report.metric_integrity["ragas__faithfulness"].degraded_count == 4
        assert report.metric_integrity["custom__hit_rate"].degraded_count == 0


# ---------------------------------------------------------------------------
# Scenario: 无降级时字段依然存在
# ---------------------------------------------------------------------------


class TestFieldAlwaysPresent:
    def test_zero_degradation_still_emits_fields(self, tmp_path: Path) -> None:
        """字段恒在 —— 阅读方不必区分「无降级」与「字段缺失」。"""
        report = _run(tmp_path, _StubEvaluatorNoNan(), n_cases=5)

        integrity = report.metric_integrity["ragas__faithfulness"]
        assert integrity.valid_count == 5
        assert integrity.degraded_count == 0
        assert integrity.degradation_ratio == 0.0
        assert integrity.reasons == {}

    def test_serialized_report_always_contains_metric_integrity(self, tmp_path: Path) -> None:
        """to_dict() 必须无条件输出 metric_integrity。

        这一点是 BaselineManager 判定「基线是否产自本能力落地之前」的依据:
        字段缺失 == 老报告 == 保守判定不可比。
        """
        report = _run(tmp_path, _StubEvaluatorNoNan(), n_cases=3)
        payload = report.to_dict()

        assert "metric_integrity" in payload
        entry = payload["metric_integrity"]["ragas__faithfulness"]
        assert entry["valid_count"] == 3
        assert entry["degraded_count"] == 0
        assert entry["reasons"] == {}

    def test_report_json_serializable(self, tmp_path: Path) -> None:
        """报告要能落盘 —— MetricIntegrity 必须被 to_dict() 转成纯字典。"""
        report = _run(tmp_path, _StubEvaluatorPartialNan(nan_cases=2), n_cases=5)
        # 不抛异常即通过(NaN 由 json 输出为 NaN 字面量,与既有行为一致)
        json.dumps(report.to_dict())


# ---------------------------------------------------------------------------
# Scenario: 非判定类指标不受影响
# ---------------------------------------------------------------------------


class TestNonJudgedMetrics:
    def test_pure_computed_metric_never_degrades(self, tmp_path: Path) -> None:
        """custom 四项是纯计算,分母恒等于总用例数。"""
        report = _run(tmp_path, _StubEvaluatorPartialNan(nan_cases=7), n_cases=10)

        hit_rate = report.metric_integrity["custom__hit_rate"]
        assert hit_rate.valid_count == 10
        assert hit_rate.degraded_count == 0
        assert hit_rate.degradation_ratio == 0.0


# ---------------------------------------------------------------------------
# 降级原因:T-1.1 阶段全部回落 UNKNOWN,由 T-2.x 填实
# ---------------------------------------------------------------------------


class TestDegradationReasonFallback:
    def test_unreported_reason_falls_back_to_unknown(self, tmp_path: Path) -> None:
        """evaluator 未上报原因时回落 unknown,而不是丢失这条降级。

        「不知道为什么失败」和「没有失败」必须能区分开 —— 这正是本变更要解决的
        静默问题的缩影。
        """
        report = _run(tmp_path, _StubEvaluatorPartialNan(nan_cases=3), n_cases=6)

        reasons = report.metric_integrity["ragas__faithfulness"].reasons
        assert reasons == {DegradationReason.UNKNOWN.value: 3}


# ---------------------------------------------------------------------------
# MetricIntegrity 自身的边界行为
# ---------------------------------------------------------------------------


class TestMetricIntegrityUnit:
    def test_empty_integrity_ratio_is_zero_not_division_error(self) -> None:
        """无样本时降级率为 0.0,不能抛 ZeroDivisionError。"""
        assert MetricIntegrity().degradation_ratio == 0.0
        assert MetricIntegrity().total_count == 0

    def test_to_dict_shape(self) -> None:
        integrity = MetricIntegrity(
            valid_count=27,
            degraded_count=15,
            reasons={DegradationReason.EMPTY_RESPONSE.value: 15},
        )
        payload = integrity.to_dict()
        assert payload["valid_count"] == 27
        assert payload["degraded_count"] == 15
        assert payload["degradation_ratio"] == pytest.approx(15 / 42)
        assert payload["reasons"] == {"empty_response": 15}
