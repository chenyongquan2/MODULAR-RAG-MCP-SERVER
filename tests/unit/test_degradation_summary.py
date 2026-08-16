"""降级摘要文本格式化的单元测试。

refs change evaluation-degradation-governance T-1.2
spec: specs/evaluation/run-integrity/spec.md § 降级情况必须在运行结束时直接可见

被测函数只**返回字符串**、不打印 —— 硬约束 5 规定 ``src/`` 下禁 ``print()``
(MCP stdio transport 的 stdout 走 JSON-RPC,污染它会破坏协议)。这个约束的
副作用是格式化逻辑天然可单测。
"""

from __future__ import annotations

import pytest

from src.core.settings import DegradationSettings, SettingsError
from src.core.types import DegradationReason, MetricIntegrity
from src.observability.evaluation.degradation_summary import format_degradation_summary


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Scenario: 存在降级时输出摘要
# ---------------------------------------------------------------------------


class TestSummaryWhenDegraded:
    def _integrity(self) -> dict[str, MetricIntegrity]:
        """还原 run 80a82405 的真实形态(42 条,faithfulness 降级 15)。"""
        return {
            "ragas__faithfulness": MetricIntegrity(
                valid_count=27,
                degraded_count=15,
                reasons={
                    DegradationReason.EMPTY_RESPONSE.value: 9,
                    DegradationReason.UNPARSEABLE.value: 6,
                },
            ),
            "custom__hit_rate": MetricIntegrity(valid_count=42, degraded_count=0),
        }

    def test_summary_contains_ratio_and_counts(self) -> None:
        text = format_degradation_summary(
            metric_integrity=self._integrity(),
            degraded_case_count=23,
            total_cases=42,
        )
        assert "54.8%" in text
        assert "23/42" in text

    def test_summary_reports_effective_denominator(self) -> None:
        """核心诉求:让「这个均值是 27 条算出来的」这句话被人看见。"""
        text = format_degradation_summary(
            metric_integrity=self._integrity(),
            degraded_case_count=23,
            total_cases=42,
        )
        assert "ragas__faithfulness" in text
        assert "有效 27" in text
        assert "降级 15" in text
        assert "27 条算出" in text

    def test_summary_breaks_down_reasons(self) -> None:
        text = format_degradation_summary(
            metric_integrity=self._integrity(),
            degraded_case_count=23,
            total_cases=42,
        )
        assert "empty_response" in text
        assert "unparseable" in text

    def test_clean_metrics_are_not_listed(self) -> None:
        """零降级的指标不进摘要 —— custom 四项恒为 0,列出来只是噪声。"""
        text = format_degradation_summary(
            metric_integrity=self._integrity(),
            degraded_case_count=23,
            total_cases=42,
        )
        assert "custom__hit_rate" not in text


# ---------------------------------------------------------------------------
# Scenario: 超标时输出显著提示
# ---------------------------------------------------------------------------


class TestThresholdCallout:
    def test_over_threshold_names_the_threshold(self) -> None:
        """光给百分比不够 —— 读者无从判断这个数算不算糟,必须点出门槛。"""
        text = format_degradation_summary(
            metric_integrity={
                "ragas__faithfulness": MetricIntegrity(valid_count=27, degraded_count=15)
            },
            degraded_case_count=23,
            total_cases=42,
            max_ratio=0.05,
        )
        assert "超过门槛" in text
        assert "5.0%" in text

    def test_under_threshold_no_callout(self) -> None:
        text = format_degradation_summary(
            metric_integrity={
                "ragas__faithfulness": MetricIntegrity(valid_count=41, degraded_count=1)
            },
            degraded_case_count=1,
            total_cases=42,
            max_ratio=0.05,
        )
        assert "超过门槛" not in text

    def test_no_threshold_given_no_callout(self) -> None:
        """调用方不关心门槛时只出摘要,不臆造判断。"""
        text = format_degradation_summary(
            metric_integrity={
                "ragas__faithfulness": MetricIntegrity(valid_count=27, degraded_count=15)
            },
            degraded_case_count=23,
            total_cases=42,
            max_ratio=None,
        )
        assert "超过门槛" not in text


# ---------------------------------------------------------------------------
# Scenario: 无降级时不制造噪声
# ---------------------------------------------------------------------------


class TestSummaryWhenClean:
    def test_zero_degradation_is_single_line(self) -> None:
        text = format_degradation_summary(
            metric_integrity={
                "ragas__faithfulness": MetricIntegrity(valid_count=42, degraded_count=0),
                "custom__hit_rate": MetricIntegrity(valid_count=42, degraded_count=0),
            },
            degraded_case_count=0,
            total_cases=42,
        )
        assert text.count("\n") == 0
        assert "0.0%" in text

    def test_zero_degradation_does_not_expand_reasons(self) -> None:
        text = format_degradation_summary(
            metric_integrity={
                "ragas__faithfulness": MetricIntegrity(valid_count=42, degraded_count=0)
            },
            degraded_case_count=0,
            total_cases=42,
        )
        assert "按指标" not in text

    def test_empty_run_does_not_divide_by_zero(self) -> None:
        text = format_degradation_summary(
            metric_integrity={}, degraded_case_count=0, total_cases=0
        )
        assert "0.0%" in text


# ---------------------------------------------------------------------------
# DegradationSettings 的启动期校验(硬约束 3:快速失败,不兜底)
# ---------------------------------------------------------------------------


class TestDegradationSettingsValidation:
    def test_defaults_match_sc006(self) -> None:
        """默认门槛必须是 SC-006 定的 5%,不是随手拍的数。"""
        assert DegradationSettings().max_ratio == 0.05
        assert DegradationSettings().unknown_reason_warn == 0.10

    @pytest.mark.parametrize("bad", [-0.1, 1.5])
    def test_out_of_range_max_ratio_rejected(self, bad: float) -> None:
        from src.core.settings import _validate_evaluation_settings

        settings = _minimal_settings()
        settings.evaluation.degradation.max_ratio = bad
        with pytest.raises(SettingsError, match="max_ratio"):
            _validate_evaluation_settings(settings)

    @pytest.mark.parametrize("bad", [-0.01, 2.0])
    def test_out_of_range_unknown_warn_rejected(self, bad: float) -> None:
        from src.core.settings import _validate_evaluation_settings

        settings = _minimal_settings()
        settings.evaluation.degradation.unknown_reason_warn = bad
        with pytest.raises(SettingsError, match="unknown_reason_warn"):
            _validate_evaluation_settings(settings)

    @pytest.mark.parametrize("ok", [0.0, 0.05, 1.0])
    def test_boundary_values_accepted(self, ok: float) -> None:
        """0 与 1 是合法边界:0 = 零容忍,1 = 关闭该闸门(design 里的回滚手段)。"""
        from src.core.settings import _validate_evaluation_settings

        settings = _minimal_settings()
        settings.evaluation.degradation.max_ratio = ok
        _validate_evaluation_settings(settings)


def _minimal_settings():
    from src.core.settings import (
        EmbeddingSettings,
        EvaluationSettings,
        LLMSettings,
        Settings,
        VectorStoreSettings,
        VisionLLMSettings,
    )

    return Settings(
        llm=LLMSettings(provider="ollama", model="llama3"),
        embedding=EmbeddingSettings(provider="openai", model="text-embedding-3-small"),
        vision_llm=VisionLLMSettings(provider="azure", model="gpt-4o"),
        vector_store=VectorStoreSettings(backend="chroma", collection_name="c"),
        evaluation=EvaluationSettings(backends=["custom"]),
    )
