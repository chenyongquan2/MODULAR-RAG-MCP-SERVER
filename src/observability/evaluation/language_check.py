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
