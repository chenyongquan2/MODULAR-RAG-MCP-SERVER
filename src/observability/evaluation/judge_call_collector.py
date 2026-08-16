"""Judge 调用结果采集器 (change evaluation-degradation-governance T-2.1)。

spec: specs/evaluation/run-integrity/spec.md § 判定失败必须带可归因的原因

## 为什么需要它

RAGAS 把 judge 的原始响应**吞掉了**:`ragas_evaluate()` 只把结果表达为
分数或 NaN 交出来。所以「为什么判不出来」这个信息在现有数据流里不是没被
记录,而是**根本拿不到**。

而 `ragas==0.1.21` 是 Feature-001 的基线锚定点(不同版本判分尺度不同),
既不能升级也不能改其源码。

唯一还能看到 judge 原始响应的位置,是项目自己的适配层 `_ragas_wrappers` ——
RAGAS 正是通过它回调项目的 `BaseLLM`。本模块就挂在那里。

## 为什么是显式注入而不是全局状态

硬约束 4 禁止 `contextvars` / `threading.local`。收集器实例由
`RagasEvaluator` 持有并显式注入适配闭包,生命周期与单次 `evaluate()` 对齐。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.core.types import DegradationReason


@dataclass
class JudgeCallOutcome:
    """单次 judge 调用的结果特征。

    Attributes:
        ok: 调用是否正常返回(未抛异常)。
        empty: 返回内容是否为空/纯空白。**空响应不等于调用失败** ——
            项目在 labeling 路径踩过这个坑:max_tokens 给少了会让模型没写完
            就被截断,HTTP 层完全成功,返回的却是空串。
        reason: 调用层能直接判定的失败原因;正常返回时为 ``None``。
        response_chars: 返回文本长度,用于事后诊断(如判断是否被截断)。
    """

    ok: bool
    empty: bool
    reason: Optional[str] = None
    response_chars: int = 0


@dataclass
class JudgeCallCollector:
    """收集一次 `evaluate()` 期间的全部 judge 调用结果。

    只记录**机械可判**的事实,不做语义推断 —— 「judge 是不是觉得材料不足」
    这类判断不在此处发生,也不应该发生。
    """

    calls: list[JudgeCallOutcome] = field(default_factory=list)

    def reset(self) -> None:
        """清空记录。每条 case 评估开始前调用。"""
        self.calls.clear()

    def record_success(self, response: str) -> None:
        """记录一次正常返回的调用。

        空响应仍算 ``ok=True`` —— 它在传输层确实成功了,失败发生在内容层。
        这个区分很重要:混为一谈会让「模型不遵从格式」和「没给够 token」
        看起来是同一个问题,而它们的修法完全不同。
        """
        text = response or ""
        self.calls.append(
            JudgeCallOutcome(
                ok=True,
                empty=not text.strip(),
                reason=DegradationReason.EMPTY_RESPONSE.value if not text.strip() else None,
                response_chars=len(text),
            )
        )

    def record_failure(self, exc: BaseException) -> None:
        """记录一次抛异常的调用,按异常特征归类。"""
        self.calls.append(
            JudgeCallOutcome(
                ok=False,
                empty=True,
                reason=classify_exception(exc),
                response_chars=0,
            )
        )

    # ------------------------------------------------------------------
    # 归约:把「调用级」事实变成「指标级」原因
    # ------------------------------------------------------------------

    def dominant_reason(self) -> str:
        """归约出本批调用最能解释降级的那个原因。

        归约规则(按优先级,越靠前越具体):
          1. 有调用抛异常 → 用第一个异常的分类(超时 / 上游拒绝)。
             调用根本没成功,后面的推断都无意义。
          2. 无异常但有空响应 → ``empty_response``。这是本项目最常踩的坑。
          3. 全部调用都成功且非空,而指标仍是 NaN → ``unparseable``。
             这是**推断**:调用层给了内容、RAGAS 却没算出值,那只能是
             结构不符合它的预期。
          4. 一次调用都没有 → ``unknown``。说明失败发生在 judge 调用之外
             (如 embedding 侧异常、RAGAS 自身逻辑抛错),本采集器看不到。

        Returns:
            ``DegradationReason`` 的值。
        """
        if not self.calls:
            return DegradationReason.UNKNOWN.value

        for call in self.calls:
            if not call.ok and call.reason:
                return call.reason

        if any(call.empty for call in self.calls):
            return DegradationReason.EMPTY_RESPONSE.value

        return DegradationReason.UNPARSEABLE.value


def classify_exception(exc: BaseException) -> str:
    """把异常归类成 ``DegradationReason``。

    只按**异常类型名与消息文本**做机械匹配,不 import 任何具体 provider 的
    异常类型 —— 硬约束 1 要求业务逻辑不依赖具体 provider,评估路径同理。
    代价是匹配靠字符串,好处是换 provider 不需要改这里。

    Args:
        exc: 判定调用抛出的异常。

    Returns:
        ``DegradationReason`` 的值。
    """
    label = f"{type(exc).__name__} {exc}".lower()

    if "timeout" in label or "timed out" in label:
        return DegradationReason.TIMEOUT.value

    # 上游拒绝的常见表征:HTTP 状态码、鉴权、限流、模型下架。
    # 本项目所在网关的模型下架是常态而非偶发 —— 同一天
    # text-embedding-3-small 与 z-ai/glm-4.7 先后 503 model_not_found。
    upstream_markers = (
        "connection",
        "unauthorized",
        "forbidden",
        "rate limit",
        "ratelimit",
        "too many requests",
        "not_found",
        "not found",
        "service unavailable",
        "bad gateway",
        "apierror",
        "apistatuserror",
        "http",
        "401",
        "403",
        "404",
        "429",
        "500",
        "502",
        "503",
    )
    if any(marker in label for marker in upstream_markers):
        return DegradationReason.UPSTREAM_ERROR.value

    return DegradationReason.UNKNOWN.value
