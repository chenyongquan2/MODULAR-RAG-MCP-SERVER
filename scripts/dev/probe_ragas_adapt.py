"""T-3.1 探针：候选模型能否真的完成 RAGAS 中文 adapt。

change: expand-chinese-golden-set

## 为什么需要这个探针

项目记录说 `minimax/minimax-m2.7` 做不到中文 adapt。但本会话证明了另一件事：
项目当初把 judge 从 `glm-4.7` 换成 minimax 的理由（「GLM 系对 JSON schema
遵从差」）**至少在标注任务上是误诊** —— 真实原因是 `max_tokens` 给少了。

所以「GLM 做不了中文 adapt」很可能是同一个误诊。**但不能因此反向假设 GLM
一定行** —— 那是把误诊的教训套成另一个未验证假设。用实测定。

## 必须一个模型一个进程

RAGAS 的 `simple` / `reasoning` / `multi_context` 是**模块级可变单例**。
2026-08-16 首轮实测：minimax 那一轮把它们**就地**改成了「已适配」状态，导致
后两个模型的 `adapt()` 一看已适配就立刻返回 —— 3 秒、0 文件、不报错，看起来
像「也失败了」，实际根本没跑。**同进程内串测多个模型的结果无效。**

## 用法

    # 单个模型（必须这样跑，进程隔离）
    PROBE_MODEL=minimax/minimax-m2.7 python -u scripts/dev/probe_ragas_adapt.py

一次性探索脚本（`scripts/dev/`，按 CLAUDE.md 的 SDD 例外清单不走 SDD 流程）。
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import time
from pathlib import Path
from typing import Dict, List

from src.core.settings import load_settings
from src.observability.evaluation.language_check import check_language

_ALL_CANDIDATES: List[str] = [
    "minimax/minimax-m2.7",
    "z-ai/glm-5.2",
    "z-ai/glm-5.2-free",
]

# PROBE_MODEL 指定单个模型；不设则跑全部（**但那样只有第一个有效**）
CANDIDATES: List[str] = (
    [os.environ["PROBE_MODEL"]] if os.environ.get("PROBE_MODEL") else _ALL_CANDIDATES
)

RAGAS_LANG = "chinese"
LANG_CODE = "zh"
EVOLUTIONS_TO_ADAPT = ("simple", "reasoning", "multi_context")


def _cache_ratio(cache_dir: Path) -> Dict[str, float]:
    """算缓存目录里每个提示词文件的目标语言字符占比。"""
    out: Dict[str, float] = {}
    for f in sorted(glob.glob(str(cache_dir / "*.json"))):
        text = Path(f).read_text(encoding="utf-8")
        out[os.path.basename(f)] = check_language(text, LANG_CODE, 0.05).ratio
    return out


def probe(model: str, settings) -> Dict[str, object]:
    """对单个模型跑一次 adapt，返回实测结果。"""
    from copy import copy
    from dataclasses import replace

    cache_root = Path("./logs/ragas_adapt_probe").resolve() / model.replace("/", "_")
    if cache_root.exists():
        shutil.rmtree(cache_root)
    (cache_root / RAGAS_LANG).mkdir(parents=True, exist_ok=True)

    # ⚠️ 覆写的必须是 evaluation.judge_llm，**不是 settings.llm**。
    # TestsetSynthesizer._ensure_generator() 走 build_ragas_judge(settings)，
    # 后者只读 settings.evaluation.judge_llm。首版探针改的是 settings.llm ——
    # 那个字段在这条路径上根本没人读，于是三轮实测跑的全是 judge_llm 里配的
    # minimax，结果无效（2026-08-16，从 GLM LLM initialized 的日志行发现）。
    # copy() 是浅拷贝，必须连 evaluation 一起复制，否则会污染原 settings。
    shim = copy(settings)
    shim.evaluation = copy(settings.evaluation)
    shim.evaluation.judge_llm = replace(
        settings.evaluation.judge_llm, model=model, request_timeout_sec=180
    )

    # 自证：确认覆写真的落到了合成端会读的那个字段。首版探针缺这一步，
    # 于是「换了模型」这件事从头到尾没被验证过。
    from src.observability.evaluation._ragas_wrappers import get_judge_identifier

    effective = get_judge_identifier(shim)
    expected = f"{settings.evaluation.judge_llm.provider}:{model}"
    if effective != expected:
        raise RuntimeError(
            f"shim did not take effect: effective judge={effective!r}, "
            f"expected={expected!r}. The probe would have measured the wrong model."
        )
    print(f"[probe] effective judge = {effective}", flush=True)

    result: Dict[str, object] = {"model": model, "effective_judge": effective}
    started = time.monotonic()
    try:
        from src.observability.evaluation.testset_synthesizer import TestsetSynthesizer

        synth = TestsetSynthesizer(shim)
        synth._ensure_generator()  # noqa: SLF001 —— 探针脚本，允许

        from ragas.testset.evolutions import multi_context, reasoning, simple

        evo = {"simple": simple, "reasoning": reasoning, "multi_context": multi_context}
        synth._generator.adapt(  # noqa: SLF001
            language=RAGAS_LANG,
            evolutions=[evo[k] for k in EVOLUTIONS_TO_ADAPT],
            cache_dir=str(cache_root),
        )
        result["adapt_raised"] = False
    except Exception as exc:  # noqa: BLE001 —— 探针要记录失败而非中断
        result["adapt_raised"] = True
        result["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"

    result["elapsed_sec"] = round(time.monotonic() - started, 1)
    ratios = _cache_ratio(cache_root / RAGAS_LANG)
    result["file_ratios"] = ratios
    result["files"] = len(ratios)
    result["max_ratio"] = max(ratios.values()) if ratios else 0.0
    result["min_ratio"] = min(ratios.values()) if ratios else 0.0
    threshold = settings.evaluation.synthesis.adapt_language_ratio_min
    # 判据：所有产出文件都达标才算真的能做中文 adapt。
    # 「没有产物」也判 FAIL —— 没有东西可以证明翻译成功。
    result["verdict"] = (
        "PASS" if ratios and all(r >= threshold for r in ratios.values()) else "FAIL"
    )
    return result


def main() -> int:
    settings = load_settings()
    threshold = settings.evaluation.synthesis.adapt_language_ratio_min
    print(f"[probe] threshold={threshold:.0%}  candidates={CANDIDATES}", flush=True)
    if len(CANDIDATES) > 1:
        print(
            "[probe] WARNING: multiple models in ONE process gives INVALID "
            "results for all but the first (RAGAS evolutions are module-level "
            "mutable singletons). Set PROBE_MODEL and run one per process.",
            flush=True,
        )

    results = []
    for model in CANDIDATES:
        print(f"[probe] === {model} ===", flush=True)
        r = probe(model, settings)
        results.append(r)
        print(
            f"[probe] {model}: verdict={r['verdict']} "
            f"raised={r.get('adapt_raised')} files={r['files']} "
            f"ratio min={r['min_ratio']:.1%} max={r['max_ratio']:.1%} "
            f"({r['elapsed_sec']}s)",
            flush=True,
        )
        if r.get("error"):
            print(f"[probe]   error: {r['error']}", flush=True)
        for name, ratio in (r.get("file_ratios") or {}).items():
            print(f"[probe]   {name:32s} {ratio:.1%}", flush=True)

    tag = os.environ.get("PROBE_MODEL", "all").replace("/", "_")
    out = Path(f"logs/ragas_adapt_probe/summary_{tag}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[probe] summary -> {out}", flush=True)

    passed = [r["model"] for r in results if r["verdict"] == "PASS"]
    print(f"[probe] PASS: {passed or '(none)'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
