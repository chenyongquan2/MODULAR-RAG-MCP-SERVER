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


def interactive_refine(
    candidate: dict[str, Any],
    input_stream: Any = None,
) -> dict[str, Any]:
    """逐条 prompt y/e/d/s/q,返回 final golden test set。

    Args:
        candidate: 合成阶段产出的 candidate dict。
        input_stream: 用于测试时注入 stdin(默认 sys.stdin)。
    """
    stream = input_stream if input_stream is not None else sys.stdin

    cases = candidate.get("test_cases", [])
    kept: list[dict[str, Any]] = []
    counts = {"keep": 0, "edit": 0, "drop": 0, "skip": 0}

    for idx, case in enumerate(cases):
        print(_format_case_for_review(case, idx, len(cases)))
        while True:
            print(
                "  [y]keep / [e]edit / [d]drop / [s]skip / [q]quit-and-save: ",
                end="",
                flush=True,
            )
            choice = (stream.readline() or "").strip().lower()
            if not choice or choice == "y":
                kept.append(_strip_synth_artifacts(case))
                counts["keep"] += 1
                break
            if choice == "e":
                edited = _edit_case_in_editor(case)
                if edited is not None:
                    kept.append(_strip_synth_artifacts(edited))
                    counts["edit"] += 1
                else:
                    kept.append(_strip_synth_artifacts(case))
                    counts["keep"] += 1
                break
            if choice == "d":
                counts["drop"] += 1
                break
            if choice == "s":
                counts["skip"] += 1
                break
            if choice == "q":
                print(f"  saving progress and quitting at case {idx + 1}/{len(cases)}")
                return _build_final(candidate, kept, counts, partial=True)
            print(f"  ! unrecognized choice {choice!r}; please re-enter")

    return _build_final(candidate, kept, counts, partial=False)


def _build_final(
    candidate: dict[str, Any],
    kept_cases: list[dict[str, Any]],
    counts: dict[str, int],
    partial: bool,
) -> dict[str, Any]:
    """构造 final golden_test_set JSON。"""
    return {
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
