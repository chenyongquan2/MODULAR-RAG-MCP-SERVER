"""Unit tests for 答案语言一致性的产出 (T-1.2)。

change: answer-language-follows-question

**这组测试守的是「能看见」，不是「答得对」。** 提示词改动在 §2，
而在改之前必须先把观测建起来 —— 否则改完不知道有没有改对。
这轮已经在同义词扩展上吃过一次教训：融合后指标看不见单路的变化，
先补了分路径口径才敢做 A/B。

两处都要有结论（``StructuredContent`` 与 trace），理由见
``TestBothChannelsCarryTheSameVerdict`` 的说明。

不联网、不调真实模型 —— LLM 用替身。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pytest

from src.core.response.response_builder import ResponseBuilder
from src.core.settings import load_settings
from src.core.types import RetrievalResult

pytestmark = pytest.mark.unit


class FakeLLM:
    """返回预置答案的 LLM 替身，并记录收到的 messages。"""

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.received: Optional[List[Dict[str, str]]] = None

    def chat(self, messages: List[Dict[str, str]], trace: Any = None, **kwargs: Any) -> str:
        self.received = messages
        return self.answer


class RecordingTrace:
    def __init__(self) -> None:
        self.metadata: Dict[str, Any] = {}

    def add_metadata(self, key: str, value: Any) -> None:
        self.metadata[key] = value

    # ResponseBuilder 把 trace 透传给 llm.chat，替身不需要其余方法


def _results() -> List[RetrievalResult]:
    return [
        RetrievalResult(
            chunk_id="c1", score=1.0, text="some context", metadata={"source": "doc.md"}
        )
    ]


def _builder(answer: str) -> ResponseBuilder:
    # 注入替身而不是先建真 LLM 再覆盖 —— 后者每次要 ~5 秒(真建一个客户端),
    # 且等于在测工厂而不是测本类。
    return ResponseBuilder(load_settings(), llm=FakeLLM(answer))  # type: ignore[arg-type]


class TestVerdictIsProduced:
    def test_inconsistent_pair_is_flagged(self) -> None:
        """英文提问 + 中文答案 —— 实测 61% 的英文问题就是这个形态。"""
        out = _builder("在设置里修改止损。").build("How to set stop loss?", _results())

        assert out.language_consistency is not None
        assert out.language_consistency["measured"] is True
        assert out.language_consistency["consistent"] is False
        assert out.language_consistency["question_language"] == "non-zh"
        assert out.language_consistency["answer_language"] == "zh"

    def test_consistent_pair(self) -> None:
        out = _builder("Set it in the config file.").build("How to set it?", _results())

        assert out.language_consistency["consistent"] is True

    def test_chinese_pair_is_consistent(self) -> None:
        out = _builder("在配置文件里改。").build("怎么设置止损", _results())

        assert out.language_consistency["consistent"] is True

    def test_threshold_comes_from_settings(self) -> None:
        """阈值必须来自配置，不能写死在生成端。"""
        settings = load_settings()
        out = _builder("Set it.").build("How?", _results())

        assert out.language_consistency["threshold"] == pytest.approx(
            settings.evaluation.synthesis.adapt_language_ratio_min
        )


class TestUndeterminedIsNotFaked:
    """判不出来时不给 ``consistent`` —— 不伪造结论。"""

    def test_numeric_question(self) -> None:
        out = _builder("Set it in the config.").build("123", _results())

        assert out.language_consistency["measured"] is False
        assert "consistent" not in out.language_consistency

    def test_empty_answer(self) -> None:
        """空答案不是「一致」，是「没有答案」。"""
        out = _builder("").build("How to set it?", _results())

        assert out.language_consistency["measured"] is False
        assert "consistent" not in out.language_consistency


class TestBothChannelsCarrySameVerdict:
    """结论必须同时进返回值与 trace，且两处相同。

    为什么两处都要：MCP 调用方拿到的是 ``StructuredContent``（trace 可能没开），
    而评估侧与仪表盘读 trace。只留一处会让另一条路看不见 ——
    把观测通道当数据通道，本项目在分路径指标那里已经拒绝过一次。
    """

    def test_trace_and_return_value_agree(self) -> None:
        trace = RecordingTrace()
        out = _builder("在设置里改。").build(
            "How to set it?", _results(), trace=trace
        )

        assert trace.metadata["language_consistency"] == out.language_consistency

    def test_works_without_trace(self) -> None:
        """不传 trace 时照常产出结论 —— 观测不能依赖 trace 开着。"""
        out = _builder("在设置里改。").build("How to set it?", _results())

        assert out.language_consistency is not None

    def test_trace_copy_is_independent(self) -> None:
        """写进 trace 的是副本 —— 调用方改返回值不该影响已落盘的追踪数据。"""
        trace = RecordingTrace()
        out = _builder("Set it.").build("How?", _results(), trace=trace)

        out.language_consistency["consistent"] = "tampered"

        assert trace.metadata["language_consistency"]["consistent"] is True


class TestInconsistencyIsLogged:
    """不一致必须在日志里直接可见 —— 这是缺陷此前藏了数月的原因。"""

    def test_warns_on_mismatch(self, caplog) -> None:
        with caplog.at_level(logging.WARNING):
            _builder("在设置里改。").build("How to set it?", _results())

        assert any(
            "语言" in r.getMessage() for r in caplog.records
        ), "答案语言不一致时没有告警"

    def test_no_warning_when_consistent(self, caplog) -> None:
        with caplog.at_level(logging.WARNING):
            _builder("Set it in the config.").build("How to set it?", _results())

        assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []

    def test_undetermined_is_info_not_warning(self, caplog) -> None:
        """判不出来是合法输入（纯数字问题），记 info 不记 warning。"""
        with caplog.at_level(logging.INFO):
            _builder("Set it.").build("123", _results())

        assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
