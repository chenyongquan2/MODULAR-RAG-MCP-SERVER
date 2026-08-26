"""守卫：重排能看到多少候选，由融合的截断决定，不是由 `rerank.top_m` 决定。

change: 无（根因明确的注释 + 回归保护，走 CLAUDE.md 的例外）

## 这组用例记录的是什么

`HybridSearch` 把融合结果截到 ``top_k * 2`` 之后才交给重排。所以**重排能看到的
候选上限是 ``top_k_final * 2``**，而不是 ``rerank.top_m``。

实测（``top_k_final = 10``，生产配置）：重排每次收到 **12~19 条**，上限 20；
而 ``rerank.top_m`` 配的是 **50** —— 它**永远不会 binding**。

### 为什么要把这件事钉住

三个具体后果：

1. **改 `top_m` 想让重排看更多候选是无效的。** 那是个看起来可调、实际不起作用
   的旋钮 —— ``rerank.top_m`` 的第三种死法（前两种：从未截断过候选；被修好后
   仍因上游更紧的截断而不可达）。
2. **归档的延迟数标错了口径。** `activate-cross-encoder-rerank` 的验收记录写
   「40（生产实际：`top_k_dense` 20 + `top_k_sparse` 20）→ 5.21 s」——
   那 40 是**融合前**两路之和，重排拿到的是**融合后截断**的结果。
   真实候选量约 15 条，对应约 2 秒，**此前的表述高估了一倍**。
3. 这类「配置被读了、也在用，但值因为上游有更紧的约束而永远不 binding」的
   **语义死配置**，`tests/unit/test_no_dead_settings.py` 那个守卫**抓不到** ——
   它守的是有没有读取点（语法层）。两个守卫覆盖不同的失效面。

不联网、不调模型 —— 检索器与重排器全部用替身。
"""

from __future__ import annotations

from typing import Any, List, Sequence

import pytest

from src.core.query_engine.fusion import Fusion
from src.core.query_engine.hybrid_search import HybridSearch
from src.core.settings import load_settings
from src.core.types import RetrievalResult

pytestmark = pytest.mark.unit


def _r(chunk_id: str) -> RetrievalResult:
    return RetrievalResult(chunk_id=chunk_id, score=0.5, text=f"t-{chunk_id}", metadata={})


class StubRetriever:
    def __init__(self, prefix: str, count: int) -> None:
        self._results = [_r(f"{prefix}{i}") for i in range(count)]

    def retrieve(self, *args: Any, **kwargs: Any) -> List[RetrievalResult]:
        return list(self._results)


class SpyReranker:
    """记录每次收到多少候选。"""

    def __init__(self) -> None:
        self.received: List[int] = []

    def rerank(self, query: str, results: Sequence[RetrievalResult], trace: Any = None):
        self.received.append(len(results))
        return list(results)


class _StubProcessor:
    def process(self, query: str, filters: Any = None) -> Any:
        from src.core.types import ProcessedQuery

        return ProcessedQuery(original_query=query, keywords=query.split(), filters={})


def _search(top_k: int, dense_n: int, sparse_n: int) -> SpyReranker:
    spy = SpyReranker()
    hybrid = HybridSearch(
        settings=None,
        query_processor=_StubProcessor(),
        dense_retriever=StubRetriever("d", dense_n),
        sparse_retriever=StubRetriever("s", sparse_n),
        fusion=Fusion(k=60, weights={"dense": 1.0, "sparse": 0.75}),
        reranker=spy,
    )
    hybrid.search("some query", top_k=top_k)
    return spy


class TestRerankSeesAtMostTwiceTopK:
    def test_capped_at_double_top_k(self) -> None:
        """两路各给 20 条互不重叠 = 40 个候选，重排只应看到 20。"""
        spy = _search(top_k=10, dense_n=20, sparse_n=20)

        assert spy.received == [20]

    @pytest.mark.parametrize("top_k", [1, 5, 10, 25])
    def test_cap_scales_with_top_k(self, top_k: int) -> None:
        spy = _search(top_k=top_k, dense_n=50, sparse_n=50)

        assert spy.received == [top_k * 2]

    def test_fewer_candidates_pass_through_unchanged(self) -> None:
        """候选本来就少于上限时不受影响。"""
        spy = _search(top_k=10, dense_n=3, sparse_n=2)

        assert spy.received == [5]

    def test_overlapping_routes_dedupe_before_the_cap(self) -> None:
        """两路命中同一批 chunk 时，去重发生在截断之前。"""
        spy = SpyReranker()
        shared = [_r(f"c{i}") for i in range(15)]

        class Same:
            def retrieve(self, *a: Any, **k: Any) -> List[RetrievalResult]:
                return list(shared)

        hybrid = HybridSearch(
            settings=None,
            query_processor=_StubProcessor(),
            dense_retriever=Same(),
            sparse_retriever=Same(),
            fusion=Fusion(k=60),
            reranker=spy,
        )
        hybrid.search("q", top_k=10)

        assert spy.received == [15]


class TestTopMIsNotTheBindingConstraint:
    """生产配置下 ``rerank.top_m`` 永远不 binding —— 这条会随配置变化而红。

    它红了不代表出了 bug，代表**上下游的约束关系变了**，需要重新想清楚
    「重排到底该看多少候选」，并同步更新延迟预期。
    """

    def test_production_config_makes_top_m_unreachable(self) -> None:
        settings = load_settings()
        fusion_cap = settings.retrieval.top_k_final * 2

        assert fusion_cap < settings.rerank.top_m, (
            f"融合截断 {fusion_cap} 已不小于 rerank.top_m {settings.rerank.top_m} —— "
            "两者的约束关系变了，请重新确认重排的候选预算与延迟预期"
        )

    def test_the_real_budget_is_documented(self) -> None:
        """把真实预算写死成断言，免得延迟估算再次基于错误的候选量。

        归档记录里那句「40 条候选 → 5.21 s」用的是**融合前**两路之和；
        重排实际只看到 ``top_k_final * 2``。
        """
        settings = load_settings()

        assert settings.retrieval.top_k_final * 2 == 20, (
            "重排候选预算变了 —— CLAUDE.md 的延迟表述需同步更新"
        )
