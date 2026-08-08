"""Unit tests for 抽样合规自检 (T023)。

测试范围:
- FR-006:抽样数 ``max(1, ceil(n × ratio))``,0 条时不抽样
- 合规率计算与 FR-007 门控判定(告警但不改退出码)
- **SC-006 拆分**:auto-kept 子集单独统计 —— 这是 analyze 阶段发现的设计
  缺口。抽样池是全部保留用例(与 SC-002 对齐),但 SC-006 问的是「机器
  自动保留的用例」的不合规率,不拆分就算不出来

见 specs/003-testset-refine-automation/data-model.md § 3。
"""

from __future__ import annotations

import math
import random
from typing import Any

import pytest

from src.observability.evaluation.testset_screener import (
    PROVENANCE_AUTO,
    PROVENANCE_HUMAN,
    compute_sample_size,
    pick_compliance_sample,
    summarize_compliance,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 抽样数 (FR-006)
# ---------------------------------------------------------------------------


class TestSampleSize:
    @pytest.mark.parametrize(
        "kept,ratio,expected",
        [
            (20, 0.10, 2),
            (10, 0.10, 1),
            (47, 0.10, 5),   # ceil(4.7)
            (3, 0.10, 1),    # 不足 1 条时仍抽 1(FR-006)
            (1, 0.10, 1),
            (100, 0.10, 10),
            (20, 0.25, 5),
        ],
    )
    def test_sample_size(self, kept: int, ratio: float, expected: int) -> None:
        assert compute_sample_size(kept, ratio) == expected

    def test_zero_kept_means_no_sampling(self) -> None:
        """0 条保留用例时不抽样 —— 不能硬凑出 1 条来(会越界)。"""
        assert compute_sample_size(0, 0.10) == 0

    def test_sample_size_never_exceeds_population(self) -> None:
        assert compute_sample_size(2, 0.90) == 2

    @pytest.mark.parametrize("kept", [1, 3, 7, 10, 47, 100])
    def test_sample_size_is_at_least_ceil_of_ratio(self, kept: int) -> None:
        size = compute_sample_size(kept, 0.10)
        assert size >= math.ceil(kept * 0.10)
        assert size <= kept


class TestPickSample:
    def test_picks_requested_count_without_duplicates(self) -> None:
        picked = pick_compliance_sample(20, 0.10, rng=random.Random(1))
        assert len(picked) == 2
        assert len(set(picked)) == 2

    def test_indices_are_within_range(self) -> None:
        picked = pick_compliance_sample(10, 0.30, rng=random.Random(7))
        assert all(0 <= i < 10 for i in picked)

    def test_returns_sorted_indices(self) -> None:
        """排序后返回,便于人工按顺序复核。"""
        picked = pick_compliance_sample(50, 0.20, rng=random.Random(3))
        assert picked == sorted(picked)

    def test_empty_population_returns_empty(self) -> None:
        assert pick_compliance_sample(0, 0.10) == []

    def test_not_seeded_by_default_varies(self) -> None:
        """默认不固定 seed(research § D7):可复核靠记录抽中结果,而非固定种子。

        固定 seed 会让重复运行永远抽到同一批,削弱抽样的覆盖意义。
        """
        runs = {tuple(pick_compliance_sample(100, 0.10)) for _ in range(12)}
        assert len(runs) > 1, "多次抽样结果不应完全相同"


# ---------------------------------------------------------------------------
# 合规率与门控 (FR-006, FR-007)
# ---------------------------------------------------------------------------


class TestSummarizeCompliance:
    def test_all_compliant(self) -> None:
        result = summarize_compliance(
            sampled_indices=[0, 1],
            compliant_flags=[True, True],
            kept_provenance=[PROVENANCE_AUTO, PROVENANCE_AUTO],
            compliance_gate=0.90,
        )
        assert result["sample_size"] == 2
        assert result["compliant"] == 2
        assert result["compliance_rate"] == 1.0
        assert result["gate_passed"] is True

    def test_below_gate_fails(self) -> None:
        result = summarize_compliance(
            sampled_indices=[0, 1],
            compliant_flags=[True, False],
            kept_provenance=[PROVENANCE_AUTO, PROVENANCE_AUTO],
            compliance_gate=0.90,
        )
        assert result["compliance_rate"] == 0.5
        assert result["gate_passed"] is False

    def test_exactly_at_gate_passes(self) -> None:
        """恰好等于门控值算通过(区间为 >=)。"""
        result = summarize_compliance(
            sampled_indices=list(range(10)),
            compliant_flags=[True] * 9 + [False],
            kept_provenance=[PROVENANCE_AUTO] * 10,
            compliance_gate=0.90,
        )
        assert result["compliance_rate"] == 0.9
        assert result["gate_passed"] is True

    def test_empty_sample_has_null_rate(self) -> None:
        """0 条抽样 → 合规率为 None,而不是 0.0(0.0 会被误读为「全不合规」)。"""
        result = summarize_compliance(
            sampled_indices=[],
            compliant_flags=[],
            kept_provenance=[],
            compliance_gate=0.90,
        )
        assert result["sample_size"] == 0
        assert result["compliance_rate"] is None
        assert result["gate_passed"] is True, "没抽样就不该判定为不达标"

    def test_records_sampled_indices(self) -> None:
        """记录实际抽中的序号 —— 这是不固定 seed 时的可复核手段。"""
        result = summarize_compliance(
            sampled_indices=[3, 7],
            compliant_flags=[True, True],
            kept_provenance=[PROVENANCE_AUTO] * 10,
            compliance_gate=0.90,
        )
        assert result["sampled_case_indices"] == [3, 7]

    def test_mismatched_flag_count_raises(self) -> None:
        """标记数与抽样数对不上说明调用方出错,快速失败(宪法 § III)。"""
        with pytest.raises(ValueError):
            summarize_compliance(
                sampled_indices=[0, 1],
                compliant_flags=[True],
                kept_provenance=[PROVENANCE_AUTO, PROVENANCE_AUTO],
                compliance_gate=0.90,
            )


# ---------------------------------------------------------------------------
# SC-006 拆分 —— analyze 阶段发现的设计缺口
# ---------------------------------------------------------------------------


class TestAutoKeptSplit:
    def test_split_counts_only_auto_kept_subset(self) -> None:
        """抽中 auto 与 human 混合时,拆分字段只统计 auto 子集。

        抽样池是全部保留用例(与 SC-002 对齐),但 SC-006 问的是机器自动
        保留部分的不合规率。不拆分的话两个口径混在一起,SC-006 算不出来。
        """
        # kept 顺序:auto, human, auto, human
        provenance = [PROVENANCE_AUTO, PROVENANCE_HUMAN, PROVENANCE_AUTO, PROVENANCE_HUMAN]
        result = summarize_compliance(
            sampled_indices=[0, 1, 2, 3],
            compliant_flags=[True, False, False, True],
            kept_provenance=provenance,
            compliance_gate=0.90,
        )
        # 全量口径:2/4
        assert result["compliance_rate"] == 0.5
        # auto 子集:索引 0(合规)与 2(不合规)→ 1/2 合规
        assert result["auto_kept_sampled"] == 2
        assert result["auto_kept_compliant"] == 1
        assert result["auto_kept_noncompliance_rate"] == 0.5

    def test_all_auto_kept_compliant_gives_zero_noncompliance(self) -> None:
        result = summarize_compliance(
            sampled_indices=[0, 1],
            compliant_flags=[True, True],
            kept_provenance=[PROVENANCE_AUTO, PROVENANCE_AUTO],
            compliance_gate=0.90,
        )
        assert result["auto_kept_noncompliance_rate"] == 0.0

    def test_no_auto_kept_in_sample_gives_null_rate(self) -> None:
        """抽中的全是人工确认过的 → auto 子集为空 → 该率为 None 而非 0。"""
        result = summarize_compliance(
            sampled_indices=[0, 1],
            compliant_flags=[True, False],
            kept_provenance=[PROVENANCE_HUMAN, PROVENANCE_HUMAN],
            compliance_gate=0.90,
        )
        assert result["auto_kept_sampled"] == 0
        assert result["auto_kept_noncompliance_rate"] is None

    def test_sc006_threshold_is_computable(self) -> None:
        """SC-006 要求 ≤ 10%,本字段必须能直接拿来判定。"""
        provenance = [PROVENANCE_AUTO] * 10
        result = summarize_compliance(
            sampled_indices=list(range(10)),
            compliant_flags=[True] * 9 + [False],
            kept_provenance=provenance,
            compliance_gate=0.90,
        )
        assert result["auto_kept_noncompliance_rate"] == pytest.approx(0.1)
        assert result["auto_kept_noncompliance_rate"] <= 0.10

    def test_provenance_shorter_than_indices_raises(self) -> None:
        """抽样序号越出 provenance 范围说明两者不同源,快速失败。"""
        with pytest.raises(ValueError):
            summarize_compliance(
                sampled_indices=[0, 5],
                compliant_flags=[True, True],
                kept_provenance=[PROVENANCE_AUTO, PROVENANCE_AUTO],
                compliance_gate=0.90,
            )

    def test_result_is_json_serializable(self) -> None:
        import json

        result = summarize_compliance(
            sampled_indices=[0],
            compliant_flags=[True],
            kept_provenance=[PROVENANCE_AUTO],
            compliance_gate=0.90,
        )
        json.dumps(result, ensure_ascii=False)
