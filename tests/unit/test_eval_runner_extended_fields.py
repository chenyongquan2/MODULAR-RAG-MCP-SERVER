"""Unit tests for EvalReport extended fields (T017).

测试范围 (refs spec FR-001 / FR-013 / FR-016 / FR-017, data-model § 2.5):
- ``run_id`` 是合法 UUID4 格式(每次 run 生成新的)
- ``acceptance_thresholds_snapshot`` 与 settings.acceptance_thresholds 一致
- ``judge_llm_identifier`` / ``embedding_identifier`` 来自 evaluator 上的方法
- ``acceptance_status`` 由 ThresholdEvaluator 计算
- NaN metric 值 → ``degraded_case_count++`` 且不污染 aggregate_metrics 均值
- ``_archive_report()`` 写 ``<run_id>.json`` + 追加 ``index.jsonl``
"""

from __future__ import annotations

import json
import math
import uuid
from pathlib import Path

import pytest

from src.core.settings import (
    AcceptanceThresholds,
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


pytestmark = pytest.mark.unit


class _StubHybridSearch:
    def search(self, query, top_k, filters=None):
        return [RetrievalResult(chunk_id="c1", score=0.9, text="ctx", metadata={})]


class _StubEvaluatorAllPass(BaseEvaluator):
    """全 8 项达标(默认业界参考阈值)的 stub evaluator。"""

    def evaluate(self, query, retrieved_ids, golden_ids, trace=None, **kwargs):
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
            "ragas__context_recall": 0.0, "ragas__context_precision": 0.0,
            "ragas__faithfulness": 0.0, "ragas__answer_relevancy": 0.0,
            "custom__hit_rate": 0.0, "custom__mrr": 0.0,
            "custom__recall": 0.0, "custom__ndcg": 0.0,
        }

    def get_judge_identifier(self):
        return "glm:glm-4"

    def get_embedding_identifier(self):
        return "openai:text-embedding-3-small"


class _StubEvaluatorWithNan(BaseEvaluator):
    """每隔一 case 返回一个 NaN metric,用于测 degraded_case_count。"""

    def __init__(self) -> None:
        self._counter = 0

    def evaluate(self, query, retrieved_ids, golden_ids, trace=None, **kwargs):
        self._counter += 1
        # 偶数 case 返回 NaN(模拟 Judge 不可达)
        if self._counter % 2 == 0:
            return {"ragas__faithfulness": float("nan"), "custom__hit_rate": 1.0}
        return {"ragas__faithfulness": 0.9, "custom__hit_rate": 1.0}

    def zero_metrics(self):
        return {"ragas__faithfulness": 0.0, "custom__hit_rate": 0.0}


class _StubEvaluatorNoIdentifiers(BaseEvaluator):
    """没有 get_judge_identifier / get_embedding_identifier 方法(模拟 custom-only)。"""

    def evaluate(self, query, retrieved_ids, golden_ids, trace=None, **kwargs):
        return {"hit_rate": 0.8}

    def zero_metrics(self):
        return {"hit_rate": 0.0}


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


def _write_test_set(tmp_path: Path, n_cases: int = 4) -> Path:
    cases = [
        {"query": f"q{i}", "expected_chunk_ids": ["c1"], "expected_sources": [], "ground_truth": ""}
        for i in range(n_cases)
    ]
    p = tmp_path / "golden.json"
    p.write_text(
        json.dumps({"_schema_version": 1, "test_cases": cases, "version": "v1.0"}, ensure_ascii=False),
        encoding="utf-8",
    )
    return p


# ---------------------------------------------------------------------------
# Run-level metadata
# ---------------------------------------------------------------------------


class TestRunMetadataFields:
    def test_run_id_is_uuid4(self, tmp_path: Path) -> None:
        runner = EvalRunner(
            settings=_settings(tmp_path),
            hybrid_search=_StubHybridSearch(),
            evaluator=_StubEvaluatorAllPass(),
        )
        report = runner.run(test_set_path=str(_write_test_set(tmp_path)), archive=False)
        # 应能 parse 为 UUID4
        parsed = uuid.UUID(report.run_id)
        assert parsed.version == 4

    def test_run_id_changes_between_runs(self, tmp_path: Path) -> None:
        """每次 run() 生成新 run_id。"""
        runner = EvalRunner(
            settings=_settings(tmp_path),
            hybrid_search=_StubHybridSearch(),
            evaluator=_StubEvaluatorAllPass(),
        )
        test_set = str(_write_test_set(tmp_path))
        r1 = runner.run(test_set_path=test_set, archive=False)
        r2 = runner.run(test_set_path=test_set, archive=False)
        assert r1.run_id != r2.run_id

    def test_collection_field_from_filters_or_settings(self, tmp_path: Path) -> None:
        """collection 字段优先取 filters,缺失时从 settings。"""
        runner = EvalRunner(
            settings=_settings(tmp_path),
            hybrid_search=_StubHybridSearch(),
            evaluator=_StubEvaluatorAllPass(),
        )
        # 不传 filters → 取 settings.vector_store.collection_name
        r1 = runner.run(test_set_path=str(_write_test_set(tmp_path)), archive=False)
        assert r1.collection == "my_col"
        # 传 filters → 取 filters.collection
        r2 = runner.run(
            test_set_path=str(_write_test_set(tmp_path)),
            filters={"collection": "filter_col"},
            archive=False,
        )
        assert r2.collection == "filter_col"

    def test_test_set_version_extracted_from_metadata(self, tmp_path: Path) -> None:
        runner = EvalRunner(
            settings=_settings(tmp_path),
            hybrid_search=_StubHybridSearch(),
            evaluator=_StubEvaluatorAllPass(),
        )
        report = runner.run(test_set_path=str(_write_test_set(tmp_path)), archive=False)
        assert report.test_set_version == "v1.0"


# ---------------------------------------------------------------------------
# Provider identifiers (FR-016 / FR-017)
# ---------------------------------------------------------------------------


class TestProviderIdentifiers:
    def test_judge_and_embedding_identifiers_from_evaluator(self, tmp_path: Path) -> None:
        runner = EvalRunner(
            settings=_settings(tmp_path),
            hybrid_search=_StubHybridSearch(),
            evaluator=_StubEvaluatorAllPass(),
        )
        report = runner.run(test_set_path=str(_write_test_set(tmp_path)), archive=False)
        assert report.judge_llm_identifier == "glm:glm-4"
        assert report.embedding_identifier == "openai:text-embedding-3-small"

    def test_evaluator_without_identifiers_yields_none(self, tmp_path: Path) -> None:
        """custom-only 评估场景下 evaluator 没有 get_*_identifier 方法 → 字段 None。"""
        runner = EvalRunner(
            settings=_settings(tmp_path),
            hybrid_search=_StubHybridSearch(),
            evaluator=_StubEvaluatorNoIdentifiers(),
        )
        report = runner.run(test_set_path=str(_write_test_set(tmp_path)), archive=False)
        assert report.judge_llm_identifier is None
        assert report.embedding_identifier is None


# ---------------------------------------------------------------------------
# Acceptance status + thresholds snapshot (FR-013)
# ---------------------------------------------------------------------------


class TestAcceptanceStatus:
    def test_status_pass_when_all_metrics_above_threshold(self, tmp_path: Path) -> None:
        runner = EvalRunner(
            settings=_settings(tmp_path),
            hybrid_search=_StubHybridSearch(),
            evaluator=_StubEvaluatorAllPass(),
        )
        report = runner.run(test_set_path=str(_write_test_set(tmp_path)), archive=False)
        assert report.acceptance_status == AcceptanceStatus.PASS

    def test_thresholds_snapshot_matches_settings(self, tmp_path: Path) -> None:
        runner = EvalRunner(
            settings=_settings(tmp_path),
            hybrid_search=_StubHybridSearch(),
            evaluator=_StubEvaluatorAllPass(),
        )
        report = runner.run(test_set_path=str(_write_test_set(tmp_path)), archive=False)
        # snapshot 应等于默认 industry-reference 值
        assert report.acceptance_thresholds_snapshot["ragas__faithfulness"] == 0.85
        assert report.acceptance_thresholds_snapshot["custom__hit_rate"] == 0.60
        assert len(report.acceptance_thresholds_snapshot) == 8


# ---------------------------------------------------------------------------
# NaN handling (FR-001 / SC-006)
# ---------------------------------------------------------------------------


class TestNanHandling:
    def test_nan_metric_increments_degraded_case_count(self, tmp_path: Path) -> None:
        """偶数 case 返 NaN → degraded_case_count = total / 2。"""
        runner = EvalRunner(
            settings=_settings(tmp_path),
            hybrid_search=_StubHybridSearch(),
            evaluator=_StubEvaluatorWithNan(),
        )
        # 4 个 case,case_2 / case_4 NaN
        report = runner.run(test_set_path=str(_write_test_set(tmp_path, n_cases=4)), archive=False)
        assert report.degraded_case_count == 2
        assert report.total_cases == 4

    def test_nan_does_not_pollute_aggregate_mean(self, tmp_path: Path) -> None:
        """NaN 不计入 aggregate_metrics 分母 — 应用 case 1 / 3 的有效值取均值。"""
        runner = EvalRunner(
            settings=_settings(tmp_path),
            hybrid_search=_StubHybridSearch(),
            evaluator=_StubEvaluatorWithNan(),
        )
        report = runner.run(test_set_path=str(_write_test_set(tmp_path, n_cases=4)), archive=False)
        # ragas__faithfulness:case 1/3 是 0.9,case 2/4 是 NaN
        # 有效均值 = (0.9 + 0.9) / 2 = 0.9
        assert math.isclose(
            report.aggregate_metrics["ragas__faithfulness"], 0.9, rel_tol=1e-9
        )
        # custom__hit_rate:全部 1.0(无 NaN),均值 = 1.0
        assert math.isclose(
            report.aggregate_metrics["custom__hit_rate"], 1.0, rel_tol=1e-9
        )


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------


class TestArchiveBehavior:
    def test_archive_writes_per_run_json_and_index_jsonl(self, tmp_path: Path) -> None:
        runner = EvalRunner(
            settings=_settings(tmp_path),
            hybrid_search=_StubHybridSearch(),
            evaluator=_StubEvaluatorAllPass(),
        )
        report = runner.run(test_set_path=str(_write_test_set(tmp_path)), archive=True)

        archive_dir = Path(tmp_path) / "reports"
        per_run_file = archive_dir / f"{report.run_id}.json"
        index_file = archive_dir / "index.jsonl"

        assert per_run_file.exists()
        assert index_file.exists()

        # per-run JSON 应是合法 JSON 含 run_id
        data = json.loads(per_run_file.read_text(encoding="utf-8"))
        assert data["run_id"] == report.run_id
        assert data["acceptance_status"] == "pass"
        # index 应有一行,内容含 run_id 与 acceptance_status
        index_lines = index_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(index_lines) == 1
        index_entry = json.loads(index_lines[0])
        assert index_entry["run_id"] == report.run_id
        assert index_entry["acceptance_status"] == "pass"
        assert index_entry["report_path"].endswith(f"{report.run_id}.json")

    def test_no_archive_skips_filesystem_write(self, tmp_path: Path) -> None:
        runner = EvalRunner(
            settings=_settings(tmp_path),
            hybrid_search=_StubHybridSearch(),
            evaluator=_StubEvaluatorAllPass(),
        )
        runner.run(test_set_path=str(_write_test_set(tmp_path)), archive=False)
        # archive_dir 不应有任何文件(或目录根本不存在)
        archive_dir = Path(tmp_path) / "reports"
        if archive_dir.exists():
            files = list(archive_dir.iterdir())
            assert files == []

    def test_index_jsonl_appends_across_runs(self, tmp_path: Path) -> None:
        """多次评估 → index.jsonl 累加,每行一条。"""
        runner = EvalRunner(
            settings=_settings(tmp_path),
            hybrid_search=_StubHybridSearch(),
            evaluator=_StubEvaluatorAllPass(),
        )
        test_set = str(_write_test_set(tmp_path))
        runner.run(test_set_path=test_set, archive=True)
        runner.run(test_set_path=test_set, archive=True)
        runner.run(test_set_path=test_set, archive=True)

        index_file = Path(tmp_path) / "reports" / "index.jsonl"
        lines = index_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3
        # 每行都是合法 JSON
        for line in lines:
            json.loads(line)
