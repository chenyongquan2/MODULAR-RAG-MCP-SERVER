"""Judge 调用结果采集与归约的单元测试。

refs change evaluation-degradation-governance T-2.1
spec: specs/evaluation/run-integrity/spec.md § 判定失败必须带可归因的原因

用桩 LLM 构造四类失败,验证均被正确采集与归约。不触真实 LLM。
"""

from __future__ import annotations

import pytest

from src.core.types import DegradationReason
from src.observability.evaluation.judge_call_collector import (
    JudgeCallCollector,
    classify_exception,
)


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 采集:四类失败特征
# ---------------------------------------------------------------------------


class TestCollectionOfFailureModes:
    def test_empty_response_recorded_as_ok_but_empty(self) -> None:
        """空响应在传输层是成功的 —— 失败发生在内容层,两者必须能区分。

        项目在 labeling 路径踩过这个坑:max_tokens 给少了导致模型没写完就被
        截断,HTTP 完全成功、返回却是空串,当时被误读成「模型不遵从 JSON」。
        """
        collector = JudgeCallCollector()
        collector.record_success("")

        assert collector.calls[0].ok is True
        assert collector.calls[0].empty is True
        assert collector.calls[0].reason == DegradationReason.EMPTY_RESPONSE.value

    def test_whitespace_only_counts_as_empty(self) -> None:
        collector = JudgeCallCollector()
        collector.record_success("   \n\t ")
        assert collector.calls[0].empty is True

    def test_normal_response_recorded_clean(self) -> None:
        collector = JudgeCallCollector()
        collector.record_success('{"verdict": 1}')

        assert collector.calls[0].ok is True
        assert collector.calls[0].empty is False
        assert collector.calls[0].reason is None
        assert collector.calls[0].response_chars == len('{"verdict": 1}')

    def test_timeout_recorded(self) -> None:
        collector = JudgeCallCollector()
        collector.record_failure(TimeoutError("request timed out after 60s"))

        assert collector.calls[0].ok is False
        assert collector.calls[0].reason == DegradationReason.TIMEOUT.value

    def test_upstream_error_recorded(self) -> None:
        collector = JudgeCallCollector()
        collector.record_failure(RuntimeError("503 model_not_found"))

        assert collector.calls[0].ok is False
        assert collector.calls[0].reason == DegradationReason.UPSTREAM_ERROR.value

    def test_reset_clears_between_cases(self) -> None:
        """收集器生命周期与单条 case 对齐,不能串味。"""
        collector = JudgeCallCollector()
        collector.record_success("x")
        collector.reset()
        assert collector.calls == []


# ---------------------------------------------------------------------------
# 异常归类:只按类型名与消息做机械匹配(硬约束 1:不 import 具体 provider)
# ---------------------------------------------------------------------------


class TestExceptionClassification:
    @pytest.mark.parametrize(
        "exc",
        [
            TimeoutError("timed out"),
            RuntimeError("Read timeout"),
            Exception("ConnectTimeout"),
        ],
    )
    def test_timeout_family(self, exc: BaseException) -> None:
        assert classify_exception(exc) == DegradationReason.TIMEOUT.value

    @pytest.mark.parametrize(
        "exc",
        [
            RuntimeError("401 Unauthorized"),
            RuntimeError("429 Too Many Requests"),
            RuntimeError("503 model_not_found"),
            ConnectionError("connection refused"),
        ],
    )
    def test_upstream_family(self, exc: BaseException) -> None:
        assert classify_exception(exc) == DegradationReason.UPSTREAM_ERROR.value

    def test_unrecognized_falls_back_to_unknown(self) -> None:
        """归不了类就诚实说不知道,不硬塞进某一类。"""
        assert classify_exception(ValueError("something odd")) == DegradationReason.UNKNOWN.value

    def test_timeout_wins_over_upstream_when_both_present(self) -> None:
        """超时更具体,优先于泛化的上游错误。"""
        assert (
            classify_exception(RuntimeError("HTTP 504 gateway timeout"))
            == DegradationReason.TIMEOUT.value
        )


# ---------------------------------------------------------------------------
# 归约:调用级事实 -> 指标级原因
# ---------------------------------------------------------------------------


class TestReductionToDominantReason:
    def test_no_calls_is_unknown(self) -> None:
        """一次调用都没有 → 失败发生在 judge 调用之外(embedding 侧、RAGAS
        自身逻辑),本采集器看不到,只能诚实报 unknown。"""
        assert JudgeCallCollector().dominant_reason() == DegradationReason.UNKNOWN.value

    def test_exception_takes_priority(self) -> None:
        """调用根本没成功时,后续推断都无意义。"""
        collector = JudgeCallCollector()
        collector.record_success("fine")
        collector.record_failure(TimeoutError("timed out"))
        collector.record_success("")

        assert collector.dominant_reason() == DegradationReason.TIMEOUT.value

    def test_empty_beats_unparseable(self) -> None:
        collector = JudgeCallCollector()
        collector.record_success("fine")
        collector.record_success("")

        assert collector.dominant_reason() == DegradationReason.EMPTY_RESPONSE.value

    def test_all_calls_clean_infers_unparseable(self) -> None:
        """全部调用成功且非空、指标却仍是 NaN → 只能是结构不符合 RAGAS 预期。

        这是本模块唯一的**推断**,其余都是直接观测。
        """
        collector = JudgeCallCollector()
        collector.record_success('{"partial": ')
        collector.record_success("not json at all")

        assert collector.dominant_reason() == DegradationReason.UNPARSEABLE.value


# ---------------------------------------------------------------------------
# 适配层接线:collector 为 None 时行为不变
# ---------------------------------------------------------------------------


class TestWrapperIntegration:
    def test_collector_is_optional_in_signature(self) -> None:
        """向后兼容:不传 collector 时 build_ragas_judge 行为与改造前一致。"""
        import inspect

        from src.observability.evaluation._ragas_wrappers import build_ragas_judge

        sig = inspect.signature(build_ragas_judge)
        assert "collector" in sig.parameters
        assert sig.parameters["collector"].default is None
