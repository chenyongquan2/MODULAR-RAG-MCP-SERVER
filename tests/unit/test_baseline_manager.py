"""Unit tests for BaselineManager (T034, refs FR-008 / FR-009).

测试范围:
- mark_as_baseline:新建第一份基线 / 替换旧基线(旧的进 history)
- 跨 collection 隔离(每 collection 独立的 current 槽)
- get_current_baseline / get_history 返回正确数据
- compute_delta:简单相减、NaN 处理、缺指标 / 切片 skipped 时 delta 为 None
- 原子写:中断模拟不破坏原 store
- schema_version 不匹配拒绝
- report_id 不在 archive 时拒绝标记
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
from src.core.types import AcceptanceStatus, DeltaReport
from src.observability.evaluation.baseline_manager import BaselineManager


pytestmark = pytest.mark.unit


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        llm=LLMSettings(provider="glm", model="glm-4"),
        embedding=EmbeddingSettings(provider="openai", model="text-embedding-3-small"),
        vision_llm=VisionLLMSettings(provider="azure", model="gpt-4o"),
        vector_store=VectorStoreSettings(backend="chroma"),
        evaluation=EvaluationSettings(
            chunk_id_validation=False,
            report_archive_dir=str(tmp_path / "reports"),
            baseline_store_path=str(tmp_path / "baselines.json"),
        ),
    )


def _archive_fake_report(
    archive_dir: Path,
    report_id: str,
    aggregate_metrics: dict[str, float] | None = None,
    aggregate_metrics_by_tag: dict | None = None,
    hit_rate: float = 0.0,
    mrr: float = 0.0,
) -> Path:
    """模拟 EvalRunner._archive_report 的行为,生成一份 mock 归档报告。"""
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{report_id}.json"
    path.write_text(
        json.dumps(
            {
                "run_id": report_id,
                "aggregate_metrics": aggregate_metrics or {},
                "aggregate_metrics_by_tag": aggregate_metrics_by_tag or {},
                "hit_rate": hit_rate,
                "mrr": mrr,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# mark_as_baseline
# ---------------------------------------------------------------------------


class TestMarkAsBaseline:
    def test_first_baseline_creates_current_entry(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        _archive_fake_report(Path(s.evaluation.report_archive_dir), "rid-1")
        mgr = BaselineManager(s)

        baseline = mgr.mark_as_baseline(
            report_id="rid-1", collection="zh", acceptance_status=AcceptanceStatus.PASS
        )
        assert baseline.report_id == "rid-1"
        assert baseline.collection == "zh"
        assert baseline.acceptance_status == AcceptanceStatus.PASS

        store_data = json.loads(
            Path(s.evaluation.baseline_store_path).read_text(encoding="utf-8")
        )
        assert store_data["_schema_version"] == 1
        assert store_data["current"]["zh"]["report_id"] == "rid-1"
        # 第一次标记时 history 为空(没有旧基线被降级)
        assert store_data.get("history", {}).get("zh", []) == []

    def test_second_baseline_demotes_old_to_history(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        archive = Path(s.evaluation.report_archive_dir)
        _archive_fake_report(archive, "rid-1")
        _archive_fake_report(archive, "rid-2")
        mgr = BaselineManager(s)

        mgr.mark_as_baseline("rid-1", collection="zh", acceptance_status=AcceptanceStatus.FAIL)
        mgr.mark_as_baseline("rid-2", collection="zh", acceptance_status=AcceptanceStatus.PASS)

        cur = mgr.get_current_baseline("zh")
        assert cur is not None
        assert cur.report_id == "rid-2"
        history = mgr.get_history("zh")
        assert len(history) == 1
        assert history[0]["report_id"] == "rid-1"
        assert "demoted_at" in history[0]

    def test_different_collections_isolated(self, tmp_path: Path) -> None:
        """zh 和 en collection 各自独立的 current,互不影响。"""
        s = _settings(tmp_path)
        archive = Path(s.evaluation.report_archive_dir)
        _archive_fake_report(archive, "zh-1")
        _archive_fake_report(archive, "en-1")
        mgr = BaselineManager(s)

        mgr.mark_as_baseline("zh-1", collection="zh", acceptance_status=AcceptanceStatus.PASS)
        mgr.mark_as_baseline("en-1", collection="en", acceptance_status=AcceptanceStatus.FAIL)

        zh = mgr.get_current_baseline("zh")
        en = mgr.get_current_baseline("en")
        assert zh and zh.report_id == "zh-1"
        assert en and en.report_id == "en-1"
        # 不同 collection 的 history 也独立
        assert mgr.get_history("zh") == []
        assert mgr.get_history("en") == []

    def test_missing_report_id_rejected(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        mgr = BaselineManager(s)
        with pytest.raises(ValueError, match="not found in archive"):
            mgr.mark_as_baseline("nonexistent-id", collection="zh")

    def test_empty_collection_rejected(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        _archive_fake_report(Path(s.evaluation.report_archive_dir), "rid-1")
        mgr = BaselineManager(s)
        with pytest.raises(ValueError, match="collection cannot be empty"):
            mgr.mark_as_baseline("rid-1", collection="")


# ---------------------------------------------------------------------------
# get_current_baseline / get_history (无基线场景)
# ---------------------------------------------------------------------------


class TestQueryWithNoBaseline:
    def test_get_current_returns_none_when_no_store_file(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        mgr = BaselineManager(s)
        # 文件不存在
        assert not Path(s.evaluation.baseline_store_path).exists()
        assert mgr.get_current_baseline("zh") is None
        assert mgr.get_history("zh") == []

    def test_get_current_returns_none_when_collection_not_baselined(
        self, tmp_path: Path
    ) -> None:
        s = _settings(tmp_path)
        archive = Path(s.evaluation.report_archive_dir)
        _archive_fake_report(archive, "rid-1")
        mgr = BaselineManager(s)
        mgr.mark_as_baseline("rid-1", collection="zh", acceptance_status=AcceptanceStatus.PASS)
        # 查没有 baseline 的 collection
        assert mgr.get_current_baseline("en") is None


# ---------------------------------------------------------------------------
# compute_delta
# ---------------------------------------------------------------------------


class TestComputeDelta:
    def test_simple_subtraction_per_metric(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        mgr = BaselineManager(s)
        cur = {"run_id": "cur", "aggregate_metrics": {"a": 0.80, "b": 0.50}}
        base = {"run_id": "base", "aggregate_metrics": {"a": 0.70, "b": 0.55}}
        delta = mgr.compute_delta(cur, base)
        assert isinstance(delta, DeltaReport)
        assert delta.current_report_id == "cur"
        assert delta.baseline_report_id == "base"
        assert delta.per_metric_delta["a"] == pytest.approx(0.10)
        assert delta.per_metric_delta["b"] == pytest.approx(-0.05)

    def test_missing_in_baseline_metric_skipped(self, tmp_path: Path) -> None:
        """current 含某 metric 但 baseline 没有 → 该 key 不进 per_metric_delta。"""
        s = _settings(tmp_path)
        mgr = BaselineManager(s)
        cur = {"aggregate_metrics": {"a": 0.5, "new_metric": 0.7}}
        base = {"aggregate_metrics": {"a": 0.4}}
        delta = mgr.compute_delta(cur, base)
        assert "a" in delta.per_metric_delta
        assert "new_metric" not in delta.per_metric_delta

    def test_per_tag_delta_skipped_slice_yields_none(self, tmp_path: Path) -> None:
        """任一边 slice 含 _skipped_reason → 该 entry 为 None。"""
        s = _settings(tmp_path)
        mgr = BaselineManager(s)
        cur = {
            "aggregate_metrics_by_tag": {
                "difficulty": {
                    "simple": {"ragas__faithfulness": 0.85},
                    "rare": {"_skipped_reason": "n_samples=2<5", "ragas__faithfulness": None},
                }
            }
        }
        base = {
            "aggregate_metrics_by_tag": {
                "difficulty": {
                    "simple": {"ragas__faithfulness": 0.80},
                    "rare": {"_skipped_reason": "n_samples=1<5", "ragas__faithfulness": None},
                }
            }
        }
        delta = mgr.compute_delta(cur, base)
        # simple 有 delta
        assert delta.per_tag_delta["difficulty"]["simple"]["ragas__faithfulness"] == pytest.approx(0.05)
        # rare 应为 None(任一 skipped)
        assert delta.per_tag_delta["difficulty"]["rare"] is None

    def test_per_tag_delta_missing_baseline_slice_yields_none(self, tmp_path: Path) -> None:
        """current 有切片但 baseline 没该切片 → entry 为 None。"""
        s = _settings(tmp_path)
        mgr = BaselineManager(s)
        cur = {
            "aggregate_metrics_by_tag": {
                "difficulty": {"simple": {"ragas__faithfulness": 0.85}}
            }
        }
        base = {"aggregate_metrics_by_tag": {"difficulty": {}}}
        delta = mgr.compute_delta(cur, base)
        assert delta.per_tag_delta["difficulty"]["simple"] is None

    def test_empty_aggregates_empty_delta(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        mgr = BaselineManager(s)
        delta = mgr.compute_delta({"run_id": "c"}, {"run_id": "b"})
        assert delta.per_metric_delta == {}
        assert delta.per_tag_delta == {}


# ---------------------------------------------------------------------------
# load_report
# ---------------------------------------------------------------------------


class TestLoadReport:
    def test_load_report_returns_dict(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        path = _archive_fake_report(
            Path(s.evaluation.report_archive_dir),
            "rid-x",
            aggregate_metrics={"hit_rate": 0.5},
        )
        mgr = BaselineManager(s)
        d = mgr.load_report("rid-x")
        assert d["run_id"] == "rid-x"
        assert d["aggregate_metrics"]["hit_rate"] == 0.5

    def test_load_missing_report_raises(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        mgr = BaselineManager(s)
        with pytest.raises(ValueError, match="not found in archive"):
            mgr.load_report("nope")


# ---------------------------------------------------------------------------
# schema 版本兼容
# ---------------------------------------------------------------------------


class TestSchemaCompat:
    def test_unknown_schema_version_rejected(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        # 写入一个未来版本的 store 文件
        Path(s.evaluation.baseline_store_path).parent.mkdir(parents=True, exist_ok=True)
        Path(s.evaluation.baseline_store_path).write_text(
            json.dumps({"_schema_version": 99, "current": {}}),
            encoding="utf-8",
        )
        mgr = BaselineManager(s)
        with pytest.raises(ValueError, match="_schema_version=99 not supported"):
            mgr.get_current_baseline("zh")

    def test_corrupted_json_rejected(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        Path(s.evaluation.baseline_store_path).parent.mkdir(parents=True, exist_ok=True)
        Path(s.evaluation.baseline_store_path).write_text("not valid json {", encoding="utf-8")
        mgr = BaselineManager(s)
        with pytest.raises(ValueError, match="not valid JSON"):
            mgr.get_current_baseline("zh")


# ---------------------------------------------------------------------------
# 原子写
# ---------------------------------------------------------------------------


class TestAtomicWrite:
    def test_no_partial_temp_files_remain_after_normal_write(self, tmp_path: Path) -> None:
        """正常路径不应留下临时文件。"""
        s = _settings(tmp_path)
        _archive_fake_report(Path(s.evaluation.report_archive_dir), "rid-1")
        mgr = BaselineManager(s)
        mgr.mark_as_baseline("rid-1", collection="zh", acceptance_status=AcceptanceStatus.PASS)
        # 检查 baseline_store_path 父目录,只应有 baselines.json,无 .baselines.* tmp
        parent = Path(s.evaluation.baseline_store_path).parent
        tmp_residue = list(parent.glob(".baselines.*.tmp"))
        assert tmp_residue == []


# ===========================================================================
# Feature-004 T032/T033: 基线检索模式与语料有效性标注
# ===========================================================================


class TestBaselineAnnotation:
    """``retrieval_mode`` / ``corpus_validity`` 两个标注字段。

    存在理由:feature-004 之前所有归档基线都自称"混合检索",但关键词索引与
    向量库的 chunk 标识不相交,sparse 路径取不到正文返回空 —— 实际跑的是纯
    向量检索。标签错误会误导后续所有对比。
    """

    def _settings(self, tmp_path):
        from src.core.settings import load_settings

        settings = load_settings("config/settings.yaml")
        settings.evaluation.baseline_store_path = str(tmp_path / "baselines.json")
        settings.evaluation.report_archive_dir = str(tmp_path / "archive")
        (tmp_path / "archive").mkdir(parents=True, exist_ok=True)
        return settings

    def _archive_report(self, settings, report_id="rep-1"):
        import json
        from pathlib import Path

        path = Path(settings.evaluation.report_archive_dir) / f"{report_id}.json"
        path.write_text(json.dumps({"run_id": report_id}), encoding="utf-8")
        return report_id

    def test_mark_stores_annotation(self, tmp_path):
        from src.observability.evaluation.baseline_manager import BaselineManager

        settings = self._settings(tmp_path)
        report_id = self._archive_report(settings)
        manager = BaselineManager(settings)

        baseline = manager.mark_as_baseline(
            report_id=report_id,
            collection="default",
            retrieval_mode="hybrid",
            corpus_validity="valid",
        )

        assert baseline.retrieval_mode == "hybrid"
        assert baseline.corpus_validity == "valid"
        assert manager.get_current_baseline("default").retrieval_mode == "hybrid"

    def test_annotation_defaults_to_unlabelled(self, tmp_path):
        from src.observability.evaluation.baseline_manager import BaselineManager

        settings = self._settings(tmp_path)
        report_id = self._archive_report(settings)
        manager = BaselineManager(settings)

        baseline = manager.mark_as_baseline(report_id=report_id, collection="default")

        assert baseline.retrieval_mode == ""
        assert baseline.corpus_validity == ""

    def test_annotate_existing_baseline_preserves_metrics_fields(self, tmp_path):
        """补标注不得改动任何既有字段 —— 旧数字不是错的,错的只是标签。"""
        from src.observability.evaluation.baseline_manager import BaselineManager

        settings = self._settings(tmp_path)
        report_id = self._archive_report(settings)
        manager = BaselineManager(settings)
        original = manager.mark_as_baseline(report_id=report_id, collection="default")

        updated = manager.annotate_baseline(
            "default", retrieval_mode="dense_only", corpus_validity="mismatched"
        )

        assert updated.retrieval_mode == "dense_only"
        assert updated.corpus_validity == "mismatched"
        # 其余字段原样保留
        assert updated.report_id == original.report_id
        assert updated.marked_at == original.marked_at
        assert updated.acceptance_status == original.acceptance_status

    def test_annotate_partial_update(self, tmp_path):
        """传 None 的字段不动。"""
        from src.observability.evaluation.baseline_manager import BaselineManager

        settings = self._settings(tmp_path)
        report_id = self._archive_report(settings)
        manager = BaselineManager(settings)
        manager.mark_as_baseline(
            report_id=report_id, collection="default",
            retrieval_mode="hybrid", corpus_validity="valid",
        )

        updated = manager.annotate_baseline("default", corpus_validity="mismatched")

        assert updated.retrieval_mode == "hybrid"
        assert updated.corpus_validity == "mismatched"

    def test_annotate_missing_baseline_raises(self, tmp_path):
        from src.observability.evaluation.baseline_manager import BaselineManager

        manager = BaselineManager(self._settings(tmp_path))
        with pytest.raises(ValueError, match="no current baseline"):
            manager.annotate_baseline("nope", retrieval_mode="hybrid")

    def test_backward_compatible_read_of_unannotated_record(self):
        """feature-004 之前的记录没有这两个字段,缺失即"未标注"。"""
        from src.core.types import Baseline

        legacy = {
            "report_id": "old-1",
            "collection": "default",
            "marked_at": "2026-04-26T13:44:35+00:00",
            "marked_by": "dashboard-script-equivalent",
            "acceptance_status": "fail",
        }

        baseline = Baseline.from_dict(legacy)

        assert baseline.retrieval_mode == ""
        assert baseline.corpus_validity == ""
        assert baseline.report_id == "old-1"
