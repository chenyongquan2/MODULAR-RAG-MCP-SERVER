"""降级率参与 acceptance_status 判定的单元测试。

refs change evaluation-degradation-governance T-5.2
spec: specs/evaluation/run-integrity/spec.md § 降级率超标必须导致验收失败

核心诉求:8 项指标全过、但其中一半是在收缩后的分母上算出来的 —— 这种 pass
是假的。指标达标与样本完整是两个独立的合格条件。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.settings import (
    AcceptanceThresholds,
    DegradationSettings,
    EmbeddingSettings,
    EvaluationSettings,
    LLMSettings,
    Settings,
    VectorStoreSettings,
    VisionLLMSettings,
)
from src.core.types import AcceptanceStatus, RetrievalResult
from src.libs.evaluator.base_evaluator import BaseEvaluator
from src.observability.evaluation.eval_runner import EvalRunner
from src.observability.evaluation.threshold_evaluator import ThresholdEvaluator


pytestmark = pytest.mark.unit


_ALL_PASSING = {
    "ragas__context_recall": 0.80,
    "ragas__context_precision": 0.75,
    "ragas__faithfulness": 0.90,
    "ragas__answer_relevancy": 0.85,
    "custom__hit_rate": 0.70,
    "custom__mrr": 0.65,
    "custom__recall": 0.80,
    "custom__ndcg": 0.65,
}


# ---------------------------------------------------------------------------
# ThresholdEvaluator 层
# ---------------------------------------------------------------------------


class TestThresholdEvaluatorGate:
    def test_over_threshold_fails_even_when_all_metrics_pass(self) -> None:
        """spec § 指标阈值通过但降级率超标 → fail。这是本任务的核心场景。"""
        evaluator = ThresholdEvaluator(AcceptanceThresholds(), max_degradation_ratio=0.05)
        assert (
            evaluator.evaluate(_ALL_PASSING, degradation_ratio=0.548)
            == AcceptanceStatus.FAIL
        )

    def test_under_threshold_keeps_original_verdict(self) -> None:
        """降级率达标时不改变既有判定 —— 它只增加失败条件,不放宽。"""
        evaluator = ThresholdEvaluator(AcceptanceThresholds(), max_degradation_ratio=0.05)
        assert (
            evaluator.evaluate(_ALL_PASSING, degradation_ratio=0.02)
            == AcceptanceStatus.PASS
        )

    def test_under_threshold_does_not_rescue_failing_metric(self) -> None:
        failing = dict(_ALL_PASSING, ragas__faithfulness=0.10)
        evaluator = ThresholdEvaluator(AcceptanceThresholds(), max_degradation_ratio=0.05)
        assert evaluator.evaluate(failing, degradation_ratio=0.0) == AcceptanceStatus.FAIL

    def test_exactly_at_threshold_passes(self) -> None:
        """门槛是「超过才失败」,恰好等于不算超标。"""
        evaluator = ThresholdEvaluator(AcceptanceThresholds(), max_degradation_ratio=0.05)
        assert (
            evaluator.evaluate(_ALL_PASSING, degradation_ratio=0.05)
            == AcceptanceStatus.PASS
        )

    def test_threshold_is_configurable(self) -> None:
        """同一个降级率,门槛不同结论不同 —— 门槛必须来自配置而非硬编码。"""
        strict = ThresholdEvaluator(AcceptanceThresholds(), max_degradation_ratio=0.05)
        lenient = ThresholdEvaluator(AcceptanceThresholds(), max_degradation_ratio=0.60)

        assert strict.evaluate(_ALL_PASSING, degradation_ratio=0.33) == AcceptanceStatus.FAIL
        assert lenient.evaluate(_ALL_PASSING, degradation_ratio=0.33) == AcceptanceStatus.PASS

    def test_ratio_one_disables_the_gate(self) -> None:
        """design § Migration Plan 的回滚手段:配成 1.0 即关闭该闸门,无需回退代码。"""
        evaluator = ThresholdEvaluator(AcceptanceThresholds(), max_degradation_ratio=1.0)
        assert (
            evaluator.evaluate(_ALL_PASSING, degradation_ratio=0.99)
            == AcceptanceStatus.PASS
        )

    def test_backward_compatible_without_degradation_args(self) -> None:
        """不传降级参数时行为与本能力落地之前完全一致。"""
        evaluator = ThresholdEvaluator(AcceptanceThresholds())
        assert evaluator.evaluate(_ALL_PASSING) == AcceptanceStatus.PASS

    def test_failed_list_names_degradation(self) -> None:
        """acceptance_status=fail 却在 8 项里找不到不达标项,会让人以为是 bug。"""
        evaluator = ThresholdEvaluator(AcceptanceThresholds(), max_degradation_ratio=0.05)
        failed = evaluator.get_failed_metrics(_ALL_PASSING, degradation_ratio=0.548)

        assert ThresholdEvaluator.DEGRADATION_FAILURE_KEY in failed
        # 降级率排最前:它一旦成立,后面的指标值本身就是在不完整样本上算的
        assert failed[0] == ThresholdEvaluator.DEGRADATION_FAILURE_KEY


# ---------------------------------------------------------------------------
# EvalRunner 端到端
# ---------------------------------------------------------------------------


class _StubHybridSearch:
    def search(self, query, top_k, filters=None):
        return [RetrievalResult(chunk_id="c1", score=0.9, text="ctx", metadata={})]


class _MostlyDegradedEvaluator(BaseEvaluator):
    """8 项全达标,但每 2 条 case 就有一条判定失败(降级率 50%)。"""

    def __init__(self) -> None:
        self._n = 0

    def evaluate(self, query, retrieved_ids, golden_ids, trace=None, **kwargs):
        self._n += 1
        metrics = dict(_ALL_PASSING)
        if self._n % 2 == 0:
            metrics["ragas__faithfulness"] = float("nan")
        return metrics

    def zero_metrics(self):
        return {k: 0.0 for k in _ALL_PASSING}


def _settings(tmp_path: Path, max_ratio: float) -> Settings:
    return Settings(
        llm=LLMSettings(provider="ollama", model="llama3"),
        embedding=EmbeddingSettings(provider="openai", model="m"),
        vision_llm=VisionLLMSettings(provider="azure", model="gpt-4o"),
        vector_store=VectorStoreSettings(backend="chroma", collection_name="c"),
        evaluation=EvaluationSettings(
            backends=["custom"],
            chunk_id_validation=False,
            report_archive_dir=str(tmp_path / "reports"),
            baseline_store_path=str(tmp_path / "baselines.json"),
            degradation=DegradationSettings(max_ratio=max_ratio),
        ),
    )


def _run(tmp_path: Path, max_ratio: float, n: int = 10):
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
            }
        ),
        encoding="utf-8",
    )
    runner = EvalRunner(
        settings=_settings(tmp_path, max_ratio),
        hybrid_search=_StubHybridSearch(),
        evaluator=_MostlyDegradedEvaluator(),
    )
    return runner.run(test_set_path=str(p), archive=False)


class TestEndToEndGate:
    def test_degradation_flips_verdict_to_fail(self, tmp_path: Path) -> None:
        report = _run(tmp_path, max_ratio=0.05)
        assert report.degraded_case_count == 5
        assert report.acceptance_status == AcceptanceStatus.FAIL

    def test_lenient_threshold_lets_it_pass(self, tmp_path: Path) -> None:
        """同一批数据,只改配置就翻转结论 —— 证明门槛真的是配置驱动的。"""
        report = _run(tmp_path, max_ratio=0.60)
        assert report.degraded_case_count == 5
        assert report.acceptance_status == AcceptanceStatus.PASS
