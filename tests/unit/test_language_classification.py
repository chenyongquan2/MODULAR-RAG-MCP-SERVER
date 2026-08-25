"""Unit tests for 文本语言归类与问答一致性 (T-1.1)。

change: answer-language-follows-question

## 这组测试在守什么

**判定的边界，以及「不知道」必须能被说出来。**

`classify_language` 刻意只做「中文 vs 非中文」的二分 —— 不是通用语言识别。
返回值叫 ``non-zh`` 而不是 ``en``，因为前者是我们真的知道的事、后者是猜的：
一段法文会被判成 ``non-zh``，而我们不会知道。这组用例把这个边界固定下来，
免得后来者以为它能识别语种。

最关键的一条是 ``TestUndeterminedIsNotAGuess``：文本里没有语言信号时必须说
「未判定」，**不能回落成任一具体语言**。回落会让「没测出来」与「测过且是那个
语言」长得一模一样 —— 本项目已因这种回落栽过多次
（`_synthesis_metadata.language_consistency`、`aggregate_metrics_by_route`
都为此刻意用 `measured: false` 而不给数）。

纯函数，不联网、不调模型。
"""

from __future__ import annotations

import pytest

from src.observability.evaluation.language_check import (
    LANGUAGE_NON_ZH,
    LANGUAGE_UNDETERMINED,
    LANGUAGE_ZH,
    classify_language,
    compare_languages,
)

pytestmark = pytest.mark.unit

THRESHOLD = 0.05


class TestClassifyLanguage:
    def test_pure_english(self) -> None:
        assert classify_language("How to configure the LLM?", THRESHOLD) == LANGUAGE_NON_ZH

    def test_pure_chinese(self) -> None:
        assert classify_language("怎么配置大模型", THRESHOLD) == LANGUAGE_ZH

    def test_chinese_with_many_ascii_identifiers(self) -> None:
        """真实形态：中文句子里嵌大量 API 标识符，仍应判为中文。

        阈值 0.05 很低（5% 汉字即判中文），刻意偏向把混合文本判成中文 ——
        与语料实际（81.4% 中文）一致。
        """
        text = "调用 IMTServerAPI::PositionGetByLoginsSymbol 时 MT_RET_ERR_NOTFOUND 怎么处理"

        assert classify_language(text, THRESHOLD) == LANGUAGE_ZH

    def test_english_with_a_stray_chinese_char_stays_english(self) -> None:
        """反向误判需要 5% 以上汉字 —— 正常英文提问不会触发。"""
        text = "What does IMTServerAPI::DealSubscribe do and how should callers use it 呢"

        assert classify_language(text, THRESHOLD) == LANGUAGE_NON_ZH

    def test_code_identifiers_are_non_zh(self) -> None:
        assert classify_language("IMTServerAPI::PositionGet", THRESHOLD) == LANGUAGE_NON_ZH

    def test_threshold_is_honoured(self) -> None:
        """阈值真的被读了 —— 同一段文本在两个阈值下结论不同。

        这条守的是「参数没生效」：写死判定逻辑的实现会让两次结果相同。
        """
        text = "abcdefghijklmnopqrs中"  # 20 字符里 1 个汉字 = 5%

        assert classify_language(text, 0.04) == LANGUAGE_ZH
        assert classify_language(text, 0.50) == LANGUAGE_NON_ZH


class TestUndeterminedIsNotAGuess:
    """没有语言信号时必须说「未判定」，不能回落成任一具体语言。"""

    @pytest.mark.parametrize(
        "text", ["", "   ", "\n\t", "123 456", "!!! ??? ...", "-- 42 --"]
    )
    def test_no_language_signal(self, text: str) -> None:
        assert classify_language(text, THRESHOLD) == LANGUAGE_UNDETERMINED

    def test_undetermined_is_distinct_from_non_zh(self) -> None:
        """「未判定」与「非中文」是两个不同的结论，不得合并。"""
        assert LANGUAGE_UNDETERMINED != LANGUAGE_NON_ZH
        assert classify_language("123", THRESHOLD) != classify_language("abc", THRESHOLD)

    def test_non_zh_label_is_not_en(self) -> None:
        """标签刻意不叫 ``en`` —— 我们只知道「不是中文」，不知道是哪种语言。

        叫 ``en`` 会让一段法文被记成英文，而那是我们没有依据的断言。
        """
        assert LANGUAGE_NON_ZH != "en"


class TestCompareLanguages:
    def test_consistent(self) -> None:
        result = compare_languages("How to set it?", "Set it in the config.", THRESHOLD)

        assert result["measured"] is True
        assert result["consistent"] is True
        assert result["question_language"] == LANGUAGE_NON_ZH
        assert result["answer_language"] == LANGUAGE_NON_ZH

    def test_inconsistent_is_the_defect_we_are_fixing(self) -> None:
        """英文提问 + 中文答案 —— 实测 61% 的英文问题就是这个形态。"""
        result = compare_languages("How to set stop loss?", "在设置里修改止损。", THRESHOLD)

        assert result["measured"] is True
        assert result["consistent"] is False
        assert result["question_language"] == LANGUAGE_NON_ZH
        assert result["answer_language"] == LANGUAGE_ZH

    def test_chinese_pair_is_consistent(self) -> None:
        result = compare_languages("怎么设置止损", "在设置里修改止损。", THRESHOLD)

        assert result["consistent"] is True

    def test_threshold_is_recorded(self) -> None:
        """阈值进结论 —— 否则事后无法判断这个判定是在什么标准下做的。"""
        result = compare_languages("How?", "Like this.", 0.07)

        assert result["threshold"] == 0.07

    def test_undetermined_gives_no_consistent_key(self) -> None:
        """任一端无法判定时**不给** ``consistent``。

        给 ``True`` 会把「没测」伪装成「测过且一致」；给 ``False`` 会把它伪装成
        「测过且不一致」。两种都是伪造结论 —— 唯一诚实的做法是不给这个键。
        """
        result = compare_languages("123", "Set it.", THRESHOLD)

        assert result["measured"] is False
        assert "consistent" not in result
        assert "question" in str(result["reason"])

    def test_undetermined_answer_also_reported(self) -> None:
        result = compare_languages("How to set it?", "42", THRESHOLD)

        assert result["measured"] is False
        assert "consistent" not in result
        assert "answer" in str(result["reason"])

    def test_empty_answer_is_undetermined_not_consistent(self) -> None:
        """空答案不是「一致」—— 它是「没有答案」。"""
        result = compare_languages("How to set it?", "", THRESHOLD)

        assert result["measured"] is False
        assert "consistent" not in result
