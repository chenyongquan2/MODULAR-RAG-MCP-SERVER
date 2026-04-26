"""Unit tests for EvalRunner ↔ BaselineManager 集成 (T035, refs FR-009).

测试范围:
- 无当前基线时 → report.baseline_id / delta_* 全部为 None
- 有当前基线时 → report 自动嵌入 baseline_id + delta_aggregate_metrics +
  delta_hit_rate + delta_mrr
- BaselineManager.compute_delta 失败时降级为 None(不阻断主评估输出)
- baseline_report 缺某指标时该 delta key 不出现
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.settings import (
    EmbeddingSettings,
    EvaluationSettings,
    LLMSettings,
    Settings,
    VectorStoreSettings,
    VisionLLMSettings,
)
from src.core.types import AcceptanceStatus, RetrievalResult
from src.libs.evaluator.base_evaluator import BaseEvaluator
from src.observability.evaluation.baseline_manager import BaselineManager
from src.observability.evaluation.eval_runner import EvalRunner


pytestmark = pytest.mark.unit


class _StubHybridSearch:
    def search(self, query, top_k, filters=None):
        return [RetrievalResult(chunk_id="c1", score=0.9, text="ctx", metadata={})]


class _StubEvaluator(BaseEvaluator):
    """Returns a deterministic per-case metrics dict."""

    def evaluate(self, query, retrieved_ids, golden_ids, trace=None, **kwargs):
        return {"hit_rate": 1.0, "mrr": 1.0, "recall": 1.0, "ndcg": 1.0}

    def zero_metrics(self):
        return {"hit_rate": 0.0, "mrr": 0.0, "recall": 0.0, "ndcg": 0.0}


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        llm=LLMSettings(provider="glm", model="glm-4"),
        embedding=EmbeddingSettings(provider="openai", model="text-embedding-3-small"),
        vision_llm=VisionLLMSettings(provider="azure", model="gpt-4o"),
        vector_store=VectorStoreSettings(backend="chroma", collection_name="zh_col"),
        evaluation=EvaluationSettings(
            backends=["custom"],
            chunk_id_validation=False,
            report_archive_dir=str(tmp_path / "reports"),
            baseline_store_path=str(tmp_path / "baselines.json"),
        ),
    )


def _write_test_set(tmp_path: Path, n: int = 2) -> Path:
    cases = [
        {"query": f"q{i}", "expected_chunk_ids": ["c1"], "expected_sources": [], "ground_truth": ""}
        for i in range(n)
    ]
    p = tmp_path / "golden.json"
    p.write_text(
        json.dumps({"_schema_version": 1, "test_cases": cases, "version": "v1.0"}, ensure_ascii=False),
        encoding="utf-8",
    )
    return p


# ---------------------------------------------------------------------------
# 无当前基线时:delta 字段全 None
# ---------------------------------------------------------------------------


class TestNoBaseline:
    def test_no_baseline_yields_no_delta_fields(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        runner = EvalRunner(
            settings=s, hybrid_search=_StubHybridSearch(), evaluator=_StubEvaluator()
        )
        report = runner.run(
            test_set_path=str(_write_test_set(tmp_path)), archive=False
        )
        assert report.baseline_id is None
        assert report.delta_aggregate_metrics is None
        assert report.delta_hit_rate is None
        assert report.delta_mrr is None
        assert report.per_tag_delta is None


# ---------------------------------------------------------------------------
# 有当前基线时:delta 自动嵌入
# ---------------------------------------------------------------------------


class TestWithBaseline:
    def test_baseline_present_attaches_delta(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        # 1) 先归档一份 baseline 报告(指标比当前低,delta 应为正)
        archive_dir = Path(s.evaluation.report_archive_dir)
        archive_dir.mkdir(parents=True, exist_ok=True)
        baseline_id = "baseline-uuid-xyz"
        (archive_dir / f"{baseline_id}.json").write_text(
            json.dumps({
                "run_id": baseline_id,
                "aggregate_metrics": {
                    "hit_rate": 0.5, "mrr": 0.4, "recall": 0.6, "ndcg": 0.55,
                },
                "aggregate_metrics_by_tag": {},
                "hit_rate": 0.5,
                "mrr": 0.4,
            }, ensure_ascii=False),
            encoding="utf-8",
        )

        # 2) 标记为当前基线
        mgr = BaselineManager(s)
        mgr.mark_as_baseline(
            report_id=baseline_id,
            collection="zh_col",  # 与 settings.vector_store.collection_name 一致
            acceptance_status=AcceptanceStatus.FAIL,
        )

        # 3) 跑评估(主聚合每项 = 1.0,vs baseline 0.5/0.4/0.6/0.55,delta 应为正)
        runner = EvalRunner(
            settings=s, hybrid_search=_StubHybridSearch(), evaluator=_StubEvaluator()
        )
        report = runner.run(
            test_set_path=str(_write_test_set(tmp_path)), archive=False
        )

        assert report.baseline_id == baseline_id
        assert report.delta_aggregate_metrics is not None
        # current 1.0 - baseline 0.5 = +0.5
        assert report.delta_aggregate_metrics["hit_rate"] == pytest.approx(0.5)
        assert report.delta_aggregate_metrics["mrr"] == pytest.approx(0.6)
        assert report.delta_aggregate_metrics["recall"] == pytest.approx(0.4)
        assert report.delta_aggregate_metrics["ndcg"] == pytest.approx(0.45)
        # 顶层 delta_hit_rate / delta_mrr
        assert report.delta_hit_rate == pytest.approx(0.5)
        assert report.delta_mrr == pytest.approx(0.6)


class TestBaselineFailureGraceful:
    def test_failed_compute_delta_yields_none_not_crash(self, tmp_path: Path) -> None:
        """BaselineManager.compute_delta 内部异常不应阻断主评估输出。"""
        s = _settings(tmp_path)
        # 创建一个会让 BaselineManager.load_report 抛错的 setup:
        # 标记基线 (报告存在),然后删掉报告文件让 load_report 失败
        archive_dir = Path(s.evaluation.report_archive_dir)
        archive_dir.mkdir(parents=True, exist_ok=True)
        bad_id = "will-be-deleted"
        report_path = archive_dir / f"{bad_id}.json"
        report_path.write_text(
            json.dumps({"run_id": bad_id, "aggregate_metrics": {"hit_rate": 0.5}}),
            encoding="utf-8",
        )
        mgr = BaselineManager(s)
        mgr.mark_as_baseline(
            report_id=bad_id, collection="zh_col",
            acceptance_status=AcceptanceStatus.PASS,
        )
        # 模拟报告文件丢失(磁盘清理/移动)
        report_path.unlink()

        runner = EvalRunner(
            settings=s, hybrid_search=_StubHybridSearch(), evaluator=_StubEvaluator()
        )
        # 不应抛错;主评估应正常完成,delta 字段降级为 None
        report = runner.run(
            test_set_path=str(_write_test_set(tmp_path)), archive=False
        )
        assert report.total_cases == 2
        # baseline_id 应保持 None(因为 load_report 失败被 try/except 捕获)
        assert report.baseline_id is None
        assert report.delta_aggregate_metrics is None


class TestBaselineWithMissingMetrics:
    def test_baseline_missing_metric_excluded_from_delta(self, tmp_path: Path) -> None:
        """baseline_report 缺某指标时,该 key 不进 delta_aggregate_metrics。"""
        s = _settings(tmp_path)
        archive_dir = Path(s.evaluation.report_archive_dir)
        archive_dir.mkdir(parents=True, exist_ok=True)
        baseline_id = "baseline-partial"
        # baseline 只含 hit_rate / mrr,缺 recall / ndcg
        (archive_dir / f"{baseline_id}.json").write_text(
            json.dumps({
                "run_id": baseline_id,
                "aggregate_metrics": {"hit_rate": 0.5, "mrr": 0.4},
                "aggregate_metrics_by_tag": {},
                "hit_rate": 0.5,
                "mrr": 0.4,
            }),
            encoding="utf-8",
        )
        mgr = BaselineManager(s)
        mgr.mark_as_baseline(
            report_id=baseline_id, collection="zh_col",
            acceptance_status=AcceptanceStatus.FAIL,
        )

        runner = EvalRunner(
            settings=s, hybrid_search=_StubHybridSearch(), evaluator=_StubEvaluator()
        )
        report = runner.run(
            test_set_path=str(_write_test_set(tmp_path)), archive=False
        )
        # delta 应只含 hit_rate / mrr
        assert report.delta_aggregate_metrics is not None
        assert "hit_rate" in report.delta_aggregate_metrics
        assert "mrr" in report.delta_aggregate_metrics
        assert "recall" not in report.delta_aggregate_metrics
        assert "ndcg" not in report.delta_aggregate_metrics
