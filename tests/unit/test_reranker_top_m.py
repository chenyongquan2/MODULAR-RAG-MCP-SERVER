"""Unit tests for Core 层 `Reranker` 的 `top_m` 截断。

change: activate-cross-encoder-rerank (T-3.1)

背景 —— 这是一条**死配置的复活**:`rerank.top_m` 在本变更之前全仓只有三处
引用(settings dataclass 定义、dashboard 展示、一个测试传值),``Reranker.rerank``
把**全部**候选原样交给后端,从不按 ``top_m`` 截断。今天撞不到上限(融合后
最多 40 条 < 50),但它是 ``llm`` 后端唯一能约束调用次数与 token 消耗的旋钮
—— 一个不生效的上限等于没有上限。

关键语义:``top_m`` 是「**重排**多少条」的预算,不是「**返回**多少条」的上限。
超出部分按原名次追加,不参与重排但也不丢弃。返回条数由
``retrieval.top_k_final`` 在 HybridSearch 里决定。丢结果会让 ``top_m`` 变成
一个隐蔽的召回削减。

不触发任何模型加载 / LLM 调用。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from src.core.query_engine.reranker import Reranker
from src.core.settings import RerankSettings
from src.core.types import RetrievalResult

pytestmark = pytest.mark.unit


class _FakeSettings:
    """最小 Settings 替身,只带 rerank 段(用真实 dataclass 以免与结构漂移)。"""

    def __init__(self, **rerank_kwargs: Any) -> None:
        self.rerank = RerankSettings(**rerank_kwargs)


class _ReversingBackend:
    """把候选顺序完全反转的假后端。

    选「反转」而不是「按分数排」是刻意的:反转让「哪些条参与了重排」在结果
    里一目了然 —— 参与的那批会倒序出现,没参与的余量保持原序。
    """

    def __init__(self) -> None:
        self.received: List[List[Dict[str, Any]]] = []

    def supports_batch_scoring(self) -> bool:
        """本组只测 top_m 截断,走整体调用路径(超时另有专门的测试文件)。"""
        return False

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        self.received.append(candidates)
        return list(reversed(candidates))


class _RecordingTrace:
    """记录 finish_stage 载荷的 trace 替身。"""

    def __init__(self) -> None:
        self.stages: Dict[str, Dict[str, Any]] = {}

    def start_stage(self, name: str) -> None:
        pass

    def finish_stage(self, name: str, payload: Dict[str, Any]) -> None:
        self.stages[name] = payload


def _candidates(n: int) -> List[RetrievalResult]:
    """构造 n 条候选,chunk_id 为 c0..c{n-1},分数递减(模拟融合后的名次)。"""
    return [
        RetrievalResult(
            chunk_id=f"c{i}",
            score=1.0 - i * 0.01,
            text=f"passage {i}",
            metadata={},
        )
        for i in range(n)
    ]


def _ids(results: List[RetrievalResult]) -> List[str]:
    return [r.chunk_id for r in results]


class TestTruncationBoundaries:
    """三种边界:超过上限 / 未超过 / 恰好等于。"""

    def test_more_candidates_than_top_m(self) -> None:
        """只有前 top_m 条送入后端,余量按原名次追加在后。"""
        backend = _ReversingBackend()
        reranker = Reranker(_FakeSettings(top_m=3), reranker_backend=backend)

        results = reranker.rerank("q", _candidates(10))

        # 后端只收到前 3 条
        assert len(backend.received) == 1
        assert [d["id"] for d in backend.received[0]] == ["c0", "c1", "c2"]

        # 前 3 条被反转,c3..c9 保持原序追加
        assert _ids(results) == [
            "c2", "c1", "c0",
            "c3", "c4", "c5", "c6", "c7", "c8", "c9",
        ]

    def test_fewer_candidates_than_top_m(self) -> None:
        """未超过上限时全部送入,无截断行为、无余量。"""
        backend = _ReversingBackend()
        reranker = Reranker(_FakeSettings(top_m=50), reranker_backend=backend)

        results = reranker.rerank("q", _candidates(8))

        assert [d["id"] for d in backend.received[0]] == [f"c{i}" for i in range(8)]
        assert _ids(results) == [f"c{i}" for i in reversed(range(8))]

    def test_exactly_top_m_candidates(self) -> None:
        """恰好等于上限:全部参与重排,余量为空(off-by-one 守卫)。"""
        backend = _ReversingBackend()
        reranker = Reranker(_FakeSettings(top_m=5), reranker_backend=backend)

        results = reranker.rerank("q", _candidates(5))

        assert len(backend.received[0]) == 5
        assert _ids(results) == ["c4", "c3", "c2", "c1", "c0"]

    def test_top_m_of_one(self) -> None:
        """极端值 top_m=1:只重排第一条,其余全部顺位带过。"""
        backend = _ReversingBackend()
        reranker = Reranker(_FakeSettings(top_m=1), reranker_backend=backend)

        results = reranker.rerank("q", _candidates(4))

        assert [d["id"] for d in backend.received[0]] == ["c0"]
        assert _ids(results) == ["c0", "c1", "c2", "c3"]


class TestNoResultLoss:
    """本组守的是最重要的性质:截断不得丢结果。"""

    @pytest.mark.parametrize("total,top_m", [(10, 3), (40, 10), (5, 50), (7, 7), (2, 1)])
    def test_total_count_preserved(self, total: int, top_m: int) -> None:
        """任何 (总数, top_m) 组合下,输出条数都等于输入条数。

        ``top_m`` 是「重排多少条」的预算,不是「返回多少条」的上限 —— 后者由
        ``retrieval.top_k_final`` 在 HybridSearch 里决定。这里丢结果会让
        ``top_m`` 变成一个隐蔽的召回削减,而且不会有任何报错。
        """
        backend = _ReversingBackend()
        reranker = Reranker(_FakeSettings(top_m=top_m), reranker_backend=backend)

        results = reranker.rerank("q", _candidates(total))

        assert len(results) == total

    @pytest.mark.parametrize("total,top_m", [(10, 3), (40, 10), (7, 7)])
    def test_no_duplicates_and_no_missing_ids(self, total: int, top_m: int) -> None:
        """id 集合完全一致 —— 既不重复也不缺失。"""
        backend = _ReversingBackend()
        reranker = Reranker(_FakeSettings(top_m=top_m), reranker_backend=backend)

        results = reranker.rerank("q", _candidates(total))

        assert sorted(_ids(results)) == sorted(f"c{i}" for i in range(total))
        assert len(set(_ids(results))) == total


class TestCarriedOverOrder:
    """余量必须保持**原名次**,不能被打乱。"""

    def test_carried_over_keeps_original_relative_order(self) -> None:
        backend = _ReversingBackend()
        reranker = Reranker(_FakeSettings(top_m=2), reranker_backend=backend)

        results = reranker.rerank("q", _candidates(6))

        # 余量部分(结果的第 3 位起)必须是 c2, c3, c4, c5 的原序
        assert _ids(results)[2:] == ["c2", "c3", "c4", "c5"]

    def test_carried_over_marked_as_not_reranked(self) -> None:
        """余量标 ``reranked=False``,让下游能区分「重排过的」与「顺位带过的」。"""
        backend = _ReversingBackend()
        reranker = Reranker(_FakeSettings(top_m=2), reranker_backend=backend)

        results = reranker.rerank("q", _candidates(5))

        assert all(r.metadata["reranked"] is True for r in results[:2])
        assert all(r.metadata["reranked"] is False for r in results[2:])


class TestTracePayload:
    """trace 要能看出截断确实发生了(否则无从判断 top_m 是否生效)。"""

    def test_trace_records_split(self) -> None:
        backend = _ReversingBackend()
        reranker = Reranker(_FakeSettings(top_m=3), reranker_backend=backend)
        trace = _RecordingTrace()

        reranker.rerank("q", _candidates(10), trace=trace)

        payload = trace.stages["rerank"]
        assert payload["top_m"] == 3
        assert payload["input_count"] == 10
        assert payload["reranked_count"] == 3
        assert payload["carried_over_count"] == 7
        assert payload["output_count"] == 10
        assert payload["fallback"] is False

    def test_trace_shows_zero_carry_over_when_under_limit(self) -> None:
        backend = _ReversingBackend()
        reranker = Reranker(_FakeSettings(top_m=50), reranker_backend=backend)
        trace = _RecordingTrace()

        reranker.rerank("q", _candidates(6), trace=trace)

        payload = trace.stages["rerank"]
        assert payload["reranked_count"] == 6
        assert payload["carried_over_count"] == 0


class TestFallbackStillReturnsEverything:
    """后端异常时的降级不能被截断改坏 —— 必须返回全部候选。"""

    def test_backend_failure_returns_all_candidates(self) -> None:
        class _BoomBackend:
            def rerank(self, *args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
                raise RuntimeError("backend exploded")

        reranker = Reranker(_FakeSettings(top_m=3), reranker_backend=_BoomBackend())

        results = reranker.rerank("q", _candidates(10))

        # 全部 10 条原序返回,含被截断掉的余量
        assert _ids(results) == [f"c{i}" for i in range(10)]
        assert all(r.metadata["rerank_fallback"] is True for r in results)

    def test_backend_failure_trace_marks_fallback(self) -> None:
        class _BoomBackend:
            def rerank(self, *args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
                raise RuntimeError("backend exploded")

        reranker = Reranker(_FakeSettings(top_m=3), reranker_backend=_BoomBackend())
        trace = _RecordingTrace()

        reranker.rerank("q", _candidates(10), trace=trace)

        assert trace.stages["rerank"]["fallback"] is True


class TestEarlyReturns:
    """空候选与空 query 的短路路径不受截断影响。"""

    def test_empty_candidates(self) -> None:
        backend = _ReversingBackend()
        reranker = Reranker(_FakeSettings(top_m=3), reranker_backend=backend)

        assert reranker.rerank("q", []) == []
        assert backend.received == []

    def test_blank_query_returns_candidates_untouched(self) -> None:
        backend = _ReversingBackend()
        reranker = Reranker(_FakeSettings(top_m=3), reranker_backend=backend)
        candidates = _candidates(5)

        results = reranker.rerank("   ", candidates)

        assert _ids(results) == [f"c{i}" for i in range(5)]
        assert backend.received == []
