"""Unit tests for 改写在 QueryProcessor 里的挂载 (T-2.3)。

change: per-route-metrics-and-synonym-rewrite

**挂载位置为什么是「``_extract_keywords()`` 之后」**：顺序颠倒的话，扩展会作用在
未经停用词过滤的原始文本上，把本该被滤掉的词带进 BM25 查询 —— 而这不会报错，
只会让 sparse 更吵。

**为什么只改 ``keywords`` 不改 ``original_query``**：稠密路吃的是原始查询，它的
embedding 本就对同义词鲁棒；往那边塞同义词只会把一个干净的语义信号稀释成一串
并列词。稀疏路吃 ``keywords``，它才是字面匹配、才需要更多词面。

不联网、不调用任何模型。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import pytest
import yaml

from src.core.query_engine.query_processor import QueryProcessor
from src.core.types import ProcessedQuery
from src.libs.query_rewriter import NoneQueryRewriter, SynonymQueryRewriter

pytestmark = pytest.mark.unit


def _synonym_processor(tmp_path, mapping: Dict[str, List[str]]) -> QueryProcessor:
    path = tmp_path / "syn.yaml"
    path.write_text(yaml.safe_dump(mapping, allow_unicode=True), encoding="utf-8")
    return QueryProcessor(
        query_rewriter=SynonymQueryRewriter(settings=None, synonym_dict=str(path))
    )


class TestDefaultIsUnchanged:
    """``strategy: none`` 时 ``ProcessedQuery`` 必须与引入本能力之前逐条相同。

    这条守的不是新功能，而是「改造没碰坏老路」。
    """

    def test_keywords_unchanged(self) -> None:
        processor = QueryProcessor()

        result = processor.process("How to configure LLM in settings?")

        assert result.keywords == ["configure", "llm", "settings"]

    def test_rewritten_query_stays_none(self) -> None:
        """没产生新词时 ``rewritten_query`` 留 ``None``。

        这样序列化形态与改写前完全一致（``to_dict`` 会滤掉 None）。
        """
        processor = QueryProcessor()

        assert processor.process("configure LLM").rewritten_query is None

    def test_to_dict_shape_unchanged(self) -> None:
        processor = QueryProcessor()

        keys = set(processor.process("configure LLM").to_dict())

        # rewrite_info 是新增的审计字段；rewritten_query 仍应缺席
        assert "rewritten_query" not in keys
        assert {"original_query", "keywords", "filters"} <= keys

    def test_explicit_none_rewriter_equals_default(self) -> None:
        default = QueryProcessor().process("configure LLM stop loss")
        explicit = QueryProcessor(query_rewriter=NoneQueryRewriter()).process(
            "configure LLM stop loss"
        )

        assert default.keywords == explicit.keywords
        assert default.rewritten_query == explicit.rewritten_query


class TestExpansionAffectsKeywordsOnly:
    def test_keywords_are_expanded(self, tmp_path) -> None:
        processor = _synonym_processor(tmp_path, {"stoploss": ["sl"]})

        result = processor.process("how to set stoploss")

        assert "stoploss" in result.keywords
        assert "sl" in result.keywords

    def test_original_query_is_untouched(self, tmp_path) -> None:
        """扩展**不得**改动 ``original_query`` —— 那是稠密路的输入。"""
        processor = _synonym_processor(tmp_path, {"stoploss": ["sl"]})

        result = processor.process("how to set stoploss")

        assert result.original_query == "how to set stoploss"

    def test_original_keywords_survive_expansion(self, tmp_path) -> None:
        """用户自己的词必须全部保留且排在前面。"""
        processor = _synonym_processor(tmp_path, {"stoploss": ["sl"]})

        result = processor.process("configure stoploss parameter")

        assert result.keywords[:3] == ["configure", "stoploss", "parameter"]


class TestRewriteHappensAfterKeywordExtraction:
    """改写必须发生在停用词过滤之后。

    顺序颠倒的话，词表里若含一个停用词（例如 ``the``），扩展就会把它带回查询里，
    而这不会报错，只会让 sparse 更吵。
    """

    def test_stopword_is_not_reintroduced_from_query_text(self, tmp_path) -> None:
        # 词表键取一个**会被保留**的词，值里放一个**会被过滤掉**的停用词。
        processor = _synonym_processor(tmp_path, {"stoploss": ["the"]})

        result = processor.process("how to set stoploss")

        # "the" 会被 tokenize 的停用词过滤掉 —— 说明扩展词也确实过了同一套切分。
        from src.core.text.tokenizer import tokenize

        if not tokenize("the"):
            assert "the" not in result.keywords

    def test_stopwords_from_query_still_filtered(self, tmp_path) -> None:
        processor = _synonym_processor(tmp_path, {"stoploss": ["sl"]})

        result = processor.process("how to set the stoploss")

        assert "the" not in result.keywords
        assert "how" not in result.keywords


class TestDeadFieldIsNowAlive:
    """``ProcessedQuery.rewritten_query`` 曾是死字段，现在必须真的被写入。

    它自 feature-002 起就定义在 ``types.py``、有文档、``from_dict`` 会读 ——
    **就是没有任何生产路径读写它**。本项目管这类东西叫招牌病：
    有实现、有文档，就是没接上。
    """

    def test_rewritten_query_is_populated_when_expansion_happens(self, tmp_path) -> None:
        processor = _synonym_processor(tmp_path, {"stoploss": ["sl"]})

        result = processor.process("set stoploss")

        assert result.rewritten_query is not None
        assert "sl" in result.rewritten_query

    def test_rewritten_query_reflects_final_keywords(self, tmp_path) -> None:
        processor = _synonym_processor(tmp_path, {"stoploss": ["sl"]})

        result = processor.process("set stoploss")

        assert result.rewritten_query == " ".join(result.keywords)

    def test_no_new_terms_means_no_rewritten_query(self, tmp_path) -> None:
        """策略生效但一个词都没匹配上 → 仍留 ``None``。

        它表示「稀疏路实际用的查询」，没变化就不该伪造一个。
        """
        processor = _synonym_processor(tmp_path, {"止损": ["SL"]})

        result = processor.process("configure llm")

        assert result.rewritten_query is None

    def test_roundtrips_through_dict(self, tmp_path) -> None:
        processor = _synonym_processor(tmp_path, {"stoploss": ["sl"]})

        result = processor.process("set stoploss")
        restored = ProcessedQuery.from_dict(result.to_dict())

        assert restored.rewritten_query == result.rewritten_query
        assert restored.keywords == result.keywords


class TestRewriteInfoAlwaysRecorded:
    """留痕必须**无条件**发生，包括「没启用」和「启用了但没匹配到」。

    省略会让这两种情况在数据上无法区分，而它们的处置完全相反：
    前者去查配置，后者去改词表。
    """

    def test_recorded_when_disabled(self) -> None:
        result = QueryProcessor().process("configure llm")

        assert result.rewrite_info is not None
        assert result.rewrite_info["strategy"] == "none"
        assert result.rewrite_info["added_count"] == 0

    def test_recorded_when_enabled_but_no_match(self, tmp_path) -> None:
        processor = _synonym_processor(tmp_path, {"止损": ["SL"]})

        result = processor.process("configure llm")

        assert result.rewrite_info["strategy"] == "synonym"
        assert result.rewrite_info["added_count"] == 0

    def test_disabled_and_no_match_are_distinguishable(self, tmp_path) -> None:
        """两者的 ``added_count`` 都是 0 —— 只有 ``strategy`` 能区分它们。"""
        disabled = QueryProcessor().process("configure llm")
        no_match = _synonym_processor(tmp_path, {"止损": ["SL"]}).process("configure llm")

        assert disabled.rewrite_info["added_count"] == no_match.rewrite_info["added_count"]
        assert disabled.rewrite_info["strategy"] != no_match.rewrite_info["strategy"]

    def test_records_before_and_after(self, tmp_path) -> None:
        processor = _synonym_processor(tmp_path, {"stoploss": ["sl"]})

        info = processor.process("set stoploss").rewrite_info

        assert "stoploss" in info["original_keywords"]
        assert "sl" not in info["original_keywords"]
        assert "sl" in info["expanded_keywords"]
        assert info["added_count"] >= 1


class TestSharedTokenizerInvariantHolds:
    """扩展后查询端与索引端的切分口径仍然一致。

    这是 feature-004 的核心不变量（FR-009）—— 两端漂移的失败是静默的：
    不报错，只是召回恒为空。
    """

    def test_expanded_keywords_are_all_tokenizer_output(self, tmp_path) -> None:
        from src.core.text.tokenizer import tokenize

        processor = _synonym_processor(tmp_path, {"stoploss": ["stop loss", "SL"]})

        result = processor.process("set stoploss")

        for keyword in result.keywords:
            # 每个关键词单独过一次 tokenizer 必须还是它自己 ——
            # 若某个词是「stop loss」这样未切分的原文，这里就会不等。
            assert tokenize(keyword) == [keyword], (
                f"关键词 {keyword!r} 不是 tokenizer 的输出，两端口径已漂移"
            )
