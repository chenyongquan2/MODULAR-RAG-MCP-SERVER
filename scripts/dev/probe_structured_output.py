"""探针：本项目的网关到底支持哪一档结构化输出。

## 为什么需要这个探针

项目现在三处 LLM 判定（预筛 / 标注 / RAGAS judge）全走「提示词请求 JSON +
容错解析」这条最脆弱的路（见 docs/learning/structured-output-explained.md §8）。
更可靠的两条路是否可用，**取决于网关而不是模型** —— `glm` 是 OpenAI 兼容端点、
路由到 minimax/claude 等上游，参数在链路上任何一跳被吃掉，结果都是「没生效」。

上游文档说支持，推不出这个网关支持。只能实测。

## 关键设计：必须校验「返回结构」，不能只看「有没有报错」

兼容端点的典型失效是**静默的** —— 参数被接受、请求成功、但被忽略，返回一段
普通文本。所以每种模式都要检查可观测的效果：

  json_schema  → 内容是否严格符合 schema（且在**诱导违规**的提示词下仍然符合）
  tools        → 响应里是否真的出现 tool_calls，而非退化成 content 文本

## 单次成功不等于「约束生效」

模型自愿遵守和被约束解码强制，单看一次成功的输出无法区分。所以每种模式都用
两个提示词跑：

  neutral      → 正常判定请求
  adversarial  → 额外要求「先详细解释思路再给判定」

真正的约束解码在 adversarial 下**物理上吐不出散文**；只是自愿遵守的模型会
破功（吐前言、吐 markdown 围栏、吐解释）。这一对的差异才是判据。

## 用法

    # 全部（读 settings 里配置的 4 个模型）
    python -u scripts/dev/probe_structured_output.py

    # 指定模型
    python -u scripts/dev/probe_structured_output.py --models minimax/minimax-m2.7

    # 只测某几种模式
    python -u scripts/dev/probe_structured_output.py --modes json_schema tools

成本：每模型每模式 2 次调用，提示词都很短。默认 4 模型 × 4 模式 × 2 = 32 次。

一次性探索脚本（`scripts/dev/`，按 CLAUDE.md 的 SDD 例外清单不走 SDD 流程）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import OpenAI

from src.core.settings import load_settings

OUT_DIR = Path("logs/structured_output_probe")

# --------------------------------------------------------------------------
# 判定契约 —— 刻意照抄 testset_screener 的三字段结构，让探针结论能直接迁移
# --------------------------------------------------------------------------

# 注意字段顺序：reason 在最前。见学习笔记 §6.1 —— 自回归模型先写 reason
# 等于在 JSON 内部完成 CoT；reason 在后只是事后编理由。
VERDICT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "reason": {"type": "string"},
        "decision": {"type": "string", "enum": ["keep", "drop", "borderline"]},
        "confidence": {"type": "number"},
    },
    # OpenAI strict 模式要求：全部字段 required + 禁止额外字段
    "required": ["reason", "decision", "confidence"],
    "additionalProperties": False,
}

_CASE = (
    "QUESTION: What does the HistorySelectByLogins method return?\n"
    "GROUND TRUTH: It returns the trade history records for the given logins.\n"
    "CONTEXT: HistorySelectByLogins(logins, total) retrieves closed order "
    "records for the specified login list and writes the count into total."
)

_NEUTRAL = (
    "You are screening a RAG golden test case. Decide keep / drop / borderline.\n\n"
    f"{_CASE}\n\n"
    'Respond with JSON: {"reason": "...", "decision": "...", "confidence": 0.0}'
)

# 诱导违规：明确要求先写散文。真被约束解码卡住的模型做不到这件事。
_ADVERSARIAL = (
    "You are screening a RAG golden test case. Decide keep / drop / borderline.\n\n"
    f"{_CASE}\n\n"
    "First explain your reasoning in two or three sentences of plain prose, "
    "then give the verdict as JSON "
    '{"reason": "...", "decision": "...", "confidence": 0.0}'
)

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


# --------------------------------------------------------------------------
# 结果模型
# --------------------------------------------------------------------------

# 四种结局。SILENTLY_IGNORED 是最危险的那个 —— 请求成功、参数无效、
# 调用方毫无察觉，正是本项目多次踩过的「静默失效」形状。
STATUS_OK = "SUPPORTED"
STATUS_IGNORED = "SILENTLY_IGNORED"
STATUS_REJECTED = "REJECTED"
STATUS_TRUNCATED = "TRUNCATED"   # 输出没写完 —— 是预算问题，不是能力问题
STATUS_TRANSIENT = "TRANSIENT"   # 429 / 5xx —— 重试后仍失败才记
STATUS_ERROR = "ERROR"


@dataclass
class Probe:
    model: str
    mode: str
    prompt_kind: str
    status: str
    detail: str
    latency_ms: int = 0
    raw_preview: str = ""
    parsed_ok: bool = False
    schema_ok: bool = False
    pure_json: bool = False
    # 归因三件套。缺了这些，「空响应」是一个无法诊断的黑洞 ——
    # 项目已经在 max_tokens=200 那次踩过一模一样的坑。
    finish_reason: str = ""
    completion_tokens: int = 0
    reasoning_tokens: int = 0


@dataclass
class Target:
    label: str          # 配置里的来源，如 evaluation.judge_llm
    model: str
    api_key: str = field(repr=False, default="")
    base_url: Optional[str] = None


# --------------------------------------------------------------------------
# 校验：内容到底符不符合契约
# --------------------------------------------------------------------------


def _inspect_content(text: str) -> Dict[str, Any]:
    """检查一段返回文本：是不是纯 JSON、能不能解析、符不符合 schema。

    ``pure_json`` 是关键指标 —— 它意味着**整段内容就是 JSON**，没有围栏、
    没有前言。约束解码下这一项必然为 True；靠自觉遵守的模型在 adversarial
    提示词下通常会破功。
    """
    stripped = (text or "").strip()
    result = {"pure_json": False, "parsed_ok": False, "schema_ok": False, "note": ""}

    if not stripped:
        result["note"] = "空响应（注意排查 max_tokens）"
        return result

    # 先判「纯 JSON」：不剥围栏、不做截取，整段直接解析
    try:
        obj = json.loads(stripped)
        result["pure_json"] = True
        result["parsed_ok"] = True
    except (json.JSONDecodeError, ValueError):
        # 退回到项目现在的容错解析口径（剥围栏 / 截取对象），
        # 能解析出来说明「模型愿意配合，但没有任何机制约束它」
        candidate = stripped
        fenced = _FENCE_RE.match(candidate)
        if fenced:
            candidate = fenced.group(1).strip()
            result["note"] = "带 markdown 围栏"
        try:
            obj = json.loads(candidate)
            result["parsed_ok"] = True
        except (json.JSONDecodeError, ValueError):
            match = re.search(r"\{.*\}", candidate, re.DOTALL)
            if not match:
                result["note"] = "无法解析出 JSON 对象"
                return result
            try:
                obj = json.loads(match.group(0))
                result["parsed_ok"] = True
                result["note"] = "JSON 前后夹带文字"
            except (json.JSONDecodeError, ValueError):
                result["note"] = "无法解析出 JSON 对象"
                return result

    if not isinstance(obj, dict):
        result["note"] = f"顶层不是对象（是 {type(obj).__name__}）"
        return result

    # schema 一致性：字段齐 + 类型对 + 枚举合法 + 无额外字段
    problems: List[str] = []
    for key in ("reason", "decision", "confidence"):
        if key not in obj:
            problems.append(f"缺字段 {key}")
    if not problems:
        if not isinstance(obj.get("reason"), str):
            problems.append("reason 非 string")
        if obj.get("decision") not in ("keep", "drop", "borderline"):
            problems.append(f"decision 非法值 {obj.get('decision')!r}")
        # bool 是 int 的子类，但不是合法置信度
        conf = obj.get("confidence")
        if isinstance(conf, bool) or not isinstance(conf, (int, float)):
            problems.append("confidence 非 number")
        extra = set(obj) - {"reason", "decision", "confidence"}
        if extra:
            problems.append(f"多余字段 {sorted(extra)}")

    result["schema_ok"] = not problems
    if problems:
        result["note"] = "; ".join(problems)
    return result


# --------------------------------------------------------------------------
# 四种模式
# --------------------------------------------------------------------------


MAX_TOKENS = 3000  # 首轮 800 时 glm-5.2-free 大面积空响应，抬高以排除预算因素


def _call(client: OpenAI, model: str, prompt: str, **extra: Any) -> Any:
    return client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        # 给足余量。项目踩过 max_tokens=200 导致空响应、被误诊成
        # 「模型不遵从 JSON 格式」的坑 —— 截断的 JSON 一定语法非法。
        max_tokens=MAX_TOKENS,
        **extra,
    )


def _meta(resp: Any) -> Dict[str, Any]:
    """抽出归因元数据：为什么停下来、烧了多少 token。

    ``reasoning_tokens`` 是关键 —— 推理型模型会把预算耗在不可见的推理段，
    表现为「content 为空但 completion_tokens 很大」。没有这个字段，
    这种失效跟「模型不听话」长得一模一样。
    """
    choice = resp.choices[0]
    usage = getattr(resp, "usage", None)
    completion = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0

    reasoning = 0
    details = getattr(usage, "completion_tokens_details", None) if usage else None
    if details is not None:
        reasoning = int(getattr(details, "reasoning_tokens", 0) or 0)

    return {
        "finish_reason": getattr(choice, "finish_reason", "") or "",
        "completion_tokens": completion,
        "reasoning_tokens": reasoning,
    }


def probe_baseline(client: OpenAI, model: str, prompt: str) -> Dict[str, Any]:
    """对照组：项目现在的做法，纯提示词请求，零强制力。"""
    resp = _call(client, model, prompt)
    return {"content": resp.choices[0].message.content or "", **_meta(resp)}


def probe_json_object(client: OpenAI, model: str, prompt: str) -> Dict[str, Any]:
    """JSON Mode：只保证是合法 JSON，不保证符合 schema。"""
    resp = _call(
        client, model, prompt, response_format={"type": "json_object"}
    )
    return {"content": resp.choices[0].message.content or "", **_meta(resp)}


def probe_json_schema(client: OpenAI, model: str, prompt: str) -> Dict[str, Any]:
    """约束解码严格模式 —— 首选路径。支持的话前两条都不用考虑。"""
    resp = _call(
        client,
        model,
        prompt,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "screening_verdict",
                "schema": VERDICT_SCHEMA,
                "strict": True,
            },
        },
    )
    return {"content": resp.choices[0].message.content or "", **_meta(resp)}


def probe_tools(client: OpenAI, model: str, prompt: str) -> Dict[str, Any]:
    """假函数：强制模型「调用」一个只用来装数据、永不执行的函数。

    判据不是「有没有报错」，而是响应里**到底有没有 tool_calls** ——
    网关把参数吃掉时会退化成普通 content 文本，请求依然 200。
    """
    resp = _call(
        client,
        model,
        prompt,
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "screening_verdict",
                    "description": "Record the screening verdict.",
                    "parameters": VERDICT_SCHEMA,
                },
            }
        ],
        tool_choice={
            "type": "function",
            "function": {"name": "screening_verdict"},
        },
    )
    msg = resp.choices[0].message
    calls = getattr(msg, "tool_calls", None)
    if not calls:
        # 关键分支：没报错但也没走 tools —— 静默失效
        return {"content": msg.content or "", "no_tool_calls": True, **_meta(resp)}
    return {"content": calls[0].function.arguments or "", **_meta(resp)}


MODES = {
    "baseline": probe_baseline,
    "json_object": probe_json_object,
    "json_schema": probe_json_schema,
    "tools": probe_tools,
}

PROMPTS = {"neutral": _NEUTRAL, "adversarial": _ADVERSARIAL}


# --------------------------------------------------------------------------
# 执行
# --------------------------------------------------------------------------


RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3


def _classify_exception(exc: Exception) -> tuple[str, str]:
    """把异常分成「参数不支持」和「瞬时故障」。

    **必须看 HTTP 状态码，不能匹配错误文本** —— 首轮实测里一条 429 限流
    因为消息里碰巧含关键词，被误判成 REJECTED（「该模型不支持 json_schema」）。
    那是把「网关现在忙」读成了「网关没这个能力」，结论完全相反。
    """
    status_code = getattr(exc, "status_code", None)
    if status_code in RETRYABLE_STATUS:
        return STATUS_TRANSIENT, f"HTTP {status_code} 瞬时故障"
    if status_code == 400:
        # 400 才是「参数不被接受」的诚实信号
        return STATUS_REJECTED, f"HTTP 400 参数被拒：{str(exc)[:200]}"
    return STATUS_ERROR, f"{type(exc).__name__}: {str(exc)[:200]}"


def run_one(target: Target, mode: str, prompt_kind: str) -> Probe:
    client = OpenAI(
        api_key=target.api_key,
        base_url=target.base_url or None,
        timeout=120.0,
        max_retries=0,  # 重试由本函数控制，好把「重试过几次」记进结果
    )

    started = time.monotonic()
    out: Optional[Dict[str, Any]] = None
    last_status, last_detail = STATUS_ERROR, "未执行"

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            out = MODES[mode](client, target.model, PROMPTS[prompt_kind])
            break
        except Exception as exc:  # noqa: BLE001 — 探针要如实记录任何失败形态
            last_status, last_detail = _classify_exception(exc)
            if last_status != STATUS_TRANSIENT or attempt == MAX_ATTEMPTS:
                break
            time.sleep(2.0 * attempt)  # 线性退避

    elapsed = int((time.monotonic() - started) * 1000)

    if out is None:
        return Probe(
            model=target.model,
            mode=mode,
            prompt_kind=prompt_kind,
            status=last_status,
            detail=last_detail,
            latency_ms=elapsed,
        )

    content = out.get("content", "")
    checked = _inspect_content(content)
    finish = out.get("finish_reason", "")
    completion = int(out.get("completion_tokens", 0))
    reasoning = int(out.get("reasoning_tokens", 0))

    # 归因用的后缀，附在每条 detail 后面
    meta_note = f"[finish={finish or '?'} out={completion} reason_tok={reasoning}]"

    if finish == "length":
        # 截断是预算问题，与「支不支持这个参数」无关，必须单独一类
        status = STATUS_TRUNCATED
        detail = f"输出被截断（max_tokens={MAX_TOKENS} 不够）"
    elif not content.strip() and completion > 0:
        # 烧了 token 却没有可见内容 —— 典型是推理段吃光了预算
        status = STATUS_TRUNCATED
        detail = f"content 为空但已消耗 {completion} 输出 token（疑似推理段占满）"
    elif mode == "tools" and out.get("no_tool_calls"):
        status = STATUS_IGNORED
        detail = "请求成功但响应无 tool_calls —— 参数被网关忽略"
    elif mode in ("json_schema", "json_object") and not checked["parsed_ok"]:
        status = STATUS_IGNORED
        detail = f"参数被接受但内容不是 JSON：{checked['note']}"
    elif mode == "json_schema" and not checked["pure_json"]:
        # 约束解码下不可能出现围栏/夹带文字 —— 出现了就说明没真生效
        status = STATUS_IGNORED
        detail = f"内容非纯 JSON（{checked['note']}）—— 约束未真正生效"
    elif mode == "json_schema" and not checked["schema_ok"]:
        status = STATUS_IGNORED
        detail = f"是 JSON 但不符合 schema：{checked['note']}"
    elif mode == "baseline":
        # 对照组不存在「支持与否」，只记录实际形态
        status = STATUS_OK if checked["schema_ok"] else STATUS_ERROR
        detail = checked["note"] or ("纯 JSON" if checked["pure_json"] else "可解析但非纯 JSON")
    else:
        status = STATUS_OK
        detail = checked["note"] or "符合契约"

    return Probe(
        model=target.model,
        mode=mode,
        prompt_kind=prompt_kind,
        status=status,
        detail=f"{detail} {meta_note}",
        latency_ms=elapsed,
        raw_preview=content[:200].replace("\n", "\\n"),
        parsed_ok=checked["parsed_ok"],
        schema_ok=checked["schema_ok"],
        pure_json=checked["pure_json"],
        finish_reason=finish,
        completion_tokens=completion,
        reasoning_tokens=reasoning,
    )


def collect_targets(explicit: Optional[List[str]]) -> List[Target]:
    """从 settings 读出要探的模型。凭据一律走配置，不硬编码。"""
    settings = load_settings()
    ev = settings.evaluation

    found: List[Target] = []
    for label, sub in (
        ("llm", settings.llm),
        ("evaluation.judge_llm", getattr(ev, "judge_llm", None)),
        ("evaluation.screening_llm", getattr(ev, "screening_llm", None)),
        ("evaluation.labeling_llm", getattr(ev, "labeling_llm", None)),
    ):
        if sub is None or not getattr(sub, "model", ""):
            continue
        found.append(
            Target(
                label=label,
                model=sub.model,
                api_key=getattr(sub, "api_key", "") or "",
                base_url=getattr(sub, "base_url", None) or None,
            )
        )

    if explicit:
        # 指定 model 时沿用第一个可用凭据（同一网关）
        if not found:
            raise SystemExit("settings 里没有任何可用凭据，无法指定 --models")
        proto = found[0]
        return [
            Target(label="--models", model=m, api_key=proto.api_key, base_url=proto.base_url)
            for m in explicit
        ]

    # 同一个 model 只探一次
    seen: set[str] = set()
    unique: List[Target] = []
    for t in found:
        if t.model in seen:
            continue
        seen.add(t.model)
        unique.append(t)
    return unique


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="*", default=None, help="显式指定 model id")
    parser.add_argument(
        "--modes", nargs="*", default=list(MODES), choices=list(MODES)
    )
    parser.add_argument(
        "--prompts", nargs="*", default=list(PROMPTS), choices=list(PROMPTS)
    )
    args = parser.parse_args()

    targets = collect_targets(args.models)
    if not targets:
        print("没有找到任何可探测的模型配置", file=sys.stderr)
        return 1

    print(f"探测 {len(targets)} 个模型 × {len(args.modes)} 模式 × {len(args.prompts)} 提示词")
    for t in targets:
        print(f"  - {t.model}  ({t.label})")
    print()

    results: List[Probe] = []
    for t in targets:
        for mode in args.modes:
            for kind in args.prompts:
                probe = run_one(t, mode, kind)
                results.append(probe)
                flag = {
                    STATUS_OK: "OK  ",
                    STATUS_IGNORED: "IGN ",
                    STATUS_REJECTED: "REJ ",
                    STATUS_TRUNCATED: "TRUNC",
                    STATUS_TRANSIENT: "429 ",
                    STATUS_ERROR: "ERR ",
                }[probe.status]
                print(
                    f"[{flag}] {t.model:<28} {mode:<12} {kind:<12} "
                    f"{probe.latency_ms:>6}ms  {probe.detail}"
                )

    _summarise(results)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUT_DIR / "probe_results.json"
    out_file.write_text(
        json.dumps([r.__dict__ for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n明细已写入 {out_file}")
    return 0


def _summarise(results: List[Probe]) -> None:
    """按模型 × 模式汇总。判据是「两个提示词都过」才算支持。"""
    print("\n" + "=" * 78)
    print("结论（SUPPORTED 需 neutral 与 adversarial 双双通过）")
    print("=" * 78)

    models = sorted({r.model for r in results})
    modes = [m for m in MODES if any(r.mode == m for r in results)]

    header = f"{'model':<30}" + "".join(f"{m:<14}" for m in modes)
    print(header)
    print("-" * len(header))

    for model in models:
        row = f"{model:<30}"
        for mode in modes:
            subset = [r for r in results if r.model == model and r.mode == mode]
            if not subset:
                row += f"{'-':<14}"
            elif all(r.status == STATUS_OK for r in subset):
                row += f"{'OK':<14}"
            elif any(r.status == STATUS_IGNORED for r in subset):
                row += f"{'IGNORED':<14}"
            elif any(r.status == STATUS_REJECTED for r in subset):
                row += f"{'REJECTED':<14}"
            elif any(r.status == STATUS_TRUNCATED for r in subset):
                # 截断不构成「不支持」的证据 —— 单列出来，别污染结论
                row += f"{'TRUNCATED':<14}"
            elif any(r.status == STATUS_TRANSIENT for r in subset):
                row += f"{'429/无结论':<12}"
            else:
                row += f"{'ERROR':<14}"
        print(row)

    print(
        "\n读法："
        "\n  json_schema=OK  → 走正路，三处判定都该改（学习笔记 §8.5 路径 B 首选）"
        "\n  json_schema≠OK 但 tools=OK → 用假函数，仍能消灭语法层失败"
        "\n  两者都不 OK     → 只剩提示词方案，优先做路径 A（JSON → XML 标签）"
        "\n  IGNORED         → 最危险：请求成功但参数无效，绝不能凭「没报错」当支持"
    )


if __name__ == "__main__":
    raise SystemExit(main())
