"""Unit tests for EvaluationService — 基线对比功能。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.observability.dashboard.services.evaluation_service import EvaluationService
from src.observability.evaluation.eval_runner import EvalReport


def _stub_report(hit_rate: float = 0.8, mrr: float = 0.7) -> EvalReport:
    """构造最小化的 EvalReport 供测试使用。"""
    return EvalReport(
        total_cases=2,
        hit_rate=hit_rate,
        mrr=mrr,
        source_hit_rate=0.5,
        aggregate_metrics={"custom__hit_rate": hit_rate, "custom__mrr": mrr},
        case_results=[],
    )


def _svc(tmp_path: Path) -> EvaluationService:
    """创建使用临时文件的 EvaluationService 实例。"""
    return EvaluationService(history_file=tmp_path / "evals.jsonl")


# ------------------------------------------------------------------
# mark_as_baseline / get_baseline_entry
# ------------------------------------------------------------------


def test_mark_as_baseline_sets_flag(tmp_path: Path) -> None:
    """mark_as_baseline 应成功标记指定 timestamp 的记录。"""
    svc = _svc(tmp_path)
    svc.append_history({"timestamp": "2026-01-01T00:00:00", "hit_rate": 0.8, "mrr": 0.7})
    svc.append_history({"timestamp": "2026-01-02T00:00:00", "hit_rate": 0.85, "mrr": 0.75})

    assert svc.mark_as_baseline("2026-01-01T00:00:00") is True
    baseline = svc.get_baseline_entry()
    assert baseline is not None
    assert baseline["timestamp"] == "2026-01-01T00:00:00"


def test_mark_as_baseline_returns_false_for_missing_timestamp(tmp_path: Path) -> None:
    """不存在的 timestamp 应返回 False，不修改文件。"""
    svc = _svc(tmp_path)
    svc.append_history({"timestamp": "2026-01-01T00:00:00", "hit_rate": 0.8})
    assert svc.mark_as_baseline("9999-01-01T00:00:00") is False


def test_only_one_baseline_at_a_time(tmp_path: Path) -> None:
    """重新标记时应清除旧基线，保证只有一条 is_baseline=True 的记录。"""
    svc = _svc(tmp_path)
    svc.append_history({"timestamp": "2026-01-01T00:00:00", "hit_rate": 0.8})
    svc.append_history({"timestamp": "2026-01-02T00:00:00", "hit_rate": 0.85})
    svc.mark_as_baseline("2026-01-01T00:00:00")
    svc.mark_as_baseline("2026-01-02T00:00:00")

    baseline_records = [r for r in svc._read_all_history() if r.get("is_baseline")]
    assert len(baseline_records) == 1
    assert baseline_records[0]["timestamp"] == "2026-01-02T00:00:00"


def test_get_baseline_entry_returns_none_when_no_baseline(tmp_path: Path) -> None:
    """无基线时 get_baseline_entry 应返回 None。"""
    svc = _svc(tmp_path)
    assert svc.get_baseline_entry() is None


# ------------------------------------------------------------------
# compare_with_baseline
# ------------------------------------------------------------------


def test_compare_with_baseline_computes_deltas(tmp_path: Path) -> None:
    """compare_with_baseline 应正确计算 delta_hit_rate / delta_mrr。"""
    svc = _svc(tmp_path)
    baseline: dict[str, Any] = {
        "timestamp": "2026-01-01T00:00:00",
        "hit_rate": 0.7,
        "mrr": 0.6,
        "aggregate_metrics": {"custom__hit_rate": 0.7, "custom__mrr": 0.6},
        "is_baseline": True,
    }
    current = _stub_report(hit_rate=0.8, mrr=0.7)

    result = svc.compare_with_baseline(current, baseline_entry=baseline)

    assert result.baseline_id == "2026-01-01T00:00:00"
    assert result.delta_hit_rate == pytest.approx(0.1)
    assert result.delta_mrr == pytest.approx(0.1)
    assert result.delta_aggregate_metrics is not None
    assert result.delta_aggregate_metrics["custom__hit_rate"] == pytest.approx(0.1)


def test_compare_returns_unmodified_report_when_no_baseline(tmp_path: Path) -> None:
    """无基线时 compare_with_baseline 应返回原报告，delta 字段均为 None。"""
    svc = _svc(tmp_path)
    current = _stub_report()
    result = svc.compare_with_baseline(current)
    assert result.baseline_id is None
    assert result.delta_hit_rate is None
    assert result.delta_mrr is None


def test_eval_report_to_dict_includes_delta_fields_when_set() -> None:
    """to_dict() 在 baseline_id 存在时应输出 delta 字段。"""
    report = _stub_report()
    report.baseline_id = "2026-01-01T00:00:00"
    report.delta_hit_rate = 0.05
    report.delta_mrr = -0.02
    report.delta_aggregate_metrics = {"custom__hit_rate": 0.05}

    d = report.to_dict()
    assert "baseline_id" in d
    assert d["delta_hit_rate"] == pytest.approx(0.05)
    assert d["delta_mrr"] == pytest.approx(-0.02)


def test_eval_report_to_dict_excludes_delta_fields_when_no_baseline() -> None:
    """to_dict() 在 baseline_id 为 None 时不应输出 delta 字段（向后兼容）。"""
    report = _stub_report()
    d = report.to_dict()
    assert "baseline_id" not in d
    assert "delta_hit_rate" not in d


# ------------------------------------------------------------------
# compare_with_baseline 不可变性 & 锁语义
# ------------------------------------------------------------------


def test_compare_with_baseline_does_not_mutate_input(tmp_path: Path) -> None:
    """compare_with_baseline 应返回新副本，不得原地修改调用者的 report。"""
    svc = _svc(tmp_path)
    baseline: dict[str, Any] = {
        "timestamp": "2026-01-01T00:00:00",
        "hit_rate": 0.7,
        "mrr": 0.6,
        "aggregate_metrics": {"custom__hit_rate": 0.7},
    }
    original = _stub_report(hit_rate=0.8, mrr=0.7)

    result = svc.compare_with_baseline(original, baseline_entry=baseline)

    # 原 report 的 delta 字段应保持 None
    assert original.baseline_id is None
    assert original.delta_hit_rate is None
    assert original.delta_mrr is None
    # 新副本应带 delta 字段
    assert result is not original
    assert result.baseline_id == "2026-01-01T00:00:00"


def test_corrupt_jsonl_line_is_skipped_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """损坏的 JSONL 行应被跳过并产生 WARNING 日志，不中断读取。"""
    svc = _svc(tmp_path)
    svc._history_file.parent.mkdir(parents=True, exist_ok=True)
    svc._history_file.write_text(
        '{"timestamp": "2026-01-01T00:00:00", "hit_rate": 0.8}\n'
        "{not valid json}\n"
        '{"timestamp": "2026-01-02T00:00:00", "hit_rate": 0.9}\n',
        encoding="utf-8",
    )

    with caplog.at_level("WARNING"):
        records = svc.load_history()

    assert len(records) == 2
    assert any("corrupted" in rec.message.lower() for rec in caplog.records)


def test_file_lock_serializes_appends(tmp_path: Path) -> None:
    """多线程并发 append_history 不应丢记录（文件锁验证）。"""
    import threading

    svc = _svc(tmp_path)
    thread_count = 10
    records_per_thread = 5

    def _writer(tid: int) -> None:
        for i in range(records_per_thread):
            svc.append_history({"timestamp": f"t-{tid}-{i}", "hit_rate": 0.5})

    threads = [threading.Thread(target=_writer, args=(i,)) for i in range(thread_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(svc._read_all_history()) == thread_count * records_per_thread
