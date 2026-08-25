"""守卫：提示词不得单向偏向某一语言 (T-2.1 / T-2.2)。

change: answer-language-follows-question

## 这组用例守的是什么

**「后来者顺手把英文那半删了」。**

这个缺陷的根因就是提示词单语：system 消息与模板**全为中文**，且没有任何一句
提到输出语言 —— 模型看到一屋子中文指令，就据此推断该用中文回答，英文提问也
一样。实测后果：**61% 的英文问题得到含中文的答案**（run `728a77ab`，41 条）。

修法是双语书写 + 显式声明「用提问所用的语言回答」。而这个修法**极容易被顺手
撤销** —— 有人觉得双语提示词啰嗦，删掉一半，缺陷就静默回归了。而它要等下一次
跑批（约 90 分钟、要烧 token）才会暴露。

所以这里用单测把「双语」和「有语言要求」这两个性质钉住：它们是**结构性质**，
不需要跑模型就能验。

纯字符串检查，不联网、不调模型。
"""

from __future__ import annotations

from typing import Any

import pytest

from src.core.response.response_builder import ResponseBuilder
from src.core.settings import load_settings

pytestmark = pytest.mark.unit


class _NoopLLM:
    def chat(self, messages: Any, trace: Any = None, **kwargs: Any) -> str:
        return ""


@pytest.fixture(scope="module")
def builder() -> ResponseBuilder:
    return ResponseBuilder(load_settings(), llm=_NoopLLM())  # type: ignore[arg-type]


def _has_cjk(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


def _has_latin_words(text: str) -> bool:
    return any(ch.isascii() and ch.isalpha() for ch in text)


class TestPromptsAreBilingual:
    """两份提示词都必须同时含中英 —— 这是 design D1 的判据。"""

    def test_system_prompt_is_bilingual(self, builder: ResponseBuilder) -> None:
        prompt = builder._system_prompt()

        assert _has_cjk(prompt), "system 提示词缺中文半边"
        assert _has_latin_words(prompt), "system 提示词缺英文半边"

    def test_template_is_bilingual(self, builder: ResponseBuilder) -> None:
        template = builder.prompt_template

        assert _has_cjk(template), "模板缺中文半边"
        assert _has_latin_words(template), "模板缺英文半边"


class TestPromptsDemandLanguageMatching:
    """必须**显式**要求「用提问所用的语言回答」。

    这条与「双语」是两件事：一份双语提示词若不说输出语言，模型仍要靠猜。
    根因诊断里最关键的一句正是「**没有任何一句提到输出语言**」。
    """

    def test_system_prompt_states_the_rule_in_english(
        self, builder: ResponseBuilder
    ) -> None:
        prompt = builder._system_prompt().lower()

        assert "same language as the question" in prompt

    def test_system_prompt_states_the_rule_in_chinese(
        self, builder: ResponseBuilder
    ) -> None:
        assert "用提问所使用的语言回答" in builder._system_prompt()

    def test_template_states_the_rule_both_ways(self, builder: ResponseBuilder) -> None:
        template = builder.prompt_template

        assert "same language as the question" in template.lower()
        assert "用提问所使用的语言回答" in template

    def test_rule_covers_the_context_language_case(
        self, builder: ResponseBuilder
    ) -> None:
        """必须说清「即使上下文是另一种语言」。

        这是本项目的常态而非边缘情况：语料双语，英文问题检索到中文上下文的
        比例相当高（实测 41 条里 18 条上下文以中文为主）。不说清楚，
        模型很可能跟着上下文走。
        """
        combined = builder._system_prompt() + builder.prompt_template

        assert "another language" in combined.lower() or "different language" in combined.lower()
        assert "即使上下文是另一种语言" in combined


class TestExistingContractsPreserved:
    """引用格式与占位符不在本变更范围内，不得顺手改。"""

    def test_placeholders_present(self, builder: ResponseBuilder) -> None:
        template = builder.prompt_template

        assert "{context}" in template
        assert "{query}" in template

    def test_template_formats_without_error(self, builder: ResponseBuilder) -> None:
        """占位符必须真的可格式化 —— 多一个花括号就会在运行期炸。"""
        rendered = builder.prompt_template.format(query="Q", context="C")

        assert "Q" in rendered
        assert "C" in rendered
        assert "{" not in rendered.replace("{}", "")

    def test_citation_markers_still_required(self, builder: ResponseBuilder) -> None:
        template = builder.prompt_template

        assert "[1]" in template
        assert "[2]" in template

    def test_context_only_grounding_still_required(
        self, builder: ResponseBuilder
    ) -> None:
        """「仅基于上下文回答」这条约束不得在改语言时丢掉。"""
        combined = (builder._system_prompt() + builder.prompt_template).lower()

        assert "only the context" in combined or "based on the provided context" in combined
