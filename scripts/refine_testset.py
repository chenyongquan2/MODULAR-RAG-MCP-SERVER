"""US2 候选精修 CLI (T021, refs FR-005 / contracts/cli_contracts.md § 3)。

读 candidate JSON,逐条 prompt y/e/d/s/q,产出 final golden_test_set_<lang>.json。
失去网络连接 / Ctrl-C 时保存进度后退出。

退出码:
    0 = 精修完成,final 金标已写出
    1 = 输入文件不存在或非法
    130 = 用户 Ctrl-C(进度部分保存)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.observability.logger import get_logger

logger = get_logger(__name__)

# Windows 默认 stdout 用 GBK 编码,遇到非 ASCII 字符(中文 / NBSP \xa0)会炸。
# 强制 UTF-8 让 case 预览正常打印(MT5 中文语料 / RAGAS 输出常含此类字符)。
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass  # Python 3.6 及以下没有 reconfigure;此分支不会发生(项目 >= 3.10)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactively refine candidate testset (Feature-001 US2 step 2)"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to candidate JSON (from synthesize_testset.py)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help=(
            "Output path (default: tests/fixtures/golden_test_set_<lang>.json, "
            "where <lang> comes from candidate's 'language' field)"
        ),
    )
    parser.add_argument(
        "--mode",
        choices=["interactive", "batch"],
        default="interactive",
        help="Refine mode (only 'interactive' supported in MVP)",
    )
    # --- Feature-003 新增 ---
    parser.add_argument(
        "--auto-mode",
        action="store_true",
        help=(
            "Screen every case with a cross-source LLM first and only prompt for "
            "borderline ones. Requires evaluation.screening_llm.* to be configured "
            "and to differ from the synthesis judge. Omit for the original "
            "case-by-case interactive flow."
        ),
    )
    parser.add_argument(
        "--allow-same-source",
        action="store_true",
        help=(
            "Proceed in auto mode even when the candidate does not record which LLM "
            "synthesized it, so cross-source cannot be verified. Does NOT bypass a "
            "confirmed same-source config."
        ),
    )
    parser.add_argument(
        "--skip-compliance-sample",
        action="store_true",
        help=(
            "Skip the closing 10%% spot-check of kept cases. The golden set is still "
            "written, but its audit record will carry compliance=null and a warning: "
            "the SC-002 quality gate was never evaluated."
        ),
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Interactive prompt loop
# ---------------------------------------------------------------------------


def _short(text: str, n: int = 100) -> str:
    """缩写文本到 n 字符,加省略号。"""
    text = text.strip()
    return text if len(text) <= n else text[:n] + "..."


def _format_case_for_review(case: dict[str, Any], idx: int, total: int) -> str:
    contexts = case.get("_synth_contexts", [])
    ctx_preview = "\n    ".join(_short(c, 80) for c in contexts[:3])
    if len(contexts) > 3:
        ctx_preview += f"\n    ...(+{len(contexts) - 3} more)"
    tags = case.get("tags", {})
    return (
        f"\n[{idx + 1}/{total}] difficulty={tags.get('difficulty', '?')} "
        f"language={tags.get('language', '?')} content_type={tags.get('content_type', '?')}\n"
        f"  query: {case.get('query', '')}\n"
        f"  ground_truth: {_short(case.get('ground_truth', ''), 200)}\n"
        f"  contexts:\n    {ctx_preview}\n"
    )


def _edit_case_in_editor(case: dict[str, Any]) -> dict[str, Any] | None:
    """启动 $EDITOR 编辑当前 case 的 JSON;保存后返回新 case,取消返回 None。"""
    editor = os.environ.get("EDITOR") or ("notepad" if os.name == "nt" else "vi")
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", encoding="utf-8", delete=False
    ) as tmp:
        json.dump(case, tmp, ensure_ascii=False, indent=2)
        tmp_path = tmp.name
    try:
        subprocess.run([editor, tmp_path], check=True)
        with open(tmp_path, "r", encoding="utf-8") as f:
            edited = json.load(f)
        return edited
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"  ! edit failed: {exc}; keeping original", file=sys.stderr)
        return None
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _strip_synth_artifacts(case: dict[str, Any]) -> dict[str, Any]:
    """删除 candidate 阶段的临时字段(如 _synth_contexts),输出 final 格式。"""
    return {k: v for k, v in case.items() if not k.startswith("_synth")}


def _read_decision(stream: Any) -> str:
    """打印提示并读取一个合法选项,返回 y/e/d/s/q 之一。

    空输入等同于 ``y``(保留原有默认行为)。无法识别的输入会重新提示,
    直到读到合法选项。

    Args:
        stream: 输入流(测试时注入)。

    Returns:
        单字符选项:``y`` / ``e`` / ``d`` / ``s`` / ``q``。
    """
    while True:
        print(
            "  [y]keep / [e]edit / [d]drop / [s]skip / [q]quit-and-save: ",
            end="",
            flush=True,
        )
        choice = (stream.readline() or "").strip().lower()
        if not choice:
            return "y"
        if choice in {"y", "e", "d", "s", "q"}:
            return choice
        print(f"  ! unrecognized choice {choice!r}; please re-enter")


def _apply_decision(
    choice: str,
    case: dict[str, Any],
    kept: list[dict[str, Any]],
    counts: dict[str, int],
) -> bool:
    """把一个人工选项应用到 kept / counts 上(不处理 ``q``)。

    Args:
        choice: ``y`` / ``e`` / ``d`` / ``s``。
        case: 当前用例。
        kept: 保留列表(原地追加)。
        counts: 计数字典(原地累加)。

    Returns:
        该用例是否被保留(供调用方记录决策来源)。
    """
    if choice == "y":
        kept.append(_strip_synth_artifacts(case))
        counts["keep"] += 1
        return True
    if choice == "e":
        edited = _edit_case_in_editor(case)
        if edited is not None:
            kept.append(_strip_synth_artifacts(edited))
            counts["edit"] += 1
        else:
            kept.append(_strip_synth_artifacts(case))
            counts["keep"] += 1
        return True
    if choice == "d":
        counts["drop"] += 1
        return False
    # choice == "s"
    counts["skip"] += 1
    return False


def interactive_refine(
    candidate: dict[str, Any],
    input_stream: Any = None,
) -> dict[str, Any]:
    """逐条 prompt y/e/d/s/q,返回 final golden test set。

    Args:
        candidate: 合成阶段产出的 candidate dict。
        input_stream: 用于测试时注入 stdin(默认 sys.stdin)。

    Note:
        Feature-003 把逐条提示与选项应用抽成 ``_read_decision`` /
        ``_apply_decision`` 供 auto 模式复用,**行为与抽取前完全一致**
        (空输入仍等同 y、无法识别仍重新提示、q 仍保存部分进度)。
    """
    stream = input_stream if input_stream is not None else sys.stdin

    cases = candidate.get("test_cases", [])
    kept: list[dict[str, Any]] = []
    counts = {"keep": 0, "edit": 0, "drop": 0, "skip": 0}

    for idx, case in enumerate(cases):
        print(_format_case_for_review(case, idx, len(cases)))
        choice = _read_decision(stream)
        if choice == "q":
            print(f"  saving progress and quitting at case {idx + 1}/{len(cases)}")
            return _build_final(candidate, kept, counts, partial=True)
        _apply_decision(choice, case, kept, counts)

    return _build_final(candidate, kept, counts, partial=False)


def _build_final(
    candidate: dict[str, Any],
    kept_cases: list[dict[str, Any]],
    counts: dict[str, int],
    partial: bool,
    review_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造 final golden_test_set JSON。

    Args:
        candidate: 输入 candidate。
        kept_cases: 保留的用例(已剥离 _synth_* 字段)。
        counts: keep/edit/drop/skip 计数。
        partial: 是否为部分结果。
        review_metadata: Feature-003 的审计记录。``None``(默认交互模式)时
            **不写出该字段**,保证既有输出结构逐字节不变(FR-004)。

    Note:
        ``_schema_version`` 固定为 1、``_refine_summary`` 保持四键 —— 两者均被
        既有测试直接断言,新增字段不得触发变更(research § Decision 3)。
    """
    final: dict[str, Any] = {
        "_schema_version": 1,
        "language": candidate.get("language", "mixed"),
        "version": "v1.0" if not partial else "v0.9-partial",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_corpus_collection": candidate.get("_synthesis_metadata", {}).get(
            "source_collection", ""
        ),
        "_refine_summary": dict(counts),
        "test_cases": kept_cases,
    }
    if review_metadata is not None:
        final["_review_metadata"] = review_metadata
    return final


# ---------------------------------------------------------------------------
# auto 模式 (Feature-003 US1)
# ---------------------------------------------------------------------------

# 退出码(见 specs/003-testset-refine-automation/contracts/cli_contract.md § 2)
EXIT_OK = 0
EXIT_BAD_INPUT = 1
EXIT_AUTO_PRECONDITION = 2
EXIT_SCREENING_UNAVAILABLE = 3
EXIT_INTERRUPTED = 130

# 决策来源常量的单一来源在 src 侧,这里重导出供脚本与其测试使用
from src.observability.evaluation.testset_screener import (  # noqa: E402
    PROVENANCE_AUTO,
    PROVENANCE_HUMAN,
)


class AutoRefineOutcome:
    """auto 模式的一次运行结果。

    Attributes:
        final: 待落盘的 golden test set(尚未注入 ``_review_metadata``,
            该注入是 US2 的职责)。
        screening: 批量预筛结果(含 verdict 列表与 borderline 占比)。
        kept_provenance: 与 ``final["test_cases"]`` **同序**的决策来源列表,
            取值 ``"auto"`` / ``"human"``。US3 的 SC-006 拆分靠它反查
            —— 抽中的用例到底是机器决定的还是人工确认过的。
        auto_decided: 机器自动决策数(自动保留 + 自动丢弃)。
        human_reviewed: 经人工处置数。
        warnings: 本次运行触发的告警(如 borderline 占比超限)。
        partial: 是否为中断/提前退出产生的部分结果。
        interrupted: 是否因 Ctrl-C 中断(供 main 返回 130)。

    Note:
        **这里刻意不用 ``@dataclass``**。本脚本被单测用
        ``importlib.util.spec_from_file_location`` 动态加载且不注册进
        ``sys.modules``;而 ``@dataclass`` 在处理类型注解时会去查
        ``sys.modules[cls.__module__]``,取到 ``None`` 后抛
        ``AttributeError: 'NoneType' object has no attribute '__dict__'``,
        导致整个测试模块无法收集。改动本文件时请勿引入 dataclass。
    """

    def __init__(
        self,
        final: dict[str, Any],
        screening: Any,
        kept_provenance: list[str] | None = None,
        auto_decided: int = 0,
        human_reviewed: int = 0,
        warnings: list[str] | None = None,
        partial: bool = False,
        interrupted: bool = False,
    ) -> None:
        self.final = final
        self.screening = screening
        self.kept_provenance = kept_provenance if kept_provenance is not None else []
        self.auto_decided = auto_decided
        self.human_reviewed = human_reviewed
        self.warnings = warnings if warnings is not None else []
        self.partial = partial
        self.interrupted = interrupted


def check_auto_preconditions(
    settings: Any,
    candidate: dict[str, Any],
    allow_same_source: bool,
) -> str | None:
    """校验 auto 模式的前置条件 (FR-002)。

    Args:
        settings: 全局 Settings。
        candidate: 已解析的 candidate dict。
        allow_same_source: 是否允许在「无法确认异源」时继续。

    Returns:
        ``None`` 表示可以继续;否则返回应打印给用户的错误说明。
    """
    from src.observability.evaluation.testset_screener import (
        SourceRelation,
        check_source_divergence,
    )

    screening = settings.evaluation.screening_llm
    if not screening.is_enabled():
        return (
            "auto mode requires evaluation.screening_llm.provider and .model to be set "
            "in config/settings.yaml (they are empty by default).\n"
            "  See specs/003-testset-refine-automation/quickstart.md for a working example,\n"
            "  or drop --auto-mode to use the original interactive flow."
        )

    relation = check_source_divergence(settings, candidate)
    if relation is SourceRelation.SAME_SOURCE:
        from src.observability.evaluation._ragas_wrappers import get_screening_identifier

        return (
            f"screening LLM ({get_screening_identifier(settings)}) is the same model that "
            "synthesized this candidate.\n"
            "  Cross-source screening is the whole point: a model grading its own output "
            "shares its blind spots.\n"
            "  Change evaluation.screening_llm.model to a different model. "
            "--allow-same-source does NOT bypass this."
        )
    if relation is SourceRelation.UNVERIFIABLE and not allow_same_source:
        return (
            "this candidate does not record which LLM synthesized it "
            "(_synthesis_metadata.judge_llm_identifier is missing or empty), so "
            "cross-source cannot be verified.\n"
            "  Pass --allow-same-source to proceed anyway if you know the models differ."
        )
    return None


def _format_case_for_compliance(case: dict[str, Any], position: int, total: int) -> str:
    """抽样自检时展示一条待复核用例(对齐 SC-002 的三项结构标准)。"""
    chunk_ids = case.get("expected_chunk_ids") or []
    return (
        f"\n[spot-check {position}/{total}]\n"
        f"  question      : {case.get('query', '')}\n"
        f"  ground_truth  : {_short(case.get('ground_truth', ''), 200)}\n"
        f"  chunk ids     : {chunk_ids}\n"
        f"  Structurally compliant? (question reads well, ground truth is verifiable, "
        f"chunk ids present)"
    )


def run_compliance_sample(
    kept_cases: list[dict[str, Any]],
    kept_provenance: list[str],
    settings: Any,
    stream: Any,
) -> tuple[dict[str, Any] | None, list[str]]:
    """按 SC-002 抽样 10% 请人工确认结构合规性 (FR-006, FR-007)。

    Args:
        kept_cases: 最终保留的用例。
        kept_provenance: 与之同序的决策来源。
        settings: 全局 Settings。
        stream: 输入流。

    Returns:
        ``(compliance dict 或 None, 新增告警列表)``。保留用例为 0 时返回
        ``(None, [...])``。
    """
    from src.observability.evaluation.testset_screener import (
        pick_compliance_sample,
        summarize_compliance,
    )

    screening_cfg = settings.evaluation.screening_llm
    indices = pick_compliance_sample(len(kept_cases), screening_cfg.sample_ratio)
    if not indices:
        return None, ["no kept cases to spot-check; compliance gate not evaluated"]

    print(
        f"\nSpot-checking {len(indices)} of {len(kept_cases)} kept case(s) "
        f"({screening_cfg.sample_ratio:.0%} sample, per SC-002) ..."
    )
    flags: list[bool] = []
    for position, index in enumerate(indices, start=1):
        print(_format_case_for_compliance(kept_cases[index], position, len(indices)))
        print("  [y]compliant / [n]not compliant: ", end="", flush=True)
        answer = (stream.readline() or "").strip().lower()
        flags.append(not answer.startswith("n"))

    compliance = summarize_compliance(
        sampled_indices=indices,
        compliant_flags=flags,
        kept_provenance=kept_provenance,
        compliance_gate=screening_cfg.compliance_gate,
    )

    warnings: list[str] = []
    if not compliance["gate_passed"]:
        warning = (
            f"compliance rate {compliance['compliance_rate']:.0%} is below the "
            f"{screening_cfg.compliance_gate:.0%} gate (SC-002). Do NOT use this golden "
            f"set for acceptance until the underlying quality issue is addressed."
        )
        warnings.append(warning)
        print(f"  ! {warning}", file=sys.stderr)
    else:
        rate = compliance["compliance_rate"]
        print(f"  compliance {rate:.0%} — gate passed")

    return compliance, warnings


def auto_refine(
    candidate: dict[str, Any],
    settings: Any,
    screener: Any = None,
    input_stream: Any = None,
    skip_compliance_sample: bool = False,
) -> AutoRefineOutcome:
    """预筛 → 自动决策 + borderline 交人工 (FR-003, FR-008, FR-010, FR-011)。

    Args:
        candidate: 合成阶段产出的 candidate dict。
        settings: 全局 Settings。
        screener: 预筛器实例;``None`` = 按配置创建(测试可注入替身)。
        input_stream: 输入流(默认 sys.stdin)。

    Returns:
        本次运行结果。

    Raises:
        ScreeningUnavailableError: 预筛模型整体不可用(由 screen_all 抛出,
            main 将其映射为退出码 3)。
    """
    from src.observability.evaluation.testset_screener import (
        ScreeningDecision,
        TestsetScreener,
        build_review_metadata,
    )

    stream = input_stream if input_stream is not None else sys.stdin
    cases = candidate.get("test_cases", [])
    screening_cfg = settings.evaluation.screening_llm

    if screener is None:
        screener = TestsetScreener(settings)

    print(f"Screening {len(cases)} case(s) with a cross-source LLM ...")
    result = screener.screen_all(candidate)

    warnings: list[str] = []
    if result.borderline_ratio > screening_cfg.borderline_ratio_warn:
        warning = (
            f"borderline ratio {result.borderline_ratio:.0%} exceeds configured limit "
            f"{screening_cfg.borderline_ratio_warn:.0%} — screening barely narrowed the "
            f"work down. Consider lowering keep_threshold/drop_threshold or switching "
            f"the screening model."
        )
        warnings.append(warning)
        print(f"  ! {warning}", file=sys.stderr)

    print(
        f"  auto-keep {len(result.auto_keep_indices)} / "
        f"auto-drop {len(result.auto_drop_indices)} / "
        f"borderline {len(result.borderline_indices)} "
        f"-> {len(result.borderline_indices)} case(s) need you"
    )

    verdict_by_index = {v.case_index: v for v in result.verdicts}
    kept: list[dict[str, Any]] = []
    kept_provenance: list[str] = []
    counts = {"keep": 0, "edit": 0, "drop": 0, "skip": 0}
    auto_decided = 0
    human_reviewed = 0
    partial = False
    interrupted = False

    try:
        for idx, case in enumerate(cases):
            verdict = verdict_by_index.get(idx)

            # 没有判定结果的用例按 borderline 处理 —— 宁可多问一次,
            # 也不能因为查不到 verdict 就静默保留或丢弃(FR-008)
            if verdict is None or verdict.decision is ScreeningDecision.BORDERLINE:
                print(_format_case_for_review(case, idx, len(cases)))
                if verdict is not None and verdict.reason:
                    print(f"  screening says borderline: {verdict.reason}")
                choice = _read_decision(stream)
                if choice == "q":
                    print(f"  saving progress and quitting at case {idx + 1}/{len(cases)}")
                    partial = True
                    break
                if _apply_decision(choice, case, kept, counts):
                    kept_provenance.append(PROVENANCE_HUMAN)
                human_reviewed += 1
                continue

            if verdict.decision is ScreeningDecision.KEEP:
                kept.append(_strip_synth_artifacts(case))
                kept_provenance.append(PROVENANCE_AUTO)
                counts["keep"] += 1
            else:  # ScreeningDecision.DROP
                counts["drop"] += 1
            auto_decided += 1
    except KeyboardInterrupt:
        # FR-010:auto 模式下中断必须保住已完成的决策。默认交互模式的中断
        # 行为不变(见 main 的 KeyboardInterrupt 分支),以满足 FR-004。
        print("\n  interrupted; saving progress made so far", file=sys.stderr)
        partial = True
        interrupted = True

    # --- 抽样合规自检 (US3) ---
    compliance: dict[str, Any] | None = None
    if skip_compliance_sample:
        warnings.append(
            "compliance spot-check skipped via --skip-compliance-sample; "
            "the SC-002 quality gate was not evaluated"
        )
    elif partial:
        # 部分结果不是完整金标,对它抽样得出的合规率没有意义
        warnings.append(
            "run ended early, so the compliance spot-check was skipped; "
            "this is a partial result, not an acceptance-ready golden set"
        )
    else:
        try:
            compliance, sample_warnings = run_compliance_sample(
                kept, kept_provenance, settings, stream
            )
            warnings.extend(sample_warnings)
            # 抽样复核数**不**计入 human_reviewed —— 后者的语义是「精修阶段
            # 路由给人工的用例数」,与 auto_decided 相加须等于输入总数
            # (data-model § 3 的不变式)。SC-002 的「人工处置占比」应算作
            # (human_reviewed + compliance.sample_size) / 总数。
        except KeyboardInterrupt:
            print("\n  interrupted during spot-check; audit will note it", file=sys.stderr)
            warnings.append("compliance spot-check interrupted before completion")
            interrupted = True

    review_metadata = build_review_metadata(
        settings=settings,
        candidate=candidate,
        screening=result,
        auto_decided=auto_decided,
        human_reviewed=human_reviewed,
        dropped=counts["drop"],
        warnings=warnings,
        partial=partial,
        compliance=compliance,
    )

    return AutoRefineOutcome(
        final=_build_final(
            candidate, kept, counts, partial=partial, review_metadata=review_metadata
        ),
        screening=result,
        kept_provenance=kept_provenance,
        auto_decided=auto_decided,
        human_reviewed=human_reviewed,
        warnings=warnings,
        partial=partial,
        interrupted=interrupted,
    )


def warn_if_overwriting(output_path: Path) -> str | None:
    """auto 模式下覆盖既有金标前,把旧文件的合规率提示出来。

    spec Edge Cases「重复运行」担心的是:抽样有偶然性,二次运行可能把一份
    合规率更高的金标静默换成更差的。这里不阻断写入(与既有行为一致),
    但把可比信息摆到眼前,让覆盖成为知情决定。

    Args:
        output_path: 待写入路径。

    Returns:
        应记入审计的告警文本;无需告警时为 ``None``。
    """
    if not output_path.exists():
        return None

    prior_rate: Any = None
    try:
        prior = json.loads(output_path.read_text(encoding="utf-8"))
        prior_rate = (prior.get("_review_metadata") or {}).get("compliance", {})
        prior_rate = (prior_rate or {}).get("compliance_rate")
    except (OSError, json.JSONDecodeError, AttributeError):
        prior_rate = None

    if prior_rate is None:
        warning = (
            f"overwriting existing golden set at {output_path} "
            "(it carries no recorded compliance rate to compare against)"
        )
    else:
        warning = (
            f"overwriting existing golden set at {output_path}, whose recorded "
            f"compliance rate was {prior_rate:.0%}. Sampling is random, so a lower "
            f"rate this run does not necessarily mean lower quality — compare before "
            f"trusting either number."
        )
    print(f"  ! {warning}", file=sys.stderr)
    return warning


def _resolve_output_path(arg_output: str | None, lang: str) -> Path:
    if arg_output:
        return Path(arg_output)
    return Path("tests/fixtures") / f"golden_test_set_{lang}.json"


def main() -> int:
    args = parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        return 1
    try:
        candidate = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Error: input not valid JSON: {exc}", file=sys.stderr)
        return 1
    if "test_cases" not in candidate:
        print("Error: input missing 'test_cases' key", file=sys.stderr)
        return 1

    if args.mode != "interactive":
        print(f"Error: only 'interactive' mode supported in MVP", file=sys.stderr)
        return 1

    lang = candidate.get("language", "mixed")
    output_path = _resolve_output_path(args.output, lang)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    exit_code = EXIT_OK

    if args.auto_mode:
        # --- auto 模式 (Feature-003) ---
        # 仅本分支读取 settings / 触碰预筛模型;默认路径完全不受影响(FR-004)
        from src.core.settings import load_settings
        from src.observability.evaluation.testset_screener import ScreeningUnavailableError

        settings = load_settings()
        problem = check_auto_preconditions(settings, candidate, args.allow_same_source)
        if problem is not None:
            print(f"Error: {problem}", file=sys.stderr)
            return EXIT_AUTO_PRECONDITION

        overwrite_warning = warn_if_overwriting(output_path)

        try:
            outcome = auto_refine(
                candidate,
                settings,
                skip_compliance_sample=args.skip_compliance_sample,
            )
        except ScreeningUnavailableError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return EXIT_SCREENING_UNAVAILABLE

        final = outcome.final
        if overwrite_warning is not None:
            # 让覆盖这件事也留在审计记录里,而不只是一条转瞬即逝的 stderr
            final.setdefault("_review_metadata", {}).setdefault("warnings", []).append(
                overwrite_warning
            )
        if outcome.interrupted:
            exit_code = EXIT_INTERRUPTED
    else:
        # --- 默认交互模式:行为与 Feature-003 之前完全一致 ---
        try:
            final = interactive_refine(candidate)
        except KeyboardInterrupt:
            # Ctrl-C: 没有 already-built progress 状态,简单地把空集落盘
            print("\nInterrupted by user; no progress saved.", file=sys.stderr)
            return 130

    output_path.write_text(
        json.dumps(final, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary = final.get("_refine_summary", {})
    print(
        f"Refined: {summary.get('keep', 0)} kept, "
        f"{summary.get('edit', 0)} edited, "
        f"{summary.get('drop', 0)} dropped, "
        f"{summary.get('skip', 0)} skipped "
        f"-> {output_path}"
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
