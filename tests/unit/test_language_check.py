"""Unit tests for 目标语言校验。

change: expand-chinese-golden-set (T-1.1)

**本文件最重要的一组是 `TestRealUntranslatedPrompt`** —— 它用的是从
`logs/ragas_adapt_cache/chinese/` 实际读出的形态:RAGAS 声称已翻译成中文、
实则一个汉字都没有的提示词。整个变更就是为了让这种产物**不可能静默通过**。

失效链条(2026-08-14 实测):
1. `adapt()` 不抛异常地返回未翻译的英文 → 只捕获异常的 fail-fast 从未触发
2. 坏产物被写进磁盘缓存,永久固化
3. 后续每次合成都读到英文提示词 → 产出英文问题
4. 第一代中文金标 47 条候选丢了 33 条(70%),只活下来 6 条

纯函数,不 import ragas、不联网。
"""

from __future__ import annotations

import pytest

from src.observability.evaluation.language_check import (
    check_language,
    language_char_ratio,
    mismatch_ratio,
    summarize_language,
    supported_languages,
)

pytestmark = pytest.mark.unit


# 从 logs/ragas_adapt_cache/chinese/answer_formulate.json 实际截取的片段。
# 它本应是中文 —— 文件路径写着 chinese，RAGAS 也没报错。
_REAL_UNTRANSLATED_PROMPT = (
    '{"name": "answer_formulate", "instruction": "Answer the question using the '
    'information from the given context. Output verdict as \'1\' if answer is '
    'present \'-1\' if answer is not present in the context.", '
    '"output_format_instruction": "The output should be a well-formatted JSON '
    'instance that conforms to the JSON schema below."}'
)

_TRANSLATED_PROMPT = (
    '{"name": "answer_formulate", "instruction": "使用给定上下文中的信息回答问题。'
    '如果上下文中存在答案则输出判定为 \'1\'，不存在则输出 \'-1\'。", '
    '"output_format_instruction": "输出应为符合下述 JSON schema 的规范 JSON 实例。"}'
)


class TestRealUntranslatedPrompt:
    """**核心回归**:真实的「假装已翻译」产物必须被判失败。"""

    def test_untranslated_prompt_has_zero_ratio(self) -> None:
        ratio, counted = language_char_ratio(_REAL_UNTRANSLATED_PROMPT, "zh")

        assert ratio == 0.0
        assert counted > 0  # 有内容，只是没有一个汉字

    def test_untranslated_prompt_fails_check(self) -> None:
        result = check_language(_REAL_UNTRANSLATED_PROMPT, "zh", threshold=0.05)

        assert result.passed is False
        assert result.ratio == 0.0

    def test_translated_prompt_passes(self) -> None:
        """译文里仍有大量 JSON 结构与英文字段名 —— 阈值必须容得下这一点。"""
        result = check_language(_TRANSLATED_PROMPT, "zh", threshold=0.05)

        assert result.passed is True
        assert result.ratio > 0.05

    def test_translated_ratio_is_well_above_threshold(self) -> None:
        """两端差距要足够大,阈值才不必精调。"""
        bad, _ = language_char_ratio(_REAL_UNTRANSLATED_PROMPT, "zh")
        good, _ = language_char_ratio(_TRANSLATED_PROMPT, "zh")

        assert bad == 0.0
        assert good > 0.20  # 实测译文远高于阈值

    def test_describe_explains_the_verdict(self) -> None:
        """错误消息要带实测占比 ——「为什么失败」比「失败了」有用得多。"""
        msg = check_language(_REAL_UNTRANSLATED_PROMPT, "zh", 0.05).describe()

        assert "FAILED" in msg
        assert "0.0%" in msg
        assert "zh" in msg


class TestRatioBasics:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("全中文文本", 1.0),
            ("pure english text", 0.0),
            ("", 0.0),
            ("   \n\t  ", 0.0),
        ],
    )
    def test_pure_cases(self, text: str, expected: float) -> None:
        ratio, _ = language_char_ratio(text, "zh")
        assert ratio == expected

    def test_mixed_text(self) -> None:
        # 4 个汉字 + 4 个字母 = 8 个非空白字符
        ratio, counted = language_char_ratio("中文abcd英文", "zh")
        assert counted == 8
        assert ratio == pytest.approx(4 / 8)

    def test_whitespace_excluded_from_denominator(self) -> None:
        """空白不计入分母 —— 否则同一段译文会因换行缩进不同得到不同比例。

        JSON 结构里换行与缩进占比很高且与语言无关。
        """
        compact, n1 = language_char_ratio("中文abc", "zh")
        spaced, n2 = language_char_ratio("中 文\n\ta b c", "zh")

        assert n1 == n2 == 5  # 中,文,a,b,c
        assert compact == spaced == pytest.approx(2 / 5)

    def test_punctuation_counts_as_non_chinese(self) -> None:
        """标点不算中文特征 —— 只有汉字算。"""
        ratio, _ = language_char_ratio("，。！？", "zh")
        assert ratio == 0.0


class TestCheckSemantics:
    def test_empty_text_always_fails(self) -> None:
        """空文本一律失败:没有内容可以证明它被翻译过。"""
        for threshold in (0.0, 0.05, 1.0):
            assert check_language("", "zh", threshold).passed is False

    def test_zero_threshold_still_rejects_empty(self) -> None:
        """即便阈值为 0,空文本也不该通过 —— 否则 adapt 返回空串会被判「已翻译」。"""
        assert check_language("", "zh", 0.0).passed is False

    def test_zero_threshold_accepts_any_nonempty(self) -> None:
        assert check_language("english only", "zh", 0.0).passed is True

    def test_result_carries_inputs(self) -> None:
        r = check_language("中文", "zh", 0.5)
        assert r.language == "zh"
        assert r.threshold == 0.5

    @pytest.mark.parametrize("bad", [-0.1, 1.1, 2.0])
    def test_threshold_out_of_range_rejected(self, bad: float) -> None:
        with pytest.raises(ValueError, match=r"\[0.0, 1.0\]"):
            check_language("中文", "zh", bad)

    def test_result_is_immutable(self) -> None:
        """结果不可变 —— 它会被写进元数据,不该被下游改掉。"""
        r = check_language("中文", "zh", 0.5)
        with pytest.raises(Exception):
            r.ratio = 0.9  # type: ignore[misc]


class TestUnsupportedLanguage:
    def test_unregistered_language_raises(self) -> None:
        """未登记的语言必须明确报错,不能静默按某个默认规则判。"""
        with pytest.raises(ValueError, match="unsupported language"):
            language_char_ratio("なにか", "ja")

    def test_error_lists_supported_and_tells_how_to_extend(self) -> None:
        with pytest.raises(ValueError, match="_LANGUAGE_RANGES"):
            check_language("x", "ja", 0.05)

    def test_supported_languages_reported(self) -> None:
        assert "zh" in supported_languages()


class TestMismatchRatio:
    """合成产物的语种一致性统计 —— 第一代实测是 70%(33/47)。"""

    def test_all_target_language(self) -> None:
        assert mismatch_ratio(["中文问题一", "中文问题二"], "zh", 0.05) == 0.0

    def test_all_wrong_language(self) -> None:
        assert mismatch_ratio(["english one", "english two"], "zh", 0.05) == 1.0

    def test_first_generation_shape(self) -> None:
        """复现第一代的形态:47 条里 33 条是英文问题。"""
        texts = ["中文问题"] * 14 + ["an english question"] * 33

        assert mismatch_ratio(texts, "zh", 0.05) == pytest.approx(33 / 47)

    def test_empty_sequence(self) -> None:
        assert mismatch_ratio([], "zh", 0.05) == 0.0

    def test_summarize_shape(self) -> None:
        s = summarize_language(["中文", "english"], "zh", 0.05)

        assert s["total"] == 2.0
        assert s["mismatch_ratio"] == 0.5
        assert s["threshold"] == 0.05
