"""降级摘要的文本格式化 (change evaluation-degradation-governance T-1.2)。

spec: specs/evaluation/run-integrity/spec.md § 降级情况必须在运行结束时直接可见

为什么单独一个模块、且只返回字符串不打印:
    硬约束 5 规定 ``src/`` 下禁止任何 ``print()`` —— MCP stdio transport 的
    stdout 走 JSON-RPC,污染它会直接破坏协议。所以这里只**产出文本**,
    由 ``scripts/evaluate.py`` 决定往哪写。副作用是这个函数天然可单测。

为什么需要这个摘要:
    ``degraded_case_count`` 与 ``metric_integrity`` 都在报告 JSON 里,而报告
    JSON 动辄上千行 —— 实测就是这样:run 80a82405 的降级率高达 54.8%
    (SC-006 门槛的 11 倍),字段一直躺在那儿,没人读到。把它打到运行结束处,
    是为了让「警报响了」这件事不依赖有人去翻文件。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期需要
    from src.core.types import MetricIntegrity


def format_degradation_summary(
    metric_integrity: dict[str, "MetricIntegrity"],
    degraded_case_count: int,
    total_cases: int,
    max_ratio: Optional[float] = None,
) -> str:
    """把降级情况格式化成人读的摘要文本。

    Args:
        metric_integrity: 按 metric 的分母披露(来自 ``EvalReport``)。
        degraded_case_count: case 级降级计数(任一 metric NaN 即计一次)。
        total_cases: 本次评估的用例总数。
        max_ratio: 配置的降级率门槛;传入时会在超标处显式点出门槛值。
            为 ``None`` 表示调用方不关心门槛(只要摘要)。

    Returns:
        多行文本(不含结尾换行)。无任何降级时返回单行说明 —— 不展开原因
        分布,避免在健康运行上制造噪声。
    """
    # 只有 LLM 判定类指标会降级;纯计算的 custom 指标恒为 0,列出来是噪声。
    degraded_metrics = {
        name: integrity
        for name, integrity in metric_integrity.items()
        if integrity.degraded_count > 0
    }

    case_ratio = (degraded_case_count / total_cases) if total_cases else 0.0

    if not degraded_metrics and degraded_case_count == 0:
        return f"降级率: 0.0% (0/{total_cases}) —— 全部用例判定成功"

    lines: list[str] = []
    header = "降级率: %.1f%% (%d/%d 条用例至少有一项指标判定失败)" % (
        case_ratio * 100,
        degraded_case_count,
        total_cases,
    )
    lines.append(header)

    # 超标必须显式点出门槛,否则读者无从判断这个百分比算不算糟
    if max_ratio is not None and case_ratio > max_ratio:
        lines.append(
            "  ⚠️ 超过门槛 %.1f%% —— 聚合指标的分母已被静默收缩,绝对值偏高且跨运行不可比"
            % (max_ratio * 100)
        )

    lines.append("  按指标:")
    for name in sorted(degraded_metrics):
        integrity = degraded_metrics[name]
        # 「均值实为 n 条算出」正是本变更要让人看见的那句话
        lines.append(
            "    %-28s 有效 %d / 降级 %d (%.1f%%) —— 该项均值实为 %d 条算出"
            % (
                name,
                integrity.valid_count,
                integrity.degraded_count,
                integrity.degradation_ratio * 100,
                integrity.valid_count,
            )
        )
        for reason in sorted(integrity.reasons):
            lines.append("        %-24s %d" % (reason, integrity.reasons[reason]))

    return "\n".join(lines)
