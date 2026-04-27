"""Unit tests for EvalRunner FR-015 by-tag 切片聚合 (T016).

测试范围:
- 命名规则 ``aggregate_metrics_by_<dim>.<value>.<metric>`` 正确
- 切片样本量 < ``tag_slice_min_samples`` → 该 entry 含 ``_skipped_reason`` +
  全 metric None
- 切片**不**参与 ``acceptance_status`` 判定 (clarify Q2)
- 无 tags 的 case 不进入任何切片(默认占位 case)
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
from src.core.types import RetrievalResult
from src.libs.evaluator.base_evaluator import BaseEvaluator
from src.observability.evaluation.eval_runner import EvalRunner


pytestmark = pytest.mark.unit


class _StubHybridSearch:
    def search(self, query, top_k, filters=None):
        return [RetrievalResult(chunk_id="c1", score=0.9, text="ctx", metadata={})]


class _StubEvaluator(BaseEvaluator):
    """Stub:第一个 case score=1.0,后续 case score 递减(便于切片差异)。"""

    def __init__(self) -> None:
        self._counter = 0

    def evaluate(self, query, retrieved_ids, golden_ids, trace=None, **kwargs):
        self._counter += 1
        # 让 metric 值随 case 序列变化,便于校验 slice 聚合是不同切片
        score = max(0.5, 1.0 - 0.05 * self._counter)
        return {
            "ragas__faithfulness": score,
            "custom__hit_rate": score,
        }

    def zero_metrics(self):
        return {"ragas__faithfulness": 0.0, "custom__hit_rate": 0.0}


def _settings(tmp_path: Path, min_samples: int = 5) -> Settings:
    return Settings(
        llm=LLMSettings(provider="ollama", model="llama3"),
        embedding=EmbeddingSettings(provider="openai", model="text-embedding-3-small"),
        vision_llm=VisionLLMSettings(provider="azure", model="gpt-4o"),
        vector_store=VectorStoreSettings(backend="chroma"),
        evaluation=EvaluationSettings(
            backends=["custom"],
            chunk_id_validation=False,
            tag_slice_min_samples=min_samples,
            report_archive_dir=str(tmp_path / "reports"),
            baseline_store_path=str(tmp_path / "baselines.json"),
        ),
    )


def _write_test_set_with_tags(tmp_path: Path, tag_distribution: list[dict]) -> Path:
    """构造一份带 tags 的测试金标。"""
    cases = [
        {
            "query": f"q{i}",
            "expected_chunk_ids": ["c1"],
            "expected_sources": [],
            "ground_truth": "",
            "tags": tags,
        }
        for i, tags in enumerate(tag_distribution)
    ]
    test_set_path = tmp_path / "golden.json"
    test_set_path.write_text(
        json.dumps({"_schema_version": 1, "test_cases": cases}, ensure_ascii=False),
        encoding="utf-8",
    )
    return test_set_path


# ---------------------------------------------------------------------------
# 切片命名规则与基本聚合
# ---------------------------------------------------------------------------


class TestByTagAggregation:
    def test_naming_follows_dim_value_metric_pattern(self, tmp_path: Path) -> None:
        """命名规则: aggregate_metrics_by_<dim>.<value>.<metric>。"""
        settings = _settings(tmp_path, min_samples=2)
        # 5 个 simple 文本 case + 5 个 reasoning 文本 case
        tags_dist = [
            {"content_type": "text", "difficulty": "simple", "language": "zh", "doc_version": "v1"}
            for _ in range(5)
        ] + [
            {"content_type": "text", "difficulty": "reasoning", "language": "zh", "doc_version": "v1"}
            for _ in range(5)
        ]
        test_set = _write_test_set_with_tags(tmp_path, tags_dist)

        runner = EvalRunner(
            settings=settings, hybrid_search=_StubHybridSearch(), evaluator=_StubEvaluator()
        )
        report = runner.run(test_set_path=str(test_set), archive=False)

        # 应有 content_type / difficulty 两个维度
        assert "content_type" in report.aggregate_metrics_by_tag
        assert "difficulty" in report.aggregate_metrics_by_tag
        # content_type.text 应有(共 10 个 case)
        assert "text" in report.aggregate_metrics_by_tag["content_type"]
        # difficulty.simple / .reasoning 应有(各 5 个 case)
        assert "simple" in report.aggregate_metrics_by_tag["difficulty"]
        assert "reasoning" in report.aggregate_metrics_by_tag["difficulty"]
        # 含两个 metric key
        text_slice = report.aggregate_metrics_by_tag["content_type"]["text"]
        assert "ragas__faithfulness" in text_slice
        assert "custom__hit_rate" in text_slice


# ---------------------------------------------------------------------------
# < 5 样本切片跳过策略
# ---------------------------------------------------------------------------


class TestSliceSkipPolicy:
    def test_slice_below_min_samples_marked_skipped(self, tmp_path: Path) -> None:
        """切片样本 < min_samples 时全 metric 为 None,且含 _skipped_reason。"""
        settings = _settings(tmp_path, min_samples=5)
        # 6 个 simple + 2 个 reasoning(reasoning 切片样本量 2 < 5,应跳过)
        tags_dist = [
            {"content_type": "text", "difficulty": "simple", "language": "zh", "doc_version": "v1"}
            for _ in range(6)
        ] + [
            {"content_type": "text", "difficulty": "reasoning", "language": "zh", "doc_version": "v1"}
            for _ in range(2)
        ]
        test_set = _write_test_set_with_tags(tmp_path, tags_dist)

        runner = EvalRunner(
            settings=settings, hybrid_search=_StubHybridSearch(), evaluator=_StubEvaluator()
        )
        report = runner.run(test_set_path=str(test_set), archive=False)

        # difficulty.simple 应正常聚合(6 ≥ 5)
        simple_slice = report.aggregate_metrics_by_tag["difficulty"]["simple"]
        assert simple_slice.get("ragas__faithfulness") is not None
        # difficulty.reasoning 应被 skipped(2 < 5)
        reasoning_slice = report.aggregate_metrics_by_tag["difficulty"]["reasoning"]
        assert reasoning_slice.get("_skipped_reason") == "n_samples=2<5"
        assert reasoning_slice.get("ragas__faithfulness") is None
        assert reasoning_slice.get("custom__hit_rate") is None


# ---------------------------------------------------------------------------
# 切片不参与 acceptance_status (clarify Q2)
# ---------------------------------------------------------------------------


class TestSliceNotParticipatingInPassFail:
    def test_slice_failure_does_not_affect_pass_when_main_passes(
        self, tmp_path: Path
    ) -> None:
        """构造一个主聚合 PASS 但某切片低于阈值的场景,acceptance_status 仍应为 PASS。

        clarify Q2:by-tag 切片仅诊断展示,不参与 pass/fail。
        """
        # 构造一个 stub evaluator,让所有 case score 都 >= 阈值(主聚合 PASS),
        # 但某些 tag 子集得分相同(切片本身只能反映平均,没有"低于阈值"概念
        # —— 所以这个测试主要验证:报告的 acceptance_status 仅由 aggregate_metrics
        # 决定,不读 aggregate_metrics_by_tag)。
        class _AllPassEvaluator(BaseEvaluator):
            def evaluate(self, query, retrieved_ids, golden_ids, trace=None, **kwargs):
                # 全 8 项达 industry-reference 阈值
                return {
                    "ragas__context_recall": 0.80,
                    "ragas__context_precision": 0.75,
                    "ragas__faithfulness": 0.90,
                    "ragas__answer_relevancy": 0.85,
                    "custom__hit_rate": 0.70,
                    "custom__mrr": 0.65,
                    "custom__recall": 0.80,
                    "custom__ndcg": 0.65,
                }

            def zero_metrics(self):
                return {
                    "ragas__context_recall": 0.0,
                    "ragas__context_precision": 0.0,
                    "ragas__faithfulness": 0.0,
                    "ragas__answer_relevancy": 0.0,
                    "custom__hit_rate": 0.0,
                    "custom__mrr": 0.0,
                    "custom__recall": 0.0,
                    "custom__ndcg": 0.0,
                }

        settings = _settings(tmp_path, min_samples=2)
        tags_dist = [
            {"content_type": "text", "difficulty": "simple", "language": "zh", "doc_version": "v1"}
            for _ in range(5)
        ]
        test_set = _write_test_set_with_tags(tmp_path, tags_dist)

        runner = EvalRunner(
            settings=settings,
            hybrid_search=_StubHybridSearch(),
            evaluator=_AllPassEvaluator(),
        )
        report = runner.run(test_set_path=str(test_set), archive=False)

        from src.core.types import AcceptanceStatus
        # 主聚合达标 → acceptance_status PASS
        assert report.acceptance_status == AcceptanceStatus.PASS
        # 切片应该存在(诊断信息)
        assert "content_type" in report.aggregate_metrics_by_tag


class TestNoTagsCases:
    def test_cases_without_tags_excluded_from_slices(self, tmp_path: Path) -> None:
        """无 tags 的 case 不应进入任何切片(占位 case 友好行为)。"""
        settings = _settings(tmp_path, min_samples=2)
        # 直接写一份不含 tags 的金标
        cases = [
            {
                "query": "q1",
                "expected_chunk_ids": ["c1"],
                "expected_sources": [],
                "ground_truth": "",
            }
            for _ in range(3)
        ]
        test_set_path = tmp_path / "no_tags.json"
        test_set_path.write_text(
            json.dumps({"_schema_version": 1, "test_cases": cases}, ensure_ascii=False),
            encoding="utf-8",
        )

        runner = EvalRunner(
            settings=settings, hybrid_search=_StubHybridSearch(), evaluator=_StubEvaluator()
        )
        report = runner.run(test_set_path=str(test_set_path), archive=False)

        # 主聚合应正常
        assert report.total_cases == 3
        # by-tag 聚合应为空 dict 或不含任何 dimension
        assert report.aggregate_metrics_by_tag == {}
