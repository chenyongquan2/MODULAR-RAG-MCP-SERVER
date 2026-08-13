"""Unit tests for 候选池化 (`ChunkPooler`)。

change: retriever-agnostic-golden-labels (T-2.1 / T-2.2)

测试范围:

1. 三路共同贡献、去重、``contributed_by`` 准确
2. 某一路空结果 / 抛异常 不中断池化
3. ``pool_top_n_rerank == 0`` 时完全不碰重排器(没装 optional extra 也能标注)
4. sparse 路必须经 ``QueryProcessor`` 提关键词(共享 tokenizer,不能自己切)
5. 用 ``query`` 而非 ``ground_truth`` 作检索输入
6. ``dense_jaccard`` 自检指标

**为什么第 1 条最重要**:``contributed_by`` 是本变更能否自证有效的唯一依据。
若产出里所有候选都只由 dense 贡献,说明池化没起作用、新方法退化成了第一代
(纯 dense top-5 回填),而这种失效**不会有任何报错**。

不触发任何真实检索 / 模型加载。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from src.core.settings import EvaluationSettings, LabelingSettings
from src.core.types import RetrievalResult
from src.observability.evaluation.chunk_pooler import (
    ROUTE_DENSE,
    ROUTE_RERANK,
    ROUTE_SPARSE,
    ChunkPooler,
    check_dense_overlap,
    dense_jaccard,
)

pytestmark = pytest.mark.unit


# ── 替身 ─────────────────────────────────────────────────────────────────


class _FakeSettings:
    """最小 Settings 替身,只带 evaluation.labeling(用真实 dataclass)。"""

    def __init__(self, **labeling_kwargs: Any) -> None:
        self.evaluation = EvaluationSettings()
        self.evaluation.labeling = LabelingSettings(**labeling_kwargs)


class _FakeDense:
    def __init__(self, ids: List[str], error: Optional[Exception] = None) -> None:
        self.ids = ids
        self.error = error
        self.calls: List[Dict[str, Any]] = []

    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
        trace: Optional[Any] = None,
    ) -> List[RetrievalResult]:
        self.calls.append({"query": query, "top_k": top_k})
        if self.error:
            raise self.error
        return _results(self.ids[: top_k or len(self.ids)])


class _FakeSparse:
    def __init__(self, ids: List[str], error: Optional[Exception] = None) -> None:
        self.ids = ids
        self.error = error
        self.calls: List[Dict[str, Any]] = []

    def retrieve(
        self,
        keywords: List[str],
        top_k: Optional[int] = None,
        trace: Optional[Any] = None,
    ) -> List[RetrievalResult]:
        self.calls.append({"keywords": keywords, "top_k": top_k})
        if self.error:
            raise self.error
        return _results(self.ids[: top_k or len(self.ids)])


class _FakeReranker:
    """把输入顺序反转,模拟「重排改变名次」。"""

    def __init__(self, error: Optional[Exception] = None) -> None:
        self.error = error
        self.calls: List[Dict[str, Any]] = []

    def rerank(
        self,
        query: str,
        candidates: List[RetrievalResult],
        trace: Optional[Any] = None,
    ) -> List[RetrievalResult]:
        self.calls.append({"query": query, "n": len(candidates)})
        if self.error:
            raise self.error
        return list(reversed(candidates))


class _FakeQueryProcessor:
    def __init__(self) -> None:
        self.calls: List[str] = []

    def process(self, query: str, filters: Optional[Dict[str, Any]] = None) -> Any:
        self.calls.append(query)

        class _Processed:
            keywords = ["kw1", "kw2"]

        return _Processed()


def _results(ids: List[str]) -> List[RetrievalResult]:
    return [
        RetrievalResult(
            chunk_id=cid, score=1.0 - i * 0.01, text=f"text of {cid}", metadata={}
        )
        for i, cid in enumerate(ids)
    ]


def _pooler(
    dense_ids: List[str],
    sparse_ids: List[str],
    *,
    rerank: bool = False,
    dense_error: Optional[Exception] = None,
    sparse_error: Optional[Exception] = None,
    rerank_error: Optional[Exception] = None,
    **labeling_kwargs: Any,
) -> tuple[ChunkPooler, _FakeDense, _FakeSparse, Optional[_FakeReranker], _FakeQueryProcessor]:
    kwargs: Dict[str, Any] = {
        "pool_top_n_dense": 20,
        "pool_top_n_sparse": 20,
        "pool_top_n_rerank": 20 if rerank else 0,
    }
    kwargs.update(labeling_kwargs)

    d = _FakeDense(dense_ids, dense_error)
    s = _FakeSparse(sparse_ids, sparse_error)
    r = _FakeReranker(rerank_error) if rerank else None
    qp = _FakeQueryProcessor()

    pooler = ChunkPooler(
        _FakeSettings(**kwargs),
        dense_retriever=d,
        sparse_retriever=s,
        reranker=r,
        query_processor=qp,
    )
    return pooler, d, s, r, qp


# ── 测试 ─────────────────────────────────────────────────────────────────


class TestMultiRouteContribution:
    """**本文件最重要的一组** —— 候选池必须由多路共同贡献。"""

    def test_union_of_two_routes(self) -> None:
        pooler, _, _, _, _ = _pooler(["a", "b"], ["b", "c"])

        result = pooler.pool("q")

        assert {c.chunk_id for c in result.candidates} == {"a", "b", "c"}

    def test_contributed_by_is_accurate(self) -> None:
        """每个候选记录它由哪几路贡献 —— 这是自证有效的唯一依据。"""
        pooler, _, _, _, _ = _pooler(["a", "b"], ["b", "c"])

        by_id = {c.chunk_id: sorted(c.contributed_by) for c in pooler.pool("q").candidates}

        assert by_id["a"] == [ROUTE_DENSE]              # 仅 dense
        assert by_id["c"] == [ROUTE_SPARSE]             # 仅 sparse
        assert by_id["b"] == sorted([ROUTE_DENSE, ROUTE_SPARSE])  # 两路都有

    def test_sparse_only_candidate_survives(self) -> None:
        """仅由 sparse 找到的 chunk 必须进池。

        第一代做法下它连进入标准答案的机会都没有 —— 这正是要修的偏差。
        """
        pooler, _, _, _, _ = _pooler(["a"], ["zzz"])

        ids = {c.chunk_id for c in pooler.pool("q").candidates}

        assert "zzz" in ids

    def test_route_counts_recorded(self) -> None:
        pooler, _, _, _, _ = _pooler(["a", "b"], ["c"])

        counts = pooler.pool("q").route_counts

        assert counts[ROUTE_DENSE] == 2
        assert counts[ROUTE_SPARSE] == 1

    def test_no_duplicates(self) -> None:
        pooler, _, _, _, _ = _pooler(["a", "b", "c"], ["a", "b", "c"])

        candidates = pooler.pool("q").candidates

        assert len(candidates) == 3
        assert len({c.chunk_id for c in candidates}) == 3


class TestRerankRoute:
    """重排路:它不产生新候选,价值在于**改变名次**从而把别的 chunk 带进前 N。"""

    def test_rerank_promotes_low_ranked_into_pool(self) -> None:
        """重排把末位提到首位后，该 chunk 应被标记为 rerank 贡献。"""
        pooler, _, _, _, _ = _pooler(["a", "b", "c"], [], rerank=True, pool_top_n_rerank=1)

        by_id = {c.chunk_id: c.contributed_by for c in pooler.pool("q").candidates}

        # 假重排器反转顺序 → 前 1 名是原本末位的 "c"
        assert ROUTE_RERANK in by_id["c"]
        assert ROUTE_RERANK not in by_id["a"]

    def test_rerank_disabled_never_touches_reranker(self) -> None:
        """``pool_top_n_rerank == 0`` 时不碰重排器。

        重排依赖是 optional extra `.[rerank]`,默认关闭保证核心安装即可标注。
        """
        pooler, _, _, r, _ = _pooler(["a"], ["b"], rerank=False)

        pooler.pool("q")

        assert r is None  # 压根没构造

    def test_rerank_input_is_union_of_both_routes(self) -> None:
        pooler, _, _, r, _ = _pooler(["a", "b"], ["b", "c"], rerank=True)

        pooler.pool("q")

        assert r is not None
        assert r.calls[0]["n"] == 3  # a, b, c 去重后

    def test_rerank_route_count_recorded(self) -> None:
        pooler, _, _, _, _ = _pooler(["a", "b"], [], rerank=True, pool_top_n_rerank=2)

        assert pooler.pool("q").route_counts[ROUTE_RERANK] == 2


class TestRouteFailuresDoNotBlock:
    """某一路失败或为空不中断池化 —— 一轮标注跑几十条 case,不能因一次抖动全废。"""

    def test_sparse_empty_does_not_break(self) -> None:
        pooler, _, _, _, _ = _pooler(["a", "b"], [])

        result = pooler.pool("q")

        assert {c.chunk_id for c in result.candidates} == {"a", "b"}
        assert result.route_counts[ROUTE_SPARSE] == 0

    def test_dense_error_recorded_and_pooling_continues(self) -> None:
        pooler, _, _, _, _ = _pooler(
            ["a"], ["b", "c"], dense_error=RuntimeError("vector store down")
        )

        result = pooler.pool("q")

        assert {c.chunk_id for c in result.candidates} == {"b", "c"}
        assert "vector store down" in result.errors[ROUTE_DENSE]
        assert result.route_counts[ROUTE_DENSE] == 0

    def test_sparse_error_recorded_and_pooling_continues(self) -> None:
        pooler, _, _, _, _ = _pooler(
            ["a"], ["b"], sparse_error=RuntimeError("bm25 index missing")
        )

        result = pooler.pool("q")

        assert {c.chunk_id for c in result.candidates} == {"a"}
        assert "bm25 index missing" in result.errors[ROUTE_SPARSE]

    def test_rerank_error_recorded_and_pooling_continues(self) -> None:
        pooler, _, _, _, _ = _pooler(
            ["a"], ["b"], rerank=True, rerank_error=RuntimeError("model load failed")
        )

        result = pooler.pool("q")

        assert {c.chunk_id for c in result.candidates} == {"a", "b"}
        assert "model load failed" in result.errors[ROUTE_RERANK]

    def test_all_routes_empty_yields_empty_pool_not_error(self) -> None:
        pooler, _, _, _, _ = _pooler([], [])

        result = pooler.pool("q")

        assert result.candidates == []


class TestRetrievalInput:
    """检索输入必须是 ``query``,且 sparse 必须经 QueryProcessor。"""

    def test_dense_receives_the_query_text(self) -> None:
        """用 query 而非 ground_truth —— 第一代用答案检索,那是「找像答案的段落」。"""
        pooler, d, _, _, _ = _pooler(["a"], ["b"])

        pooler.pool("如何配置保证金计算方式？")

        assert d.calls[0]["query"] == "如何配置保证金计算方式？"

    def test_sparse_keywords_come_from_query_processor(self) -> None:
        """必须经 QueryProcessor —— 它用共享的 tokenizer。

        自己切一份会让查询端与索引端口径漂移,而那种失败是**静默的**:
        不报错,只是召回恒为空。这是本项目已记录的陷阱。
        """
        pooler, _, s, _, qp = _pooler(["a"], ["b"])

        pooler.pool("some query")

        assert qp.calls == ["some query"]
        assert s.calls[0]["keywords"] == ["kw1", "kw2"]

    def test_top_n_passed_per_route(self) -> None:
        pooler, d, s, _, _ = _pooler(
            ["a"], ["b"], pool_top_n_dense=7, pool_top_n_sparse=3
        )

        pooler.pool("q")

        assert d.calls[0]["top_k"] == 7
        assert s.calls[0]["top_k"] == 3

    def test_empty_query_rejected(self) -> None:
        pooler, _, _, _, _ = _pooler(["a"], ["b"])

        with pytest.raises(ValueError, match="Query cannot be empty"):
            pooler.pool("   ")


class TestDeterministicOrdering:
    """输出顺序必须确定,让产出可复现、可 diff。"""

    def test_same_input_same_order(self) -> None:
        pooler_a, _, _, _, _ = _pooler(["b", "a"], ["c"])
        pooler_b, _, _, _, _ = _pooler(["b", "a"], ["c"])

        order_a = [c.chunk_id for c in pooler_a.pool("q").candidates]
        order_b = [c.chunk_id for c in pooler_b.pool("q").candidates]

        assert order_a == order_b


class TestDenseJaccard:
    """自检指标:标注结果与纯 dense top-K 的重合度。"""

    def test_identical_sets_return_one(self) -> None:
        """完全重合 = 新方法没起作用,应该被告警抓到。"""
        assert dense_jaccard(["a", "b", "c"], ["a", "b", "c"]) == 1.0

    def test_disjoint_sets_return_zero(self) -> None:
        assert dense_jaccard(["a", "b"], ["c", "d"]) == 0.0

    def test_partial_overlap(self) -> None:
        # 交集 {b}，并集 {a,b,c} → 1/3
        assert dense_jaccard(["a", "b"], ["b", "c"]) == pytest.approx(1 / 3)

    def test_both_empty_returns_zero_not_one(self) -> None:
        """空集与空集「完全重合」是无意义的巧合,报 1.0 会触发误导性告警。"""
        assert dense_jaccard([], []) == 0.0

    def test_one_empty_returns_zero(self) -> None:
        assert dense_jaccard([], ["a"]) == 0.0
        assert dense_jaccard(["a"], []) == 0.0

    def test_duplicates_do_not_skew(self) -> None:
        """按集合算,重复 id 不影响结果。"""
        assert dense_jaccard(["a", "a", "b"], ["a", "b"]) == 1.0


class TestDenseOverlapWarning:
    """重合度告警:超阈值时给信号,但不阻断产出。"""

    def test_no_warning_below_threshold(self) -> None:
        assert check_dense_overlap(["a", "b"], ["c", "d"], 0.90) is None

    def test_warning_above_threshold(self) -> None:
        warning = check_dense_overlap(["a", "b"], ["a", "b"], 0.90)

        assert warning is not None
        assert "Jaccard=1.000" in warning

    def test_threshold_is_exclusive(self) -> None:
        """恰好等于阈值不告警(只有**超过**才告警)。"""
        # 交集 {a,b}，并集 {a,b,c,d} → 0.5
        assert check_dense_overlap(["a", "b"], ["a", "b", "c", "d"], 0.5) is None
        assert check_dense_overlap(["a", "b"], ["a", "b", "c", "d"], 0.49) is not None

    def test_warning_lists_possible_causes(self) -> None:
        """告警要给排查方向 —— 高重合有好几种可能原因,程序分不清,人才行。"""
        warning = check_dense_overlap(["a"], ["a"], 0.5)

        assert warning is not None
        assert "two pool routes" in warning        # 池化退化成单路？
        assert "rejecting anything" in warning     # 判定过于宽松？
        assert "genuinely sufficient" in warning   # 或者 dense 本来就够用？

    def test_both_empty_does_not_warn(self) -> None:
        """空集与空集不该触发误导性告警。"""
        assert check_dense_overlap([], [], 0.90) is None


class TestConstruction:
    def test_none_settings_rejected(self) -> None:
        with pytest.raises(ValueError, match="Settings cannot be None"):
            ChunkPooler(None)  # type: ignore[arg-type]
