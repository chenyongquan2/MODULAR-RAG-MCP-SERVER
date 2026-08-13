"""金标标注的 LLM 相关性判定 (change retriever-agnostic-golden-labels T-3.1 / T-3.2)。

## 判定什么

对候选池里每个 ``(query, ground_truth, chunk)``,让 LLM 回答「这个 chunk 是否
支撑该问题的答案」,返回 0-3 分级相关度:

- 0 无关
- 1 沾边(提到了相关话题但不含回答所需信息)
- 2 部分支撑(含回答所需信息的一部分)
- 3 直接回答

``>= evaluation.labeling.relevance_threshold`` 的纳入 ``expected_chunk_ids``。

## 为什么不用相似度阈值

第一代做法是「与答案文本的余弦相似度 >= 0.6」。**相似度高不等于支撑答案** ——
一段复述问题措辞却不含任何信息的文字可能相似度很高。判定要回答的是「读了这段
能否回答该问题」,那是语义判断,不是向量距离。

## 两类失败必须严格区分

沿用 ``testset_screener`` 建立的先例:

- **模型整体不可用**(凭据错、网络断、模型下架)→ 抛 ``LabelingUnavailableError``,
  CLI 映射为退出码 3。**必须显式失败**,否则会让人以为跑了自动标注、实际得到
  一份全是"不相关"的空金标。
- **模型通但单条输出不合格**(返回的文字里解析不出分级)→ 标记该候选为
  ``judge_failed``,整轮继续。失败计数进元数据,超比例告警。

把前者降级成后者是本项目反复强调要避免的那类静默失效。

## 异源约束

``ground_truth`` 是 ``evaluation.judge_llm`` 合成的。用同一个模型判断「哪些
chunk 支撑我自己写的答案」是自我确认,必须拒绝。判据是**完整标识串**
``<provider>:<model>`` 相等 —— 不是 provider 相等(实测 judge 标识为
``glm:minimax/minimax-m2.7``,provider 名义是 glm 但模型经 OpenAI 兼容端点路由
到 minimax;只比 provider 会把真正异源的 ``glm:glm-4.6`` 误判为同源)。

不在查询链路上,是离线标注工具。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from src.observability.evaluation.testset_screener import (
    SourceRelation,
    _is_degenerate_identifier,
    _normalize_identifier,
)
from src.observability.logger import get_logger

if TYPE_CHECKING:
    from src.core.settings import Settings

logger = get_logger(__name__)


# 分级相关度的取值域。集中定义以免各处散落魔数。
GRADE_IRRELEVANT = 0
GRADE_TANGENTIAL = 1
GRADE_PARTIAL = 2
GRADE_DIRECT = 3
VALID_GRADES = frozenset({GRADE_IRRELEVANT, GRADE_TANGENTIAL, GRADE_PARTIAL, GRADE_DIRECT})

GRADE_DESCRIPTIONS = {
    GRADE_IRRELEVANT: "irrelevant — does not mention the topic at all",
    GRADE_TANGENTIAL: "tangential — mentions the topic but carries none of the "
    "information needed to answer",
    GRADE_PARTIAL: "partially supports — carries part of the information needed",
    GRADE_DIRECT: "directly answers — carries the information needed to answer",
}


class LabelingUnavailableError(RuntimeError):
    """判定模型整体不可用(全部调用均因传输层异常失败)。

    与「模型通但输出不合格」严格区分:后者应逐条标记 judge_failed 让人看到,
    前者必须显式失败 —— 否则会让人以为跑了自动标注、实际得到一份全是
    「不相关」的空金标,而空金标会让所有召回指标归零并被误读成检索崩了。
    CLI 将本异常映射为退出码 3(沿用 Feature-003 的退出码语义)。
    """


@dataclass
class ChunkVerdict:
    """单个候选的判定结果。

    Attributes:
        chunk_id: 候选标识。
        grade: 0-3 分级相关度;判定失败时为 None。
        reason: LLM 给出的理由。人工抽检时作为上下文,是校准判定口径的依据。
        judge_failed: 是否判定失败(输出无法解析)。**失败不等于不相关** ——
            混为一谈会让解析 bug 伪装成「语料里没有相关内容」。
        transport_failed: 是否因传输层异常(调用没打通)失败。仅供上层区分
            「模型整体不可用」与「模型通但输出不合格」,不落盘。
    """

    chunk_id: str
    grade: Optional[int] = None
    reason: str = ""
    judge_failed: bool = False
    transport_failed: bool = False

    def is_relevant(self, threshold: int) -> bool:
        """是否达到纳入标准答案的门槛。

        判定失败的候选**不纳入**,但它与「判定为不相关」在元数据里是两种状态。
        """
        return self.grade is not None and self.grade >= threshold


@dataclass
class LabelingRun:
    """一轮判定的汇总。

    Attributes:
        verdicts: 全部判定结果。
        judged_count: 实际发起过判定调用的候选数。
        skipped_count: 因达到 ``max_judgements`` 上限而未判定的候选数。
            **必须记录** —— 不能让部分完成的产出看起来像全部完成。
        warnings: 告警列表(判定失败率过高等)。
    """

    verdicts: List[ChunkVerdict] = field(default_factory=list)
    judged_count: int = 0
    skipped_count: int = 0
    warnings: List[str] = field(default_factory=list)

    @property
    def failure_ratio(self) -> float:
        """判定失败占**已发起判定**的比例(不把 skipped 算进分母)。"""
        if self.judged_count <= 0:
            return 0.0
        return sum(1 for v in self.verdicts if v.judge_failed) / self.judged_count


# ---------------------------------------------------------------------------
# 异源检测 (T-3.2)
# ---------------------------------------------------------------------------


def get_labeling_identifier(settings: Settings) -> str:
    """返回 ``"<provider>:<model>"`` 形式的判定 LLM 标识。

    与 ``get_judge_identifier`` / ``get_screening_identifier`` 同格式,使
    「判定端 vs 合成端」可直接比对。
    """
    cfg = settings.evaluation.labeling_llm
    return f"{cfg.provider}:{cfg.model}"


def check_labeling_divergence(
    settings: Settings,
    golden: Dict[str, Any],
) -> SourceRelation:
    """判定「标注模型」与「合成 ground_truth 的模型」是否异源。

    复用 ``testset_screener`` 的三态关系与标识规范化口径 —— 同一个问题不该有
    两套判据。

    合成端标识的来源按优先级:``_synthesis_metadata.judge_llm_identifier``
    (合成脚本写入),其次 ``_review_metadata.synthesis_identifier``(精修阶段
    写入)。两者都缺 → UNVERIFIABLE。

    Args:
        settings: 全局 Settings(读 ``evaluation.labeling_llm``)。
        golden: 金标 dict(可能是 candidate 或已精修的金标)。

    Returns:
        三态关系。``UNVERIFIABLE`` 表示任一侧标识缺失或退化。
    """
    labeling_id = _normalize_identifier(get_labeling_identifier(settings))

    synthesis_raw = ""
    for meta_key, field_key in (
        ("_synthesis_metadata", "judge_llm_identifier"),
        ("_review_metadata", "synthesis_identifier"),
    ):
        meta = golden.get(meta_key) or {}
        value = meta.get(field_key) or ""
        if str(value).strip():
            synthesis_raw = str(value)
            break
    synthesis_id = _normalize_identifier(synthesis_raw)

    if _is_degenerate_identifier(labeling_id) or _is_degenerate_identifier(synthesis_id):
        logger.warning(
            "cannot verify source divergence: labeling=%r synthesis=%r",
            labeling_id,
            synthesis_id,
        )
        return SourceRelation.UNVERIFIABLE

    if labeling_id == synthesis_id:
        logger.warning(
            "labeling LLM is same-source as synthesis LLM (%s); it would be "
            "judging which chunks support an answer it wrote itself",
            labeling_id,
        )
        return SourceRelation.SAME_SOURCE

    logger.info(
        "source divergence confirmed: labeling=%s vs synthesis=%s",
        labeling_id,
        synthesis_id,
    )
    return SourceRelation.DIVERGENT


# ---------------------------------------------------------------------------
# 判定 (T-3.1)
# ---------------------------------------------------------------------------

_PROMPT_TEMPLATE = """You are grading whether a retrieved passage supports the answer to a question.

Question:
{query}

Reference answer:
{ground_truth}

Retrieved passage:
{chunk}

Grade the passage on this scale:
0 = {g0}
1 = {g1}
2 = {g2}
3 = {g3}

Judge whether the PASSAGE carries the information needed to answer the QUESTION.
Do NOT reward the passage merely for using similar wording to the question or the
reference answer — a passage that restates the question without adding information
scores 0 or 1. A passage that answers the question in completely different words
scores 2 or 3.

Respond with JSON only, no other text:
{{"grade": <0|1|2|3>, "reason": "<one short sentence>"}}"""


class ChunkLabeler:
    """用 LLM 对候选做分级相关性判定。

    Example:
        >>> labeler = ChunkLabeler(settings)
        >>> run = labeler.label_all(query, ground_truth, candidates)
        >>> [v.chunk_id for v in run.verdicts if v.is_relevant(2)]
    """

    def __init__(
        self,
        settings: Settings,
        llm: Optional[Any] = None,
        max_chunk_chars: int = 2000,
    ) -> None:
        """构造判定器。

        Args:
            settings: 应用配置,读 ``evaluation.labeling*``。
            llm: 可选的 LLM 实例(测试注入);未提供则经 LLMFactory 按
                ``evaluation.labeling_llm`` 构造 —— 宪法原则一,不 import
                具体 provider。
            max_chunk_chars: 单个 chunk 送入 prompt 的字符上限。真实 chunk
                中位约 428 字符,2000 足够容纳绝大多数而不至于让 token 失控。

        Raises:
            ValueError: settings 为 None。
        """
        if settings is None:
            raise ValueError("Settings cannot be None")

        self._settings = settings
        self._threshold = settings.evaluation.labeling.relevance_threshold
        self._max_chunk_chars = max_chunk_chars

        if llm is not None:
            self._llm = llm
        else:
            self._llm = self._build_llm(settings)

    @staticmethod
    def _build_llm(settings: Settings) -> Any:
        """按 ``evaluation.labeling_llm`` 经 LLMFactory 构造判定模型。

        用一个仅覆盖 llm 段的浅包装传给 factory —— factory 读的是
        ``settings.llm``,而判定要用的是 ``evaluation.labeling_llm``。
        这样既不改 factory,也不 import 任何具体 provider。
        """
        from copy import copy

        from src.core.settings import LLMSettings
        from src.libs.llm.llm_factory import LLMFactory

        cfg = settings.evaluation.labeling_llm
        shim = copy(settings)
        shim.llm = LLMSettings(
            provider=cfg.provider,
            model=cfg.model,
            api_key=cfg.api_key,
            base_url=cfg.base_url or "",
            request_timeout_sec=cfg.request_timeout_sec,
            max_retries=cfg.max_retries,
        )
        return LLMFactory.create(shim)

    def label_one(
        self,
        query: str,
        ground_truth: str,
        chunk_id: str,
        chunk_text: str,
    ) -> ChunkVerdict:
        """判定单个候选。

        Returns:
            判定结果。调用打不通 → ``transport_failed=True``;调用通了但输出
            解析不出分级 → ``judge_failed=True``。两者都不抛异常 —— 单条失败
            不该终止整轮(由 ``label_all`` 汇总后决定是否整体失败)。
        """
        prompt = _PROMPT_TEMPLATE.format(
            query=query,
            ground_truth=ground_truth,
            chunk=chunk_text[: self._max_chunk_chars],
            g0=GRADE_DESCRIPTIONS[GRADE_IRRELEVANT],
            g1=GRADE_DESCRIPTIONS[GRADE_TANGENTIAL],
            g2=GRADE_DESCRIPTIONS[GRADE_PARTIAL],
            g3=GRADE_DESCRIPTIONS[GRADE_DIRECT],
        )

        try:
            # max_tokens 必须给足：此前硬编码 200，真实语料上几乎全军覆没
            # （367 字符的 chunk 就返回空响应）。预算不足时输出被截断成半个
            # JSON 或干脆为空，于是每条都标 judge_failed —— 表现为「模型不会
            # 遵从 JSON 格式」，真实原因是没给它写完的余量。见配置项 docstring。
            response = self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self._settings.evaluation.labeling_llm.max_tokens,
                temperature=self._settings.evaluation.labeling_llm.temperature,
            )
        except Exception as exc:  # noqa: BLE001 —— 单条失败不终止整轮
            logger.warning("labeling call failed for chunk %s: %s", chunk_id, exc)
            return ChunkVerdict(
                chunk_id=chunk_id,
                judge_failed=True,
                transport_failed=True,
                reason=f"labeling call failed: {exc}",
            )

        grade, reason = _parse_verdict(response)
        if grade is None:
            logger.warning(
                "unparseable labeling output for chunk %s: %r", chunk_id, response[:120]
            )
            return ChunkVerdict(
                chunk_id=chunk_id,
                judge_failed=True,
                reason="unparseable judge output",
            )

        return ChunkVerdict(chunk_id=chunk_id, grade=grade, reason=reason)

    def label_all(
        self,
        query: str,
        ground_truth: str,
        candidates: Sequence[Any],
        budget: Optional[int] = None,
        already_judged: Optional[Dict[str, ChunkVerdict]] = None,
    ) -> LabelingRun:
        """判定一批候选。

        Args:
            query: 问题文本。
            ground_truth: 参考答案。
            candidates: 候选序列,每项需有 ``chunk_id`` 与 ``text``。
            budget: 本次最多发起多少判定调用(剩余预算)。None = 不限。
                超出部分记入 ``skipped_count`` —— **不静默丢弃**。
            already_judged: 已判定过的候选(chunk_id -> 判定),用于续跑。
                命中的候选直接复用,不再调用 LLM。

        Returns:
            本轮汇总。

        Raises:
            LabelingUnavailableError: 有候选需要判定,且**全部**因传输层异常
                失败 —— 说明模型整体不可用,不是个别输出不合格。
        """
        already = already_judged or {}
        run = LabelingRun()
        remaining = budget

        for candidate in candidates:
            chunk_id = getattr(candidate, "chunk_id", None) or candidate["chunk_id"]
            chunk_text = getattr(candidate, "text", None)
            if chunk_text is None:
                chunk_text = candidate.get("text", "")

            cached = already.get(chunk_id)
            if cached is not None:
                run.verdicts.append(cached)
                continue

            if remaining is not None and remaining <= 0:
                run.skipped_count += 1
                continue

            verdict = self.label_one(query, ground_truth, chunk_id, chunk_text)
            run.verdicts.append(verdict)
            run.judged_count += 1
            if remaining is not None:
                remaining -= 1

        # 「模型整体不可用」的判据:发起过判定,且全部是传输层失败。
        # 与「个别输出不合格」严格区分 —— 后者继续跑并留痕。
        if run.judged_count > 0:
            transport_failures = sum(1 for v in run.verdicts if v.transport_failed)
            if transport_failures == run.judged_count:
                raise LabelingUnavailableError(
                    f"all {run.judged_count} labeling calls failed at the transport "
                    "layer (credentials / network / model unavailable). Refusing to "
                    "emit a golden set where every chunk is 'irrelevant' — that "
                    "would zero out every recall metric and read as a retrieval "
                    f"collapse. Check the gateway: curl "
                    f"${{GLM_BASE_URL}}/models"
                )

        failure_ratio = run.failure_ratio
        warn_at = self._settings.evaluation.labeling.judge_failure_warn_ratio
        if failure_ratio > warn_at:
            run.warnings.append(
                f"judge failure ratio {failure_ratio:.1%} exceeds "
                f"{warn_at:.1%} for query {query[:40]!r}; unparseable outputs are "
                "NOT the same as 'not relevant' — check the prompt or the model"
            )

        return run

    def relevant_ids(self, run: LabelingRun) -> List[str]:
        """从判定汇总里取出达到门槛的 chunk id(保持输入顺序)。"""
        return [v.chunk_id for v in run.verdicts if v.is_relevant(self._threshold)]


def _parse_verdict(response: str) -> tuple[Optional[int], str]:
    """从 LLM 回复里解析 ``(grade, reason)``。

    容忍三种形态,依次尝试:
    1. 纯 JSON
    2. 文本里嵌了 JSON 对象(模型爱加 ``Here is the grade:`` 之类的前言)
    3. 裸数字(``2`` / ``Grade: 2``)—— 此时 reason 为空

    解析不出返回 ``(None, "")``,由调用方标记 judge_failed。**不要在这里兜底
    成 0** —— 「解析失败」与「判定为不相关」是两种状态,混为一谈会让解析 bug
    伪装成「语料里没有相关内容」。
    """
    if not response or not isinstance(response, str):
        return None, ""

    text = response.strip()

    for payload in _json_candidates(text):
        grade = payload.get("grade")
        if isinstance(grade, bool):
            continue
        if isinstance(grade, (int, float)) and int(grade) in VALID_GRADES:
            reason = payload.get("reason") or ""
            return int(grade), str(reason).strip()

    # 裸数字兜底：取第一个 0-3 的独立数字
    match = re.search(r"\b([0-3])\b", text)
    if match:
        return int(match.group(1)), ""

    return None, ""


def _json_candidates(text: str) -> List[Dict[str, Any]]:
    """尽力从文本里抽出 JSON 对象(先整体,再找第一个 {...} 片段)。"""
    out: List[Dict[str, Any]] = []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            out.append(parsed)
    except (json.JSONDecodeError, ValueError):
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                out.append(parsed)
        except (json.JSONDecodeError, ValueError):
            pass
    return out
