"""目标语言校验 (change expand-chinese-golden-set T-1.1)。

## 这个模块解决什么问题

RAGAS 的 `TestsetGenerator.adapt(language=...)` 把内部提示词翻译到目标语言。
它**可能在不抛出任何异常的情况下返回未翻译的原文** —— 2026-08-14 实测:
`logs/ragas_adapt_cache/chinese/` 下五个「中文」提示词文件里,CJK 字符数**全部
为 0**。

后果链条:

1. adapt「成功」返回 → 现有的 fail-fast(只捕获异常)从未触发
2. 未翻译的英文提示词被写进磁盘缓存,**永久固化**
3. 后续每次合成都从磁盘读到英文提示词 → 产出英文问题
4. 第一代中文金标 47 条候选里 **33 条(70%)因语种不符被丢**,只活下来 6 条

**「没报错」不等于「做对了」。** 检测这种失效必须校验产物本身,而不是等异常。

## 为什么用字符集占比而不是语言识别库

判断的是「这段文本到底有没有被翻译」,这是个二值问题。引入 `langdetect` /
`fasttext` 会给它套上一个概率模型,反而多一处不确定性 —— 而且新增依赖不值得。
实测两端差异极大:未翻译时占比恒为 **0.0%**,翻译后显著为正,落在中间的概率低。

代价是每加一门语言要补一条字符集规则,但 `lang_to_ragas` 映射本来就要逐语言
登记,没有额外负担。

纯函数、零依赖:不 import ragas、不联网,单测可完全离线。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Sequence, Tuple


@dataclass(frozen=True)
class LanguageCheck:
    """一次语言校验的结果。

    刻意返回结构体而非裸 bool —— 调用方几乎总是既要判定、又要把实测占比写进
    日志或元数据(「为什么判失败」比「失败了」有用得多)。

    Attributes:
        language: 被校验的目标语言代码。
        ratio: 目标语言特征字符占全部**非空白**字符的比例。
        threshold: 本次判定所用的下限。
        passed: `ratio >= threshold`。
        counted_chars: 参与统计的非空白字符总数。
    """

    language: str
    ratio: float
    threshold: float
    passed: bool
    counted_chars: int

    def describe(self) -> str:
        """一句话说明,可直接进错误消息或元数据。"""
        verdict = "passed" if self.passed else "FAILED"
        return (
            f"language check {verdict}: {self.ratio:.1%} of {self.counted_chars} "
            f"characters are {self.language} (threshold {self.threshold:.1%})"
        )


# 各语言的特征字符区间。新增语言在此登记,与 lang_to_ragas 映射一一对应。
#
# 中文用 CJK 统一表意文字基本区 (U+4E00–U+9FFF)。刻意不含标点、不含扩展区:
# 基本区足以判断「有没有汉字」,而扩展区的罕用字在提示词里几乎不出现。
_LANGUAGE_RANGES: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "zh": (("一", "鿿"),),
}


def supported_languages() -> Tuple[str, ...]:
    """已登记特征字符规则的语言代码。"""
    return tuple(sorted(_LANGUAGE_RANGES))


def language_char_ratio(text: str, language: str) -> Tuple[float, int]:
    """算目标语言特征字符占**非空白**字符的比例。

    分母排除空白,是因为 JSON 结构里换行与缩进占比很高且与语言无关 —— 算进去
    会让同一段译文因为格式化方式不同而得到不同的比例。

    Args:
        text: 待检文本。
        language: 目标语言代码,须在 `supported_languages()` 内。

    Returns:
        `(比例, 参与统计的字符数)`。文本为空时返回 `(0.0, 0)`。

    Raises:
        ValueError: 语言未登记。
    """
    ranges = _LANGUAGE_RANGES.get(language)
    if ranges is None:
        raise ValueError(
            f"unsupported language for character-set check: {language!r}. "
            f"Supported: {list(supported_languages())}. Register its character "
            "ranges in _LANGUAGE_RANGES before using it."
        )

    counted = 0
    hits = 0
    for ch in text:
        if ch.isspace():
            continue
        counted += 1
        if any(lo <= ch <= hi for lo, hi in ranges):
            hits += 1

    if counted == 0:
        return 0.0, 0
    return hits / counted, counted


def check_language(text: str, language: str, threshold: float) -> LanguageCheck:
    """校验文本是否达到目标语言的字符占比下限。

    Args:
        text: 待检文本。
        language: 目标语言代码。
        threshold: 占比下限,取值 `[0.0, 1.0]`。

    Returns:
        校验结果。

    Raises:
        ValueError: 语言未登记,或阈值超出 `[0.0, 1.0]`。
    """
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"threshold must be in [0.0, 1.0], got {threshold!r}")

    ratio, counted = language_char_ratio(text, language)
    return LanguageCheck(
        language=language,
        ratio=ratio,
        threshold=threshold,
        # 空文本一律判失败：没有内容可以证明它被翻译过。
        passed=counted > 0 and ratio >= threshold,
        counted_chars=counted,
    )


def mismatch_ratio(texts: Sequence[str], language: str, threshold: float) -> float:
    """算一批文本里「语种与目标语言不一致」的比例。

    用于合成产物的语种一致性统计(T-3.2 / spec 第三条需求):合成完的问题到底
    是不是目标语言,是「适配有没有真的起作用」最直接的证据。第一代中文合成的
    这个值是 **70%(33/47)**。

    Args:
        texts: 待检文本序列(通常是候选集里的 question 字段)。
        language: 目标语言代码。
        threshold: 单条文本的占比下限。

    Returns:
        不一致比例 `[0.0, 1.0]`。空序列返回 `0.0`。
    """
    items = list(texts)
    if not items:
        return 0.0
    bad = sum(1 for t in items if not check_language(t, language, threshold).passed)
    return bad / len(items)


def summarize_language(
    texts: Iterable[str], language: str, threshold: float
) -> Dict[str, float]:
    """一批文本的语种统计,可直接写进元数据。"""
    items = list(texts)
    return {
        "total": float(len(items)),
        "mismatch_ratio": mismatch_ratio(items, language, threshold),
        "threshold": threshold,
    }


# ---------------------------------------------------------------------------
# 文本的语言归类(change answer-language-follows-question T-1.1)
# ---------------------------------------------------------------------------
#
# ⚠️ 这**不是**通用语言识别,是「中文 vs 非中文」的二分。
#
# 为什么只做到这一步:本项目语料是中英双语,二分够用;而声称更多就是过度承诺 ——
# 一段法文会被判成 `non-zh`,而我们不会知道。所以返回值刻意叫 `non-zh` 而不是
# `en`:前者是我们真的知道的事,后者是猜的。
#
# 为什么不给 `en` 登记字符集:拉丁字母在中文技术文本里也大量出现(API 标识符、
# 代码片段),按占比判 `en` 会与按占比判 `zh` 互相矛盾 —— 同一段文本可能两边
# 都「达标」。**二分只能有一个基准语言。**

#: 判为中文。
LANGUAGE_ZH = "zh"

#: 判为非中文。刻意不叫 `en` —— 见上方说明。
LANGUAGE_NON_ZH = "non-zh"

#: 无法判定 —— 文本里没有承载语言信号的字符(纯数字/标点/空白)。
#:
#: **必须与「判为非中文」区分开。** 回落成任一具体语言会让「没测出来」与
#: 「测过且是那个语言」长得一模一样,而本项目已因这种回落栽过多次。
LANGUAGE_UNDETERMINED = "undetermined"


def _has_language_signal(text: str) -> bool:
    """文本里是否有承载语言信号的字符(字母或 CJK)。

    纯数字、纯标点、纯空白都判为没有 —— 那种文本无法归类,
    调用方应记 :data:`LANGUAGE_UNDETERMINED`。
    """
    for ch in text or "":
        if ch.isalpha():
            return True
    return False


def classify_language(text: str, threshold: float) -> str:
    """把文本归类为中文 / 非中文 / 无法判定。

    Args:
        text: 待归类文本。
        threshold: CJK 字符占比下限,达到即判中文。调用方从配置读
            (本模块保持纯函数,不 import settings)。

    Returns:
        :data:`LANGUAGE_ZH` / :data:`LANGUAGE_NON_ZH` / :data:`LANGUAGE_UNDETERMINED`。

    Example:
        >>> classify_language("How to configure LLM?", 0.05)
        'non-zh'
        >>> classify_language("怎么配置 LLM?", 0.05)
        'zh'
        >>> classify_language("123 !!!", 0.05)
        'undetermined'
    """
    if not text or not text.strip():
        return LANGUAGE_UNDETERMINED
    if not _has_language_signal(text):
        return LANGUAGE_UNDETERMINED
    ratio, _counted = language_char_ratio(text, LANGUAGE_ZH)
    return LANGUAGE_ZH if ratio >= threshold else LANGUAGE_NON_ZH


def compare_languages(question: str, answer: str, threshold: float) -> Dict[str, object]:
    """问答两端的语言归类与一致性结论,可直接写进元数据或 trace。

    **为什么需要这个结论被显式记下来**:答案语言错了与答案质量差,在最终指标上
    表现相同 —— 两者都只是分数变低。没有这个字段就无法区分这两件事,而它们的
    处置完全不同(改提示词 / 改检索或模型)。本项目的这个缺陷存在了数月而无人
    发现,正是因为没有任何地方直接说出「这次答错语言了」。

    Args:
        question: 用户的问题。
        answer: 生成的答案。
        threshold: CJK 占比下限,见 :func:`classify_language`。

    Returns:
        含 ``measured`` / ``question_language`` / ``answer_language`` /
        ``threshold`` 的字典。**只有 ``measured`` 为真时才有 ``consistent``** ——
        任一端无法判定时不给这个键,回落成 ``True`` 会让「没测」与
        「测过且一致」无法区分。
    """
    q_lang = classify_language(question, threshold)
    a_lang = classify_language(answer, threshold)
    result: Dict[str, object] = {
        "question_language": q_lang,
        "answer_language": a_lang,
        "threshold": threshold,
    }
    if LANGUAGE_UNDETERMINED in (q_lang, a_lang):
        result["measured"] = False
        result["reason"] = (
            "cannot classify language: no alphabetic or CJK characters in "
            + ("question" if q_lang == LANGUAGE_UNDETERMINED else "answer")
        )
        return result
    result["measured"] = True
    result["consistent"] = q_lang == a_lang
    return result
