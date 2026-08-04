"""金标候选用例的异源 LLM 预筛 (Feature-003 US1)。

把 ``scripts/refine_testset.py`` 的「逐条 100% 人工确认」改造为「机器预筛 →
只有存疑用例交人工」。本模块只负责**判定**,不负责任何交互:

* 宪法 § V(NON-NEGOTIABLE):本模块零 ``print()``,日志走 ``observability.logger``
  输出 stderr。交互式打印留在 ``scripts/`` 侧。
* 宪法 § I:预筛 LLM 经 ``LLMFactory`` 按配置创建,不 import 任何具体 provider。
* 宪法 § II:provider / model / 阈值全部来自 ``evaluation.screening_llm.*``。

**核心安全不变式(FR-008)**:任何异常路径 —— LLM 调用失败、返回非 JSON、字段
缺失、置信度越界 —— 都只能流向 ``BORDERLINE`` 交人工,绝不允许流向自动保留或
自动丢弃。机器的不确定性只允许增加人工量,不允许污染金标。

设计文档:specs/003-testset-refine-automation/{spec,plan,data-model}.md
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from src.observability.evaluation._ragas_wrappers import (
    build_project_llm_from_sub_settings,
    get_screening_identifier,
)
from src.observability.logger import get_logger

if TYPE_CHECKING:
    from src.core.settings import Settings

logger = get_logger(__name__)

DEFAULT_PROMPT_PATH = Path("config/prompts/testset_screening.txt")

# 提示词文件缺失时的兜底(与 chunk_refiner 等既有模块同一约定)
DEFAULT_PROMPT = """You are a quality screener for a RAG evaluation golden test set.
Judge ONE candidate test case against three criteria: the question is well-formed,
the ground truth is supported by the supplied contexts, and the expected chunk id
list is non-empty. Answer "keep" if all hold, "drop" if any clearly fails, and
"borderline" if you are unsure. Respond with STRICT JSON only:
{{"decision": "keep|drop|borderline", "confidence": 0.0, "reason": "one sentence"}}

QUESTION:
{query}

GROUND TRUTH:
{ground_truth}

EXPECTED CHUNK IDS:
{expected_chunk_ids}

SUPPLIED CONTEXTS:
{contexts}

JSON verdict:
"""

# 从夹带文字中提取第一个 JSON 对象(非贪婪到最后一个 })
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
# markdown 代码围栏:```json ... ``` 或 ``` ... ```
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


class ScreeningDecision(str, Enum):
    """预筛三态结论 (FR-001)。"""

    KEEP = "keep"
    DROP = "drop"
    BORDERLINE = "borderline"


class SourceRelation(str, Enum):
    """预筛端与合成端的同源关系 (FR-002)。"""

    DIVERGENT = "divergent"
    """异源 —— 满足 FR-002 前提,可以继续。"""

    SAME_SOURCE = "same_source"
    """同源 —— 预筛等于自己批自己的作业,必须拒绝。"""

    UNVERIFIABLE = "unverifiable"
    """无法确认 —— 任一侧标识缺失;需使用者显式承担风险后才继续。"""


class ScreeningUnavailableError(RuntimeError):
    """预筛模型整体不可用(全部调用均因传输层异常失败)。

    与「模型通但输出不合格」严格区分:后者应全部降级 borderline 让人工兜住,
    前者必须显式失败,否则会让人以为跑了自动化、实际却在全量手工处理。
    CLI 将本异常映射为退出码 3。
    """


@dataclass
class ScreeningVerdict:
    """单条候选用例的机器判定 (data-model § 2)。

    Attributes:
        case_index: 在 candidate ``test_cases`` 中的序号。
        decision: 三态结论。
        confidence: 置信度 [0.0, 1.0];降级路径固定为 0.0。
        reason: 判定理由,人工处置 borderline 时作为上下文。
        transport_failed: 是否因**传输层**异常(调用没打通)而降级。仅供
            ``screen_all`` 区分「模型不可用」与「模型通但输出不合格」,不落盘。
    """

    case_index: int
    decision: ScreeningDecision
    confidence: float
    reason: str = ""
    transport_failed: bool = False


@dataclass
class ScreeningResult:
    """一次批量预筛的结果。"""

    verdicts: list[ScreeningVerdict] = field(default_factory=list)

    @property
    def auto_keep_indices(self) -> list[int]:
        """高置信保留 —— 无需人工介入。"""
        return [v.case_index for v in self.verdicts if v.decision is ScreeningDecision.KEEP]

    @property
    def auto_drop_indices(self) -> list[int]:
        """高置信丢弃 —— 无需人工介入。"""
        return [v.case_index for v in self.verdicts if v.decision is ScreeningDecision.DROP]

    @property
    def borderline_indices(self) -> list[int]:
        """存疑 —— 必须交人工处置。"""
        return [
            v.case_index for v in self.verdicts if v.decision is ScreeningDecision.BORDERLINE
        ]

    @property
    def borderline_ratio(self) -> float:
        """存疑占比。超过配置上限时 CLI 应告警(FR-011)。"""
        if not self.verdicts:
            return 0.0
        return len(self.borderline_indices) / len(self.verdicts)


# ---------------------------------------------------------------------------
# 同源检测 (FR-002)
# ---------------------------------------------------------------------------


def _normalize_identifier(raw: str) -> str:
    """把 ``"<provider>:<model>"`` 标识规范化(两段各自去空白)。"""
    provider, _, model = raw.partition(":")
    return f"{provider.strip()}:{model.strip()}"


def _is_degenerate_identifier(identifier: str) -> bool:
    """provider 与 model 皆空的标识无法据以判定同源。"""
    provider, _, model = identifier.partition(":")
    return not provider.strip() and not model.strip()


def check_source_divergence(settings: "Settings", candidate: dict[str, Any]) -> SourceRelation:
    """判定预筛模型与合成端是否异源 (FR-002)。

    合成端把 ``get_judge_identifier()`` 的结果写进 candidate 的
    ``_synthesis_metadata.judge_llm_identifier``,故判据是两个标识串相等。

    Args:
        settings: 全局 Settings(读 ``evaluation.screening_llm``)。
        candidate: 合成阶段产出的 candidate dict。

    Returns:
        三态关系。``UNVERIFIABLE`` 表示任一侧标识缺失或退化。

    Note:
        判据是**完整标识串**相等,不是 provider 相等。实测某 candidate 的 judge
        标识为 ``"glm:minimax/minimax-m2.7"`` —— provider 名义是 ``glm`` 但模型
        经 OpenAI 兼容端点路由到 minimax;若只比 provider,真正异源的
        ``glm:glm-4.6`` 会被误判同源而遭拒绝。
    """
    screening_id = _normalize_identifier(get_screening_identifier(settings))
    metadata = candidate.get("_synthesis_metadata") or {}
    synthesis_raw = metadata.get("judge_llm_identifier") or ""
    synthesis_id = _normalize_identifier(str(synthesis_raw))

    if _is_degenerate_identifier(screening_id) or _is_degenerate_identifier(synthesis_id):
        logger.warning(
            "cannot verify source divergence: screening=%r synthesis=%r",
            screening_id,
            synthesis_id,
        )
        return SourceRelation.UNVERIFIABLE

    if screening_id == synthesis_id:
        logger.warning(
            "screening LLM is same-source as synthesis LLM (%s); "
            "auto mode would be the model grading its own homework",
            screening_id,
        )
        return SourceRelation.SAME_SOURCE

    logger.info(
        "source divergence confirmed: screening=%s vs synthesis=%s",
        screening_id,
        synthesis_id,
    )
    return SourceRelation.DIVERGENT


# ---------------------------------------------------------------------------
# 预筛
# ---------------------------------------------------------------------------


def _load_prompt_template(prompt_path: Optional[str] = None) -> str:
    """加载提示词模板,缺失时回落到内嵌默认值。"""
    if prompt_path and Path(prompt_path).exists():
        return Path(prompt_path).read_text(encoding="utf-8")
    if DEFAULT_PROMPT_PATH.exists():
        return DEFAULT_PROMPT_PATH.read_text(encoding="utf-8")
    logger.warning("prompt file not found at %s; using embedded default", DEFAULT_PROMPT_PATH)
    return DEFAULT_PROMPT


def _extract_json_object(raw: str) -> Optional[dict[str, Any]]:
    """从模型输出中提取 JSON 对象;失败或非对象时返回 None。

    容忍两种常见偏差:markdown 代码围栏、JSON 前后夹带解释文字。
    但**不**从数组内部挖对象 —— 顶层是数组说明模型没按契约输出单条判定,
    宁可降级为 borderline 也不猜测其意图。
    """
    text = raw.strip()
    if not text:
        return None

    fenced = _FENCE_RE.match(text)
    if fenced:
        text = fenced.group(1).strip()

    # 先整体解析:能解析且是对象才算合格;是数组等其他类型则判不合格
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    else:
        return parsed if isinstance(parsed, dict) else None

    # 整体解析失败 → 尝试从夹带文字中截取对象
    match = _JSON_OBJECT_RE.search(text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _coerce_confidence(value: Any) -> Optional[float]:
    """校验置信度:必须是 [0.0, 1.0] 内的实数。非法返回 None。"""
    # bool 是 int 的子类,但 True/False 不是有效置信度
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    confidence = float(value)
    if not 0.0 <= confidence <= 1.0:
        return None
    return confidence


class TestsetScreener:
    """按配置创建异源预筛模型,对候选用例做三态判定。

    Args:
        settings: 全局 Settings,读 ``evaluation.screening_llm``。
        llm: 预筛 LLM 实例。默认 ``None`` = 按配置懒创建;测试可注入替身。
        prompt_template: 提示词模板。默认 ``None`` = 从
            ``config/prompts/testset_screening.txt`` 加载。
        prompt_path: 自定义提示词路径(仅在 ``prompt_template`` 为 None 时生效)。
    """

    # 阻止 pytest 把这个类当成测试类(类名以 Test 开头会被 pytest 默认收集)
    __test__ = False

    def __init__(
        self,
        settings: "Settings",
        llm: Optional[Any] = None,
        prompt_template: Optional[str] = None,
        prompt_path: Optional[str] = None,
    ) -> None:
        self._settings = settings
        self._screening = settings.evaluation.screening_llm
        self._llm = llm
        self._prompt_template = (
            prompt_template if prompt_template is not None else _load_prompt_template(prompt_path)
        )

    # -- LLM 懒加载 --------------------------------------------------------

    @property
    def llm(self) -> Any:
        """预筛 LLM 实例(首次访问时按配置创建)。"""
        if self._llm is None:
            self._llm = build_project_llm_from_sub_settings(self._settings, self._screening)
            logger.info(
                "screening LLM ready: %s", _normalize_identifier(
                    get_screening_identifier(self._settings)
                )
            )
        return self._llm

    # -- 单条判定 ----------------------------------------------------------

    def _render_prompt(self, case: dict[str, Any]) -> str:
        contexts = case.get("_synth_contexts") or []
        return self._prompt_template.format(
            query=case.get("query", ""),
            ground_truth=case.get("ground_truth", ""),
            expected_chunk_ids=json.dumps(
                case.get("expected_chunk_ids") or [], ensure_ascii=False
            ),
            contexts="\n---\n".join(str(c) for c in contexts),
        )

    def _borderline(
        self, case_index: int, reason: str, transport_failed: bool = False
    ) -> ScreeningVerdict:
        """构造降级判定。置信度 0.0 表示「机器没能给出可信结论」。"""
        logger.warning("case %d downgraded to borderline: %s", case_index, reason)
        return ScreeningVerdict(
            case_index=case_index,
            decision=ScreeningDecision.BORDERLINE,
            confidence=0.0,
            reason=reason,
            transport_failed=transport_failed,
        )

    def screen_case(self, case: dict[str, Any], case_index: int) -> ScreeningVerdict:
        """判定单条用例。**任何异常都降级为 borderline,绝不抛出**(FR-008)。

        Args:
            case: 单条候选用例。
            case_index: 在 candidate ``test_cases`` 中的序号。

        Returns:
            判定结果。异常路径一律为 ``BORDERLINE``。
        """
        try:
            raw = self.llm.chat([{"role": "user", "content": self._render_prompt(case)}])
        except Exception as exc:  # noqa: BLE001 — 任何上游异常都只降级,不外抛
            # 传输层失败单独打标,供 screen_all 区分「模型不可用」与「输出不合格」
            return self._borderline(
                case_index, f"screening call failed: {exc}", transport_failed=True
            )

        payload = _extract_json_object(raw)
        if payload is None:
            return self._borderline(case_index, "response was not a JSON object")

        raw_decision = payload.get("decision")
        if not isinstance(raw_decision, str):
            return self._borderline(case_index, "verdict missing 'decision' field")
        try:
            decision = ScreeningDecision(raw_decision.strip().lower())
        except ValueError:
            return self._borderline(case_index, f"unknown decision {raw_decision!r}")

        confidence = _coerce_confidence(payload.get("confidence"))
        if confidence is None:
            return self._borderline(
                case_index, f"invalid confidence {payload.get('confidence')!r}"
            )

        reason = str(payload.get("reason") or "").strip()

        # 显式 borderline 直接透传,不看阈值
        if decision is ScreeningDecision.BORDERLINE:
            return ScreeningVerdict(case_index, decision, confidence, reason)

        # keep / drop 各自比对独立阈值;未达阈值降级为 borderline
        threshold = (
            self._screening.keep_threshold
            if decision is ScreeningDecision.KEEP
            else self._screening.drop_threshold
        )
        if confidence < threshold:
            return self._borderline(
                case_index,
                f"{decision.value} confidence {confidence:.2f} below threshold {threshold:.2f}"
                + (f" ({reason})" if reason else ""),
            )

        return ScreeningVerdict(case_index, decision, confidence, reason)

    # -- 批量 --------------------------------------------------------------

    def screen_all(self, candidate: dict[str, Any]) -> ScreeningResult:
        """对 candidate 全部用例逐条预筛。

        Args:
            candidate: 合成阶段产出的 candidate dict。

        Returns:
            批量判定结果(verdicts 按 ``case_index`` 升序)。

        Raises:
            ScreeningUnavailableError: 存在用例且**全部**因传输层异常失败时。
                空输入不抛异常,直接返回空结果且不发起任何调用。
        """
        cases = candidate.get("test_cases") or []
        if not cases:
            logger.info("candidate contains no test cases; skipping screening entirely")
            return ScreeningResult()

        verdicts = [self.screen_case(case, index) for index, case in enumerate(cases)]
        transport_failures = sum(1 for v in verdicts if v.transport_failed)

        if transport_failures == len(cases):
            raise ScreeningUnavailableError(
                f"all {len(cases)} screening calls failed at transport level; "
                "the screening model appears unreachable. Fix credentials/network, "
                "or drop --auto-mode to fall back to full interactive review."
            )

        result = ScreeningResult(verdicts=verdicts)
        logger.info(
            "screening done: %d cases -> auto_keep=%d auto_drop=%d borderline=%d (%.1f%%)",
            len(cases),
            len(result.auto_keep_indices),
            len(result.auto_drop_indices),
            len(result.borderline_indices),
            result.borderline_ratio * 100,
        )
        return result
