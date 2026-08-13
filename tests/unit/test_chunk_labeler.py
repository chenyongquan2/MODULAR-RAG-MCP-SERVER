"""Unit tests for LLM 相关性判定 (`ChunkLabeler`)。

change: retriever-agnostic-golden-labels (T-3.1 / T-3.2)

测试范围:

1. 四档分级解析(纯 JSON / 嵌在文本里的 JSON / 裸数字)
2. **解析失败 → 标记 judge_failed,不是静默算作「不相关」**
3. **模型整体不可用 → 抛 LabelingUnavailableError**;个别输出不合格 → 继续跑
4. 单条失败不终止整轮
5. 预算上限与续跑
6. 异源检测三态(复用 testset_screener 的 SourceRelation)

**为什么第 2、3 条最重要**:把「解析失败」当成「不相关」会让解析 bug 伪装成
「语料里没有相关内容」;把「模型整体不可用」降级成告警会产出一份全是不相关的
空金标,而空金标让所有召回指标归零并被误读成检索崩了。

LLM 全部 mock,不触网。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from src.core.settings import (
    EvaluationSettings,
    JudgeLLMSettings,
    LabelingLLMSettings,
    LabelingSettings,
)
from src.observability.evaluation.chunk_labeler import (
    GRADE_DIRECT,
    GRADE_IRRELEVANT,
    GRADE_PARTIAL,
    GRADE_TANGENTIAL,
    ChunkLabeler,
    ChunkVerdict,
    LabelingUnavailableError,
    _parse_verdict,
    check_labeling_divergence,
    get_labeling_identifier,
)
from src.observability.evaluation.testset_screener import SourceRelation

pytestmark = pytest.mark.unit


class _FakeSettings:
    def __init__(
        self,
        labeling_provider: str = "glm",
        labeling_model: str = "glm-4.6",
        judge_model: str = "minimax/minimax-m2.7",
        **labeling_kwargs: Any,
    ) -> None:
        self.evaluation = EvaluationSettings()
        self.evaluation.labeling = LabelingSettings(**labeling_kwargs)
        self.evaluation.labeling_llm = LabelingLLMSettings(
            provider=labeling_provider, model=labeling_model
        )
        self.evaluation.judge_llm = JudgeLLMSettings(
            provider="glm", model=judge_model
        )


class _FakeLLM:
    """按预设回复序列应答;`error` 非空则抛异常。"""

    def __init__(
        self,
        responses: Optional[List[str]] = None,
        error: Optional[Exception] = None,
    ) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.calls: List[Dict[str, Any]] = []

    def chat(self, messages: List[Dict[str, str]], **kwargs: Any) -> str:
        self.calls.append({"messages": messages, **kwargs})
        if self.error:
            raise self.error
        if not self.responses:
            return '{"grade": 0, "reason": "no more canned responses"}'
        return self.responses.pop(0)


def _candidates(ids: List[str]) -> List[Dict[str, Any]]:
    return [{"chunk_id": cid, "text": f"passage {cid}"} for cid in ids]


def _labeler(
    responses: Optional[List[str]] = None,
    error: Optional[Exception] = None,
    **settings_kwargs: Any,
) -> tuple[ChunkLabeler, _FakeLLM]:
    llm = _FakeLLM(responses, error)
    return ChunkLabeler(_FakeSettings(**settings_kwargs), llm=llm), llm


# ── 分级解析 ─────────────────────────────────────────────────────────────


class TestParseVerdict:
    """四档分级的解析容忍度。"""

    @pytest.mark.parametrize("grade", [0, 1, 2, 3])
    def test_pure_json(self, grade: int) -> None:
        parsed, reason = _parse_verdict(f'{{"grade": {grade}, "reason": "because"}}')
        assert parsed == grade
        assert reason == "because"

    def test_json_embedded_in_prose(self) -> None:
        """模型爱加前言 —— 要能从文本里把 JSON 抠出来。"""
        parsed, reason = _parse_verdict(
            'Here is my assessment:\n{"grade": 3, "reason": "answers directly"}\nDone.'
        )
        assert parsed == GRADE_DIRECT
        assert reason == "answers directly"

    def test_bare_number_fallback(self) -> None:
        parsed, reason = _parse_verdict("2")
        assert parsed == GRADE_PARTIAL
        assert reason == ""

    def test_grade_prefix_fallback(self) -> None:
        parsed, _ = _parse_verdict("Grade: 1")
        assert parsed == GRADE_TANGENTIAL

    def test_out_of_range_grade_in_json_rejected(self) -> None:
        """JSON 里给 7 分不该被接受(也不该被 clamp 成 3)。"""
        parsed, _ = _parse_verdict('{"grade": 7, "reason": "x"}')
        assert parsed is None

    def test_bool_grade_rejected(self) -> None:
        """``true`` 在 Python 里 == 1,必须单独挡掉。"""
        parsed, _ = _parse_verdict('{"grade": true, "reason": "x"}')
        assert parsed is None

    @pytest.mark.parametrize("junk", ["", "   ", "I cannot assess this", "N/A", None])
    def test_unparseable_returns_none(self, junk: Any) -> None:
        """**返回 None 而不是 0** —— 见类 docstring。"""
        parsed, _ = _parse_verdict(junk)
        assert parsed is None

    def test_missing_reason_is_empty_not_error(self) -> None:
        parsed, reason = _parse_verdict('{"grade": 2}')
        assert parsed == GRADE_PARTIAL
        assert reason == ""


# ── 判定失败 ≠ 不相关 ────────────────────────────────────────────────────


class TestJudgeFailureIsNotIrrelevant:
    """**本文件最重要的一组之一**。

    把「解析失败」当成「不相关」会让解析 bug 伪装成「语料里没有相关内容」——
    金标会静默变空,而空金标让所有召回指标归零、被误读成检索崩了。
    """

    def test_unparseable_marks_judge_failed(self) -> None:
        labeler, _ = _labeler(["total gibberish, no number here"])

        verdict = labeler.label_one("q", "gt", "c1", "text")

        assert verdict.judge_failed is True
        assert verdict.grade is None

    def test_judge_failed_is_not_relevant_but_grade_stays_none(self) -> None:
        """不纳入标准答案,但 grade 保持 None 而非 0 —— 两种状态必须可区分。"""
        v = ChunkVerdict(chunk_id="c1", judge_failed=True)

        assert v.is_relevant(threshold=2) is False
        assert v.grade is None

    def test_grade_zero_is_distinguishable_from_failure(self) -> None:
        judged_irrelevant = ChunkVerdict(chunk_id="c1", grade=GRADE_IRRELEVANT)
        failed = ChunkVerdict(chunk_id="c2", judge_failed=True)

        assert judged_irrelevant.judge_failed is False
        assert judged_irrelevant.grade == 0
        assert failed.grade is None

    def test_failure_ratio_warning(self) -> None:
        # 3 条候选，2 条解析失败 → 失败率 66.7% > 默认 10%
        labeler, _ = _labeler(['{"grade": 3}', "junk", "more junk"])

        run = labeler.label_all("q", "gt", _candidates(["a", "b", "c"]))

        assert run.failure_ratio == pytest.approx(2 / 3)
        assert any("judge failure ratio" in w for w in run.warnings)

    def test_warning_explains_the_distinction(self) -> None:
        labeler, _ = _labeler(["junk", "junk"])

        run = labeler.label_all("q", "gt", _candidates(["a", "b"]))

        assert any("NOT the same as" in w for w in run.warnings)

    def test_no_warning_when_all_parse(self) -> None:
        labeler, _ = _labeler(['{"grade": 3}', '{"grade": 0}'])

        run = labeler.label_all("q", "gt", _candidates(["a", "b"]))

        assert run.warnings == []
        assert run.failure_ratio == 0.0


# ── 模型整体不可用 vs 个别输出不合格 ─────────────────────────────────────


class TestModelUnavailableVsBadOutput:
    """**本文件最重要的一组之二** —— 两类失败必须严格区分。"""

    def test_all_transport_failures_raises(self) -> None:
        """全部调用打不通 → 模型整体不可用,必须显式失败。"""
        labeler, _ = _labeler(error=ConnectionError("gateway unreachable"))

        with pytest.raises(LabelingUnavailableError, match="transport"):
            labeler.label_all("q", "gt", _candidates(["a", "b", "c"]))

    def test_error_message_says_why_refusing(self) -> None:
        """错误消息要说明为什么不能降级 —— 否则下一个人会想「加个兜底不就行了」。"""
        labeler, _ = _labeler(error=ConnectionError("boom"))

        with pytest.raises(LabelingUnavailableError, match="zero out every recall"):
            labeler.label_all("q", "gt", _candidates(["a"]))

    def test_partial_transport_failure_does_not_raise(self) -> None:
        """部分打不通 ≠ 模型整体不可用,整轮继续。"""
        class _FlakyLLM:
            def __init__(self) -> None:
                self.n = 0

            def chat(self, messages: List[Dict[str, str]], **kwargs: Any) -> str:
                self.n += 1
                if self.n == 1:
                    raise ConnectionError("transient")
                return '{"grade": 3, "reason": "ok"}'

        labeler = ChunkLabeler(_FakeSettings(), llm=_FlakyLLM())

        run = labeler.label_all("q", "gt", _candidates(["a", "b", "c"]))

        assert len(run.verdicts) == 3
        assert sum(1 for v in run.verdicts if v.transport_failed) == 1
        assert sum(1 for v in run.verdicts if v.grade == GRADE_DIRECT) == 2

    def test_bad_output_never_raises(self) -> None:
        """模型通但输出全不合格 → 不抛,逐条留痕 + 告警。"""
        labeler, _ = _labeler(["junk", "junk", "junk"])

        run = labeler.label_all("q", "gt", _candidates(["a", "b", "c"]))

        assert all(v.judge_failed for v in run.verdicts)
        assert all(not v.transport_failed for v in run.verdicts)
        assert run.warnings

    def test_no_candidates_does_not_raise(self) -> None:
        """没有候选时不该误判为「模型不可用」。"""
        labeler, _ = _labeler(error=ConnectionError("boom"))

        run = labeler.label_all("q", "gt", [])

        assert run.verdicts == []
        assert run.judged_count == 0


# ── 纳入门槛 ─────────────────────────────────────────────────────────────


class TestRelevanceThreshold:
    def test_threshold_two_includes_partial_and_direct(self) -> None:
        labeler, _ = _labeler(
            ['{"grade": 0}', '{"grade": 1}', '{"grade": 2}', '{"grade": 3}'],
            relevance_threshold=2,
        )

        run = labeler.label_all("q", "gt", _candidates(["g0", "g1", "g2", "g3"]))

        assert labeler.relevant_ids(run) == ["g2", "g3"]

    def test_threshold_three_includes_direct_only(self) -> None:
        labeler, _ = _labeler(
            ['{"grade": 2}', '{"grade": 3}'], relevance_threshold=3
        )

        run = labeler.label_all("q", "gt", _candidates(["g2", "g3"]))

        assert labeler.relevant_ids(run) == ["g3"]

    def test_relevant_ids_preserves_input_order(self) -> None:
        labeler, _ = _labeler(['{"grade": 3}', '{"grade": 3}', '{"grade": 3}'])

        run = labeler.label_all("q", "gt", _candidates(["z", "a", "m"]))

        assert labeler.relevant_ids(run) == ["z", "a", "m"]


# ── 预算与续跑 ───────────────────────────────────────────────────────────


class TestBudgetAndResume:
    def test_budget_limits_calls_and_records_skipped(self) -> None:
        """超出预算的候选记入 skipped_count —— **不静默丢弃**。"""
        labeler, llm = _labeler(['{"grade": 3}'] * 10)

        run = labeler.label_all("q", "gt", _candidates(["a", "b", "c", "d"]), budget=2)

        assert run.judged_count == 2
        assert run.skipped_count == 2
        assert len(llm.calls) == 2

    def test_zero_budget_judges_nothing(self) -> None:
        labeler, llm = _labeler(['{"grade": 3}'])

        run = labeler.label_all("q", "gt", _candidates(["a", "b"]), budget=0)

        assert run.judged_count == 0
        assert run.skipped_count == 2
        assert llm.calls == []

    def test_none_budget_is_unlimited(self) -> None:
        labeler, llm = _labeler(['{"grade": 3}'] * 5)

        run = labeler.label_all("q", "gt", _candidates(["a", "b", "c"]), budget=None)

        assert run.judged_count == 3
        assert run.skipped_count == 0

    def test_resume_skips_already_judged(self) -> None:
        labeler, llm = _labeler(['{"grade": 3}'] * 5)
        cached = {"a": ChunkVerdict(chunk_id="a", grade=GRADE_PARTIAL, reason="cached")}

        run = labeler.label_all(
            "q", "gt", _candidates(["a", "b"]), already_judged=cached
        )

        assert len(llm.calls) == 1  # 只判定了 b
        assert run.judged_count == 1
        by_id = {v.chunk_id: v for v in run.verdicts}
        assert by_id["a"].reason == "cached"

    def test_cached_candidates_do_not_consume_budget(self) -> None:
        labeler, llm = _labeler(['{"grade": 3}'] * 5)
        cached = {
            cid: ChunkVerdict(chunk_id=cid, grade=GRADE_DIRECT) for cid in ("a", "b")
        }

        run = labeler.label_all(
            "q", "gt", _candidates(["a", "b", "c"]), budget=1, already_judged=cached
        )

        assert run.judged_count == 1   # 只有 c 花了预算
        assert run.skipped_count == 0
        assert len(run.verdicts) == 3


# ── prompt 内容 ──────────────────────────────────────────────────────────


class TestPromptContent:
    def test_prompt_carries_query_answer_and_chunk(self) -> None:
        labeler, llm = _labeler(['{"grade": 3}'])

        labeler.label_one("my question", "the answer", "c1", "the passage")

        prompt = llm.calls[0]["messages"][0]["content"]
        assert "my question" in prompt
        assert "the answer" in prompt
        assert "the passage" in prompt

    def test_prompt_warns_against_rewarding_wording_similarity(self) -> None:
        """这是与第一代的核心差异 —— 判的是「能否回答」,不是「像不像」。"""
        labeler, llm = _labeler(['{"grade": 3}'])

        labeler.label_one("q", "gt", "c1", "text")

        prompt = llm.calls[0]["messages"][0]["content"]
        assert "similar wording" in prompt
        assert "different words" in prompt

    def test_max_tokens_comes_from_config_not_hardcoded(self) -> None:
        """max_tokens 必须读配置。

        此前硬编码 200,真实语料上 367 字符的 chunk 就返回空响应 → 每条都标
        judge_failed,表现得像「模型不会遵从 JSON 格式」。真实原因是没给它
        写完的余量。见 LabelingLLMSettings.max_tokens 的 docstring。
        """
        labeler, llm = _labeler(['{"grade": 3}'])
        labeler._settings.evaluation.labeling_llm.max_tokens = 1234  # noqa: SLF001

        labeler.label_one("q", "gt", "c1", "text")

        assert llm.calls[0]["max_tokens"] == 1234

    def test_default_max_tokens_is_not_the_broken_200(self) -> None:
        labeler, llm = _labeler(['{"grade": 3}'])

        labeler.label_one("q", "gt", "c1", "text")

        assert llm.calls[0]["max_tokens"] >= 800

    def test_truncated_json_does_not_silently_become_irrelevant(self) -> None:
        """截断的 JSON 要么解析出真实 grade,要么标 judge_failed。

        实测的截断形态:'{"grade": 0, "reason": "The passage only introduces'
        —— JSON 永远以 {"grade": N 开头,所以裸数字兜底取到的第一个 0-3 数字
        就是真实 grade。这是可接受的;**不可接受的是把空响应当成 0 分**。
        """
        truncated = '{"grade": 2, "reason": "The passage partially cove'
        grade, _ = _parse_verdict(truncated)
        assert grade == 2

        empty_grade, _ = _parse_verdict("")
        assert empty_grade is None  # 空响应 → judge_failed，不是 0 分

    def test_chunk_truncated(self) -> None:
        labeler, llm = _labeler(['{"grade": 3}'])
        long_text = "x" * 5000

        labeler.label_one("q", "gt", "c1", long_text)

        prompt = llm.calls[0]["messages"][0]["content"]
        assert "x" * 2000 in prompt
        assert "x" * 2001 not in prompt


# ── 异源检测 ─────────────────────────────────────────────────────────────


class TestSourceDivergence:
    """复用 testset_screener 的三态口径 —— 同一个问题不该有两套判据。"""

    def test_identifier_format(self) -> None:
        s = _FakeSettings(labeling_provider="glm", labeling_model="glm-4.6")
        assert get_labeling_identifier(s) == "glm:glm-4.6"

    def test_same_source_detected(self) -> None:
        s = _FakeSettings(labeling_model="minimax/minimax-m2.7")
        golden = {
            "_synthesis_metadata": {"judge_llm_identifier": "glm:minimax/minimax-m2.7"}
        }

        assert check_labeling_divergence(s, golden) is SourceRelation.SAME_SOURCE

    def test_same_provider_different_model_is_divergent(self) -> None:
        """判据是完整标识串,不是 provider。

        实测 judge 标识为 "glm:minimax/minimax-m2.7" —— provider 名义是 glm 但
        模型经 OpenAI 兼容端点路由到 minimax。只比 provider 会把真正异源的
        glm:glm-4.6 误判为同源。
        """
        s = _FakeSettings(labeling_provider="glm", labeling_model="glm-4.6")
        golden = {
            "_synthesis_metadata": {"judge_llm_identifier": "glm:minimax/minimax-m2.7"}
        }

        assert check_labeling_divergence(s, golden) is SourceRelation.DIVERGENT

    def test_missing_synthesis_identifier_is_unverifiable(self) -> None:
        s = _FakeSettings()

        assert check_labeling_divergence(s, {}) is SourceRelation.UNVERIFIABLE

    def test_empty_labeling_model_is_unverifiable(self) -> None:
        s = _FakeSettings(labeling_provider="", labeling_model="")
        golden = {"_synthesis_metadata": {"judge_llm_identifier": "glm:x"}}

        assert check_labeling_divergence(s, golden) is SourceRelation.UNVERIFIABLE

    def test_falls_back_to_review_metadata(self) -> None:
        """精修阶段写的是 _review_metadata.synthesis_identifier。"""
        s = _FakeSettings(labeling_model="minimax/minimax-m2.7")
        golden = {
            "_review_metadata": {"synthesis_identifier": "glm:minimax/minimax-m2.7"}
        }

        assert check_labeling_divergence(s, golden) is SourceRelation.SAME_SOURCE

    def test_whitespace_in_identifier_normalized(self) -> None:
        s = _FakeSettings(labeling_provider=" glm ", labeling_model=" glm-4.6 ")
        golden = {"_synthesis_metadata": {"judge_llm_identifier": "glm: glm-4.6"}}

        assert check_labeling_divergence(s, golden) is SourceRelation.SAME_SOURCE


class TestConstruction:
    def test_none_settings_rejected(self) -> None:
        with pytest.raises(ValueError, match="Settings cannot be None"):
            ChunkLabeler(None)  # type: ignore[arg-type]

    def test_temperature_from_config(self) -> None:
        labeler, llm = _labeler(['{"grade": 3}'])

        labeler.label_one("q", "gt", "c1", "text")

        assert llm.calls[0]["temperature"] == 0.0
