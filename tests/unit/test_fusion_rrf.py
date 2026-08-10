"""Fusion (带权 RRF) 单元测试。

**关于 feature-005 的改动范围（T007 的纪律说明）**：

本文件原有 9 个用例。改造为命名映射入参后，**没有任何一条断言的语义被修改**
—— 全部改动仅是调用形态 ``fuse([dense, sparse])`` → ``fuse({"dense": dense,
"sparse": sparse})``。原断言检查的是条数、chunk_id、metadata 归属、top_k
截断等，与入参形态无关，因此原样保留。

唯一的行为变化是**同分项的排序**，说明见
``TestEqualWeightCompatibility.test_tie_breaking_is_now_deterministic``。

新增的三组守卫（``TestOrderIndependence`` / ``TestEmptyRouteNoSideEffect`` /
``TestEqualWeightCompatibility``）守的失败**都是静默的** —— 不抛异常、不告警，
只是检索效果悄悄变差。因此必须由测试固定，不能靠 code review 兜底。
"""

import pytest

from src.core.query_engine.fusion import DEFAULT_ROUTE_WEIGHT, Fusion
from src.core.types import RetrievalResult

pytestmark = pytest.mark.unit


def _r(chunk_id: str, score: float = 0.5, text: str = "", metadata=None) -> RetrievalResult:
    """构造 RetrievalResult 的简写。"""
    return RetrievalResult(
        chunk_id=chunk_id,
        score=score,
        text=text or f"text-{chunk_id}",
        metadata=metadata if metadata is not None else {},
    )


class TestFusion:
    """Fusion 类的单元测试（feature-005 仅适配调用形态，断言未改）。"""

    def test_fuse_empty_lists(self):
        """测试空结果列表融合。"""
        fusion = Fusion()
        result = fusion.fuse({})
        assert result == []

    def test_fuse_single_list(self):
        """测试单列表融合。"""
        fusion = Fusion()
        results = [
            RetrievalResult(chunk_id="1", score=0.9, text="text1", metadata={}),
            RetrievalResult(chunk_id="2", score=0.8, text="text2", metadata={}),
        ]
        fused = fusion.fuse({"dense": results})
        assert len(fused) == 2
        assert fused[0].chunk_id == "1"

    def test_fuse_two_lists_different_order(self):
        """测试两个不同顺序的列表融合。"""
        fusion = Fusion()
        dense = [
            RetrievalResult(chunk_id="1", score=0.9, text="text1", metadata={}),
            RetrievalResult(chunk_id="2", score=0.8, text="text2", metadata={}),
        ]
        sparse = [
            RetrievalResult(chunk_id="2", score=0.7, text="text2", metadata={}),
            RetrievalResult(chunk_id="1", score=0.6, text="text1", metadata={}),
        ]
        fused = fusion.fuse({"dense": dense, "sparse": sparse})
        assert fused[0].chunk_id in ["1", "2"]
        assert fused[1].chunk_id in ["1", "2"]

    def test_fuse_duplicate_chunk_ids(self):
        """测试重复 chunk_id 的融合。"""
        fusion = Fusion(k=60)
        dense = [
            RetrievalResult(chunk_id="1", score=0.9, text="text1", metadata={}),
            RetrievalResult(chunk_id="2", score=0.8, text="text2", metadata={}),
        ]
        sparse = [
            RetrievalResult(chunk_id="1", score=0.7, text="text1_v2", metadata={}),
        ]
        fused = fusion.fuse({"dense": dense, "sparse": sparse})
        assert len(fused) == 2

    def test_fuse_with_top_k(self):
        """测试 top_k 参数。"""
        fusion = Fusion()
        results = [
            RetrievalResult(chunk_id=str(i), score=1.0 - i * 0.1, text=f"text{i}", metadata={})
            for i in range(10)
        ]
        fused = fusion.fuse({"dense": results}, top_k=3)
        assert len(fused) == 3

    def test_fuse_preserves_metadata(self):
        """测试融合后保留最高分结果的 metadata。"""
        fusion = Fusion()
        dense = [
            RetrievalResult(chunk_id="1", score=0.9, text="text1", metadata={"source": "dense"}),
        ]
        sparse = [
            RetrievalResult(chunk_id="1", score=0.7, text="text1", metadata={"source": "sparse"}),
        ]
        fused = fusion.fuse({"dense": dense, "sparse": sparse})
        assert fused[0].metadata["source"] == "dense"

    def test_fuse_custom_k(self):
        """测试自定义 k 参数。"""
        fusion_aggressive = Fusion(k=1)
        fusion_conservative = Fusion(k=100)

        results1 = [
            RetrievalResult(chunk_id="1", score=0.9, text="text1", metadata={}),
            RetrievalResult(chunk_id="2", score=0.8, text="text2", metadata={}),
        ]
        results2 = [
            RetrievalResult(chunk_id="2", score=0.7, text="text2", metadata={}),
            RetrievalResult(chunk_id="1", score=0.6, text="text1", metadata={}),
        ]

        fused_aggressive = fusion_aggressive.fuse({"dense": results1, "sparse": results2})
        fused_conservative = fusion_conservative.fuse({"dense": results1, "sparse": results2})

        assert len(fused_aggressive) == 2
        assert len(fused_conservative) == 2

    def test_fuse_empty_result_in_list(self):
        """测试包含空列表的融合。"""
        fusion = Fusion()
        results = [
            RetrievalResult(chunk_id="1", score=0.9, text="text1", metadata={}),
        ]
        fused = fusion.fuse({"dense": results, "sparse": []})
        assert len(fused) == 1

    def test_fuse_ignores_empty_chunk_id(self):
        """测试忽略空 chunk_id。"""
        fusion = Fusion()
        results = [
            RetrievalResult(chunk_id="", score=0.9, text="text1", metadata={}),
            RetrievalResult(chunk_id="1", score=0.8, text="text2", metadata={}),
        ]
        fused = fusion.fuse({"dense": results})
        assert len(fused) == 1
        assert fused[0].chunk_id == "1"


# ===========================================================================
# T008：顺序无关守卫（SC-012 / FR-002）
# ===========================================================================


class TestOrderIndependence:
    """★ 本 feature 最重要的一组守卫。

    权重必须按路径**名字**查找，不得依赖传入顺序。

    **为什么这条最重要**：错配后系统照常运行、不抛异常、不告警，只是语义路径
    拿到了关键词路径的权重、效果悄悄变差。而这种混淆**在本项目真实发生过**
    —— feature-005 之前 ``fusion.py`` 有一条注释写着
    ``result_lists=[sparse_result, dense_result]``，而 ``hybrid_search.py``
    实际传的是 ``[dense, sparse]``，顺序正好写反。等权时该错误完全无害，
    所以它一直存活到本 feature 才被发现。
    """

    @staticmethod
    def _fixture():
        dense = [_r("a"), _r("b"), _r("c")]
        sparse = [_r("c"), _r("d"), _r("a")]
        return dense, sparse

    def test_identical_output_regardless_of_key_insertion_order(self):
        """交换 routes 中键的插入顺序，输出必须逐条完全相同。"""
        dense, sparse = self._fixture()
        fusion = Fusion(k=60, weights={"dense": 1.0, "sparse": 0.25})

        forward = fusion.fuse({"dense": dense, "sparse": sparse})
        backward = fusion.fuse({"sparse": sparse, "dense": dense})

        assert [x.chunk_id for x in forward] == [x.chunk_id for x in backward]
        assert [x.score for x in forward] == [x.score for x in backward]

    def test_asymmetric_weights_attach_to_correct_route(self):
        """权重必须真正跟着路径走，而不是跟着位置走。

        dense 独占 ``x``、sparse 独占 ``y``，两者在各自路里同为第 1 名。
        给 dense 更高权重后，``x`` 必须排在 ``y`` 前面 —— 无论传入顺序如何。
        """
        heavy_dense = Fusion(k=60, weights={"dense": 1.0, "sparse": 0.1})

        for routes in (
            {"dense": [_r("x")], "sparse": [_r("y")]},
            {"sparse": [_r("y")], "dense": [_r("x")]},
        ):
            fused = heavy_dense.fuse(routes)
            assert [f.chunk_id for f in fused] == ["x", "y"], routes

    def test_swapping_weights_swaps_ranking(self):
        """权重确实在起作用：把两路权重对调，排序应随之翻转。

        这条排除了「顺序无关是因为权重压根没生效」这种假通过。
        """
        routes = {"dense": [_r("x")], "sparse": [_r("y")]}

        heavy_dense = Fusion(k=60, weights={"dense": 1.0, "sparse": 0.1})
        heavy_sparse = Fusion(k=60, weights={"dense": 0.1, "sparse": 1.0})

        assert [f.chunk_id for f in heavy_dense.fuse(routes)] == ["x", "y"]
        assert [f.chunk_id for f in heavy_sparse.fuse(routes)] == ["y", "x"]

    def test_tied_scores_break_deterministically(self):
        """同分时也必须顺序无关。

        这是顺序无关能成立的技术关键：只按 score 排序时，同分项的相对次序会
        随插入顺序变化（Python 排序稳定），而插入顺序又随 routes 键顺序变化。
        因此实现用 ``(-score, chunk_id)`` 作排序键。
        """
        fusion = Fusion(k=60, weights={"dense": 1.0, "sparse": 1.0})
        # p 在 dense 第 1、q 在 sparse 第 1 → 等权下得分完全相同
        forward = fusion.fuse({"dense": [_r("p")], "sparse": [_r("q")]})
        backward = fusion.fuse({"sparse": [_r("q")], "dense": [_r("p")]})

        assert [x.chunk_id for x in forward] == [x.chunk_id for x in backward]


# ===========================================================================
# T009：空路无副作用守卫（SC-013 / FR-004）
# ===========================================================================


class TestEmptyRouteNoSideEffect:
    """某路为空时，其余路的相对排序不得改变。

    **这条要求靠「不引入动态归一化」来满足，而非靠新增代码。** 若在某路为空时
    把其权重重新分配给剩余路径，会：

    - **不改变任何可观测排序**（等比缩放是单调变换）
    - 却让同一内容的绝对得分随「另一路是否恰好为空」跳变，跨查询不可比
    - 引入一个只在边界触发、无可观测收益的分支

    因此本组测试的作用是守住它**不被后人当作"优化"加回来**。
    详见 specs/005-weighted-fusion/research.md Decision 4。
    """

    def test_empty_route_matches_omitted_route(self):
        """传入空列表与压根不传该路，排序必须一致。"""
        dense = [_r("a"), _r("b"), _r("c")]
        fusion = Fusion(k=60, weights={"dense": 1.0, "sparse": 0.5})

        with_empty = fusion.fuse({"dense": dense, "sparse": []})
        omitted = fusion.fuse({"dense": dense})

        assert [x.chunk_id for x in with_empty] == [x.chunk_id for x in omitted]

    def test_empty_route_does_not_rescale_scores(self):
        """空路不得触发权重归一化 —— 绝对得分也必须一致。

        排序相同不足以证明没做归一化（等比缩放不改排序）。这条查绝对值。
        """
        dense = [_r("a"), _r("b")]
        fusion = Fusion(k=60, weights={"dense": 0.5, "sparse": 0.5})

        with_empty = fusion.fuse({"dense": dense, "sparse": []})
        omitted = fusion.fuse({"dense": dense})

        assert [x.score for x in with_empty] == [x.score for x in omitted]
        # 且得分就是 weight/(k+rank)，没有被放大到 1.0/(k+rank)
        assert with_empty[0].score == pytest.approx(0.5 / 61)

    def test_all_routes_empty(self):
        assert Fusion().fuse({"dense": [], "sparse": []}) == []

    def test_relative_order_within_surviving_route_preserved(self):
        """存活路内部的相对次序必须与其原始名次一致。"""
        dense = [_r(c) for c in ("first", "second", "third")]
        fused = Fusion(weights={"dense": 1.0, "sparse": 2.0}).fuse(
            {"dense": dense, "sparse": []}
        )
        assert [x.chunk_id for x in fused] == ["first", "second", "third"]


# ===========================================================================
# T010：等权兼容守卫（SC-006 / FR-003）
# ===========================================================================


class TestEqualWeightCompatibility:
    """权重全相等时，排序与 feature-005 之前一致。

    数学依据：等权时新公式 ``w/(k+rank)`` 是旧公式 ``1/(k+rank)`` 的常数倍，
    而排序对等比缩放（单调变换）不变。
    """

    @staticmethod
    def _legacy_fuse(result_lists, k=60, top_k=None):
        """feature-005 之前的实现，逐行复刻用于对照。

        刻意保留原样（包括只按 score 排序、不设次级键），以便对比新旧行为。
        """
        chunk_scores, chunk_data = {}, {}
        for result_list in result_lists:
            if not result_list:
                continue
            for rank, result in enumerate(result_list, start=1):
                if not result.chunk_id:
                    continue
                s = 1.0 / (k + rank)
                if result.chunk_id in chunk_scores:
                    chunk_scores[result.chunk_id] += s
                else:
                    chunk_scores[result.chunk_id] = s
                    chunk_data[result.chunk_id] = result
        out = [
            RetrievalResult(
                chunk_id=cid,
                score=sc,
                text=chunk_data[cid].text,
                metadata=chunk_data[cid].metadata,
            )
            for cid, sc in chunk_scores.items()
        ]
        out.sort(key=lambda x: x.score, reverse=True)
        return out[:top_k] if top_k else out

    def test_equal_weights_match_legacy_on_distinct_scores(self):
        """得分互不相同时，新旧实现输出逐条相等。"""
        dense = [_r("a"), _r("b"), _r("c"), _r("d")]
        sparse = [_r("b"), _r("e")]

        new = Fusion(k=60, weights={"dense": 1.0, "sparse": 1.0}).fuse(
            {"dense": dense, "sparse": sparse}
        )
        legacy = self._legacy_fuse([dense, sparse], k=60)

        assert [x.chunk_id for x in new] == [x.chunk_id for x in legacy]
        assert [pytest.approx(x.score) for x in new] == [x.score for x in legacy]

    def test_no_weights_argument_equals_equal_weights(self):
        """不传 weights 与显式等权必须完全一致（FR-003 的默认路径）。"""
        dense, sparse = [_r("a"), _r("b")], [_r("b"), _r("c")]

        default = Fusion(k=60).fuse({"dense": dense, "sparse": sparse})
        explicit = Fusion(k=60, weights={"dense": 1.0, "sparse": 1.0}).fuse(
            {"dense": dense, "sparse": sparse}
        )

        assert [x.chunk_id for x in default] == [x.chunk_id for x in explicit]
        assert [x.score for x in default] == [x.score for x in explicit]

    def test_tie_breaking_is_now_deterministic(self):
        """**唯一的行为变化，理由留档。**

        旧实现是 ``sort(key=score, reverse=True)``。Python 排序稳定，因此同分项
        的相对次序由插入顺序决定，而插入顺序随路径遍历顺序变化 —— 也就是说
        **旧行为在同分时本来就是顺序依赖的**（同分在 RRF 里不罕见：两个不同
        chunk 分别在两路拿到相同名次即同分）。

        因此加 ``chunk_id`` 次级键不是破坏向后兼容，而是把一处原本不确定的
        行为变确定。SC-006 的「逐条一致」相应地只对非同分输入断言。
        """
        fusion = Fusion(k=60)
        routes_fwd = {"dense": [_r("zzz")], "sparse": [_r("aaa")]}
        routes_bwd = {"sparse": [_r("aaa")], "dense": [_r("zzz")]}

        # 新实现：同分按 chunk_id 升序，两种传入顺序结果一致
        assert [x.chunk_id for x in fusion.fuse(routes_fwd)] == ["aaa", "zzz"]
        assert [x.chunk_id for x in fusion.fuse(routes_bwd)] == ["aaa", "zzz"]

        # 旧实现：同分次序随传入顺序翻转 —— 这正是被修掉的不确定性
        legacy_fwd = self._legacy_fuse([[_r("zzz")], [_r("aaa")]])
        legacy_bwd = self._legacy_fuse([[_r("aaa")], [_r("zzz")]])
        assert [x.chunk_id for x in legacy_fwd] != [x.chunk_id for x in legacy_bwd]


# ===========================================================================
# T011：权重语义（SC-005 + 相对比例）
# ===========================================================================


class TestWeightSemantics:
    """权重的语义性质。"""

    def test_zero_weight_route_has_no_effect(self):
        """某路权重为 0 时该路不影响任何结果（SC-005）。

        这是「关闭关键词路径 ⇒ 等价于纯语义检索」的直接依据。
        """
        dense = [_r("a"), _r("b")]
        sparse = [_r("x"), _r("y")]

        zeroed = Fusion(k=60, weights={"dense": 1.0, "sparse": 0.0}).fuse(
            {"dense": dense, "sparse": sparse}
        )
        dense_only = Fusion(k=60, weights={"dense": 1.0}).fuse({"dense": dense})

        assert [x.chunk_id for x in zeroed] == [x.chunk_id for x in dense_only]
        assert [x.score for x in zeroed] == [x.score for x in dense_only]
        # sparse 独占的内容压根不该出现
        assert {"x", "y"}.isdisjoint({x.chunk_id for x in zeroed})

    def test_only_relative_ratio_matters(self):
        """比例相同的两组权重产出完全相同的排序。

        ``{dense:1, sparse:0.5}`` 与 ``{dense:2, sparse:1}`` 的得分相差常数倍，
        而排序对等比缩放不变。这条性质直接决定了校准只需扫一个自由度
        （见 data-model.md § 2）。
        """
        dense = [_r("a"), _r("b"), _r("c")]
        sparse = [_r("c"), _r("d")]
        routes = {"dense": dense, "sparse": sparse}

        small = Fusion(k=60, weights={"dense": 1.0, "sparse": 0.5}).fuse(routes)
        large = Fusion(k=60, weights={"dense": 2.0, "sparse": 1.0}).fuse(routes)

        assert [x.chunk_id for x in small] == [x.chunk_id for x in large]
        # 得分是 2 倍关系，不是相等
        for s, l in zip(small, large):
            assert l.score == pytest.approx(s.score * 2)

    def test_missing_route_weight_defaults_to_one(self):
        """配置里没写的路径按缺省 1.0 处理，不报错。

        设计如此：新增检索路径时不应强制所有部署同步改配置。
        """
        fusion = Fusion(k=60, weights={"dense": 1.0})
        assert fusion.weight_for("sparse") == DEFAULT_ROUTE_WEIGHT
        assert fusion.weight_for("brand_new_route") == DEFAULT_ROUTE_WEIGHT

    def test_weights_property_returns_copy(self):
        """``weights`` 属性返回副本，外部改动不得污染内部状态。"""
        fusion = Fusion(weights={"dense": 1.0, "sparse": 0.25})
        snapshot = fusion.weights
        snapshot["dense"] = 999.0
        assert fusion.weight_for("dense") == 1.0

    def test_weights_property_exposes_effective_config(self):
        """追踪打点要靠它读出「本次生效的权重」（FR-008）。"""
        assert Fusion(weights={"dense": 1.0, "sparse": 0.25}).weights == {
            "dense": 1.0,
            "sparse": 0.25,
        }

    def test_higher_weight_lifts_single_route_hit_above_lower_ranked_dual_hit(self):
        """权重足够高时，单路命中可以压过双路命中 —— 证明权重真在改变结果。"""
        # d 只被 dense 命中且排第 1；s 被两路命中但都排第 3
        dense = [_r("d"), _r("pad1"), _r("s")]
        sparse = [_r("pad2"), _r("pad3"), _r("s")]

        heavy_dense = Fusion(k=1, weights={"dense": 10.0, "sparse": 0.1})
        fused = heavy_dense.fuse({"dense": dense, "sparse": sparse})

        assert fused[0].chunk_id == "d"
