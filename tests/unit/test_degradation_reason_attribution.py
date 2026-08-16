"""降级原因从 evaluator 到报告的端到端归因测试。

refs change evaluation-degradation-governance T-2.2
spec: specs/evaluation/run-integrity/spec.md § 判定失败必须带可归因的原因

覆盖链路:judge 调用特征 → RagasEvaluator 归约 → CompositeEvaluator 加前缀
→ EvalRunner 写入 case → 报告按原因聚合。

**前缀这一环最容易出错**:CompositeEvaluator 的 evaluate() 会把 metric 加上
``ragas__`` 前缀,若原因字典不加同样的前缀,EvalRunner 就永远查不到,全部
回落 unknown —— 归因功能会静默失效,恰恰是本变更在治理的那类失败。
"""

from __future__ import annotations

import json
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
from src.core.types import DegradationReason, RetrievalResult
from src.libs.evaluator.base_evaluator import BaseEvaluator
from src.observability.evaluation.composite_evaluator import (
    CompositeEvaluator,
    _class_name_to_prefix,
)
from src.observability.evaluation.eval_runner import EvalRunner


pytestmark = pytest.mark.unit


class _StubHybridSearch:
    def search(self, query, top_k, filters=None):
        return [RetrievalResult(chunk_id="c1", score=0.9, text="ctx", metadata={})]


class _RagasLikeEvaluator(BaseEvaluator):
    """模拟 RagasEvaluator:判定失败时上报原因。

    类名以 Ragas 开头,让 CompositeEvaluator 生成 ``ragas__`` 前缀。
    """

    def __init__(self, reason: str, fail_every: int = 1) -> None:
        self._reason = reason
        self._fail_every = fail_every
        self._counter = 0
        self._last: dict[str, str] = {}

    def evaluate(self, query, retrieved_ids, golden_ids, trace=None, **kwargs):
        self._counter += 1
        if self._counter % self._fail_every == 0:
            self._last = {"faithfulness": self._reason}
            return {"faithfulness": float("nan"), "context_recall": 0.8}
        self._last = {}
        return {"faithfulness": 0.9, "context_recall": 0.8}

    def zero_metrics(self):
        return {"faithfulness": 0.0, "context_recall": 0.0}

    def get_last_degradation_reasons(self) -> dict[str, str]:
        return dict(self._last)


class _CustomLikeEvaluator(BaseEvaluator):
    """纯计算评估器:没有降级概念,也没有 get_last_degradation_reasons。"""

    def evaluate(self, query, retrieved_ids, golden_ids, trace=None, **kwargs):
        return {"hit_rate": 1.0}

    def zero_metrics(self):
        return {"hit_rate": 0.0}


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        llm=LLMSettings(provider="ollama", model="llama3"),
        embedding=EmbeddingSettings(provider="openai", model="text-embedding-3-small"),
        vision_llm=VisionLLMSettings(provider="azure", model="gpt-4o"),
        vector_store=VectorStoreSettings(backend="chroma", collection_name="c"),
        evaluation=EvaluationSettings(
            backends=["custom"],
            chunk_id_validation=False,
            report_archive_dir=str(tmp_path / "reports"),
            baseline_store_path=str(tmp_path / "baselines.json"),
        ),
    )


def _write_test_set(tmp_path: Path, n: int) -> Path:
    p = tmp_path / "golden.json"
    p.write_text(
        json.dumps(
            {
                "_schema_version": 1,
                "version": "v1.0",
                "test_cases": [
                    {
                        "query": f"q{i}",
                        "expected_chunk_ids": ["c1"],
                        "expected_sources": [],
                        "ground_truth": "",
                    }
                    for i in range(n)
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return p


def _run(tmp_path: Path, evaluator: BaseEvaluator, n: int = 4):
    runner = EvalRunner(
        settings=_settings(tmp_path),
        hybrid_search=_StubHybridSearch(),
        evaluator=evaluator,
    )
    return runner.run(test_set_path=str(_write_test_set(tmp_path, n)), archive=False)


# ---------------------------------------------------------------------------
# Scenario: 空响应被归类 / 解析失败被归类
# ---------------------------------------------------------------------------


class TestReasonPropagation:
    def test_empty_response_reason_reaches_report(self, tmp_path: Path) -> None:
        report = _run(
            tmp_path,
            _RagasLikeEvaluator(DegradationReason.EMPTY_RESPONSE.value),
            n=4,
        )
        reasons = report.metric_integrity["faithfulness"].reasons
        assert reasons == {DegradationReason.EMPTY_RESPONSE.value: 4}

    def test_unparseable_reason_reaches_report(self, tmp_path: Path) -> None:
        report = _run(
            tmp_path,
            _RagasLikeEvaluator(DegradationReason.UNPARSEABLE.value),
            n=3,
        )
        reasons = report.metric_integrity["faithfulness"].reasons
        assert reasons == {DegradationReason.UNPARSEABLE.value: 3}

    def test_reason_recorded_on_case_result(self, tmp_path: Path) -> None:
        report = _run(
            tmp_path, _RagasLikeEvaluator(DegradationReason.TIMEOUT.value), n=2
        )
        assert report.case_results[0].degradation_reasons == {
            "faithfulness": DegradationReason.TIMEOUT.value
        }


# ---------------------------------------------------------------------------
# Scenario: 原因分布可聚合
# ---------------------------------------------------------------------------


class TestReasonAggregation:
    def test_mixed_reasons_are_counted_separately(self, tmp_path: Path) -> None:
        class _Alternating(_RagasLikeEvaluator):
            def __init__(self) -> None:
                super().__init__(reason="")
                self._n = 0

            def evaluate(self, query, retrieved_ids, golden_ids, trace=None, **kwargs):
                self._n += 1
                reason = (
                    DegradationReason.EMPTY_RESPONSE.value
                    if self._n % 2
                    else DegradationReason.TIMEOUT.value
                )
                self._last = {"faithfulness": reason}
                return {"faithfulness": float("nan"), "context_recall": 0.8}

        report = _run(tmp_path, _Alternating(), n=4)
        reasons = report.metric_integrity["faithfulness"].reasons
        assert reasons[DegradationReason.EMPTY_RESPONSE.value] == 2
        assert reasons[DegradationReason.TIMEOUT.value] == 2

    def test_partial_degradation_only_counts_failed_cases(self, tmp_path: Path) -> None:
        """4 条里每 2 条失败一次 → 降级 2、有效 2。"""
        report = _run(
            tmp_path,
            _RagasLikeEvaluator(DegradationReason.EMPTY_RESPONSE.value, fail_every=2),
            n=4,
        )
        integrity = report.metric_integrity["faithfulness"]
        assert integrity.degraded_count == 2
        assert integrity.valid_count == 2


# ---------------------------------------------------------------------------
# Scenario: 兜底类别不得掩盖问题
# ---------------------------------------------------------------------------


class TestUnknownFallback:
    def test_evaluator_without_attribution_falls_back_to_unknown(
        self, tmp_path: Path
    ) -> None:
        """evaluator 不支持归因时降级仍被计数,只是原因是 unknown。"""

        class _NoAttribution(BaseEvaluator):
            def evaluate(self, query, retrieved_ids, golden_ids, trace=None, **kwargs):
                return {"faithfulness": float("nan")}

            def zero_metrics(self):
                return {"faithfulness": 0.0}

        report = _run(tmp_path, _NoAttribution(), n=3)
        integrity = report.metric_integrity["faithfulness"]
        assert integrity.degraded_count == 3
        assert integrity.reasons == {DegradationReason.UNKNOWN.value: 3}

    def test_reason_for_non_nan_metric_is_discarded(self, tmp_path: Path) -> None:
        """evaluator 多报的原因不得污染统计 —— 只认真的是 NaN 的那些。"""

        class _OverReporting(BaseEvaluator):
            def evaluate(self, query, retrieved_ids, golden_ids, trace=None, **kwargs):
                return {"faithfulness": 0.9}

            def zero_metrics(self):
                return {"faithfulness": 0.0}

            def get_last_degradation_reasons(self):
                return {"faithfulness": DegradationReason.TIMEOUT.value}

        report = _run(tmp_path, _OverReporting(), n=2)
        assert report.metric_integrity["faithfulness"].degraded_count == 0
        assert report.metric_integrity["faithfulness"].reasons == {}


# ---------------------------------------------------------------------------
# CompositeEvaluator 的前缀一致性(最易静默失效的一环)
# ---------------------------------------------------------------------------


class TestCompositePrefixConsistency:
    def test_prefix_matches_between_metrics_and_reasons(self, tmp_path: Path) -> None:
        """多评估器时 metric 带了前缀,原因也必须带**同一个**前缀。

        刻意不硬写 ``ragas__`` 字面量:前缀由 ``_class_name_to_prefix`` 从类名
        推导,测试要守的是两侧一致,而不是某个具体拼写。
        """
        composite = CompositeEvaluator(
            [
                _RagasLikeEvaluator(DegradationReason.EMPTY_RESPONSE.value),
                _CustomLikeEvaluator(),
            ]
        )
        report = _run(tmp_path, composite, n=2)

        prefix = _class_name_to_prefix(_RagasLikeEvaluator.__name__)
        key = f"{prefix}__faithfulness"

        # metric 侧确实带了前缀
        assert key in report.metric_integrity
        # 原因侧必须对上,否则会全部回落 unknown(归因静默失效)
        assert report.metric_integrity[key].reasons == {
            DegradationReason.EMPTY_RESPONSE.value: 2
        }
        # 且降级确实被计数了 —— 排除「前缀对上但没数据」的假通过
        assert report.metric_integrity[key].degraded_count == 2

    def test_single_evaluator_has_no_prefix_on_either_side(self, tmp_path: Path) -> None:
        """单评估器时两侧都不加前缀,保持与历史 baseline 的 key 一致。"""
        composite = CompositeEvaluator(
            [_RagasLikeEvaluator(DegradationReason.UNPARSEABLE.value)]
        )
        report = _run(tmp_path, composite, n=2)

        assert "faithfulness" in report.metric_integrity
        assert report.metric_integrity["faithfulness"].reasons == {
            DegradationReason.UNPARSEABLE.value: 2
        }

    def test_pure_computed_evaluator_contributes_no_reasons(self, tmp_path: Path) -> None:
        composite = CompositeEvaluator(
            [_RagasLikeEvaluator(DegradationReason.TIMEOUT.value), _CustomLikeEvaluator()]
        )
        report = _run(tmp_path, composite, n=2)

        key = f"{_class_name_to_prefix(_CustomLikeEvaluator.__name__)}__hit_rate"
        assert report.metric_integrity[key].reasons == {}
        assert report.metric_integrity[key].degraded_count == 0
