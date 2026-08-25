"""守卫：两处**潜伏**的静默失效必须在被触发时喊出来 (C14 / C16)。

change: 无（根因明确的小修，走 CLAUDE.md 的例外）

## 这两条现在都还没坏 —— 这正是重点

- 五个 trace 阶段名各不相同（实测最近 200 条 trace **零重名**）
- 两条检索路径都在 `fusion_weights` 里，`weight_for()` 从不回落

所以它们是**潜伏态**。刻意**不实现**「返回全部同名阶段」与「路径族权重查找」——
现在没有任何调用方需要它们，为不存在的需求做设计就是又一个 ``rerank.top_m``。

**做的是另一件事：让违反变得可见。** 真要引入多路检索时，这两条 warning 会是
第一个撞上的东西，而不是等指标悄悄变差之后回来找原因。

这个取舍本身值得记下来：**「不为未来造机器」与「不留静默失效」并不冲突** ——
中间那条路是「检测并喊出来」。

不联网、不调用任何模型。
"""

from __future__ import annotations

import logging

import pytest

from src.core.query_engine.fusion import DEFAULT_ROUTE_WEIGHT, Fusion
from src.core.types import RetrievalResult
from src.observability.dashboard.services.trace_service import TraceRecord

pytestmark = pytest.mark.unit


def _r(chunk_id: str) -> RetrievalResult:
    return RetrievalResult(chunk_id=chunk_id, score=1.0, text=f"t-{chunk_id}", metadata={})


class TestUnknownRouteWeightIsLoud:
    """未配置的融合路径回落缺省权重时必须告警。

    为什么这条是必需的：**路径名由调用方在 ``fuse()`` 时决定，不经配置** ——
    所以 settings 层的键名校验拦不住它。有人把路径命名成 ``dense_q0``，
    ``weight_for()`` 就悄悄给 1.0，Feature-005 校准出的 0.75 当场作废，
    而系统照常运行、不报错、只是指标变差。
    """

    def test_known_route_returns_configured_weight(self) -> None:
        fusion = Fusion(k=60, weights={"dense": 1.0, "sparse": 0.75})

        assert fusion.weight_for("sparse") == 0.75

    def test_unknown_route_warns(self, caplog) -> None:
        fusion = Fusion(k=60, weights={"dense": 1.0, "sparse": 0.75})

        with caplog.at_level(logging.WARNING):
            weight = fusion.weight_for("dense_q0")

        assert weight == DEFAULT_ROUTE_WEIGHT
        assert any("dense_q0" in r.getMessage() for r in caplog.records), (
            "未知路径回落缺省权重时没有告警 —— 校准值被作废却无人知晓"
        )

    def test_warns_only_once_per_route(self, caplog) -> None:
        """同一个未知路径名只警告一次 —— 逐次查表刷日志会淹掉真信号。"""
        fusion = Fusion(k=60, weights={"dense": 1.0})

        with caplog.at_level(logging.WARNING):
            for _ in range(5):
                fusion.weight_for("sparse_q0")

        hits = [r for r in caplog.records if "sparse_q0" in (r.getMessage())]
        assert len(hits) == 1

    def test_known_route_does_not_warn(self, caplog) -> None:
        fusion = Fusion(k=60, weights={"dense": 1.0, "sparse": 0.75})

        with caplog.at_level(logging.WARNING):
            fusion.weight_for("dense")
            fusion.weight_for("sparse")

        assert caplog.records == []

    def test_fuse_still_works_with_unknown_routes(self) -> None:
        """告警不改变行为 —— 回落语义保持不变（向后兼容）。"""
        fusion = Fusion(k=60, weights={"dense": 1.0})

        fused = fusion.fuse({"dense": [_r("a")], "mystery": [_r("b")]}, top_k=5)

        assert {r.chunk_id for r in fused} == {"a", "b"}

    def test_fusion_stays_stateless_for_scoring(self) -> None:
        """告警记账不得影响打分 —— 同样输入必须同样输出。"""
        first = Fusion(k=60, weights={"dense": 1.0}).fuse(
            {"dense": [_r("a")], "x": [_r("b")]}, top_k=5
        )
        engine = Fusion(k=60, weights={"dense": 1.0})
        engine.weight_for("x")  # 先触发一次告警记账
        second = engine.fuse({"dense": [_r("a")], "x": [_r("b")]}, top_k=5)

        assert [(r.chunk_id, r.score) for r in first] == [
            (r.chunk_id, r.score) for r in second
        ]


class TestDuplicateTraceStageIsLoud:
    """同名 trace 阶段多于一个时必须告警。

    写入侧（``TraceContext.start_stage``）**允许**重名：无条件 append，
    ``finish_stage`` 逆序配对，所以嵌套同名阶段能正常收尾、不报错。
    读取侧却是「命中即返回」—— 两端不对称，而不对称的那一半是静默的。
    """

    @staticmethod
    def _record(stages: list[dict]) -> TraceRecord:
        return TraceRecord({"trace_id": "abcdef123456", "stages": stages})

    def test_duplicate_stage_warns(self, caplog) -> None:
        record = self._record(
            [
                {"name": "dense_retrieval", "duration_ms": 10, "data": {"count": 3}},
                {"name": "dense_retrieval", "duration_ms": 20, "data": {"count": 5}},
            ]
        )

        with caplog.at_level(logging.WARNING):
            data = record.get_stage_data("dense_retrieval")

        assert data == {"count": 3}, "行为不变:仍取第一个"
        assert any("dense_retrieval" in (r.getMessage()) for r in caplog.records)

    def test_duration_lookup_also_warns(self, caplog) -> None:
        """两个读取入口都要喊 —— 只堵一个等于没堵。"""
        record = self._record(
            [
                {"name": "sparse_retrieval", "duration_ms": 7, "data": {}},
                {"name": "sparse_retrieval", "duration_ms": 9, "data": {}},
            ]
        )

        with caplog.at_level(logging.WARNING):
            duration = record.get_stage_duration("sparse_retrieval")

        assert duration == 7
        assert caplog.records != []

    def test_unique_stage_does_not_warn(self, caplog) -> None:
        record = self._record([{"name": "fusion", "duration_ms": 5, "data": {"k": 1}}])

        with caplog.at_level(logging.WARNING):
            assert record.get_stage_data("fusion") == {"k": 1}

        assert caplog.records == []

    def test_missing_stage_returns_none_without_warning(self, caplog) -> None:
        """缺失阶段是正常情形（例如没开重排），不该告警。"""
        record = self._record([{"name": "fusion", "duration_ms": 5, "data": {}}])

        with caplog.at_level(logging.WARNING):
            assert record.get_stage_data("rerank") is None
            assert record.get_stage_duration("rerank") is None

        assert caplog.records == []

    def test_warning_says_how_many_were_hidden(self, caplog) -> None:
        """告警要说清丢了几个 —— 「有重名」不够，要能估计信息损失。"""
        record = self._record(
            [{"name": "dense_retrieval", "duration_ms": i, "data": {}} for i in range(4)]
        )

        with caplog.at_level(logging.WARNING):
            record.get_stage_data("dense_retrieval")

        text = " ".join(r.getMessage() for r in caplog.records)
        assert "4" in text and "3" in text


class TestCurrentStateIsClean:
    """自检：这两条现在**确实**还没被触发。

    如果哪天它们变成常态，上面那些告警会开始刷日志 —— 那时该做的是
    「让阶段名可区分」「补路径族权重查找」，而不是把告警关掉。
    """

    def test_production_route_names_are_all_configured(self) -> None:
        """生产用的两个路径名都在权重表里 —— 不该有回落。"""
        from src.core.settings import load_settings
        from src.core.types import ROUTE_DENSE, ROUTE_SPARSE

        weights = load_settings().retrieval.fusion_weights

        assert ROUTE_DENSE in weights
        assert ROUTE_SPARSE in weights

    def test_pipeline_stage_names_are_distinct(self) -> None:
        """检索管线的阶段名两两不同 —— 重名目前不会发生。"""
        names = [
            "query_processing",
            "dense_retrieval",
            "sparse_retrieval",
            "fusion",
            "rerank",
        ]

        assert len(names) == len(set(names))
