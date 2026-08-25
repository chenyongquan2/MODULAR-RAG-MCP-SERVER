"""Unit tests for HybridSearch 的分路径返回通道 (T-1.1)。

change: per-route-metrics-and-synonym-rewrite

**为什么需要这个通道**：融合后的指标量不出单路的改善。本项目稀疏路的生效权重
只有稠密路的十分之一（``fusion_weights.sparse = 0.1``），所以任何只作用于稀疏路
的改进（同义词扩展就是），其效果在融合后指标上几乎看不见 —— 会得出「没有效果」
的错误结论，而改善其实真的发生了，只是被融合口径这把尺子量丢了。

**本文件最重要的一组是** ``TestSearchBehaviourUnchanged`` —— 它守的不是新功能，
而是「改造没有碰坏老路」。``search()`` 是 MCP server 与 ``scripts/query.py`` 的
主入口，它的签名与返回类型自始未变，现在只是转调 ``search_with_routes()``。

不触发任何 LLM / 向量库调用 —— 全部用替身。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

import pytest

from src.core.query_engine.fusion import Fusion
from src.core.query_engine.hybrid_search import HybridSearch
from src.core.types import ROUTE_DENSE, ROUTE_SPARSE, RetrievalResult, SearchOutcome

pytestmark = pytest.mark.unit


def _r(chunk_id: str, meta: Optional[Dict[str, Any]] = None) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=chunk_id,
        score=0.5,
        text=f"t-{chunk_id}",
        metadata=dict(meta or {}),
    )


class StubRetriever:
    """固定返回给定结果的检索器替身。"""

    def __init__(self, results: Sequence[RetrievalResult]) -> None:
        self._results = list(results)

    def retrieve(self, *args: Any, **kwargs: Any) -> List[RetrievalResult]:
        return list(self._results)


class FailingRetriever:
    """总是抛错的检索器替身 —— 用于验证单路失败时的降级行为。"""

    def retrieve(self, *args: Any, **kwargs: Any) -> List[RetrievalResult]:
        raise RuntimeError("boom")


class PassthroughReranker:
    def rerank(self, query: str, results: Sequence[RetrievalResult], trace: Any = None):
        return list(results)


def _build(
    dense: Sequence[RetrievalResult],
    sparse: Sequence[RetrievalResult],
    weights: Optional[Mapping[str, float]] = None,
    dense_retriever: Any = None,
    sparse_retriever: Any = None,
) -> HybridSearch:
    """构造一个只用替身的 HybridSearch（不读配置、不联网）。

    刻意用**真实的** ``Fusion`` 而不是替身 —— 本文件有一组用例断言
    「只留一路时分路径指标等于融合后结果」，那是分路径口径唯一的自检手段，
    用假融合器验它等于什么都没验。
    """
    return HybridSearch(
        settings=None,
        query_processor=_StubProcessor(),
        dense_retriever=dense_retriever or StubRetriever(dense),
        sparse_retriever=sparse_retriever or StubRetriever(sparse),
        fusion=Fusion(k=60, weights=dict(weights) if weights else None),
        reranker=PassthroughReranker(),
    )


class _StubProcessor:
    """最简查询预处理替身 —— 关键词就是原文分词后的结果。"""

    def process(self, query: str, filters: Any = None) -> Any:
        from src.core.types import ProcessedQuery

        return ProcessedQuery(original_query=query, keywords=query.split(), filters={})


# ---------------------------------------------------------------------------
# 老路不能被碰坏
# ---------------------------------------------------------------------------


class TestSearchBehaviourUnchanged:
    """``search()`` 的签名、返回类型与结果必须与改造前逐条相同。"""

    def test_search_still_returns_a_plain_list(self) -> None:
        hybrid = _build([_r("a")], [_r("b")])

        results = hybrid.search("q", top_k=5)

        assert isinstance(results, list)
        assert all(isinstance(r, RetrievalResult) for r in results)

    def test_search_equals_outcome_results(self) -> None:
        """``search()`` 就是 ``search_with_routes().results``，不多不少。"""
        hybrid = _build([_r("a"), _r("c")], [_r("b")])

        via_search = hybrid.search("q", top_k=5)
        via_outcome = hybrid.search_with_routes("q", top_k=5).results

        assert [r.chunk_id for r in via_search] == [r.chunk_id for r in via_outcome]

    def test_empty_query_still_raises(self) -> None:
        hybrid = _build([_r("a")], [_r("b")])

        with pytest.raises(ValueError, match="Query cannot be empty"):
            hybrid.search("   ")

    def test_invalid_top_k_still_raises(self) -> None:
        hybrid = _build([_r("a")], [_r("b")])

        with pytest.raises(ValueError, match="top_k must be a positive integer"):
            hybrid.search("q", top_k=0)


# ---------------------------------------------------------------------------
# 分路径通道本身
# ---------------------------------------------------------------------------


class TestRoutesExposed:
    def test_returns_search_outcome(self) -> None:
        hybrid = _build([_r("a")], [_r("b")])

        outcome = hybrid.search_with_routes("q", top_k=5)

        assert isinstance(outcome, SearchOutcome)

    def test_both_routes_present_with_their_own_results(self) -> None:
        hybrid = _build([_r("a"), _r("c")], [_r("b")])

        outcome = hybrid.search_with_routes("q", top_k=5)

        assert [r.chunk_id for r in outcome.routes[ROUTE_DENSE]] == ["a", "c"]
        assert [r.chunk_id for r in outcome.routes[ROUTE_SPARSE]] == ["b"]

    def test_route_order_is_preserved(self) -> None:
        """名次就是信息 —— 分路径结果的顺序必须原样保留。"""
        hybrid = _build([_r("z"), _r("y"), _r("x")], [])

        outcome = hybrid.search_with_routes("q", top_k=5)

        assert [r.chunk_id for r in outcome.routes[ROUTE_DENSE]] == ["z", "y", "x"]

    def test_empty_route_keeps_its_key(self) -> None:
        """某一路无结果时键仍在、值为空。

        省略键会让「这一路没检索到东西」与「根本没跑这一路」在数据上无法区分，
        而两者的处置完全不同。
        """
        hybrid = _build([_r("a")], [])

        outcome = hybrid.search_with_routes("q", top_k=5)

        assert ROUTE_SPARSE in outcome.routes
        assert outcome.routes[ROUTE_SPARSE] == []

    def test_both_routes_empty_still_has_both_keys(self) -> None:
        hybrid = _build([], [])

        outcome = hybrid.search_with_routes("q", top_k=5)

        assert outcome.results == []
        assert set(outcome.routes) == {ROUTE_DENSE, ROUTE_SPARSE}
        assert outcome.routes[ROUTE_DENSE] == []
        assert outcome.routes[ROUTE_SPARSE] == []

    def test_failing_route_reports_empty_not_missing(self) -> None:
        """一路抛错时走既有的降级逻辑，该路记为空而不是让整次检索失败。"""
        hybrid = _build([], [_r("b")], sparse_retriever=None, dense_retriever=FailingRetriever())

        outcome = hybrid.search_with_routes("q", top_k=5)

        assert outcome.routes[ROUTE_DENSE] == []
        assert [r.chunk_id for r in outcome.routes[ROUTE_SPARSE]] == ["b"]
        assert [r.chunk_id for r in outcome.results] == ["b"]

    def test_no_extra_retrieval_calls(self) -> None:
        """分路径指标不得靠多跑一次检索来实现。

        两路结果在融合前本就已经拿到，``routes`` 只是把它们也交出去。
        若某天有人改成「为了分路径再检索一遍」，这条会红。
        """

        class CountingRetriever(StubRetriever):
            def __init__(self, results: Sequence[RetrievalResult]) -> None:
                super().__init__(results)
                self.calls = 0

            def retrieve(self, *args: Any, **kwargs: Any) -> List[RetrievalResult]:
                self.calls += 1
                return super().retrieve(*args, **kwargs)

        dense = CountingRetriever([_r("a")])
        sparse = CountingRetriever([_r("b")])
        hybrid = _build([], [], dense_retriever=dense, sparse_retriever=sparse)

        hybrid.search_with_routes("q", top_k=5)

        assert dense.calls == 1
        assert sparse.calls == 1


class TestRoutesRespectMetadataFilters:
    """分路径结果必须与最终结果经过**同样**的元数据过滤。

    口径不一致的话，分路径指标就不能与融合后指标对照 —— 而「只留一路时两者
    应当相等」正是分路径口径唯一的自检手段。
    """

    def test_filter_applied_to_routes(self) -> None:
        hybrid = _build(
            [_r("a", {"doc_type": "pdf"}), _r("c", {"doc_type": "md"})],
            [_r("b", {"doc_type": "pdf"})],
        )

        outcome = hybrid.search_with_routes("q", top_k=5, filters={"doc_type": "pdf"})

        assert [r.chunk_id for r in outcome.routes[ROUTE_DENSE]] == ["a"]
        assert [r.chunk_id for r in outcome.routes[ROUTE_SPARSE]] == ["b"]
        assert {r.chunk_id for r in outcome.results} == {"a", "b"}

    def test_no_filter_means_no_filtering(self) -> None:
        hybrid = _build([_r("a", {"doc_type": "md"})], [])

        outcome = hybrid.search_with_routes("q", top_k=5)

        assert [r.chunk_id for r in outcome.routes[ROUTE_DENSE]] == ["a"]


class TestSingleRouteSelfCheck:
    """把其余路的权重配成 0 时，该路的结果应与融合后结果一致。

    这是分路径口径**唯一的自检手段** —— 没有它，分路径指标算错了也没人会知道。
    （规格里那条同名场景在评估层面的对应物；这里在检索层面先守一道。）
    """

    def test_dense_only_matches_fused_order(self) -> None:
        hybrid = _build(
            [_r("a"), _r("b"), _r("c")],
            [_r("z"), _r("y")],
            weights={ROUTE_DENSE: 1.0, ROUTE_SPARSE: 0.0},
        )

        outcome = hybrid.search_with_routes("q", top_k=3)

        dense_ids = [r.chunk_id for r in outcome.routes[ROUTE_DENSE]]
        fused_ids = [r.chunk_id for r in outcome.results]
        assert fused_ids[: len(dense_ids)] == dense_ids

    def test_sparse_only_matches_fused_order(self) -> None:
        hybrid = _build(
            [_r("a"), _r("b")],
            [_r("z"), _r("y"), _r("x")],
            weights={ROUTE_DENSE: 0.0, ROUTE_SPARSE: 1.0},
        )

        outcome = hybrid.search_with_routes("q", top_k=3)

        sparse_ids = [r.chunk_id for r in outcome.routes[ROUTE_SPARSE]]
        fused_ids = [r.chunk_id for r in outcome.results]
        assert fused_ids[: len(sparse_ids)] == sparse_ids


class TestRouteNamesAreCanonical:
    """路径名必须来自共享常量，不能各处手写字面量。

    ``Fusion.weight_for()`` 查不到路径名会**静默回落 1.0** —— 于是校准出来的
    权重被悄悄作废，而系统照常运行、不报错。三处（``fuse()`` 的键、
    ``fusion_weights`` 的键、``routes`` 的键）必须是同一个字符串。
    """

    def test_route_keys_match_fusion_weight_keys(self) -> None:
        weights = {ROUTE_DENSE: 1.0, ROUTE_SPARSE: 0.1}
        fusion = Fusion(k=60, weights=weights)
        hybrid = HybridSearch(
            settings=None,
            query_processor=_StubProcessor(),
            dense_retriever=StubRetriever([_r("a")]),
            sparse_retriever=StubRetriever([_r("b")]),
            fusion=fusion,
            reranker=PassthroughReranker(),
        )

        outcome = hybrid.search_with_routes("q", top_k=5)

        for name in outcome.routes:
            # 查得到 = 不会落到 DEFAULT_ROUTE_WEIGHT
            assert name in weights, f"路径名 {name!r} 在权重表里查不到，会静默回落 1.0"
            assert fusion.weight_for(name) == weights[name]

    def test_constants_have_the_expected_values(self) -> None:
        """常量的字面值就是配置文件里的键名 —— 改了它就等于改了配置契约。"""
        assert ROUTE_DENSE == "dense"
        assert ROUTE_SPARSE == "sparse"
