"""Unit tests for refine_testset auto 模式 (T015, T016)。

测试范围:
- CLI 契约:退出码 2(前置条件不满足)/ 3(预筛模型不可用)/ 130(中断)
- **FR-004 关键回归点**:不带 --auto-mode 时零 LLM 调用、输出无 _review_metadata
- FR-010:auto 模式中断保住已完成决策 + v0.9-partial
- FR-011:borderline 占比超限告警且不影响退出码
- 决策来源映射(kept_provenance)—— US3 的 SC-006 拆分依赖它

契约见 specs/003-testset-refine-automation/contracts/cli_contract.md § 2 / § 5。
全程 mock 预筛 LLM,不发起真实调用。
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
    LLMSettings,
    ScreeningLLMSettings,
    Settings,
    VectorStoreSettings,
    VisionLLMSettings,
)
from src.observability.evaluation.testset_screener import (
    ScreeningDecision,
    ScreeningResult,
    ScreeningUnavailableError,
    ScreeningVerdict,
)

pytestmark = pytest.mark.unit

# 加载 scripts/refine_testset.py 作为模块(它不在 src/ 包里)
_spec = importlib.util.spec_from_file_location(
    "refine_testset_auto_module",
    Path(__file__).parent.parent.parent / "scripts" / "refine_testset.py",
)
refine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(refine)


SYNTHESIS_ID = "glm:minimax/minimax-m2.7"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _settings(provider: str = "glm", model: str = "glm-4.6", **overrides: Any) -> Settings:
    evaluation = EvaluationSettings()
    evaluation.screening_llm = ScreeningLLMSettings(
        provider=provider, model=model, **overrides
    )
    return Settings(
        llm=LLMSettings(provider="glm", model="glm-4"),
        embedding=EmbeddingSettings(provider="openai", model="text-embedding-3-small"),
        vision_llm=VisionLLMSettings(provider="azure", model="gpt-4o"),
        vector_store=VectorStoreSettings(backend="chroma"),
        evaluation=evaluation,
    )


def _candidate(n: int = 3, judge_identifier: Any = SYNTHESIS_ID) -> dict[str, Any]:
    meta: dict[str, Any] = {"generator": "ragas"}
    if judge_identifier is not None:
        meta["judge_llm_identifier"] = judge_identifier
    return {
        "_schema_version": 1,
        "language": "zh",
        "_synthesis_metadata": meta,
        "test_cases": [
            {
                "query": f"问题 {i}",
                "ground_truth": f"答案 {i}",
                "expected_chunk_ids": [f"chunk-{i}"],
                "expected_sources": ["doc.md"],
                "_synth_contexts": ["ctx"],
                "tags": {"language": "zh"},
            }
            for i in range(n)
        ],
    }


class _StubScreener:
    """按预设 decision 序列返回 verdict,不调用任何 LLM。"""

    def __init__(self, decisions: list[ScreeningDecision], raise_unavailable: bool = False):
        self._decisions = decisions
        self._raise = raise_unavailable
        self.called = False

    def screen_all(self, candidate: dict[str, Any]) -> ScreeningResult:
        self.called = True
        if self._raise:
            raise ScreeningUnavailableError("all calls failed")
        return ScreeningResult(
            verdicts=[
                ScreeningVerdict(
                    case_index=i,
                    decision=d,
                    confidence=0.0 if d is ScreeningDecision.BORDERLINE else 0.95,
                    reason="stub",
                )
                for i, d in enumerate(self._decisions)
            ]
        )


def _run_main(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    candidate: dict[str, Any],
    argv_extra: list[str],
    settings: Settings | None = None,
    screener: Any = None,
    stdin_text: str = "",
) -> tuple[int, Path]:
    """驱动 main():写入 candidate、打桩 settings/screener、返回 (退出码, 输出路径)。"""
    in_path = tmp_path / "candidate.json"
    in_path.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")
    out_path = tmp_path / "golden.json"

    monkeypatch.setattr(
        "sys.argv",
        ["refine_testset.py", "--input", str(in_path), "--output", str(out_path)]
        + argv_extra,
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin_text))

    if settings is not None:
        monkeypatch.setattr("src.core.settings.load_settings", lambda: settings)
    if screener is not None:
        monkeypatch.setattr(refine, "auto_refine", _auto_refine_with(screener))

    return refine.main(), out_path


def _auto_refine_with(screener: Any):
    """把 stub screener 注入 auto_refine(保留其余真实逻辑)。"""
    real = refine.auto_refine

    def _wrapped(candidate, settings, screener_arg=None, input_stream=None):
        return real(candidate, settings, screener=screener, input_stream=input_stream)

    return _wrapped


# ---------------------------------------------------------------------------
# FR-004:默认路径零变化 —— 本组是最关键的回归保护
# ---------------------------------------------------------------------------


class TestDefaultPathUnchanged:
    def test_without_auto_mode_no_settings_or_llm_touched(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """不带 --auto-mode 时不得读取 settings,更不得创建预筛模型。

        这是 FR-004 的核心:既有用法完全不受本 feature 影响,连配置都不碰。
        """

        def _explode() -> None:
            raise AssertionError("load_settings() must not be called in default mode")

        monkeypatch.setattr("src.core.settings.load_settings", _explode)
        code, out_path = _run_main(
            monkeypatch, tmp_path, _candidate(2), argv_extra=[], stdin_text="y\ny\n"
        )
        assert code == 0
        assert out_path.exists()

    def test_without_auto_mode_output_has_no_review_metadata(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        code, out_path = _run_main(
            monkeypatch, tmp_path, _candidate(2), argv_extra=[], stdin_text="y\ny\n"
        )
        assert code == 0
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        assert "_review_metadata" not in payload
        # 既有字段语义不变
        assert payload["_schema_version"] == 1
        assert set(payload["_refine_summary"]) == {"keep", "edit", "drop", "skip"}


# ---------------------------------------------------------------------------
# 退出码 2:auto 前置条件 (FR-002)
# ---------------------------------------------------------------------------


class TestAutoPreconditions:
    def test_unconfigured_screening_exits_2(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        code, out_path = _run_main(
            monkeypatch,
            tmp_path,
            _candidate(),
            argv_extra=["--auto-mode"],
            settings=_settings(provider="", model=""),
        )
        assert code == 2
        assert not out_path.exists(), "前置条件失败时不应写出金标"

    def test_same_source_exits_2_and_writes_nothing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        code, out_path = _run_main(
            monkeypatch,
            tmp_path,
            _candidate(),
            argv_extra=["--auto-mode"],
            settings=_settings(provider="glm", model="minimax/minimax-m2.7"),
        )
        assert code == 2
        assert not out_path.exists()

    def test_same_source_not_bypassable_by_allow_flag(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """--allow-same-source 只豁免「无法确认」,不豁免已确认的同源。"""
        code, _ = _run_main(
            monkeypatch,
            tmp_path,
            _candidate(),
            argv_extra=["--auto-mode", "--allow-same-source"],
            settings=_settings(provider="glm", model="minimax/minimax-m2.7"),
        )
        assert code == 2

    def test_missing_identifier_exits_2_without_flag(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        code, _ = _run_main(
            monkeypatch,
            tmp_path,
            _candidate(judge_identifier=None),
            argv_extra=["--auto-mode"],
            settings=_settings(),
        )
        assert code == 2

    def test_missing_identifier_proceeds_with_flag(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        code, out_path = _run_main(
            monkeypatch,
            tmp_path,
            _candidate(2, judge_identifier=None),
            argv_extra=["--auto-mode", "--allow-same-source"],
            settings=_settings(),
            screener=_StubScreener([ScreeningDecision.KEEP, ScreeningDecision.KEEP]),
        )
        assert code == 0
        assert out_path.exists()

    def test_divergent_source_proceeds(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """provider 相同但 model 不同 → 异源,应正常继续。"""
        code, out_path = _run_main(
            monkeypatch,
            tmp_path,
            _candidate(1),
            argv_extra=["--auto-mode"],
            settings=_settings(provider="glm", model="glm-4.6"),
            screener=_StubScreener([ScreeningDecision.KEEP]),
        )
        assert code == 0
        assert json.loads(out_path.read_text(encoding="utf-8"))["_refine_summary"]["keep"] == 1


# ---------------------------------------------------------------------------
# 退出码 3:预筛模型不可用
# ---------------------------------------------------------------------------


def test_screening_unavailable_exits_3(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """全部调用失败 → 退出码 3,不写文件。

    必须与「模型通但输出不合格」区分:后者应降级 borderline 让人工兜住。
    """
    code, out_path = _run_main(
        monkeypatch,
        tmp_path,
        _candidate(2),
        argv_extra=["--auto-mode"],
        settings=_settings(),
        screener=_StubScreener([], raise_unavailable=True),
    )
    assert code == 3
    assert not out_path.exists()


# ---------------------------------------------------------------------------
# auto 路由与决策来源
# ---------------------------------------------------------------------------


class TestAutoRouting:
    def test_only_borderline_prompts_human(self) -> None:
        """2 条自动 + 1 条 borderline → 只消费一次 stdin。"""
        stream = io.StringIO("y\n")
        outcome = refine.auto_refine(
            _candidate(3),
            _settings(),
            screener=_StubScreener(
                [
                    ScreeningDecision.KEEP,
                    ScreeningDecision.BORDERLINE,
                    ScreeningDecision.DROP,
                ]
            ),
            input_stream=stream,
        )
        assert outcome.auto_decided == 2
        assert outcome.human_reviewed == 1
        assert stream.read() == "", "应恰好消费一行输入"
        assert outcome.final["_refine_summary"]["keep"] == 2  # 1 auto + 1 human
        assert outcome.final["_refine_summary"]["drop"] == 1

    def test_kept_provenance_aligns_with_test_cases(self) -> None:
        """kept_provenance 必须与输出的 test_cases 同序 —— SC-006 拆分靠它。"""
        outcome = refine.auto_refine(
            _candidate(3),
            _settings(),
            screener=_StubScreener(
                [
                    ScreeningDecision.KEEP,
                    ScreeningDecision.BORDERLINE,
                    ScreeningDecision.KEEP,
                ]
            ),
            input_stream=io.StringIO("y\n"),
        )
        assert len(outcome.kept_provenance) == len(outcome.final["test_cases"])
        assert outcome.kept_provenance == [
            refine.PROVENANCE_AUTO,
            refine.PROVENANCE_HUMAN,
            refine.PROVENANCE_AUTO,
        ]

    def test_dropped_borderline_not_in_provenance(self) -> None:
        """人工丢弃的用例不进 kept_provenance(它不在输出里)。"""
        outcome = refine.auto_refine(
            _candidate(2),
            _settings(),
            screener=_StubScreener(
                [ScreeningDecision.BORDERLINE, ScreeningDecision.KEEP]
            ),
            input_stream=io.StringIO("d\n"),
        )
        assert outcome.kept_provenance == [refine.PROVENANCE_AUTO]
        assert len(outcome.final["test_cases"]) == 1

    def test_missing_verdict_is_treated_as_borderline(self) -> None:
        """verdict 缺失也要问人,不能静默处置(FR-008 精神)。"""
        outcome = refine.auto_refine(
            _candidate(2),
            _settings(),
            screener=_StubScreener([ScreeningDecision.KEEP]),  # 只给 1 条 verdict
            input_stream=io.StringIO("y\n"),
        )
        assert outcome.human_reviewed == 1


# ---------------------------------------------------------------------------
# FR-011:borderline 占比告警 (T016)
# ---------------------------------------------------------------------------


class TestBorderlineRatioWarning:
    def test_warns_when_ratio_exceeds_limit(self) -> None:
        outcome = refine.auto_refine(
            _candidate(2),
            _settings(borderline_ratio_warn=0.4),
            screener=_StubScreener(
                [ScreeningDecision.BORDERLINE, ScreeningDecision.BORDERLINE]
            ),
            input_stream=io.StringIO("y\ny\n"),
        )
        assert outcome.screening.borderline_ratio == 1.0
        assert len(outcome.warnings) == 1
        assert "borderline ratio" in outcome.warnings[0]

    def test_no_warning_when_within_limit(self) -> None:
        outcome = refine.auto_refine(
            _candidate(4),
            _settings(borderline_ratio_warn=0.4),
            screener=_StubScreener(
                [
                    ScreeningDecision.KEEP,
                    ScreeningDecision.KEEP,
                    ScreeningDecision.KEEP,
                    ScreeningDecision.BORDERLINE,
                ]
            ),
            input_stream=io.StringIO("y\n"),
        )
        assert outcome.screening.borderline_ratio == 0.25
        assert outcome.warnings == []

    def test_warning_does_not_change_exit_code(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """告警是提示性的 —— 仍然写出文件、退出码仍为 0。"""
        code, out_path = _run_main(
            monkeypatch,
            tmp_path,
            _candidate(2),
            argv_extra=["--auto-mode"],
            settings=_settings(borderline_ratio_warn=0.4),
            screener=_StubScreener(
                [ScreeningDecision.BORDERLINE, ScreeningDecision.BORDERLINE]
            ),
            stdin_text="y\ny\n",
        )
        assert code == 0
        assert out_path.exists()


# ---------------------------------------------------------------------------
# FR-010:auto 模式中断保住进度 (T016)
# ---------------------------------------------------------------------------


class TestInterruptPreservesProgress:
    def test_quit_marks_partial_and_keeps_prior_decisions(self) -> None:
        """q 退出:已完成的自动决策与人工决策都要保住。"""
        outcome = refine.auto_refine(
            _candidate(4),
            _settings(),
            screener=_StubScreener(
                [
                    ScreeningDecision.KEEP,        # auto 保留
                    ScreeningDecision.BORDERLINE,  # 人工 y
                    ScreeningDecision.BORDERLINE,  # 人工 q → 停
                    ScreeningDecision.KEEP,        # 未处理
                ]
            ),
            input_stream=io.StringIO("y\nq\n"),
        )
        assert outcome.partial is True
        assert outcome.final["version"] == "v0.9-partial"
        assert len(outcome.final["test_cases"]) == 2
        assert outcome.kept_provenance == [refine.PROVENANCE_AUTO, refine.PROVENANCE_HUMAN]

    def test_keyboard_interrupt_preserves_progress(self) -> None:
        """Ctrl-C:FR-010 要求已完成决策不丢。

        默认交互模式的中断行为保持原样(不保存),仅 auto 模式保住进度,
        以免违反 FR-004。
        """

        class _InterruptingStream:
            def __init__(self) -> None:
                self.reads = 0

            def readline(self) -> str:
                self.reads += 1
                if self.reads == 1:
                    return "y\n"
                raise KeyboardInterrupt

        outcome = refine.auto_refine(
            _candidate(4),
            _settings(),
            screener=_StubScreener(
                [
                    ScreeningDecision.KEEP,
                    ScreeningDecision.BORDERLINE,
                    ScreeningDecision.BORDERLINE,
                    ScreeningDecision.KEEP,
                ]
            ),
            input_stream=_InterruptingStream(),
        )
        assert outcome.interrupted is True
        assert outcome.partial is True
        assert outcome.final["version"] == "v0.9-partial"
        assert len(outcome.final["test_cases"]) == 2

    def test_quit_exits_0_and_writes_partial_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """q 是**正常的保存退出**,退出码 0,文件标为 partial。"""
        code, out_path = _run_main(
            monkeypatch,
            tmp_path,
            _candidate(3),
            argv_extra=["--auto-mode"],
            settings=_settings(),
            screener=_StubScreener(
                [
                    ScreeningDecision.KEEP,
                    ScreeningDecision.BORDERLINE,
                    ScreeningDecision.BORDERLINE,
                ]
            ),
            stdin_text="q\n",
        )
        assert code == 0
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        assert payload["version"] == "v0.9-partial"
        assert len(payload["test_cases"]) == 1

    def test_ctrl_c_exits_130_but_still_writes_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Ctrl-C → 退出码 130,**但文件必须已写出**,否则进度还是丢了。

        这是 FR-010 与 cli_contract § 3.3 的核心:auto 模式下中断不等于放弃。
        """
        in_path = tmp_path / "candidate.json"
        in_path.write_text(json.dumps(_candidate(3), ensure_ascii=False), encoding="utf-8")
        out_path = tmp_path / "golden.json"

        class _InterruptingStdin:
            """第一次读正常返回,第二次抛 KeyboardInterrupt。"""

            def __init__(self) -> None:
                self.reads = 0

            def readline(self) -> str:
                self.reads += 1
                if self.reads == 1:
                    return "y\n"
                raise KeyboardInterrupt

        monkeypatch.setattr(
            "sys.argv",
            [
                "refine_testset.py",
                "--input",
                str(in_path),
                "--output",
                str(out_path),
                "--auto-mode",
            ],
        )
        monkeypatch.setattr("sys.stdin", _InterruptingStdin())
        monkeypatch.setattr("src.core.settings.load_settings", lambda: _settings())
        monkeypatch.setattr(
            refine,
            "auto_refine",
            _auto_refine_with(
                _StubScreener(
                    [
                        ScreeningDecision.KEEP,
                        ScreeningDecision.BORDERLINE,
                        ScreeningDecision.BORDERLINE,
                    ]
                )
            ),
        )

        code = refine.main()

        assert code == 130
        assert out_path.exists(), "中断后必须已落盘,否则 FR-010 形同虚设"
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        assert payload["version"] == "v0.9-partial"
        # 1 条 auto-keep + 1 条人工 y,第 3 条被中断
        assert len(payload["test_cases"]) == 2
