"""Unit tests for `scripts/calibrate_fusion_weights.py` (Feature-005 T017-T020)。

测试范围:

1. **缓存重放的确定性**（FR-010）：同缓存 + 同权重必得同结果
2. **缓存与 collection 绑定**：不匹配时必须报错而非静默重放 —— 跨 collection
   的检索结果不可比，静默重放会得出错误结论且无人察觉
3. 选择判据的三个分支（research.md Decision 6）
4. `sparse=0` 候选等价于纯语义检索
5. 重放必须复用真实的 ``Fusion`` 而非另写打分逻辑

不触发任何 LLM / 向量库调用。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, ".")

from scripts import calibrate_fusion_weights as cal

pytestmark = pytest.mark.unit


def _case(query: str, expected, dense, sparse, difficulty="simple") -> cal.CachedCase:
    return cal.CachedCase(
        query=query,
        expected_chunk_ids=list(expected),
        difficulty=difficulty,
        routes={"dense": list(dense), "sparse": list(sparse)},
    )


@pytest.fixture()
def cache() -> cal.Cache:
    return cal.Cache(
        collection="test_collection",
        lang="en",
        cases=[
            _case("q1", ["a", "b"], dense=["a", "x", "y"], sparse=["b", "z", "a"]),
            _case("q2", ["c"], dense=["p", "c"], sparse=["q", "r"]),
            _case("q3", ["d", "e"], dense=["d"], sparse=["e", "d"]),
        ],
    )


class TestScoreRanking:
    """单条 case 的指标计算。"""

    def test_perfect_ranking(self):
        m = cal.score_ranking(["a", "b"], ["a", "b"])
        assert m["hit"] == 1.0
        assert m["recall"] == 1.0
        assert m["rr"] == 1.0
        assert m["ndcg"] == pytest.approx(1.0)

    def test_no_hit(self):
        m = cal.score_ranking(["x", "y"], ["a"])
        assert m == {"hit": 0.0, "recall": 0.0, "rr": 0.0, "ndcg": 0.0}

    def test_partial_recall(self):
        m = cal.score_ranking(["a", "x"], ["a", "b"])
        assert m["hit"] == 1.0
        assert m["recall"] == 0.5

    def test_reciprocal_rank_uses_first_hit(self):
        assert cal.score_ranking(["x", "a"], ["a"])["rr"] == pytest.approx(0.5)
        assert cal.score_ranking(["x", "y", "a"], ["a"])["rr"] == pytest.approx(1 / 3)

    def test_empty_expected_is_zero_not_crash(self):
        assert cal.score_ranking(["a"], [])["recall"] == 0.0

    def test_ndcg_rewards_earlier_hits(self):
        early = cal.score_ranking(["a", "x", "y"], ["a"])["ndcg"]
        late = cal.score_ranking(["x", "y", "a"], ["a"])["ndcg"]
        assert early > late


class TestReplayDeterminism:
    """FR-010：校准必须可复现。"""

    def test_same_inputs_same_output(self, cache):
        a = cal.replay(cache, {"dense": 1.0, "sparse": 0.3}, k=60, top_k=10)
        b = cal.replay(cache, {"dense": 1.0, "sparse": 0.3}, k=60, top_k=10)
        assert (a.hit_rate, a.recall, a.mrr, a.ndcg) == (b.hit_rate, b.recall, b.mrr, b.ndcg)

    def test_replay_is_offline(self, cache, monkeypatch):
        """重放不得触碰任何检索器 —— 那样就失去「离线」的全部意义。"""
        import src.core.query_engine.dense_retriever as dr

        def explode(*args, **kwargs):
            raise AssertionError("replay 不应构造检索器")

        monkeypatch.setattr(dr, "DenseRetriever", explode)
        cal.replay(cache, {"dense": 1.0, "sparse": 1.0}, k=60, top_k=10)

    def test_uses_real_fusion_not_a_reimplementation(self):
        """必须复用生产的 Fusion。

        另写一份打分逻辑会让校准结论与生产行为**静默漂移** —— 校准说好，
        线上却是另一回事。
        """
        source = Path("scripts/calibrate_fusion_weights.py").read_text(encoding="utf-8")
        assert "from src.core.query_engine.fusion import Fusion" in source
        assert "Fusion(k=k, weights=weights)" in source

    def test_weight_affects_result(self, cache):
        """权重不同结果应不同，否则说明重放没真正用上权重。"""
        low = cal.replay(cache, {"dense": 1.0, "sparse": 0.0}, k=60, top_k=10)
        high = cal.replay(cache, {"dense": 1.0, "sparse": 2.0}, k=60, top_k=10)
        assert (low.mrr, low.ndcg) != (high.mrr, high.ndcg)


class TestSparseZeroEqualsDenseOnly:
    def test_zero_sparse_ignores_sparse_route(self, cache):
        """``sparse=0`` 必须与压根没有 sparse 路一致（SC-005 的校准侧对应）。"""
        with_zero = cal.replay(cache, {"dense": 1.0, "sparse": 0.0}, k=60, top_k=10)

        dense_only_cache = cal.Cache(
            collection=cache.collection,
            lang=cache.lang,
            cases=[
                cal.CachedCase(
                    query=c.query,
                    expected_chunk_ids=c.expected_chunk_ids,
                    difficulty=c.difficulty,
                    routes={"dense": c.routes["dense"]},
                )
                for c in cache.cases
            ],
        )
        without = cal.replay(dense_only_cache, {"dense": 1.0}, k=60, top_k=10)

        assert (with_zero.hit_rate, with_zero.recall, with_zero.mrr, with_zero.ndcg) == (
            without.hit_rate, without.recall, without.mrr, without.ndcg
        )


class TestCacheIntegrity:
    """缓存必须与 collection 绑定 —— 跨 collection 重放会得出错误结论。"""

    def test_roundtrip(self, cache, tmp_path):
        path = tmp_path / "c.json"
        path.write_text(json.dumps(cache.to_json(), ensure_ascii=False), encoding="utf-8")

        loaded = cal.Cache.from_json(
            json.loads(path.read_text(encoding="utf-8")),
            expected_collection="test_collection",
        )

        assert loaded.collection == "test_collection"
        assert len(loaded.cases) == 3
        assert loaded.cases[0].routes["dense"] == ["a", "x", "y"]

    def test_collection_mismatch_raises(self, cache):
        """不匹配必须**报错**，不能静默重放。

        检索结果与 collection 强绑定；拿 A 集合的缓存去论证 B 集合的权重，
        结论是错的**而且不会有任何提示**。
        """
        with pytest.raises(ValueError, match="not comparable across collections"):
            cal.Cache.from_json(cache.to_json(), expected_collection="other_collection")

    def test_unsupported_format_version_raises(self, cache):
        data = cache.to_json()
        data["_format_version"] = 99
        with pytest.raises(ValueError, match="Unsupported cache format"):
            cal.Cache.from_json(data, expected_collection="test_collection")

    def test_missing_format_version_raises(self, cache):
        data = cache.to_json()
        del data["_format_version"]
        with pytest.raises(ValueError, match="Unsupported cache format"):
            cal.Cache.from_json(data, expected_collection="test_collection")

    def test_route_order_preserved(self, cache, tmp_path):
        """名次就是信息 —— 缓存往返不得重排。"""
        loaded = cal.Cache.from_json(cache.to_json(), expected_collection="test_collection")
        for original, restored in zip(cache.cases, loaded.cases):
            assert restored.routes["dense"] == original.routes["dense"]
            assert restored.routes["sparse"] == original.routes["sparse"]


class TestSelectionCriterion:
    """research.md Decision 6 的三个分支。"""

    @staticmethod
    def _m(recall: float, mrr: float) -> cal.Metrics:
        return cal.Metrics(n=42, hit_rate=0.0, recall=recall, mrr=mrr, ndcg=0.0)

    def test_picks_max_mrr_among_qualified(self):
        dense_only = self._m(0.40, 0.30)
        rows = [
            (0.0, self._m(0.40, 0.30)),
            (0.1, self._m(0.42, 0.35)),
            (0.5, self._m(0.41, 0.50)),   # 满足硬约束且 MRR 最高
            (1.0, self._m(0.35, 0.60)),   # MRR 更高但 recall 不达标
        ]
        out = cal.select_recommended(rows, dense_only)
        assert out.recommended == 0.5
        assert out.satisfied_hard_constraint is True

    def test_falls_back_to_max_recall_when_none_qualifies(self):
        dense_only = self._m(0.50, 0.30)
        rows = [
            (0.0, self._m(0.50, 0.30)),
            (0.1, self._m(0.45, 0.40)),
            (0.5, self._m(0.48, 0.35)),
        ]
        out = cal.select_recommended(rows, dense_only)
        assert out.recommended == 0.5           # recall 最大的候选
        assert out.satisfied_hard_constraint is False
        assert "无候选满足硬约束" in out.reason

    def test_excludes_sparse_zero_from_candidates(self):
        """``sparse=0`` 不是「混合」，不应被推荐为混合权重。"""
        dense_only = self._m(0.50, 0.30)
        rows = [(0.0, self._m(0.50, 0.99)), (0.5, self._m(0.45, 0.35))]
        out = cal.select_recommended(rows, dense_only)
        assert out.recommended == 0.5

    def test_reason_is_always_explicit(self):
        """判据必须显式可读 —— 不做隐式选择（T019）。"""
        out = cal.select_recommended(
            [(0.0, self._m(0.4, 0.3)), (0.5, self._m(0.45, 0.4))], self._m(0.4, 0.3)
        )
        assert out.reason
        assert "硬约束" in out.reason

    def test_no_candidates_at_all(self):
        out = cal.select_recommended([(0.0, self._m(0.4, 0.3))], self._m(0.4, 0.3))
        assert out.recommended is None


class TestSweepRange:
    def test_default_candidates_include_zero_and_equal_weight(self):
        """扫描范围必须含 0（纯语义对照）与 1.0（等权，即改造前行为）。"""
        assert 0.0 in cal.DEFAULT_SPARSE_CANDIDATES
        assert 1.0 in cal.DEFAULT_SPARSE_CANDIDATES

    def test_sweep_covers_all_candidates(self, cache):
        out = cal.sweep(cache, k=60, top_k=10)
        assert [w for w, _ in out.rows] == list(cal.DEFAULT_SPARSE_CANDIDATES)
