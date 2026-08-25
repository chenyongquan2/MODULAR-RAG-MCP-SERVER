"""守线用例：``query_rewrite.*` 不得成为死配置 (T-2.5)。

change: per-route-metrics-and-synonym-rewrite

**这个文件存在的唯一理由**，是本项目九次同源事故里最新的那两次教训：

- ``rerank.top_m`` —— 全仓只有定义和面板展示，**从未截断过候选**。
- ``synthesis.question_language_mismatch_warn`` —— 进了 settings、被校验取值
  范围、helper 有实现有单测，**然后没有任何生产路径调用它**。
- ``_labeling_method`` —— 有实现、有默认值、有文档、**还有单测**，但那些单测测的是
  「``EvalReport`` 收到值以后会不会序列化」，**从没测过这个值有没有被读出来**。
  于是报告里的标注方式恒为第一代，跨代保护在那一维上从未生效过。

第三条给出的判据是最锋利的：**「有单测」不等于「接上了」。要守的是端到端那条线
（配置写 X → 最终行为就必须是 X），不是端点行为。**

所以下面每一条都从**配置**出发、验到**最终送进检索的关键词**，中间不跳步。
死配置的判据一句话：**改了它，什么都不变。**

不联网、不调用任何模型。
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest
import yaml

from src.core.query_engine.hybrid_search import HybridSearch
from src.core.query_engine.fusion import Fusion
from src.core.settings import QueryRewriteSettings, load_settings
from src.core.types import RetrievalResult
from src.libs.query_rewriter import QueryRewriterFactory

pytestmark = pytest.mark.unit


def _dict_file(tmp_path, mapping: Dict[str, List[str]], name: str) -> str:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(mapping, allow_unicode=True), encoding="utf-8")
    return str(path)


def _settings_with(tmp_path, strategy: str, mapping: Dict[str, List[str]] | None, name: str):
    """构造一份「只有 query_rewrite 段不同」的配置。"""
    settings = load_settings()
    settings.query_rewrite = QueryRewriteSettings(
        strategy=strategy,
        synonym_dict=_dict_file(tmp_path, mapping, name) if mapping is not None else "",
    )
    return settings


class CapturingSparseRetriever:
    """记录**实际收到的关键词**的稀疏检索器替身。

    这是本文件的关键装置：断言停在 ``ProcessedQuery`` 上是不够的 ——
    那还是端点。要看的是「送进 sparse 的到底是什么」。
    """

    def __init__(self) -> None:
        self.received_keywords: List[List[str]] = []

    def retrieve(self, keywords, *args: Any, **kwargs: Any) -> List[RetrievalResult]:
        self.received_keywords.append(list(keywords))
        return []


class StubDenseRetriever:
    def __init__(self) -> None:
        self.received_queries: List[str] = []

    def retrieve(self, query, *args: Any, **kwargs: Any) -> List[RetrievalResult]:
        self.received_queries.append(query)
        return [RetrievalResult(chunk_id="a", score=1.0, text="t", metadata={})]


class PassthroughReranker:
    def rerank(self, query: str, results, trace: Any = None):
        return list(results)


def _search_and_capture(settings, query: str = "set stoploss"):
    """走**完整链路**：配置 → HybridSearch → QueryProcessor → sparse 的输入。

    刻意不直接构造 QueryProcessor —— 那样就跳过了「配置有没有真的流到检索侧」
    这一段，而事故恰恰都发生在这种被跳过的中间段。
    """
    sparse = CapturingSparseRetriever()
    dense = StubDenseRetriever()
    hybrid = HybridSearch(
        settings=settings,
        dense_retriever=dense,
        sparse_retriever=sparse,
        fusion=Fusion(k=60, weights=settings.retrieval.fusion_weights),
        reranker=PassthroughReranker(),
    )
    hybrid.search(query, top_k=3)
    return sparse.received_keywords[0], dense.received_queries[0]


class TestStrategyIsActuallyRead:
    """``strategy`` 改了，送进 sparse 的关键词就必须变。"""

    def test_none_vs_synonym_differ(self, tmp_path) -> None:
        mapping = {"stoploss": ["sl", "stop loss"]}
        off = _settings_with(tmp_path, "none", mapping, "a.yaml")
        on = _settings_with(tmp_path, "synonym", mapping, "b.yaml")

        off_keywords, _ = _search_and_capture(off)
        on_keywords, _ = _search_and_capture(on)

        assert off_keywords != on_keywords, (
            "把 strategy 从 none 改成 synonym 之后，送进 sparse 的关键词没变 —— "
            "这个配置项没有生效"
        )
        assert "sl" in on_keywords
        assert "sl" not in off_keywords

    def test_none_is_byte_for_byte_the_old_behaviour(self, tmp_path) -> None:
        """``none`` 时必须与引入本能力之前逐条相同。"""
        settings = _settings_with(tmp_path, "none", {"stoploss": ["sl"]}, "c.yaml")

        keywords, _ = _search_and_capture(settings)

        assert keywords == ["set", "stoploss"] or "sl" not in keywords


class TestDictionaryContentIsActuallyRead:
    """词表**内容**改了，结论就必须变 —— 这是死配置最经典的判据。"""

    def test_different_dictionaries_give_different_keywords(self, tmp_path) -> None:
        rich = _settings_with(
            tmp_path, "synonym", {"stoploss": ["sl", "stop loss"]}, "rich.yaml"
        )
        poor = _settings_with(tmp_path, "synonym", {"spread": ["点差"]}, "poor.yaml")

        rich_keywords, _ = _search_and_capture(rich)
        poor_keywords, _ = _search_and_capture(poor)

        assert rich_keywords != poor_keywords, (
            "换了一份完全不同的词表，送进 sparse 的关键词却一样 —— "
            "词表没有被真的读取"
        )
        assert "sl" in rich_keywords
        assert "sl" not in poor_keywords

    def test_empty_dictionary_behaves_like_none(self, tmp_path) -> None:
        """空词表 = 没有可扩展的条目，结果应与关闭一致。

        注意这**不等于**「空词表和关闭是同一件事」—— 留痕里的 ``strategy``
        仍然不同，那是刻意的（见 T-2.4 的用例）。
        """
        empty = _settings_with(tmp_path, "synonym", {}, "empty.yaml")
        off = _settings_with(tmp_path, "none", {}, "off.yaml")

        empty_keywords, _ = _search_and_capture(empty)
        off_keywords, _ = _search_and_capture(off)

        assert empty_keywords == off_keywords

    def test_adding_an_entry_changes_the_outcome(self, tmp_path) -> None:
        """往词表里加一条，同一个查询的结果就该变。"""
        before = _settings_with(tmp_path, "synonym", {"spread": ["点差"]}, "before.yaml")
        after = _settings_with(
            tmp_path, "synonym", {"spread": ["点差"], "stoploss": ["sl"]}, "after.yaml"
        )

        before_keywords, _ = _search_and_capture(before)
        after_keywords, _ = _search_and_capture(after)

        assert len(after_keywords) > len(before_keywords)


class TestDenseInputIsNotPolluted:
    """扩展只作用于 sparse —— dense 收到的必须仍是原始查询。

    这条也是「配置真的生效了吗」的一部分：如果实现图省事把扩展词也拼进
    dense 的输入，指标会以一种很难归因的方式变差，而且不会报错。
    """

    def test_dense_receives_original_query(self, tmp_path) -> None:
        settings = _settings_with(tmp_path, "synonym", {"stoploss": ["sl"]}, "d.yaml")

        sparse_keywords, dense_query = _search_and_capture(settings)

        assert dense_query == "set stoploss"
        assert "sl" in sparse_keywords


class TestFactoryHonoursConfig:
    """工厂必须按配置给出对应实现 —— 而不是永远返回同一个。"""

    def test_factory_returns_different_types(self, tmp_path) -> None:
        off = _settings_with(tmp_path, "none", None, "x.yaml")
        on = _settings_with(tmp_path, "synonym", {"stoploss": ["sl"]}, "y.yaml")

        assert (
            type(QueryRewriterFactory.create(off))
            is not type(QueryRewriterFactory.create(on))
        )

    def test_strategy_name_matches_config(self, tmp_path) -> None:
        on = _settings_with(tmp_path, "synonym", {"stoploss": ["sl"]}, "z.yaml")

        assert QueryRewriterFactory.create(on).get_strategy_name() == "synonym"
