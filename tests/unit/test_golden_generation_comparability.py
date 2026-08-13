"""Unit tests for 两代金标的可区分性 (T-5.1) 与旧脚本收尾 (T-5.2)。

change: retriever-agnostic-golden-labels

**为什么这组测试重要**:两代金标的 ``expected_chunk_ids`` 构造方式不同 ——
第一代是纯 dense top-K 回填,新一代是多路池化 + LLM 判定。**分数不是同一把
尺子**,直接做减法会把「标注口径变了」误读成「检索质量变了」,而且方向完全
可能相反。报告必须能让人看出这一点。

设计取舍:跨代时 **delta 仍然输出**,只是标注为不可比。隐藏它会让人以为没算,
标注它才能让人知道别误读。

不触发任何 LLM / 检索调用。
"""

from __future__ import annotations

import inspect

import pytest

from src.observability.evaluation.eval_runner import (
    LABELING_METHOD_DENSE_TOP_K,
    EvalReport,
)

pytestmark = pytest.mark.unit


def _report(**kwargs: object) -> EvalReport:
    base = {
        "total_cases": 1,
        "hit_rate": 0.5,
        "mrr": 0.5,
        "source_hit_rate": 0.0,
        "aggregate_metrics": {"mrr": 0.5},
        "case_results": [],
    }
    base.update(kwargs)
    return EvalReport(**base)  # type: ignore[arg-type]


class TestLabelingMethodField:
    """报告要记录金标的标注方式。"""

    def test_first_generation_constant(self) -> None:
        """第一代金标文件没有 ``_labeling_method`` 字段,缺失即视为这一代。"""
        assert LABELING_METHOD_DENSE_TOP_K == "dense-top-k"

    def test_serialized_when_set(self) -> None:
        report = _report(labeling_method="pooled-llm-judged")

        assert report.to_dict()["labeling_method"] == "pooled-llm-judged"

    def test_omitted_when_empty(self) -> None:
        """空值不输出 —— 保持与既有报告 schema 的向后兼容。"""
        assert "labeling_method" not in _report().to_dict()


class TestDeltaComparability:
    """跨代 delta 必须被标注为不可比。"""

    def test_same_generation_is_comparable(self) -> None:
        report = _report(
            baseline_id="b1",
            labeling_method="pooled-llm-judged",
            delta_comparable=True,
        )

        assert report.to_dict()["delta_comparable"] is True

    def test_cross_generation_flagged(self) -> None:
        report = _report(
            baseline_id="b1",
            labeling_method="pooled-llm-judged",
            delta_comparable=False,
            delta_incomparable_reason="labeling method changed",
        )
        d = report.to_dict()

        assert d["delta_comparable"] is False
        assert "labeling method changed" in d["delta_incomparable_reason"]

    def test_deltas_still_emitted_when_incomparable(self) -> None:
        """**不可比时 delta 仍然输出**。

        隐藏它会让人以为没算;标注它才能让人知道别误读。
        """
        report = _report(
            baseline_id="b1",
            delta_hit_rate=-0.12,
            delta_mrr=-0.12,
            delta_aggregate_metrics={"mrr": -0.12},
            delta_comparable=False,
            delta_incomparable_reason="changed",
        )
        d = report.to_dict()

        assert d["delta_hit_rate"] == -0.12
        assert d["delta_aggregate_metrics"] == {"mrr": -0.12}
        assert d["delta_comparable"] is False

    def test_comparability_fields_absent_without_baseline(self) -> None:
        """没有基线时不输出这两个字段 —— 向后兼容。"""
        d = _report(delta_comparable=True).to_dict()

        assert "delta_comparable" not in d
        assert "delta_incomparable_reason" not in d

    def test_none_comparability_not_emitted(self) -> None:
        """未判定(None)与「已判定为可比」(True)必须可区分。"""
        d = _report(baseline_id="b1").to_dict()

        assert "delta_comparable" not in d


class TestCrossGenerationDetectionLogic:
    """``_attach_baseline_delta`` 里跨代判定的逻辑要点。"""

    def test_missing_baseline_method_defaults_to_first_generation(self) -> None:
        """基线报告没有 labeling_method → 视为第一代。

        既有基线全部是第一代产出的,它们的报告里没这个字段。若默认成
        「与当前相同」,跨代 delta 就永远不会被标注出来。
        """
        source = inspect.getsource(
            __import__(
                "src.observability.evaluation.eval_runner",
                fromlist=["EvalRunner"],
            ).EvalRunner._attach_baseline_delta
        )
        assert "LABELING_METHOD_DENSE_TOP_K" in source
        assert 'baseline_report_dict.get("labeling_method")' in source

    def test_reason_explains_the_measuring_stick(self) -> None:
        """理由要说清「变的是尺子不是被测量的东西」。"""
        source = inspect.getsource(
            __import__(
                "src.observability.evaluation.eval_runner",
                fromlist=["EvalRunner"],
            ).EvalRunner._attach_baseline_delta
        )
        assert "measuring stick" in source
        assert "Re-baseline" in source


class TestLegacyBackfillScript:
    """T-5.2:旧脚本必须标明代次,且死参数已修。"""

    def test_docstring_warns_and_points_to_replacement(self) -> None:
        import scripts.backfill_chunk_ids as legacy

        doc = legacy.__doc__ or ""
        assert "label_golden_chunks.py" in doc
        assert "dense-anchored" in doc

    def test_docstring_explains_why_it_is_kept(self) -> None:
        """保留理由要写清 —— 否则下一个人会想「这不是有问题吗,删了吧」。

        它是第一代金标的可复现来源,删了就无法重现历史基线是怎么来的。
        """
        import scripts.backfill_chunk_ids as legacy

        assert "可复现来源" in (legacy.__doc__ or "")

    def test_backfill_one_no_longer_takes_dead_collection_param(self) -> None:
        """死参数已移除 —— 它被接受但从不用于实际查询。

        用户以为 --collection 切换了检索范围,实际查的一直是配置里那个集合,
        而且不报错。与 Feature-004 修掉的 getattr(..., "bm25_index_path",
        default) 同类。
        """
        from scripts.backfill_chunk_ids import _backfill_one

        params = inspect.signature(_backfill_one).parameters
        assert "collection" not in params

    def test_collection_now_overrides_settings(self) -> None:
        """``--collection`` 现在真的生效:覆盖 collection_name 后再建 store。"""
        import scripts.backfill_chunk_ids as legacy

        source = inspect.getsource(legacy.main)
        override_idx = source.index("settings.vector_store.collection_name = args.collection")
        store_idx = source.index("VectorStoreFactory.create")
        assert override_idx < store_idx, (
            "覆盖必须在构造 vector_store 之前 —— 之后改就不生效了"
        )
