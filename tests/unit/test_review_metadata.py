"""Unit tests for _review_metadata 审计记录 (T019)。

测试范围:
- FR-005:10 个审计字段齐全,数字与实际运行一致
- 不变式:``auto_decided + human_reviewed == 输入用例总数``(非 partial 时)
- SC-005:仅凭金标文件即可回答「多少条机器决定 / 哪个模型 / 阈值多少 / 合规率」
- **FR-004 硬约束**:``_refine_summary`` 四键与 ``_schema_version == 1`` 不得变动

见 specs/003-testset-refine-automation/data-model.md § 3。
"""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from typing import Any

import pytest

from src.core.settings import (
    EmbeddingSettings,
    EvaluationSettings,
    JudgeLLMSettings,
    LLMSettings,
    ScreeningLLMSettings,
    Settings,
    VectorStoreSettings,
    VisionLLMSettings,
)
from src.observability.evaluation.testset_screener import (
    ScreeningDecision,
    ScreeningResult,
    ScreeningVerdict,
    build_review_metadata,
)

pytestmark = pytest.mark.unit

_spec = importlib.util.spec_from_file_location(
    "refine_testset_meta_module",
    Path(__file__).parent.parent.parent / "scripts" / "refine_testset.py",
)
refine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(refine)

SYNTHESIS_ID = "glm:minimax/minimax-m2.7"
SCREENING_ID = "glm:glm-4.6"

# data-model.md § 3 规定的 10 个字段
REQUIRED_FIELDS = {
    "auto_decided",
    "human_reviewed",
    "dropped",
    "screening_llm_identifier",
    "synthesis_llm_identifier",
    "thresholds_snapshot",
    "borderline_ratio",
    "compliance",
    "partial",
    "warnings",
}


def _settings() -> Settings:
    evaluation = EvaluationSettings()
    evaluation.judge_llm = JudgeLLMSettings(provider="glm", model="minimax/minimax-m2.7")
    evaluation.screening_llm = ScreeningLLMSettings(provider="glm", model="glm-4.6")
    return Settings(
        llm=LLMSettings(provider="glm", model="glm-4"),
        embedding=EmbeddingSettings(provider="openai", model="text-embedding-3-small"),
        vision_llm=VisionLLMSettings(provider="azure", model="gpt-4o"),
        vector_store=VectorStoreSettings(backend="chroma"),
        evaluation=evaluation,
    )


def _candidate(n: int = 3) -> dict[str, Any]:
    return {
        "_schema_version": 1,
        "language": "zh",
        "_synthesis_metadata": {"judge_llm_identifier": SYNTHESIS_ID},
        "test_cases": [
            {
                "query": f"q{i}",
                "ground_truth": f"a{i}",
                "expected_chunk_ids": [f"c{i}"],
                "_synth_contexts": ["ctx"],
                "tags": {},
            }
            for i in range(n)
        ],
    }


def _screening(decisions: list[ScreeningDecision]) -> ScreeningResult:
    return ScreeningResult(
        verdicts=[
            ScreeningVerdict(i, d, 0.0 if d is ScreeningDecision.BORDERLINE else 0.95)
            for i, d in enumerate(decisions)
        ]
    )


class TestReviewMetadataFields:
    def test_all_required_fields_present(self) -> None:
        meta = build_review_metadata(
            settings=_settings(),
            candidate=_candidate(3),
            screening=_screening(
                [ScreeningDecision.KEEP, ScreeningDecision.DROP, ScreeningDecision.BORDERLINE]
            ),
            auto_decided=2,
            human_reviewed=1,
            dropped=1,
        )
        assert REQUIRED_FIELDS <= set(meta), f"缺字段: {REQUIRED_FIELDS - set(meta)}"

    def test_counts_reflect_actual_run(self) -> None:
        meta = build_review_metadata(
            settings=_settings(),
            candidate=_candidate(5),
            screening=_screening([ScreeningDecision.KEEP] * 5),
            auto_decided=4,
            human_reviewed=1,
            dropped=2,
        )
        assert meta["auto_decided"] == 4
        assert meta["human_reviewed"] == 1
        assert meta["dropped"] == 2

    def test_invariant_auto_plus_human_equals_total(self) -> None:
        """非 partial 时两路计数之和必须等于输入用例总数。"""
        meta = build_review_metadata(
            settings=_settings(),
            candidate=_candidate(5),
            screening=_screening([ScreeningDecision.KEEP] * 5),
            auto_decided=3,
            human_reviewed=2,
            dropped=0,
            partial=False,
        )
        assert meta["auto_decided"] + meta["human_reviewed"] == 5

    def test_both_identifiers_recorded(self) -> None:
        """两端标识都要落盘,一眼能看出异源关系(FR-002 审计)。"""
        meta = build_review_metadata(
            settings=_settings(),
            candidate=_candidate(1),
            screening=_screening([ScreeningDecision.KEEP]),
            auto_decided=1,
            human_reviewed=0,
            dropped=0,
        )
        assert meta["screening_llm_identifier"] == SCREENING_ID
        assert meta["synthesis_llm_identifier"] == SYNTHESIS_ID
        assert meta["screening_llm_identifier"] != meta["synthesis_llm_identifier"]

    def test_thresholds_snapshot_is_complete(self) -> None:
        """阈值快照让历史金标在换模型后仍可追溯当时的判定条件(FR-005)。"""
        meta = build_review_metadata(
            settings=_settings(),
            candidate=_candidate(1),
            screening=_screening([ScreeningDecision.KEEP]),
            auto_decided=1,
            human_reviewed=0,
            dropped=0,
        )
        snapshot = meta["thresholds_snapshot"]
        assert set(snapshot) == {
            "keep_threshold",
            "drop_threshold",
            "borderline_ratio_warn",
            "sample_ratio",
            "compliance_gate",
        }
        assert snapshot["keep_threshold"] == 0.80

    def test_borderline_ratio_matches_screening(self) -> None:
        meta = build_review_metadata(
            settings=_settings(),
            candidate=_candidate(4),
            screening=_screening(
                [
                    ScreeningDecision.KEEP,
                    ScreeningDecision.KEEP,
                    ScreeningDecision.KEEP,
                    ScreeningDecision.BORDERLINE,
                ]
            ),
            auto_decided=3,
            human_reviewed=1,
            dropped=0,
        )
        assert meta["borderline_ratio"] == 0.25

    def test_compliance_defaults_to_none(self) -> None:
        """US3 未接入时 compliance 为 null,而不是缺字段或空 dict。"""
        meta = build_review_metadata(
            settings=_settings(),
            candidate=_candidate(1),
            screening=_screening([ScreeningDecision.KEEP]),
            auto_decided=1,
            human_reviewed=0,
            dropped=0,
        )
        assert meta["compliance"] is None

    def test_partial_flag_and_warnings_passthrough(self) -> None:
        meta = build_review_metadata(
            settings=_settings(),
            candidate=_candidate(3),
            screening=_screening([ScreeningDecision.KEEP] * 3),
            auto_decided=1,
            human_reviewed=0,
            dropped=0,
            warnings=["borderline ratio too high"],
            partial=True,
        )
        assert meta["partial"] is True
        assert meta["warnings"] == ["borderline ratio too high"]

    def test_metadata_is_json_serializable(self) -> None:
        """审计记录要随金标落盘,必须能 json.dumps。"""
        meta = build_review_metadata(
            settings=_settings(),
            candidate=_candidate(2),
            screening=_screening([ScreeningDecision.KEEP, ScreeningDecision.BORDERLINE]),
            auto_decided=1,
            human_reviewed=1,
            dropped=0,
        )
        json.dumps(meta, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 与 _build_final 的集成 + FR-004 硬约束
# ---------------------------------------------------------------------------


class TestBuildFinalInjection:
    def test_review_metadata_injected_when_provided(self) -> None:
        final = refine._build_final(
            _candidate(2),
            kept_cases=[],
            counts={"keep": 0, "edit": 0, "drop": 0, "skip": 0},
            partial=False,
            review_metadata={"auto_decided": 1},
        )
        assert final["_review_metadata"] == {"auto_decided": 1}

    def test_absent_when_not_provided(self) -> None:
        """默认交互模式不得写出该字段(FR-004)。"""
        final = refine._build_final(
            _candidate(2),
            kept_cases=[],
            counts={"keep": 0, "edit": 0, "drop": 0, "skip": 0},
            partial=False,
        )
        assert "_review_metadata" not in final

    def test_refine_summary_keys_unchanged(self) -> None:
        """**FR-004 硬约束**:四个计数键的名称与语义不可变。"""
        final = refine._build_final(
            _candidate(2),
            kept_cases=[],
            counts={"keep": 1, "edit": 2, "drop": 3, "skip": 4},
            partial=False,
            review_metadata={"auto_decided": 1},
        )
        assert set(final["_refine_summary"]) == {"keep", "edit", "drop", "skip"}
        assert final["_refine_summary"]["keep"] == 1
        assert final["_refine_summary"]["edit"] == 2
        assert final["_refine_summary"]["drop"] == 3
        assert final["_refine_summary"]["skip"] == 4

    def test_schema_version_stays_1_even_with_metadata(self) -> None:
        """**FR-004 硬约束**:新增字段不得触发 schema 升版。"""
        final = refine._build_final(
            _candidate(2),
            kept_cases=[],
            counts={"keep": 0, "edit": 0, "drop": 0, "skip": 0},
            partial=False,
            review_metadata={"auto_decided": 1},
        )
        assert final["_schema_version"] == 1

    def test_partial_marks_version_and_metadata_consistently(self) -> None:
        """中断产生的部分结果:version 与审计字段要一致标注,避免误当完整金标。"""
        meta = build_review_metadata(
            settings=_settings(),
            candidate=_candidate(3),
            screening=_screening([ScreeningDecision.KEEP] * 3),
            auto_decided=1,
            human_reviewed=0,
            dropped=0,
            partial=True,
        )
        final = refine._build_final(
            _candidate(3),
            kept_cases=[],
            counts={"keep": 0, "edit": 0, "drop": 0, "skip": 0},
            partial=True,
            review_metadata=meta,
        )
        assert final["version"] == "v0.9-partial"
        assert final["_review_metadata"]["partial"] is True


# ---------------------------------------------------------------------------
# 端到端:auto 模式产出的金标自带审计记录 (SC-005)
# ---------------------------------------------------------------------------


class _StubScreener:
    def __init__(self, decisions: list[ScreeningDecision]) -> None:
        self._decisions = decisions

    def screen_all(self, candidate: dict[str, Any]) -> ScreeningResult:
        return _screening(self._decisions)


def test_auto_mode_output_carries_review_metadata() -> None:
    """SC-005:仅凭金标文件即可回答四个问题。"""
    outcome = refine.auto_refine(
        _candidate(3),
        _settings(),
        screener=_StubScreener(
            [ScreeningDecision.KEEP, ScreeningDecision.BORDERLINE, ScreeningDecision.DROP]
        ),
        # 先 y 处置 borderline,再 y 回答抽样自检
        input_stream=io.StringIO("y\ny\n"),
    )
    meta = outcome.final["_review_metadata"]

    assert REQUIRED_FIELDS <= set(meta)
    # 多少条机器决定
    assert meta["auto_decided"] == 2
    assert meta["human_reviewed"] == 1
    # 用的哪个预筛模型
    assert meta["screening_llm_identifier"] == SCREENING_ID
    # 当时阈值多少
    assert meta["thresholds_snapshot"]["keep_threshold"] == 0.80
    # 抽样合规率(US3 接入后有值)
    assert meta["compliance"] is not None
    assert meta["compliance"]["compliance_rate"] == 1.0
    # 不变式:抽样复核数不计入 human_reviewed,故两路之和仍等于输入总数
    assert meta["auto_decided"] + meta["human_reviewed"] == 3


def test_skip_compliance_sample_leaves_null_and_warns() -> None:
    """--skip-compliance-sample:compliance 为 null,且必须留下告警。

    跳过质量门控是有代价的决定,不能悄无声息 —— 否则后来人看到
    compliance=null 会以为是「没抽到」而不是「主动跳过」。
    """
    outcome = refine.auto_refine(
        _candidate(2),
        _settings(),
        screener=_StubScreener([ScreeningDecision.KEEP, ScreeningDecision.KEEP]),
        input_stream=io.StringIO(""),
        skip_compliance_sample=True,
    )
    meta = outcome.final["_review_metadata"]
    assert meta["compliance"] is None
    assert any("skipped" in w for w in meta["warnings"])


def test_partial_run_skips_compliance_with_reason() -> None:
    """中断产生的部分结果不做抽样 —— 对半成品算合规率没有意义。"""
    outcome = refine.auto_refine(
        _candidate(3),
        _settings(),
        screener=_StubScreener(
            [ScreeningDecision.BORDERLINE, ScreeningDecision.KEEP, ScreeningDecision.KEEP]
        ),
        input_stream=io.StringIO("q\n"),
    )
    meta = outcome.final["_review_metadata"]
    assert meta["partial"] is True
    assert meta["compliance"] is None
    assert any("partial result" in w for w in meta["warnings"])


def test_auto_mode_dropped_count_includes_both_paths() -> None:
    """dropped 要含机器丢弃 + 人工丢弃两路。"""
    outcome = refine.auto_refine(
        _candidate(3),
        _settings(),
        screener=_StubScreener(
            [ScreeningDecision.DROP, ScreeningDecision.BORDERLINE, ScreeningDecision.KEEP]
        ),
        input_stream=io.StringIO("d\n"),
        skip_compliance_sample=True,
    )
    assert outcome.final["_review_metadata"]["dropped"] == 2


def test_compliance_split_reaches_metadata() -> None:
    """SC-006 的 auto-kept 拆分必须一路传到金标里,否则指标仍不可计算。"""
    outcome = refine.auto_refine(
        _candidate(2),
        _settings(),
        screener=_StubScreener([ScreeningDecision.KEEP, ScreeningDecision.KEEP]),
        input_stream=io.StringIO("y\n"),
    )
    compliance = outcome.final["_review_metadata"]["compliance"]
    assert compliance["auto_kept_sampled"] == 1
    assert compliance["auto_kept_noncompliance_rate"] == 0.0
