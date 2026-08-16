"""分母一致性守卫的单元测试。

refs change evaluation-degradation-governance T-4.1
spec: specs/evaluation/run-integrity/spec.md § 分母不一致的两次运行不得被当作可比

为什么需要这个守卫:judge 判定失败的 case 不计入均值分母。若两次运行降级条数
不同,两个均值就是在**不同样本集**上算的 —— 相减得到的 delta 混了「质量变化」
与「分母变化」两件事。实测 run 80a82405 的 faithfulness 是 27 条的均值。
"""

from __future__ import annotations

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
from src.observability.evaluation.baseline_manager import BaselineManager


pytestmark = pytest.mark.unit


def _manager(tmp_path: Path) -> BaselineManager:
    return BaselineManager(
        settings=Settings(
            llm=LLMSettings(provider="ollama", model="llama3"),
            embedding=EmbeddingSettings(provider="openai", model="m"),
            vision_llm=VisionLLMSettings(provider="azure", model="gpt-4o"),
            vector_store=VectorStoreSettings(backend="chroma", collection_name="c"),
            evaluation=EvaluationSettings(
                report_archive_dir=str(tmp_path / "reports"),
                baseline_store_path=str(tmp_path / "baselines.json"),
            ),
        )
    )


def _report(
    run_id: str,
    *,
    metrics: dict[str, float],
    integrity: dict[str, dict] | None = None,
    degraded_case_count: int = 0,
    total_cases: int = 42,
) -> dict:
    report: dict = {
        "run_id": run_id,
        "total_cases": total_cases,
        "aggregate_metrics": metrics,
        "degraded_case_count": degraded_case_count,
    }
    if integrity is not None:
        report["metric_integrity"] = integrity
    return report


def _integrity(valid: int, degraded: int = 0) -> dict:
    return {"valid_count": valid, "degraded_count": degraded, "reasons": {}}


# ---------------------------------------------------------------------------
# Scenario: 分母不同则标注不可比 / 分母相同则正常比较
# ---------------------------------------------------------------------------


class TestDenominatorGuard:
    def test_mismatched_denominator_marked_incomparable(self, tmp_path: Path) -> None:
        current = _report(
            "cur",
            metrics={"ragas__faithfulness": 0.90},
            integrity={"ragas__faithfulness": _integrity(30, 12)},
        )
        baseline = _report(
            "base",
            metrics={"ragas__faithfulness": 0.8887},
            integrity={"ragas__faithfulness": _integrity(27, 15)},
            degraded_case_count=15,
        )

        delta = _manager(tmp_path).compute_delta(current, baseline)

        assert "ragas__faithfulness" in delta.incomparable_metrics
        assert "n=30" in delta.incomparable_metrics["ragas__faithfulness"]
        assert "n=27" in delta.incomparable_metrics["ragas__faithfulness"]

    def test_incomparable_metric_still_reports_delta(self, tmp_path: Path) -> None:
        """不可比不等于不输出 —— 隐藏会让人以为没算,标注才能让人知道别误读。

        这与既有的跨代 delta_comparable 语义一致。
        """
        current = _report(
            "cur",
            metrics={"ragas__faithfulness": 0.90},
            integrity={"ragas__faithfulness": _integrity(30)},
        )
        baseline = _report(
            "base",
            metrics={"ragas__faithfulness": 0.80},
            integrity={"ragas__faithfulness": _integrity(27)},
        )

        delta = _manager(tmp_path).compute_delta(current, baseline)

        assert delta.per_metric_delta["ragas__faithfulness"] == pytest.approx(0.10)
        assert "ragas__faithfulness" in delta.incomparable_metrics

    def test_matching_denominator_is_comparable(self, tmp_path: Path) -> None:
        current = _report(
            "cur",
            metrics={"ragas__faithfulness": 0.90},
            integrity={"ragas__faithfulness": _integrity(42)},
        )
        baseline = _report(
            "base",
            metrics={"ragas__faithfulness": 0.80},
            integrity={"ragas__faithfulness": _integrity(42)},
        )

        delta = _manager(tmp_path).compute_delta(current, baseline)
        assert delta.incomparable_metrics == {}

    def test_only_mismatched_metric_flagged(self, tmp_path: Path) -> None:
        """一个指标不可比不该牵连其他指标。"""
        current = _report(
            "cur",
            metrics={"ragas__faithfulness": 0.9, "custom__hit_rate": 0.6},
            integrity={
                "ragas__faithfulness": _integrity(30, 12),
                "custom__hit_rate": _integrity(42),
            },
        )
        baseline = _report(
            "base",
            metrics={"ragas__faithfulness": 0.8, "custom__hit_rate": 0.6},
            integrity={
                "ragas__faithfulness": _integrity(27, 15),
                "custom__hit_rate": _integrity(42),
            },
            degraded_case_count=15,
        )

        delta = _manager(tmp_path).compute_delta(current, baseline)
        assert set(delta.incomparable_metrics) == {"ragas__faithfulness"}


# ---------------------------------------------------------------------------
# Scenario: 基线缺少分母信息时保守处理
# ---------------------------------------------------------------------------


class TestLegacyBaseline:
    def test_legacy_baseline_with_degradation_marks_all_incomparable(
        self, tmp_path: Path
    ) -> None:
        """还原真实处境:run 80a82405 有 23 条降级但没有 metric_integrity。"""
        current = _report(
            "cur",
            metrics={"ragas__faithfulness": 0.90, "custom__hit_rate": 0.62},
            integrity={
                "ragas__faithfulness": _integrity(30, 12),
                "custom__hit_rate": _integrity(42),
            },
        )
        baseline = _report(
            "80a82405",
            metrics={"ragas__faithfulness": 0.8887, "custom__hit_rate": 0.619},
            integrity=None,  # 老报告没有这个字段
            degraded_case_count=23,
        )

        delta = _manager(tmp_path).compute_delta(current, baseline)

        assert set(delta.incomparable_metrics) == {"ragas__faithfulness", "custom__hit_rate"}
        assert "predates" in delta.incomparable_metrics["ragas__faithfulness"]

    def test_legacy_baseline_is_not_mutated(self, tmp_path: Path) -> None:
        """历史报告是事实记录 —— 守卫只读,绝不回填。"""
        baseline = _report(
            "old",
            metrics={"ragas__faithfulness": 0.8887},
            integrity=None,
            degraded_case_count=23,
        )
        snapshot = dict(baseline)

        _manager(tmp_path).compute_delta(
            _report(
                "cur",
                metrics={"ragas__faithfulness": 0.9},
                integrity={"ragas__faithfulness": _integrity(30)},
            ),
            baseline,
        )

        assert baseline == snapshot
        assert "metric_integrity" not in baseline

    def test_clean_legacy_baseline_uses_total_cases_as_denominator(
        self, tmp_path: Path
    ) -> None:
        """零降级的老基线仍可核对 —— 分母必然等于总条数,这是推论不是估计。

        一刀切判不可比会白白丢弃大量可用历史。
        """
        current = _report(
            "cur",
            metrics={"ragas__faithfulness": 0.90},
            integrity={"ragas__faithfulness": _integrity(42)},
            total_cases=42,
        )
        baseline = _report(
            "clean-old",
            metrics={"ragas__faithfulness": 0.85},
            integrity=None,
            degraded_case_count=0,
            total_cases=42,
        )

        delta = _manager(tmp_path).compute_delta(current, baseline)
        assert delta.incomparable_metrics == {}

    def test_clean_legacy_baseline_still_caught_when_current_degrades(
        self, tmp_path: Path
    ) -> None:
        current = _report(
            "cur",
            metrics={"ragas__faithfulness": 0.90},
            integrity={"ragas__faithfulness": _integrity(30, 12)},
            total_cases=42,
        )
        baseline = _report(
            "clean-old",
            metrics={"ragas__faithfulness": 0.85},
            integrity=None,
            degraded_case_count=0,
            total_cases=42,
        )

        delta = _manager(tmp_path).compute_delta(current, baseline)
        assert "ragas__faithfulness" in delta.incomparable_metrics


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_incomparable_metrics_in_dict(self, tmp_path: Path) -> None:
        delta = _manager(tmp_path).compute_delta(
            _report(
                "cur",
                metrics={"m": 0.9},
                integrity={"m": _integrity(30)},
            ),
            _report("base", metrics={"m": 0.8}, integrity={"m": _integrity(27)}),
        )
        payload = delta.to_dict()
        assert "incomparable_metrics" in payload
        assert "m" in payload["incomparable_metrics"]
