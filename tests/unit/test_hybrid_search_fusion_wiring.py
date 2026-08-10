"""Unit tests for HybridSearch → Fusion 的接线 (Feature-005 T012/T013/T014/T015)。

测试范围:

1. ``Fusion`` 由 settings 构造 —— 配置的 ``rrf_k`` 与 ``fusion_weights`` 必须
   真正传达到融合器（此前 ``Fusion()`` 无参构造、``k=60`` 硬编码，属宪法原则二
   禁止的硬编码可调参数）
2. ``fuse()`` 收到的是**命名映射**而非位置列表（FR-002）
3. fusion 打点 payload 含本次生效的权重（FR-008 / SC-008）

不触发任何 LLM / 向量库调用 —— 全部用替身。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

import pytest

from src.core.query_engine.hybrid_search import HybridSearch
from src.core.settings import load_settings
from src.core.types import RetrievalResult

pytestmark = pytest.mark.unit


_REAL_CONFIG = "config/settings.yaml"


def _r(chunk_id: str) -> RetrievalResult:
    return RetrievalResult(chunk_id=chunk_id, score=0.5, text=f"t-{chunk_id}", metadata={})


class RecordingFusion:
    """记录 fuse() 收到什么的融合器替身。"""

    def __init__(self, weights: Optional[Dict[str, float]] = None, k: int = 60) -> None:
        self._weights = weights or {}
        self._k = k
        self.received: Optional[Any] = None

    @property
    def weights(self) -> Dict[str, float]:
        return dict(self._weights)

    def fuse(self, routes: Any, top_k: Optional[int] = None) -> List[RetrievalResult]:
        self.received = routes
        if isinstance(routes, Mapping):
            merged: List[RetrievalResult] = []
            for results in routes.values():
                merged.extend(results)
            return merged
        raise AssertionError(f"fuse() 收到的不是映射而是 {type(routes).__name__}")


class StubRetriever:
    """固定返回给定结果的检索器替身。"""

    def __init__(self, results: Sequence[RetrievalResult]) -> None:
        self._results = list(results)

    def retrieve(self, *args: Any, **kwargs: Any) -> List[RetrievalResult]:
        return list(self._results)


class PassthroughReranker:
    def rerank(self, query: str, results: Sequence[RetrievalResult], trace: Any = None):
        return list(results)


class RecordingTrace:
    """只记录 finish_stage payload 的 trace 替身。"""

    def __init__(self) -> None:
        self.stages: Dict[str, Dict[str, Any]] = {}

    def start_stage(self, name: str) -> None:
        pass

    def finish_stage(self, name: str, payload: Optional[Dict[str, Any]] = None) -> None:
        self.stages[name] = dict(payload or {})


def _build(settings, fusion=None, dense=("a",), sparse=("b",)) -> HybridSearch:
    return HybridSearch(
        settings=settings,
        dense_retriever=StubRetriever([_r(c) for c in dense]),
        sparse_retriever=StubRetriever([_r(c) for c in sparse]),
        fusion=fusion,
        reranker=PassthroughReranker(),
    )


class TestFusionBuiltFromSettings:
    """T012：融合器必须从配置构造。"""

    def test_rrf_k_from_settings_reaches_fusion(self):
        settings = load_settings(_REAL_CONFIG)
        settings.retrieval.rrf_k = 17

        search = _build(settings)

        assert search._fusion._k == 17

    def test_weights_from_settings_reach_fusion(self):
        settings = load_settings(_REAL_CONFIG)
        settings.retrieval.fusion_weights = {"dense": 1.0, "sparse": 0.25}

        search = _build(settings)

        assert search._fusion.weights == {"dense": 1.0, "sparse": 0.25}

    def test_no_longer_constructed_without_arguments(self):
        """回归保护：此前是 ``Fusion()`` 无参构造，k=60 硬编码。

        改配置若不生效，症状是「调了权重没反应」—— 而这不会报错。

        注：只匹配真实的赋值语句，不看注释 —— 代码里刻意留了一段说明历史的
        注释，其中含 ``Fusion()`` 字样。
        """
        import re
        from pathlib import Path

        source = Path("src/core/query_engine/hybrid_search.py").read_text(encoding="utf-8")
        no_arg_construction = re.search(r"^\s*self\._fusion\s*=\s*Fusion\(\s*\)", source, re.M)
        assert no_arg_construction is None

    def test_missing_settings_rejected_when_fusion_not_injected(self):
        """settings 为 None 且未注入 fusion 时必须明确报错，不静默用默认值。"""
        with pytest.raises(ValueError, match="settings must be provided"):
            HybridSearch(
                settings=None,
                dense_retriever=StubRetriever([]),
                sparse_retriever=StubRetriever([]),
                reranker=PassthroughReranker(),
            )


class TestFuseCalledWithNamedMapping:
    """T013：必须按命名映射调用，不得回退到位置列表。"""

    def test_fuse_receives_mapping_with_expected_keys(self):
        settings = load_settings(_REAL_CONFIG)
        fusion = RecordingFusion()

        _build(settings, fusion=fusion, dense=("d1", "d2"), sparse=("s1",)).search("q")

        assert isinstance(fusion.received, Mapping)
        assert set(fusion.received) == {"dense", "sparse"}

    def test_routes_carry_the_correct_results(self):
        """键与内容必须对应正确 —— 这是 FR-002 在调用侧的落点。

        `fusion.py` 此前有一条注释把两路顺序写反（写作
        ``[sparse_result, dense_result]``，实际传 ``[dense, sparse]``）。
        等权时无害，加权重后就是让 dense 拿到 sparse 权重的真 bug。
        """
        settings = load_settings(_REAL_CONFIG)
        fusion = RecordingFusion()

        _build(settings, fusion=fusion, dense=("dense_only",), sparse=("sparse_only",)).search("q")

        assert [r.chunk_id for r in fusion.received["dense"]] == ["dense_only"]
        assert [r.chunk_id for r in fusion.received["sparse"]] == ["sparse_only"]

    def test_no_positional_list_call_remains(self):
        """回归保护：不得回退到位置列表调用（只看代码，不看注释）。"""
        import re
        from pathlib import Path

        source = Path("src/core/query_engine/hybrid_search.py").read_text(encoding="utf-8")
        positional_call = re.search(
            r"^\s*[^#\n]*\.fuse\(\s*\[\s*dense_results", source, re.M
        )
        assert positional_call is None


class TestFusionTracePayload:
    """T014 / FR-008：打点必须含本次生效的权重。"""

    def test_payload_contains_effective_weights(self):
        settings = load_settings(_REAL_CONFIG)
        settings.retrieval.fusion_weights = {"dense": 1.0, "sparse": 0.3}
        trace = RecordingTrace()

        _build(settings).search("q", trace=trace)

        assert trace.stages["fusion"]["weights"] == {"dense": 1.0, "sparse": 0.3}

    def test_payload_contains_rrf_k(self):
        settings = load_settings(_REAL_CONFIG)
        settings.retrieval.rrf_k = 42
        trace = RecordingTrace()

        _build(settings).search("q", trace=trace)

        assert trace.stages["fusion"]["rrf_k"] == 42

    def test_existing_payload_fields_preserved(self):
        """既有的三个字段不得因新增而丢失。"""
        settings = load_settings(_REAL_CONFIG)
        trace = RecordingTrace()

        _build(settings, dense=("a", "b"), sparse=("c",)).search("q", trace=trace)

        payload = trace.stages["fusion"]
        assert payload["input_dense"] == 2
        assert payload["input_sparse"] == 1
        assert "output_count" in payload
        assert payload["method"] == "Fusion"


class TestEndToEndWeightEffect:
    """权重经完整链路真的生效（SC-004 / SC-005 的单测版）。"""

    def test_zero_sparse_weight_drops_sparse_only_hits(self):
        """sparse 权重为 0 时，仅被 sparse 命中的内容不应出现在结果里。"""
        settings = load_settings(_REAL_CONFIG)
        settings.retrieval.fusion_weights = {"dense": 1.0, "sparse": 0.0}

        results = _build(settings, dense=("keep",), sparse=("drop",)).search("q", top_k=10)

        ids = {r.chunk_id for r in results}
        assert "keep" in ids
        assert "drop" not in ids

    def test_equal_weights_include_both_routes(self):
        settings = load_settings(_REAL_CONFIG)
        settings.retrieval.fusion_weights = {"dense": 1.0, "sparse": 1.0}

        results = _build(settings, dense=("from_dense",), sparse=("from_sparse",)).search(
            "q", top_k=10
        )

        assert {"from_dense", "from_sparse"} <= {r.chunk_id for r in results}
