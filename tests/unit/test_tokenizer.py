"""Unit tests for the shared tokenizer (Feature-004 T022/T023/T024/T025).

本文件守住 Feature-004 最核心的不变量:**查询端与索引端必须对同一段文本
产出完全相同的词条序列**。

为什么单独强调这条:违反它的失败是**静默的** —— 不报错、不告警,只是召回
恒为空。缺陷 D3 正是这样潜伏至今的(名为 ``mt5_docs_chinese`` 的索引里
7165 个词条含汉字 0 个,而没有任何日志提示过异常)。

不触发任何 LLM / 向量库调用。
"""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, ".")

from src.core.text.tokenizer import (
    DEFAULT_STOP_WORDS,
    MAX_TERM_LENGTH,
    MIN_TERM_LENGTH,
    contains_cjk,
    is_cjk_term,
    tokenize,
)

pytestmark = pytest.mark.unit


class TestCJKSegmentation:
    """CJK 段按相邻二字滑窗切分。"""

    def test_bigrams_from_chinese_run(self):
        assert tokenize("预约技师") == ["预约", "约技", "技师"]

    def test_two_char_run_yields_single_bigram(self):
        assert tokenize("技师") == ["技师"]

    def test_single_char_run_yields_that_char(self):
        """单字必须成词。

        否则「钱」「房」这类单字查询在关键词路径上永远无结果 —— 而且不报错。
        """
        assert tokenize("钱") == ["钱"]

    def test_single_char_between_punctuation(self):
        assert tokenize("说：好。") == ["说", "好"]

    def test_bigram_count_is_len_minus_one(self):
        text = "只能在主服务器上运行"
        assert len(tokenize(text)) == len(text) - 1

    def test_cjk_terms_are_not_length_filtered(self):
        """长度约束只作用于非 CJK —— 单字 CJK 词条长度为 1,不得被吃掉。"""
        assert tokenize("钱", min_length=5) == ["钱"]

    def test_cjk_terms_are_not_stopword_filtered(self):
        """停用词表是英文表,对 CJK 词条不适用。"""
        assert tokenize("的应用", stop_words=frozenset({"的应"})) == ["的应", "应用"]


class TestASCIISegmentation:
    """非 CJK 段沿用取词 + 停用词 + 长度约束。"""

    def test_lowercases(self):
        assert tokenize("Hello WORLD") == ["hello", "world"]

    def test_splits_on_hyphen(self):
        """连字符处切开。

        修复前索引端切成 well/known、查询端保留 well-known,于是
        ``well-known`` 这类查询**永远匹配不上** —— 与中文失效同类的静默失败。
        """
        assert tokenize("well-known") == ["well", "known"]

    def test_splits_on_underscore(self):
        assert tokenize("MT_RET_ERR_NOTFOUND") == ["mt", "ret", "err", "notfound"]

    def test_filters_stop_words(self):
        assert tokenize("the quick brown fox") == ["quick", "brown", "fox"]

    def test_filters_short_terms(self):
        assert "a" not in tokenize("a quick fox")

    def test_filters_overlong_terms(self):
        long_token = "x" * (MAX_TERM_LENGTH + 1)
        assert tokenize(long_token) == []

    def test_keeps_digits(self):
        assert tokenize("API v2 2026") == ["api", "v2", "2026"]

    def test_preserves_order_and_duplicates(self):
        """必须保留重复 —— 索引端要靠出现次数算词频。"""
        assert tokenize("hello world hello") == ["hello", "world", "hello"]


class TestMixedText:
    """中英混排 —— MT5 中文文档里夹杂大量英文术语。"""

    def test_chinese_and_ascii_coexist(self):
        assert tokenize("预约技师 API_v2") == ["预约", "约技", "技师", "api", "v2"]

    def test_ascii_capability_not_weakened_by_cjk_support(self):
        """FR-010:新增中文支持不得削弱既有英文术语匹配。"""
        assert tokenize("MT_RET_ERR_NOTFOUND 错误码") == [
            "mt", "ret", "err", "notfound", "错误", "误码",
        ]

    def test_no_bigram_across_ascii_boundary(self):
        """CJK 段被英文隔断时不得跨段组词。"""
        tokens = tokenize("错误 code 码")
        assert "误码" not in tokens
        assert tokens == ["错误", "code", "码"]


class TestEdgeCases:
    @pytest.mark.parametrize("text", ["", "   ", "\n\t"])
    def test_blank_input(self, text):
        assert tokenize(text) == []

    def test_punctuation_only(self):
        assert tokenize("！？。，—— ...") == []

    def test_deterministic(self):
        text = "只能在主服务器上运行的应用程序 API_v2"
        assert tokenize(text) == tokenize(text)


class TestStopWordUnion:
    """停用词表是两个旧表的并集(见模块 docstring)。"""

    @pytest.mark.parametrize("word", ["also", "dare", "may", "might", "must", "shall", "used", "whose"])
    def test_index_only_stop_words_now_filtered_on_both_sides(self, word):
        """这 9 个词此前只有索引端过滤 —— 查询会搜它们而索引里没有,白搜。"""
        assert word in DEFAULT_STOP_WORDS

    @pytest.mark.parametrize("word", ["about", "above", "because", "cannot", "between"])
    def test_query_only_stop_words_now_filtered_on_both_sides(self, word):
        assert word in DEFAULT_STOP_WORDS

    def test_meaningful_terms_not_swallowed(self):
        """并集不得误伤有信息量的词。"""
        for term in ("server", "config", "retrieval", "api", "error"):
            assert term not in DEFAULT_STOP_WORDS


class TestHelpers:
    def test_contains_cjk(self):
        assert contains_cjk("hello 世界")
        assert not contains_cjk("hello world")

    def test_is_cjk_term(self):
        assert is_cjk_term("预约")
        assert not is_cjk_term("api")

    def test_japanese_and_korean_go_through_cjk_branch(self):
        """假名与谚文若落到 ASCII 分支会被**静默丢弃**,重演 D3。"""
        assert tokenize("こんにちは") != []
        assert tokenize("안녕하세요") != []


class TestBothEndsAgree:
    """★ 核心不变量:索引端与查询端产出完全相同的词条序列。

    这是本 feature 的中心约束(FR-009)。两端各留一份实现正是 D3 的成因,
    而口径漂移的失败**不报错** —— 查询切出的词条永远匹配不上索引里的,
    召回恒为空。
    """

    SAMPLES = [
        "只能在主服务器上运行的应用程序才能添加或更新配置吗？",
        "What triggers the MT_RET_ERR_NOTFOUND error?",
        "IMTAdminAPI 接口在 MTAdminCreate 中的输出参数起什么作用？",
        "well-known API_v2 configuration",
        "预约技师",
        "钱",
    ]

    @pytest.mark.parametrize("text", SAMPLES)
    def test_index_side_and_query_side_produce_identical_tokens(self, text):
        from src.core.query_engine.query_processor import QueryProcessor
        from src.ingestion.embedding.sparse_encoder import SparseEncoder

        index_side = SparseEncoder()._tokenize(text)
        query_side = QueryProcessor()._tokenize_shared(text)

        assert index_side == query_side, (
            f"两端切分口径漂移:{text!r}\n"
            f"  索引端: {index_side}\n"
            f"  查询端: {query_side}\n"
            "这类失败是静默的 —— 不报错,只是召回恒为空。"
        )

    @pytest.mark.parametrize("text", SAMPLES)
    def test_both_ends_delegate_to_shared_tokenizer(self, text):
        from src.core.query_engine.query_processor import QueryProcessor
        from src.ingestion.embedding.sparse_encoder import SparseEncoder

        expected = tokenize(text)
        assert SparseEncoder()._tokenize(text) == expected
        assert QueryProcessor()._tokenize_shared(text) == expected

    def test_phrase_from_corpus_text_matches_that_text(self):
        """往返验证:正文里真实出现的短语,切出的词条必须是正文词条的子集。

        这是「索引里能被查到」的直接前提。
        """
        document = "只能在主服务器上运行的应用程序才能添加或更新配置"
        query = "主服务器"

        doc_tokens = set(tokenize(document))
        query_tokens = tokenize(query)

        assert query_tokens
        assert set(query_tokens) <= doc_tokens

    def test_no_duplicated_tokenizer_implementation_in_src(self):
        """回归守卫:两端不得再各写一份正则。

        D3 的成因就是 sparse_encoder.py:128 与 query_processor.py:145
        各有一份只留 ASCII 的正则。
        """
        from pathlib import Path

        for path in (
            "src/ingestion/embedding/sparse_encoder.py",
            "src/core/query_engine/query_processor.py",
        ):
            source = Path(path).read_text(encoding="utf-8")
            assert r"[^a-z0-9\s-]" not in source, f"{path} 仍留有本地切分正则"
            assert r"\b[a-z0-9]+\b" not in source, f"{path} 仍留有本地切分正则"
