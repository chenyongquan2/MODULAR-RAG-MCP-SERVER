"""Unit tests for Core 层 `Reranker` 的超时兜底。

change: activate-cross-encoder-rerank (T-3.2)

背景 —— 超时机制此前**根本不存在**(不是「死代码」)。
`docs/learning/rerank-and-cross-encoder.md` §6.4 说 `CrossEncoderReranker`
存了 `self.timeout`、`_score_pairs()` 里没有超时检查、`CoreReranker.config.timeout`
从未被使用 —— 对着代码 grep,`src/libs/reranker/` 与
`src/core/query_engine/reranker.py` 里一个 `timeout` 字样都没有,文中提到的
那些成员全不存在。

为什么只能靠分批 + 批间计时:cross-encoder 是**同步 CPU 推理**,Python 里
没有能中断一段正在跑的同步计算的可用手段 —— `signal.alarm` 在 Windows 不
支持且非主线程无效;工作线程 + `join(timeout)` 超时后线程仍在跑,无法中断
torch 推理,只会泄漏线程并继续吃 CPU。

超时语义:已打分部分按分数降序,未打分部分保持原名次追加。
**不抛异常、不丢候选** —— 超时是慢,不是错。

不触发任何模型加载 / LLM 调用(用可控的假后端 sleep 固定时长)。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import pytest

from src.core.query_engine.reranker import Reranker
from src.core.settings import RerankSettings
from src.core.types import RetrievalResult

pytestmark = pytest.mark.unit


class _FakeSettings:
    def __init__(self, **rerank_kwargs: Any) -> None:
        self.rerank = RerankSettings(**rerank_kwargs)


class _SlowBatchBackend:
    """支持分批打分的假后端,每批固定 sleep。

    分数设计成「原始下标越大分越高」—— 这样正常完成时结果应完全倒序,
    一眼就能看出哪些条参与了打分。
    """

    def __init__(self, sleep_per_batch: float, total: int) -> None:
        self.sleep_per_batch = sleep_per_batch
        self.total = total
        self.batches_seen: List[int] = []
        self._cursor = 0

    def supports_batch_scoring(self) -> bool:
        return True

    def score_batch(self, query: str, candidates: List[Dict[str, Any]]) -> List[float]:
        self.batches_seen.append(len(candidates))
        time.sleep(self.sleep_per_batch)
        scores = [float(self._cursor + i) for i in range(len(candidates))]
        self._cursor += len(candidates)
        return scores

    def get_backend_name(self) -> str:
        return "fake_batch"


class _FastBatchBackend(_SlowBatchBackend):
    """不 sleep 的版本,用于验证「限时内完成」的路径。"""

    def __init__(self, total: int) -> None:
        super().__init__(sleep_per_batch=0.0, total=total)


class _LegacyBackend:
    """不支持分批打分的后端 —— 必须退回整体调用,不能报错。"""

    def __init__(self) -> None:
        self.called = False

    def supports_batch_scoring(self) -> bool:
        return False

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        self.called = True
        return list(reversed(candidates))

    def get_backend_name(self) -> str:
        return "legacy"


class _RecordingTrace:
    def __init__(self) -> None:
        self.stages: Dict[str, Dict[str, Any]] = {}

    def start_stage(self, name: str) -> None:
        pass

    def finish_stage(self, name: str, payload: Dict[str, Any]) -> None:
        self.stages[name] = payload


def _candidates(n: int) -> List[RetrievalResult]:
    return [
        RetrievalResult(
            chunk_id=f"c{i}", score=1.0 - i * 0.01, text=f"passage {i}", metadata={}
        )
        for i in range(n)
    ]


def _ids(results: List[RetrievalResult]) -> List[str]:
    return [r.chunk_id for r in results]


class TestCompletesWithinTimeout:
    """限时内完成:全部候选参与排序,无超时标记。"""

    def test_all_candidates_scored(self) -> None:
        backend = _FastBatchBackend(total=10)
        reranker = Reranker(
            _FakeSettings(top_m=50, batch_size=4, timeout_sec=30.0),
            reranker_backend=backend,
        )

        results = reranker.rerank("q", _candidates(10))

        # 分数随下标递增 → 结果完全倒序
        assert _ids(results) == [f"c{i}" for i in reversed(range(10))]

    def test_no_timeout_flag_in_trace(self) -> None:
        backend = _FastBatchBackend(total=6)
        reranker = Reranker(
            _FakeSettings(top_m=50, batch_size=2, timeout_sec=30.0),
            reranker_backend=backend,
        )
        trace = _RecordingTrace()

        reranker.rerank("q", _candidates(6), trace=trace)

        payload = trace.stages["rerank"]
        assert payload["timed_out"] is False
        assert payload["scored_count"] == 6

    def test_batches_are_sliced_by_batch_size(self) -> None:
        """按 batch_size 切批,最后一批可以不满。"""
        backend = _FastBatchBackend(total=10)
        reranker = Reranker(
            _FakeSettings(top_m=50, batch_size=4, timeout_sec=30.0),
            reranker_backend=backend,
        )

        reranker.rerank("q", _candidates(10))

        assert backend.batches_seen == [4, 4, 2]


class TestTimeoutMidway:
    """中途超时:部分结果保留,余下保持原名次。"""

    def test_partial_scores_preserved_and_rest_keeps_order(self) -> None:
        # 每批 sleep 0.1s、batch_size=2、超时 0.15s
        # → 第 1 批后 0.1s < 0.15s 继续;第 2 批后 0.2s >= 0.15s 且还有剩余 → 停
        backend = _SlowBatchBackend(sleep_per_batch=0.1, total=10)
        reranker = Reranker(
            _FakeSettings(top_m=50, batch_size=2, timeout_sec=0.15),
            reranker_backend=backend,
        )

        results = reranker.rerank("q", _candidates(10))

        # 打分了 c0..c3(分数 0,1,2,3)→ 降序为 c3,c2,c1,c0
        # 未打分的 c4..c9 保持原名次追加
        assert _ids(results) == [
            "c3", "c2", "c1", "c0",
            "c4", "c5", "c6", "c7", "c8", "c9",
        ]

    def test_no_candidate_lost_on_timeout(self) -> None:
        """超时不得丢候选 —— 本组最重要的一条。"""
        backend = _SlowBatchBackend(sleep_per_batch=0.1, total=12)
        reranker = Reranker(
            _FakeSettings(top_m=50, batch_size=2, timeout_sec=0.05),
            reranker_backend=backend,
        )

        results = reranker.rerank("q", _candidates(12))

        assert len(results) == 12
        assert sorted(_ids(results)) == sorted(f"c{i}" for i in range(12))

    def test_no_exception_raised_on_timeout(self) -> None:
        """超时是慢,不是错 —— 查询必须成功返回。"""
        backend = _SlowBatchBackend(sleep_per_batch=0.1, total=8)
        reranker = Reranker(
            _FakeSettings(top_m=50, batch_size=2, timeout_sec=0.05),
            reranker_backend=backend,
        )

        results = reranker.rerank("q", _candidates(8))  # 不应抛异常
        assert results

    def test_trace_marks_timeout_and_scored_count(self) -> None:
        backend = _SlowBatchBackend(sleep_per_batch=0.1, total=10)
        reranker = Reranker(
            _FakeSettings(top_m=50, batch_size=2, timeout_sec=0.05),
            reranker_backend=backend,
        )
        trace = _RecordingTrace()

        reranker.rerank("q", _candidates(10), trace=trace)

        payload = trace.stages["rerank"]
        assert payload["timed_out"] is True
        assert payload["scored_count"] == 2
        assert payload["output_count"] == 10
        assert payload["fallback"] is False  # 超时不是降级,两者必须区分
        assert payload["timeout_sec"] == 0.05

    def test_stops_early_and_does_not_score_remaining_batches(self) -> None:
        """超时后不得继续跑后续批次 —— 否则超时形同虚设。"""
        backend = _SlowBatchBackend(sleep_per_batch=0.1, total=20)
        reranker = Reranker(
            _FakeSettings(top_m=50, batch_size=2, timeout_sec=0.05),
            reranker_backend=backend,
        )

        reranker.rerank("q", _candidates(20))

        # 只应跑第一批
        assert backend.batches_seen == [2]


class TestTimeoutBoundary:
    """超时判定的边界:全部打完就不算超时,哪怕总耗时超限。"""

    def test_last_batch_overrun_is_not_a_timeout(self) -> None:
        """最后一批跑完才超限 → 不标超时。

        此时没有任何候选被牺牲,标超时会误报。这也是为什么判定条件里带了
        「还有剩余批次」这一项。
        """
        backend = _SlowBatchBackend(sleep_per_batch=0.1, total=4)
        reranker = Reranker(
            _FakeSettings(top_m=50, batch_size=2, timeout_sec=0.15),
            reranker_backend=backend,
        )
        trace = _RecordingTrace()

        results = reranker.rerank("q", _candidates(4), trace=trace)

        # 两批共 0.2s > 0.15s,但第 2 批之后已无剩余 → 正常完成
        assert backend.batches_seen == [2, 2]
        assert trace.stages["rerank"]["timed_out"] is False
        assert trace.stages["rerank"]["scored_count"] == 4
        assert _ids(results) == ["c3", "c2", "c1", "c0"]

    def test_single_batch_never_times_out(self) -> None:
        """候选数 <= batch_size 时只有一批,超时粒度盖不住它。

        这是同步推理不可中断的固有代价:最坏情况会超出 timeout_sec 一个批次
        的时间。把它写成测试是为了让这个已知局限**显式**,而不是让后来人以为
        超时是精确的。
        """
        backend = _SlowBatchBackend(sleep_per_batch=0.2, total=3)
        reranker = Reranker(
            _FakeSettings(top_m=50, batch_size=8, timeout_sec=0.01),
            reranker_backend=backend,
        )
        trace = _RecordingTrace()

        results = reranker.rerank("q", _candidates(3), trace=trace)

        assert backend.batches_seen == [3]
        assert trace.stages["rerank"]["timed_out"] is False
        assert len(results) == 3


class TestDeterministicOrdering:
    """同分时的次序必须确定,不依赖排序实现的偶然行为。"""

    def test_ties_broken_by_original_rank(self) -> None:
        class _ConstantBackend:
            def supports_batch_scoring(self) -> bool:
                return True

            def score_batch(
                self, query: str, candidates: List[Dict[str, Any]]
            ) -> List[float]:
                return [1.0] * len(candidates)

            def get_backend_name(self) -> str:
                return "constant"

        reranker = Reranker(
            _FakeSettings(top_m=50, batch_size=3, timeout_sec=30.0),
            reranker_backend=_ConstantBackend(),
        )

        results = reranker.rerank("q", _candidates(7))

        # 全部同分 → 完全保持原名次
        assert _ids(results) == [f"c{i}" for i in range(7)]


class TestScoreWriteBack:
    """重排分数必须落到 ``RetrievalResult.metadata``。

    这里曾有一个真实缺陷:``_rerank_with_timeout`` 把 ``rerank_score`` 写在
    中间 dict 上,而转回 ``RetrievalResult`` 时只取 ``_retrieval_result``,
    那些分数**被直接丢掉**。dict 用完即弃,下游(dashboard / trace)什么都
    看不到 —— 又一处「写了但没人用」的死代码。本组守住它不再复发。
    """

    def test_rerank_score_lands_in_metadata(self) -> None:
        backend = _FastBatchBackend(total=4)
        reranker = Reranker(
            _FakeSettings(top_m=50, batch_size=2, timeout_sec=30.0),
            reranker_backend=backend,
        )

        results = reranker.rerank("q", _candidates(4))

        assert _ids(results) == ["c3", "c2", "c1", "c0"]
        # 假后端的分数就是原始下标 → c3 得 3.0、c0 得 0.0
        assert [r.metadata["rerank_score"] for r in results] == [3.0, 2.0, 1.0, 0.0]

    def test_backend_name_lands_in_metadata(self) -> None:
        """``reranked_by`` 是判别静默降级的信号之一,必须可见。"""
        backend = _FastBatchBackend(total=3)
        reranker = Reranker(
            _FakeSettings(top_m=50, batch_size=2, timeout_sec=30.0),
            reranker_backend=backend,
        )

        results = reranker.rerank("q", _candidates(3))

        assert all(r.metadata["reranked_by"] == "fake_batch" for r in results)

    def test_unscored_candidates_carry_no_rerank_score(self) -> None:
        """超时未打分的候选不该带 ``rerank_score`` —— 否则无从区分。"""
        backend = _SlowBatchBackend(sleep_per_batch=0.1, total=6)
        reranker = Reranker(
            _FakeSettings(top_m=50, batch_size=2, timeout_sec=0.05),
            reranker_backend=backend,
        )

        results = reranker.rerank("q", _candidates(6))

        scored = [r for r in results if "rerank_score" in r.metadata]
        unscored = [r for r in results if "rerank_score" not in r.metadata]
        assert len(scored) == 2
        assert len(unscored) == 4
        assert _ids(unscored) == ["c2", "c3", "c4", "c5"]


class TestBatchSupportProbing:
    """探测「后端是否支持分批」必须是严格判断,不能被鸭子类型坑到。

    后端是鸭子类型的:``Reranker`` 可以注入任意对象,测试里常用 ``Mock()``。
    对 ``Mock()`` 而言任何方法调用都返回一个**真值** Mock —— 用普通真值判断
    会把它误判成支持分批,接着 zip 一个 Mock 分数列表并炸成降级。这个回归
    在实施 T-3.2 时真的发生过(``test_reranker_fallback.py`` 的 6 个用例全红)。
    """

    def test_bare_mock_backend_falls_back_to_whole_list_call(self) -> None:
        from unittest.mock import Mock

        backend = Mock()
        backend.rerank.return_value = [
            {"id": "c1", "text": "passage 1", "score": 0.99, "_retrieval_result": None},
        ]

        reranker = Reranker(
            _FakeSettings(top_m=50, batch_size=2, timeout_sec=30.0),
            reranker_backend=backend,
        )
        reranker.rerank("q", _candidates(3))

        # 必须走整体调用,而不是分批
        backend.rerank.assert_called_once()
        backend.score_batch.assert_not_called()

    def test_backend_without_the_method_at_all(self) -> None:
        """连 ``supports_batch_scoring`` 都没有的后端也要能用(老的第三方实现)。"""

        class _AncientBackend:
            def rerank(
                self,
                query: str,
                candidates: List[Dict[str, Any]],
                trace: Optional[Any] = None,
                **kwargs: Any,
            ) -> List[Dict[str, Any]]:
                return list(reversed(candidates))

        reranker = Reranker(
            _FakeSettings(top_m=50, batch_size=2, timeout_sec=30.0),
            reranker_backend=_AncientBackend(),
        )

        results = reranker.rerank("q", _candidates(4))

        assert _ids(results) == [f"c{i}" for i in reversed(range(4))]

    def test_truthy_non_true_return_does_not_enable_batching(self) -> None:
        """返回 ``"yes"`` / ``1`` 这类真值但非 True 的,不算声明支持。"""

        class _SloppyBackend:
            def supports_batch_scoring(self) -> Any:
                return "yes"  # 真值,但不是 True

            def rerank(
                self,
                query: str,
                candidates: List[Dict[str, Any]],
                trace: Optional[Any] = None,
                **kwargs: Any,
            ) -> List[Dict[str, Any]]:
                return list(candidates)

            def score_batch(
                self, query: str, candidates: List[Dict[str, Any]]
            ) -> List[float]:
                raise AssertionError("不该走到分批路径")

        reranker = Reranker(
            _FakeSettings(top_m=50, batch_size=2, timeout_sec=30.0),
            reranker_backend=_SloppyBackend(),
        )

        results = reranker.rerank("q", _candidates(3))  # 不该抛异常
        assert len(results) == 3


class TestBackendsWithoutBatchSupport:
    """不支持分批的后端必须退回整体调用,不能报错、不能被超时逻辑波及。"""

    def test_legacy_backend_still_works(self) -> None:
        backend = _LegacyBackend()
        reranker = Reranker(
            _FakeSettings(top_m=50, batch_size=2, timeout_sec=0.001),
            reranker_backend=backend,
        )

        results = reranker.rerank("q", _candidates(5))

        assert backend.called is True
        assert _ids(results) == [f"c{i}" for i in reversed(range(5))]

    def test_legacy_backend_never_marked_timed_out(self) -> None:
        """整体调用路径没有超时能力,不该谎报 timed_out。"""
        backend = _LegacyBackend()
        reranker = Reranker(
            _FakeSettings(top_m=50, batch_size=2, timeout_sec=0.001),
            reranker_backend=backend,
        )
        trace = _RecordingTrace()

        reranker.rerank("q", _candidates(5), trace=trace)

        assert trace.stages["rerank"]["timed_out"] is False


class TestTimeoutInteractsWithTopM:
    """超时与 top_m 截断叠加时,两个余量都要正确回填。"""

    def test_top_m_truncation_plus_timeout(self) -> None:
        # 20 条候选 → top_m=8 截断 → 打分时超时只完成前 2 条
        backend = _SlowBatchBackend(sleep_per_batch=0.1, total=8)
        reranker = Reranker(
            _FakeSettings(top_m=8, batch_size=2, timeout_sec=0.05),
            reranker_backend=backend,
        )
        trace = _RecordingTrace()

        results = reranker.rerank("q", _candidates(20), trace=trace)

        payload = trace.stages["rerank"]
        assert payload["reranked_count"] == 8       # 送入重排的
        assert payload["scored_count"] == 2         # 实际打分的
        assert payload["carried_over_count"] == 12  # top_m 截断掉的
        assert payload["timed_out"] is True

        # c1,c0 打了分(降序)→ c2..c7 超时未打分 → c8..c19 被 top_m 截断
        assert _ids(results) == ["c1", "c0"] + [f"c{i}" for i in range(2, 20)]
        assert len(results) == 20
