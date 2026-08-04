"""Unit tests for Feature-003 预筛模块 (T008, T009)。

测试范围:
1. 三态路由:keep/drop 达阈值 → 自动决策;未达阈值或显式 borderline → 人工
2. **全部降级路径**:LLM 抛异常 / 非 JSON / 缺字段 / 置信度越界 / 未知结论
   → 一律 borderline。核心不变式:**任何异常路径都不得流向自动保留或自动丢弃**
3. ``screen_all`` 的批量行为:空输入零调用、全失败抛异常、borderline 占比
4. ``check_source_divergence`` 同源检测三态

覆盖 spec § FR-001 / FR-002 / FR-008 + data-model.md § 2。

全程 mock 预筛 LLM,不发起任何真实调用。
"""

from __future__ import annotations

from typing import Any

import pytest

from src.core.settings import (
    EmbeddingSettings,
    EvaluationSettings,
    LLMSettings,
    ScreeningLLMSettings,
    Settings,
    VectorStoreSettings,
    VisionLLMSettings,
)
from src.observability.evaluation.testset_screener import (
    ScreeningDecision,
    ScreeningUnavailableError,
    SourceRelation,
    TestsetScreener,
    check_source_divergence,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------


def _settings(**screening_overrides: Any) -> Settings:
    """构造带 screening_llm 配置的最小 Settings。"""
    screening = ScreeningLLMSettings(
        provider="glm",
        model="glm-4.6",
        **screening_overrides,
    )
    evaluation = EvaluationSettings()
    evaluation.screening_llm = screening
    return Settings(
        llm=LLMSettings(provider="glm", model="glm-4"),
        embedding=EmbeddingSettings(provider="openai", model="text-embedding-3-small"),
        vision_llm=VisionLLMSettings(provider="azure", model="gpt-4o"),
        vector_store=VectorStoreSettings(backend="chroma"),
        evaluation=evaluation,
    )


class _FakeLLM:
    """最小 BaseLLM 替身:按预设序列返回 chat() 结果,或抛异常。

    ``responses`` 元素为 str 则原样返回;为 Exception 实例则抛出。
    """

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        self.calls += 1
        item = self._responses.pop(0) if self._responses else '{"decision":"keep","confidence":1.0}'
        if isinstance(item, Exception):
            raise item
        return item


def _case(idx: int = 0) -> dict[str, Any]:
    return {
        "query": f"问题 {idx}",
        "ground_truth": f"答案 {idx}",
        "expected_chunk_ids": [f"chunk-{idx}"],
        "expected_sources": ["doc.md"],
        "_synth_contexts": ["上下文片段"],
        "tags": {"language": "zh", "difficulty": "simple"},
    }


def _screener(responses: list[Any], **screening_overrides: Any) -> TestsetScreener:
    return TestsetScreener(
        settings=_settings(**screening_overrides),
        llm=_FakeLLM(responses),
        prompt_template="{query}|{ground_truth}|{expected_chunk_ids}|{contexts}",
    )


# ---------------------------------------------------------------------------
# 三态路由 (FR-001, FR-003)
# ---------------------------------------------------------------------------


class TestThreeWayRouting:
    def test_keep_above_threshold_is_auto_keep(self) -> None:
        s = _screener(['{"decision":"keep","confidence":0.95,"reason":"ok"}'])
        v = s.screen_case(_case(), 0)
        assert v.decision is ScreeningDecision.KEEP
        assert v.confidence == 0.95
        assert v.reason == "ok"
        assert v.case_index == 0

    def test_drop_above_threshold_is_auto_drop(self) -> None:
        s = _screener(['{"decision":"drop","confidence":0.9,"reason":"bad gt"}'])
        assert s.screen_case(_case(), 0).decision is ScreeningDecision.DROP

    def test_keep_below_threshold_downgrades_to_borderline(self) -> None:
        """置信度不达阈值的 keep 不能自动保留 —— 必须交人工。"""
        s = _screener(['{"decision":"keep","confidence":0.5}'], keep_threshold=0.8)
        assert s.screen_case(_case(), 0).decision is ScreeningDecision.BORDERLINE

    def test_drop_below_threshold_downgrades_to_borderline(self) -> None:
        s = _screener(['{"decision":"drop","confidence":0.5}'], drop_threshold=0.8)
        assert s.screen_case(_case(), 0).decision is ScreeningDecision.BORDERLINE

    def test_explicit_borderline_stays_borderline(self) -> None:
        s = _screener(['{"decision":"borderline","confidence":0.99}'])
        assert s.screen_case(_case(), 0).decision is ScreeningDecision.BORDERLINE

    def test_threshold_boundary_is_inclusive(self) -> None:
        """置信度恰好等于阈值应当自动决策(区间为 >=)。"""
        s = _screener(['{"decision":"keep","confidence":0.8}'], keep_threshold=0.8)
        assert s.screen_case(_case(), 0).decision is ScreeningDecision.KEEP

    def test_keep_and_drop_thresholds_are_independent(self) -> None:
        """keep 严、drop 松时,同一置信度应得到不同处置。"""
        s = _screener(
            ['{"decision":"keep","confidence":0.7}', '{"decision":"drop","confidence":0.7}'],
            keep_threshold=0.9,
            drop_threshold=0.6,
        )
        assert s.screen_case(_case(0), 0).decision is ScreeningDecision.BORDERLINE
        assert s.screen_case(_case(1), 1).decision is ScreeningDecision.DROP


# ---------------------------------------------------------------------------
# 降级路径 (FR-008) —— 本组是本 feature 的安全底线
# ---------------------------------------------------------------------------


_DEGRADED_RESPONSES = [
    pytest.param(RuntimeError("upstream 500"), id="llm-raises"),
    pytest.param(TimeoutError("timed out"), id="llm-timeout"),
    pytest.param("not json at all", id="non-json"),
    pytest.param("", id="empty-string"),
    pytest.param("{}", id="empty-object"),
    pytest.param('{"confidence":0.9}', id="missing-decision"),
    pytest.param('{"decision":"keep"}', id="missing-confidence"),
    pytest.param('{"decision":"maybe","confidence":0.9}', id="unknown-decision"),
    pytest.param('{"decision":"keep","confidence":1.5}', id="confidence-above-1"),
    pytest.param('{"decision":"keep","confidence":-0.1}', id="confidence-below-0"),
    pytest.param('{"decision":"keep","confidence":"high"}', id="confidence-not-number"),
    pytest.param('[{"decision":"keep","confidence":0.9}]', id="json-array-not-object"),
]


class TestDegradationPaths:
    @pytest.mark.parametrize("response", _DEGRADED_RESPONSES)
    def test_all_bad_responses_become_borderline(self, response: Any) -> None:
        """FR-008 不变式:任何异常路径只能流向 borderline。

        这是本 feature 的安全底线 —— 机器的不确定性只允许增加人工量,
        绝不允许污染金标(静默保留劣质用例或静默丢弃优质用例)。
        """
        s = _screener([response])
        v = s.screen_case(_case(), 0)
        assert v.decision is ScreeningDecision.BORDERLINE
        assert v.decision is not ScreeningDecision.KEEP
        assert v.decision is not ScreeningDecision.DROP

    def test_degraded_verdict_records_case_index(self) -> None:
        """降级也要带上 case_index,否则无法回查是哪条出的问题。"""
        s = _screener([RuntimeError("boom")])
        assert s.screen_case(_case(7), 7).case_index == 7

    def test_degraded_verdict_reason_is_non_empty(self) -> None:
        """降级原因必须可读,人工处置 borderline 时要知道为什么轮到自己。"""
        s = _screener(["not json"])
        assert s.screen_case(_case(), 0).reason.strip() != ""

    def test_markdown_fenced_json_is_tolerated(self) -> None:
        """提示词要求裸 JSON,但模型常自作主张加 ``` 围栏,应当容忍。"""
        s = _screener(['```json\n{"decision":"keep","confidence":0.95}\n```'])
        assert s.screen_case(_case(), 0).decision is ScreeningDecision.KEEP

    def test_surrounding_prose_is_tolerated(self) -> None:
        """JSON 前后夹带解释文字时,应能提取出对象。"""
        s = _screener(['Here is my verdict: {"decision":"drop","confidence":0.9} — done.'])
        assert s.screen_case(_case(), 0).decision is ScreeningDecision.DROP


# ---------------------------------------------------------------------------
# screen_all 批量行为
# ---------------------------------------------------------------------------


class TestScreenAll:
    def test_empty_candidate_makes_no_llm_call(self) -> None:
        """空输入不得发起任何 LLM 调用(spec Edge Cases「空输入」)。"""
        llm = _FakeLLM([])
        s = TestsetScreener(settings=_settings(), llm=llm, prompt_template="{query}")
        result = s.screen_all({"test_cases": []})
        assert result.verdicts == []
        assert llm.calls == 0

    def test_verdicts_align_with_case_indices(self) -> None:
        s = _screener(
            [
                '{"decision":"keep","confidence":0.95}',
                '{"decision":"drop","confidence":0.95}',
                '{"decision":"borderline","confidence":0.5}',
            ]
        )
        result = s.screen_all({"test_cases": [_case(0), _case(1), _case(2)]})
        assert [v.case_index for v in result.verdicts] == [0, 1, 2]
        assert result.auto_keep_indices == [0]
        assert result.auto_drop_indices == [1]
        assert result.borderline_indices == [2]

    def test_borderline_ratio(self) -> None:
        s = _screener(
            [
                '{"decision":"keep","confidence":0.95}',
                '{"decision":"borderline","confidence":0.5}',
                '{"decision":"borderline","confidence":0.5}',
                '{"decision":"keep","confidence":0.95}',
            ]
        )
        result = s.screen_all({"test_cases": [_case(i) for i in range(4)]})
        assert result.borderline_ratio == 0.5

    def test_borderline_ratio_of_empty_is_zero(self) -> None:
        s = _screener([])
        assert s.screen_all({"test_cases": []}).borderline_ratio == 0.0

    def test_partial_failures_do_not_raise(self) -> None:
        """个别调用失败只让那几条进 borderline,不影响整体流程。"""
        s = _screener(
            [
                '{"decision":"keep","confidence":0.95}',
                RuntimeError("boom"),
                '{"decision":"keep","confidence":0.95}',
            ]
        )
        result = s.screen_all({"test_cases": [_case(i) for i in range(3)]})
        assert result.borderline_indices == [1]
        assert result.auto_keep_indices == [0, 2]

    def test_all_failures_raise_unavailable(self) -> None:
        """全部调用失败 → 抛可区分异常,供 CLI 映射为退出码 3。

        这里必须显式失败,而不是把全部用例判为 borderline 后宣称「自动完成」——
        那等于让人工全量处理却以为跑了自动化(spec Edge Cases)。
        """
        s = _screener([RuntimeError("boom"), RuntimeError("boom")])
        with pytest.raises(ScreeningUnavailableError):
            s.screen_all({"test_cases": [_case(0), _case(1)]})

    def test_parse_failures_are_not_unavailable(self) -> None:
        """全部返回非法 JSON ≠ 模型不可用 —— 模型是通的,只是输出不合格。

        这种情况应全部降级 borderline 让人工兜住,而不是当作服务不可用退出。
        """
        s = _screener(["not json", "also not json"])
        result = s.screen_all({"test_cases": [_case(0), _case(1)]})
        assert result.borderline_ratio == 1.0

    def test_missing_test_cases_key_treated_as_empty(self) -> None:
        s = _screener([])
        assert s.screen_all({}).verdicts == []


# ---------------------------------------------------------------------------
# 同源检测 (FR-002) —— T009
# ---------------------------------------------------------------------------


def _candidate(judge_identifier: Any = "glm:minimax/minimax-m2.7") -> dict[str, Any]:
    meta: dict[str, Any] = {"generator": "ragas.testset.TestsetGenerator"}
    if judge_identifier is not None:
        meta["judge_llm_identifier"] = judge_identifier
    return {"_schema_version": 1, "language": "zh", "_synthesis_metadata": meta, "test_cases": []}


class TestSourceDivergence:
    def test_identical_identifier_is_same_source(self) -> None:
        s = _settings()
        s.evaluation.screening_llm.model = "minimax/minimax-m2.7"
        assert check_source_divergence(s, _candidate()) is SourceRelation.SAME_SOURCE

    def test_same_provider_different_model_is_divergent(self) -> None:
        """**关键用例**:provider 相同但 model 不同必须判异源。

        实测 candidate 的 judge 标识是 "glm:minimax/minimax-m2.7" —— provider
        名义是 glm 但模型经 OpenAI 兼容端点路由到 minimax。若只比 provider,
        真正异源的 glm:glm-4.6 会被误判同源而遭拒绝。
        """
        s = _settings()  # screening = glm:glm-4.6
        assert check_source_divergence(s, _candidate()) is SourceRelation.DIVERGENT

    def test_different_provider_is_divergent(self) -> None:
        s = _settings()
        s.evaluation.screening_llm.provider = "openai"
        s.evaluation.screening_llm.model = "gpt-4o"
        assert check_source_divergence(s, _candidate()) is SourceRelation.DIVERGENT

    def test_missing_synthesis_metadata_is_unverifiable(self) -> None:
        assert (
            check_source_divergence(_settings(), {"test_cases": []})
            is SourceRelation.UNVERIFIABLE
        )

    def test_missing_identifier_key_is_unverifiable(self) -> None:
        assert (
            check_source_divergence(_settings(), _candidate(judge_identifier=None))
            is SourceRelation.UNVERIFIABLE
        )

    @pytest.mark.parametrize("blank", ["", "   ", ":"])
    def test_blank_identifier_is_unverifiable(self, blank: str) -> None:
        """空标识或退化的 ":"(provider 与 model 都空)都无法据以判定。"""
        assert (
            check_source_divergence(_settings(), _candidate(judge_identifier=blank))
            is SourceRelation.UNVERIFIABLE
        )

    def test_unconfigured_screening_is_unverifiable(self) -> None:
        """预筛端自己没配时也无法比对 —— 交由 CLI 以「未配置」路径处理。"""
        s = _settings()
        s.evaluation.screening_llm.provider = ""
        s.evaluation.screening_llm.model = ""
        assert check_source_divergence(s, _candidate()) is SourceRelation.UNVERIFIABLE

    def test_comparison_ignores_surrounding_whitespace(self) -> None:
        s = _settings()
        s.evaluation.screening_llm.model = "  minimax/minimax-m2.7  "
        assert check_source_divergence(s, _candidate()) is SourceRelation.SAME_SOURCE
