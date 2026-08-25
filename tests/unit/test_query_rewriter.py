"""Unit tests for 查询改写器 (T-2.2)。

change: per-route-metrics-and-synonym-rewrite

**同义词扩展在解决什么**：BM25 是**字面匹配** —— 查询写 ``SL`` 而文档写「止损」
时，命中数为零。而稠密路的 embedding 本就对同义词鲁棒（两者的向量本来就近）。
所以「多给几组词面」这件事，受益的是 sparse 而不是 dense，这不是偏好问题，
是两种检索机制的构造决定的。

**本文件里两组用例守的是易漂移的口径**：

- ``TestExpandedTermsGoThroughTokenizer`` —— 扩展词必须与索引端共用同一个
  切分实现。两端漂移的失败是**静默的**（不报错，只是永远不命中）。
- ``TestZeroCost`` —— 「零 LLM、零延迟、零 token」是选中这个策略的**全部理由**，
  一旦实现里悄悄引入模型调用，这个理由就不成立，而它不会以任何错误的形式出现。

不联网、不调用任何模型。
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

import pytest
import yaml

from src.core.settings import QueryRewriteSettings, load_settings
from src.libs.query_rewriter import (
    BaseQueryRewriter,
    NoneQueryRewriter,
    QueryRewriterFactory,
    SynonymQueryRewriter,
)

pytestmark = pytest.mark.unit


def _dict_file(tmp_path, mapping: Dict[str, List[str]], name="syn.yaml") -> str:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(mapping, allow_unicode=True), encoding="utf-8")
    return str(path)


def _rewriter(tmp_path, mapping: Dict[str, List[str]]) -> SynonymQueryRewriter:
    return SynonymQueryRewriter(settings=None, synonym_dict=_dict_file(tmp_path, mapping))


# ---------------------------------------------------------------------------
# 默认策略
# ---------------------------------------------------------------------------


class TestNoneStrategy:
    def test_passthrough_preserves_order(self) -> None:
        """不改写时必须**原样**返回（含顺序）——``strategy: none`` 的行为
        要与引入本能力之前逐条相同。"""
        rewriter = NoneQueryRewriter()

        assert rewriter.rewrite_keywords(["b", "a", "c"]) == ["b", "a", "c"]

    def test_strategy_name(self) -> None:
        assert NoneQueryRewriter().get_strategy_name() == "none"

    def test_does_not_use_llm(self) -> None:
        assert NoneQueryRewriter().uses_llm() is False


# ---------------------------------------------------------------------------
# 同义词扩展
# ---------------------------------------------------------------------------


class TestSynonymExpansion:
    def test_hits_term_expands_whole_group(self, tmp_path) -> None:
        rewriter = _rewriter(tmp_path, {"止损": ["SL", "stoploss"]})

        result = rewriter.rewrite_keywords(["止损"])

        assert "止损" in result
        assert "sl" in [w.lower() for w in result]
        assert "stoploss" in [w.lower() for w in result]

    def test_hits_abbreviation_expands_whole_group(self, tmp_path) -> None:
        """**双向展开** —— 用户既可能写术语也可能写缩写。

        单向展开会漏掉一半情形，而漏掉的那一半不会有任何提示。
        """
        rewriter = _rewriter(tmp_path, {"止损": ["SL", "stoploss"]})

        result = rewriter.rewrite_keywords(["SL"])

        assert "止损" in result

    def test_case_insensitive_matching(self, tmp_path) -> None:
        rewriter = _rewriter(tmp_path, {"止损": ["SL"]})

        assert "止损" in rewriter.rewrite_keywords(["sl"])
        assert "止损" in rewriter.rewrite_keywords(["Sl"])

    def test_miss_returns_original_unchanged(self, tmp_path) -> None:
        """没命中任何词表条目时必须原样返回 —— 不能凭空造词。"""
        rewriter = _rewriter(tmp_path, {"止损": ["SL"]})

        assert rewriter.rewrite_keywords(["点差", "杠杆"]) == ["点差", "杠杆"]

    def test_original_keywords_come_first_and_keep_order(self, tmp_path) -> None:
        """原关键词全部保留且顺序不变，扩展词追加在后。

        原查询词是用户的真实措辞，不该被替换掉或打乱。
        """
        rewriter = _rewriter(tmp_path, {"止损": ["SL"]})

        result = rewriter.rewrite_keywords(["设置", "止损", "参数"])

        assert result[:3] == ["设置", "止损", "参数"]

    def test_deduplicates(self, tmp_path) -> None:
        """同一个词面可能由多个关键词各自引出，只保留一份。"""
        rewriter = _rewriter(tmp_path, {"止损": ["SL"], "stoploss": ["SL"]})

        result = rewriter.rewrite_keywords(["止损", "stoploss"])

        lowered = [w.lower() for w in result]
        assert len(lowered) == len(set(lowered))

    def test_empty_dictionary_is_passthrough(self, tmp_path) -> None:
        """空词表 = 什么都不扩展，但**不报错** —— 它表示「暂时没有条目」。"""
        rewriter = _rewriter(tmp_path, {})

        assert rewriter.rewrite_keywords(["止损"]) == ["止损"]
        assert rewriter.group_count == 0

    def test_empty_keywords(self, tmp_path) -> None:
        rewriter = _rewriter(tmp_path, {"止损": ["SL"]})

        assert rewriter.rewrite_keywords([]) == []

    def test_single_member_group_is_ignored(self, tmp_path) -> None:
        """只有一个词面的「组」没有扩展意义，不计入。"""
        rewriter = _rewriter(tmp_path, {"止损": []})

        assert rewriter.group_count == 0

    def test_deterministic(self, tmp_path) -> None:
        """同样的输入必须产出同样的输出 —— 无跨调用状态。"""
        rewriter = _rewriter(tmp_path, {"止损": ["SL", "stop loss"]})

        first = rewriter.rewrite_keywords(["止损"])
        second = rewriter.rewrite_keywords(["止损"])

        assert first == second

    def test_requires_a_dictionary_path(self) -> None:
        """不给词表就构造，必须报错。

        一个「什么都不做但看起来在做」的改写器正是本项目要消灭的形态。
        """
        with pytest.raises(ValueError, match="synonym dictionary"):
            SynonymQueryRewriter(settings=None, synonym_dict="")


class TestExpandedTermsGoThroughTokenizer:
    """扩展词必须与索引端共用同一个切分实现。

    词表里写的是「stop loss」这种自然写法，而索引端存的是**切分后**的词条。
    不切分就等于往查询里塞了一个索引里永远不存在的词 —— 这类失败是静默的：
    不报错，只是永远不命中。本项目已因两端口径漂移踩过一次
    （``tests/unit/test_tokenizer.py::TestBothEndsAgree`` 守的是同一件事）。
    """

    def test_multiword_synonym_is_tokenized(self, tmp_path) -> None:
        from src.core.text.tokenizer import tokenize

        rewriter = _rewriter(tmp_path, {"止损": ["stop loss"]})

        result = rewriter.rewrite_keywords(["止损"])

        expected_tokens = tokenize("stop loss")
        assert expected_tokens, "前提检查：tokenize 应当能切出词条"
        for token in expected_tokens:
            assert token in [w.lower() for w in result] or token in result, (
                f"扩展词 {token!r} 没有出现在结果里 —— 说明扩展词没过 tokenizer"
            )

    def test_raw_multiword_string_is_not_injected_verbatim(self, tmp_path) -> None:
        """不能把「stop loss」原样塞进关键词。

        索引端不存在这样一个整体词条，塞进去只是一个永远不会命中的查询词。
        """
        from src.core.text.tokenizer import tokenize

        rewriter = _rewriter(tmp_path, {"止损": ["stop loss"]})

        result = rewriter.rewrite_keywords(["止损"])

        if len(tokenize("stop loss")) > 1:
            assert "stop loss" not in result

    def test_chinese_synonym_is_tokenized(self, tmp_path) -> None:
        """中文同义词同样要过切分 —— CJK 走的是 bigram 口径。"""
        from src.core.text.tokenizer import tokenize

        rewriter = _rewriter(tmp_path, {"SL": ["止损单"]})

        result = rewriter.rewrite_keywords(["SL"])

        for token in tokenize("止损单"):
            assert token in result


class TestZeroCost:
    """标称零成本的策略**不得**引入任何模型调用。

    「零 token、零延迟」是选中同义词扩展的**全部理由**。若实现里悄悄加了一次
    LLM 调用，这个理由就不成立了 —— 而它不会以任何错误的形式表现出来，
    只是查询慢了、账单涨了。靠人工代码审查发现这类回归是不可靠的。
    """

    def test_declares_no_llm(self, tmp_path) -> None:
        assert _rewriter(tmp_path, {"止损": ["SL"]}).uses_llm() is False

    def test_no_llm_factory_call_during_rewrite(self, tmp_path, monkeypatch) -> None:
        """把 LLMFactory.create 换成会炸的替身，跑一次改写。

        只要实现里碰了 LLM，这条就会红。
        """
        from src.libs.llm import llm_factory

        def _boom(*args: Any, **kwargs: Any):
            raise AssertionError(
                "同义词扩展调用了 LLMFactory —— 它标称零 token/零延迟，"
                "引入模型调用就等于把选中它的理由抽掉了"
            )

        monkeypatch.setattr(llm_factory.LLMFactory, "create", _boom)

        rewriter = _rewriter(tmp_path, {"止损": ["SL", "stop loss"]})
        result = rewriter.rewrite_keywords(["止损", "设置"])

        assert "止损" in result

    def test_construction_does_not_call_llm(self, tmp_path, monkeypatch) -> None:
        """构造期同样不得调模型（词表加载是纯文件操作）。"""
        from src.libs.llm import llm_factory

        monkeypatch.setattr(
            llm_factory.LLMFactory,
            "create",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("构造期调用了 LLM")),
        )

        rewriter = _rewriter(tmp_path, {"止损": ["SL"]})

        assert rewriter.group_count == 1


# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------


class TestFactory:
    def test_registers_both_builtin_strategies(self) -> None:
        assert QueryRewriterFactory.list_providers() == ["none", "synonym"]

    def test_creates_none_by_default(self) -> None:
        settings = load_settings()

        rewriter = QueryRewriterFactory.create(settings)

        assert isinstance(rewriter, NoneQueryRewriter)

    def test_never_returns_none_object(self) -> None:
        """关闭时返回 ``NoneQueryRewriter`` 而不是 ``None``。

        这样调用点不必写 ``if rewriter is not None`` —— 关闭与启用走同一条
        代码路径，少一个分支就少一处漂移的可能。
        """
        settings = load_settings()

        assert QueryRewriterFactory.create(settings) is not None

    def test_creates_synonym_when_configured(self, tmp_path) -> None:
        settings = load_settings()
        settings.query_rewrite = QueryRewriteSettings(
            strategy="synonym", synonym_dict=_dict_file(tmp_path, {"止损": ["SL"]})
        )

        rewriter = QueryRewriterFactory.create(settings)

        assert isinstance(rewriter, SynonymQueryRewriter)
        assert rewriter.get_strategy_name() == "synonym"

    def test_unknown_strategy_raises(self) -> None:
        settings = load_settings()
        settings.query_rewrite = QueryRewriteSettings(strategy="hyde")

        with pytest.raises(ValueError, match="Unsupported query rewrite strategy"):
            QueryRewriterFactory.create(settings)

    def test_rejects_non_subclass_registration(self) -> None:
        class NotARewriter:
            pass

        with pytest.raises(ValueError, match="must inherit from BaseQueryRewriter"):
            QueryRewriterFactory.register_provider("bogus", NotARewriter)  # type: ignore[arg-type]


class TestProviderAgnostic:
    """业务代码不得 import 具体实现，也不得出现按策略名分支（宪法原则一）。

    用纯 Python 扫文件而不是 ``git grep`` —— 后者在 Windows 上会因控制台编码
    把中文源码解成乱码，且依赖 git 可用。
    """

    @staticmethod
    def _business_sources() -> List[Any]:
        from pathlib import Path

        roots = [Path("src/core"), Path("src/mcp_server"), Path("scripts")]
        files: List[Any] = []
        for root in roots:
            if root.exists():
                files.extend(
                    p for p in root.rglob("*.py") if "__pycache__" not in p.parts
                )
        return files

    def test_core_does_not_import_concrete_rewriters(self) -> None:
        offenders = []
        for path in self._business_sources():
            text = path.read_text(encoding="utf-8")
            if "SynonymQueryRewriter" in text or "synonym_query_rewriter" in text:
                offenders.append(str(path))

        assert offenders == [], (
            "业务代码里出现了具体改写器实现（应只经 QueryRewriterFactory）："
            f"{offenders}"
        )

    def test_no_strategy_name_branching_in_core(self) -> None:
        """检索路径上不得按策略名分支。

        ⚠️ **`src/core/settings.py` 是既定例外**：配置校验本来就必须知道
        「哪个策略需要哪个资源」（``synonym`` 要词表、``none`` 不要）。
        ``_validate_rerank_settings`` 里的 ``backend != "none"`` 是同一形态，
        是本模块的既有约定。宪法原则一禁的是**业务逻辑**按 provider 名分支，
        不是配置校验按取值分辨必填项。
        """
        # 用普通子串而不是正则 —— 要找的几种写法都很短，正则在这里只会带来
        # 引号转义的麻烦，读起来也不如直接列出来清楚。
        needles = ['== "synonym"', "== 'synonym'", '== "hyde"', "== 'hyde'"]
        offenders = []
        for path in self._business_sources():
            if path.name == "settings.py":
                continue
            text = path.read_text(encoding="utf-8")
            if any(needle in text for needle in needles):
                offenders.append(str(path))

        assert offenders == [], f"业务代码里出现了按策略名分支：{offenders}"

    def test_the_scan_actually_finds_things(self) -> None:
        """自检：扫描逻辑本身得能命中东西，否则上面两条是空过。

        「检查跑了但什么都没检查到」正是本项目的招牌病 —— 一个永远为空的
        扫描和一个永远通过的断言长得一模一样。
        """
        files = self._business_sources()

        assert len(files) > 20, f"只扫到 {len(files)} 个文件，扫描范围可能配错了"
