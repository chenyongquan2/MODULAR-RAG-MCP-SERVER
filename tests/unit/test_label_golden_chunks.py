"""Unit tests for `scripts/label_golden_chunks.py`。

change: retriever-agnostic-golden-labels (T-4.1 / T-4.2 / T-4.3)

测试范围:

1. 前置检查:``labeling_llm`` 未配置 / 同源 / 无法确认异源 的三种拒绝
   —— 以及**同源不可被 `--allow-same-source` 豁免**
2. 续跑:从已有产出读回已判定候选
3. 人工抽检:分层抽样(相关与不相关各半)、一致率计算
4. 不得原地覆盖输入文件

**为什么「同源不可豁免」要单独测**:`--allow-same-source` 的语义边界很容易被
后来人误解成「万能开关」。它只豁免「无法确认」,不豁免「已确认同源」——
一个模型给自己写的答案打相关性分,拿不到独立判断。

不触发任何 LLM 调用。
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.core.settings import (
    EvaluationSettings,
    JudgeLLMSettings,
    LabelingLLMSettings,
    LabelingSettings,
)
from src.observability.evaluation.chunk_labeler import ChunkVerdict

from scripts.label_golden_chunks import (  # noqa: E402
    GOLDEN_VERSION_V2,
    LABELING_METHOD,
    _default_output,
    check_preconditions,
    compute_agreement,
    export_sample,
    load_prior_verdicts,
)

pytestmark = pytest.mark.unit


class _FakeSettings:
    def __init__(
        self,
        labeling_provider: str = "glm",
        labeling_model: str = "glm-4.6",
        judge_model: str = "minimax/minimax-m2.7",
    ) -> None:
        self.evaluation = EvaluationSettings()
        self.evaluation.labeling = LabelingSettings()
        self.evaluation.labeling_llm = LabelingLLMSettings(
            provider=labeling_provider, model=labeling_model
        )
        self.evaluation.judge_llm = JudgeLLMSettings(provider="glm", model=judge_model)


def _golden(synthesis_id: str = "glm:minimax/minimax-m2.7") -> Dict[str, Any]:
    return {
        "_synthesis_metadata": {"judge_llm_identifier": synthesis_id},
        "test_cases": [{"query": "q", "ground_truth": "gt", "expected_chunk_ids": []}],
    }


# ── 前置检查 (T-3.2 的 CLI 侧) ───────────────────────────────────────────


class TestPreconditions:
    def test_unconfigured_labeling_llm_rejected(self) -> None:
        s = _FakeSettings(labeling_provider="", labeling_model="")

        problem = check_preconditions(s, _golden(), allow_same_source=False)

        assert problem is not None
        assert "labeling_llm" in problem

    def test_error_explains_why_divergence_matters(self) -> None:
        s = _FakeSettings(labeling_provider="", labeling_model="")

        problem = check_preconditions(s, _golden(), allow_same_source=False)

        assert problem is not None
        assert "wrote itself" in problem

    def test_same_source_rejected(self) -> None:
        s = _FakeSettings(labeling_model="minimax/minimax-m2.7")

        problem = check_preconditions(s, _golden(), allow_same_source=False)

        assert problem is not None
        assert "same model" in problem

    def test_same_source_NOT_waivable(self) -> None:
        """``--allow-same-source`` 只豁免「无法确认」,不豁免「已确认同源」。

        这条边界很容易被后来人误解成万能开关。一个模型给自己写的答案打相关性
        分,拿不到独立判断 —— 那是本变更要修的偏差换了个形式回来。
        """
        s = _FakeSettings(labeling_model="minimax/minimax-m2.7")

        problem = check_preconditions(s, _golden(), allow_same_source=True)

        assert problem is not None
        assert "NOT waivable" in problem

    def test_divergent_passes(self) -> None:
        s = _FakeSettings(labeling_model="glm-4.6")

        assert check_preconditions(s, _golden(), allow_same_source=False) is None

    def test_unverifiable_rejected_by_default(self) -> None:
        s = _FakeSettings()
        golden = {"test_cases": []}  # 没有任何合成端标识

        problem = check_preconditions(s, golden, allow_same_source=False)

        assert problem is not None
        assert "cannot verify" in problem

    def test_unverifiable_waivable(self) -> None:
        s = _FakeSettings()
        golden = {"test_cases": []}

        assert check_preconditions(s, golden, allow_same_source=True) is None


# ── 续跑 (T-4.2) ─────────────────────────────────────────────────────────


class TestResume:
    def test_no_prior_output_returns_empty(self, tmp_path: Path) -> None:
        assert load_prior_verdicts(tmp_path / "nope.json") == {}

    def test_reads_back_judged_candidates(self, tmp_path: Path) -> None:
        out = tmp_path / "v2.json"
        out.write_text(
            json.dumps(
                {
                    "test_cases": [
                        {
                            "query": "q1",
                            "_chunk_labels": [
                                {"chunk_id": "a", "grade": 3, "reason": "yes"},
                                {"chunk_id": "b", "grade": 0, "reason": "no"},
                            ],
                        },
                        {"query": "q2", "_chunk_labels": [{"chunk_id": "c", "grade": 2}]},
                    ]
                }
            ),
            encoding="utf-8",
        )

        prior = load_prior_verdicts(out)

        assert set(prior.keys()) == {"q1", "q2"}
        assert prior["q1"]["a"].grade == 3
        assert prior["q1"]["a"].reason == "yes"
        assert prior["q2"]["c"].grade == 2

    def test_judge_failed_is_NOT_cached_so_resume_retries_it(
        self, tmp_path: Path
    ) -> None:
        """判定失败的候选**不缓存**,让续跑重试它。

        「解析失败」不是持久结论,而是一次瞬时故障(输出被截断、模型偶发不遵从
        格式)。若当已完成缓存起来,一次抖动就永久污染那条标签,且越续跑越固化。
        英文那轮 625 次判定里有 62 条(9.9%)失败 —— 全缓存等于放弃这 9.9%。
        """
        out = tmp_path / "v2.json"
        out.write_text(
            json.dumps(
                {
                    "test_cases": [
                        {
                            "query": "q1",
                            "_chunk_labels": [
                                {"chunk_id": "ok", "grade": 3, "reason": "yes"},
                                {"chunk_id": "bad", "grade": None, "judge_failed": True},
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        prior = load_prior_verdicts(out)

        assert "ok" in prior["q1"], "成功的判定必须缓存,否则续跑白花钱"
        assert "bad" not in prior["q1"], "失败的判定不该缓存,续跑要重试它"

    def test_case_with_only_failures_is_not_treated_as_done(
        self, tmp_path: Path
    ) -> None:
        """整条 case 全部判定失败时,不该被当成「已完成」跳过。"""
        out = tmp_path / "v2.json"
        out.write_text(
            json.dumps(
                {
                    "test_cases": [
                        {
                            "query": "q1",
                            "_chunk_labels": [
                                {"chunk_id": "a", "grade": None, "judge_failed": True},
                                {"chunk_id": "b", "grade": None, "judge_failed": True},
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        assert load_prior_verdicts(out) == {}

    def test_corrupt_prior_output_does_not_crash(self, tmp_path: Path) -> None:
        out = tmp_path / "v2.json"
        out.write_text("{ not json", encoding="utf-8")

        assert load_prior_verdicts(out) == {}

    def test_entries_without_chunk_id_skipped(self, tmp_path: Path) -> None:
        out = tmp_path / "v2.json"
        out.write_text(
            json.dumps({"test_cases": [{"query": "q1", "_chunk_labels": [{"grade": 3}]}]}),
            encoding="utf-8",
        )

        assert load_prior_verdicts(out) == {}


# ── 人工抽检 (T-4.3) ─────────────────────────────────────────────────────


def _labelled_golden(n_accepted: int, n_rejected: int) -> Dict[str, Any]:
    labels: List[Dict[str, Any]] = []
    accepted: List[str] = []
    for i in range(n_accepted):
        cid = f"acc{i}"
        accepted.append(cid)
        labels.append(
            {"chunk_id": cid, "grade": 3, "reason": "r", "chunk_text": "t"}
        )
    for i in range(n_rejected):
        labels.append(
            {"chunk_id": f"rej{i}", "grade": 0, "reason": "r", "chunk_text": "t"}
        )
    return {
        "test_cases": [
            {"query": "q", "expected_chunk_ids": accepted, "_chunk_labels": labels}
        ]
    }


class TestResumeKeyedByQuery:
    """续跑缓存必须按 query 做键,不能按位置索引。

    无解的 case 会被移出产出的 test_cases(否则 evaluate.py 的非空校验会阻断
    整轮评估),于是产出与输入条数不再一致 —— 按索引匹配会把缓存判定套到
    **错误的 case** 上,而且不会有任何报错,只是标签悄悄错位。
    """

    def test_dropped_case_does_not_shift_others(self, tmp_path: Path) -> None:
        out = tmp_path / "v2.json"
        out.write_text(
            json.dumps(
                {
                    # 产出里只剩 2 条（第 2 条无解被移出），输入原本 3 条
                    "test_cases": [
                        {"query": "qA", "_chunk_labels": [{"chunk_id": "a", "grade": 3}]},
                        {"query": "qC", "_chunk_labels": [{"chunk_id": "c", "grade": 3}]},
                    ],
                    "_labeling_metadata": {
                        "unanswerable_cases": [
                            {
                                "query": "qB",
                                "_chunk_labels": [{"chunk_id": "b", "grade": 1}],
                            }
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )

        prior = load_prior_verdicts(out)

        assert prior["qA"]["a"].grade == 3
        assert prior["qC"]["c"].grade == 3
        # 无解 case 的判定也要读回，否则每次续跑都重判它
        assert prior["qB"]["b"].grade == 1

    def test_case_without_query_skipped(self, tmp_path: Path) -> None:
        out = tmp_path / "v2.json"
        out.write_text(
            json.dumps({"test_cases": [{"_chunk_labels": [{"chunk_id": "x", "grade": 3}]}]}),
            encoding="utf-8",
        )

        assert load_prior_verdicts(out) == {}


class TestExportSample:
    def test_stratified_across_accepted_and_rejected(self) -> None:
        """**必须覆盖两类** —— 只抽通过的无法发现「判定过于宽松」。

        而过于宽松正是最可能的失效方向:LLM 倾向于说「有关」。
        """
        golden = _labelled_golden(n_accepted=20, n_rejected=20)

        sample = export_sample(golden, 10, seed=42)

        assert len(sample) == 10
        assert any(r["llm_accepted"] for r in sample)
        assert any(not r["llm_accepted"] for r in sample)

    def test_human_label_left_blank(self) -> None:
        golden = _labelled_golden(5, 5)

        sample = export_sample(golden, 4, seed=1)

        assert all(r["human_label"] is None for r in sample)

    def test_carries_context_for_review(self) -> None:
        """人工要能只看这个文件就做判断 —— query / 正文 / LLM 理由都要带。"""
        golden = _labelled_golden(2, 2)

        record = export_sample(golden, 1, seed=1)[0]

        assert "query" in record
        assert "chunk_text" in record
        assert "llm_reason" in record
        assert "llm_grade" in record

    def test_seed_makes_sampling_reproducible(self) -> None:
        golden = _labelled_golden(10, 10)

        a = [r["chunk_id"] for r in export_sample(golden, 6, seed=7)]
        b = [r["chunk_id"] for r in export_sample(golden, 6, seed=7)]

        assert a == b

    def test_backfills_from_other_stratum_when_short(self) -> None:
        """某一层不够时从另一层补足,不返回少于请求数。"""
        golden = _labelled_golden(n_accepted=1, n_rejected=20)

        sample = export_sample(golden, 10, seed=3)

        assert len(sample) == 10

    def test_no_labels_yields_empty(self) -> None:
        assert export_sample({"test_cases": []}, 10) == []


class TestComputeAgreement:
    def test_perfect_agreement(self) -> None:
        sample = [
            {"llm_accepted": True, "human_label": True},
            {"llm_accepted": False, "human_label": False},
        ]

        rate, reviewed, agree = compute_agreement(sample)

        assert rate == 1.0
        assert (reviewed, agree) == (2, 2)

    def test_total_disagreement(self) -> None:
        sample = [
            {"llm_accepted": True, "human_label": False},
            {"llm_accepted": False, "human_label": True},
        ]

        rate, reviewed, agree = compute_agreement(sample)

        assert rate == 0.0
        assert (reviewed, agree) == (2, 0)

    def test_unfilled_entries_excluded_not_counted_as_disagreement(self) -> None:
        """没填的不算「不一致」—— 否则一致率会因为人偷懒而虚低。"""
        sample = [
            {"llm_accepted": True, "human_label": True},
            {"llm_accepted": True, "human_label": None},
            {"llm_accepted": False},
        ]

        rate, reviewed, agree = compute_agreement(sample)

        assert reviewed == 1
        assert rate == 1.0

    def test_nothing_reviewed_returns_zero(self) -> None:
        rate, reviewed, agree = compute_agreement(
            [{"llm_accepted": True, "human_label": None}]
        )

        assert (rate, reviewed, agree) == (0.0, 0, 0)

    def test_partial_agreement(self) -> None:
        sample = [
            {"llm_accepted": True, "human_label": True},
            {"llm_accepted": True, "human_label": True},
            {"llm_accepted": True, "human_label": False},
            {"llm_accepted": False, "human_label": False},
        ]

        rate, reviewed, agree = compute_agreement(sample)

        assert reviewed == 4
        assert agree == 3
        assert rate == 0.75


# ── 产出约定 ─────────────────────────────────────────────────────────────


class TestPartialResultsSurviveModelOutage:
    """**这组是一次真实事故的回归测试**(2026-08-13)。

    英文标注跑到第 20 个 case 时网关挂掉(Connection error),脚本按设计抛
    LabelingUnavailableError 并以退出码 3 拒绝产出空金标 —— 那部分是对的。
    但当时的 `except` 分支**直接 return,没写出已完成的部分**,于是前 19 个
    case 约 630 次判定、2.5 小时的工作全部丢失。而续跑恰恰依赖产出文件存在:
    「模型不可用」这条快速失败路径把 spec 要求的「可续跑」直接架空了。

    快速失败要防的是「产出一份全是不相关的空金标」,不是「丢掉已经算好的
    结果」—— 两者不冲突。

    当时的单测只验了「异常被抛出」,没验 CLI 在那条路径上的写盘行为:
    测了库,没测集成。本组补这个缺口。
    """

    def test_model_unavailable_path_writes_before_exiting(self) -> None:
        """`except LabelingUnavailableError` 不得直接 return。"""
        import scripts.label_golden_chunks as cli

        source = inspect.getsource(cli.main)
        handler_start = source.index("except LabelingUnavailableError")
        handler_end = source.index("except KeyboardInterrupt")
        handler = source[handler_start:handler_end]

        # 只看真正的 return **语句**（行首缩进后紧跟 return），不看注释里
        # 提到的 "return" 这个词 —— 那段注释正是在解释为什么不能 return。
        return_statements = [
            line for line in handler.splitlines()
            if line.strip().startswith("return")
        ]
        assert not return_statements, (
            f"模型不可用时直接 return 会丢掉已完成的判定（实测丢了 2.5 小时的"
            f"工作）—— 必须落到统一的写出路径，再按退出码优先级返回 3。"
            f"发现的 return 语句: {return_statements}"
        )
        assert "model_unavailable = True" in handler

    def test_model_unavailable_marks_version_partial(self) -> None:
        """产出必须标 partial,不能让调用方误以为跑完了。"""
        import scripts.label_golden_chunks as cli

        source = inspect.getsource(cli.main)
        assert "interrupted or skipped_total or model_unavailable" in source

    def test_model_unavailable_still_exits_three(self) -> None:
        """写出部分结果**不降低**退出码 —— 它仍是需要人去修网关的信号。"""
        import scripts.label_golden_chunks as cli

        source = inspect.getsource(cli.main)
        idx_write = source.index("output_path.write_text")
        idx_exit = source.index("if model_unavailable:\n        return EXIT_MODEL_UNAVAILABLE")
        assert idx_write < idx_exit, "必须先写盘再返回退出码 3"

    def test_metadata_records_model_unavailable(self) -> None:
        """元数据要能区分「正常完成」「被中断」「模型挂了」三种收尾。"""
        import scripts.label_golden_chunks as cli

        source = inspect.getsource(cli.main)
        assert '"model_unavailable": model_unavailable,' in source
        assert '"interrupted": interrupted,' in source


class TestOutputConventions:
    def test_default_output_differs_from_input(self) -> None:
        """默认产出名必须与输入不同 —— 两代金标不是同一把尺子。"""
        src = Path("tests/fixtures/golden_test_set_en.json")

        out = _default_output(src)

        assert out != src
        assert out.name == "golden_test_set_en_v2.json"

    def test_version_and_method_constants(self) -> None:
        """报告侧靠这两个字段判定跨代 delta 是否可比。"""
        assert GOLDEN_VERSION_V2 == "v2.0"
        assert LABELING_METHOD == "pooled-llm-judged"
