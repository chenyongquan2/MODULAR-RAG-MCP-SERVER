"""切分实现 —— 查询端与索引端的**唯一**来源。

⚠️ **禁止在别处复制这里的逻辑。**

本模块的存在理由是 Feature-004 修复的缺陷 D3:此前
``src/ingestion/embedding/sparse_encoder.py`` 与
``src/core/query_engine/query_processor.py`` **各自维护了一份切分实现**,
实测出三处互不一致:

============  ======================  ======================  ===================
差异          索引端(旧)              查询端(旧)              后果
============  ======================  ======================  ===================
CJK 字符      正则只留 ASCII,丢弃    同样丢弃                中文关键词检索完全
                                                              失效(名为
                                                              mt5_docs_chinese 的
                                                              索引 7165 词条含汉字
                                                              **0 个**)
停用词表      89 词                   181 词                  9 个词索引过滤了而
                                                              查询没过滤 → 查了也
                                                              永远匹配不上
连字符        ``well-known`` 切成     保留整体                 ``well-known`` 这类
              ``well`` + ``known``    ``well-known``           查询永远匹配不上
============  ======================  ======================  ===================

比"中文失效"更危险的是这类失败的形态:**两端口径一旦漂移,查询切出的词条
就永远匹配不上索引里的词条,而这个过程不报错、不告警,只是召回恒为空**。
D3 正是这样潜伏至今的。因此本模块是单一实现,并由
``tests/unit/test_tokenizer.py`` 的往返测试守住这条不变量。

**职责边界**:本模块只负责「文本 → 词条序列」。调用方各自的后处理策略留在
调用方 —— 索引端要按词频计数(``Counter``),查询端要去重并截断到 top-N。
那些是策略,不是切分。

切分规则见 specs/004-retrieval-infra-fix/data-model.md § 1。
"""

from __future__ import annotations

import re
from typing import FrozenSet, List, Optional

__all__ = [
    "CJK_PATTERN",
    "DEFAULT_STOP_WORDS",
    "MAX_TERM_LENGTH",
    "MIN_TERM_LENGTH",
    "contains_cjk",
    "is_cjk_term",
    "tokenize",
]


#: CJK 字符区间。
#:
#: 包含日文假名与韩文音节,虽然当前语料是中文 —— 它们若出现在语料里,
#: 落到非 CJK 分支就会被 ASCII 正则**静默丢弃**,重演 D3 的失败模式。
#: 纳入 CJK 分支走 bigram 处理,代价为零。
_CJK_RANGES = (
    "぀-ヿ"  # 平假名 + 片假名
    "㐀-䶿"  # CJK 扩展 A
    "一-鿿"  # CJK 基本区
    "豈-﫿"  # CJK 兼容表意文字
    "가-힯"  # 谚文音节
)

#: 匹配单个 CJK 字符
CJK_PATTERN = re.compile(f"[{_CJK_RANGES}]")

#: 把文本切成「连续 CJK 段」与「其余段」
_SEGMENT_PATTERN = re.compile(f"([{_CJK_RANGES}]+)")

#: 非 CJK 段的取词规则(与旧索引端一致:连字符处切开)
_ASCII_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")

#: 词长约束。**只作用于非 CJK 词条** —— CJK 单字词条长度为 1,
#: 套用这个下限会把它们全部吃掉,与「单字段落成词」的规则自相矛盾。
MIN_TERM_LENGTH = 2
MAX_TERM_LENGTH = 50

#: 停用词表 = 旧索引端(89 词)与旧查询端(181 词)的**并集**。
#:
#: 取并集而非二选一,是因为两个方向的失配都要消除:
#:
#: - 只在查询端的 101 词:查询本就不会搜它们,加进索引侧只省空间,无损失
#: - 只在索引端的 9 词(also/dare/may/might/must/need/shall/used/whose):
#:   此前查询会搜它们而索引里没有 → 白搜。补进查询侧即消除
DEFAULT_STOP_WORDS: FrozenSet[str] = frozenset({
    # ── 冠词 / 连词 / 介词 ──
    "a", "an", "the", "and", "but", "if", "or", "because", "as", "until",
    "while", "of", "at", "by", "for", "with", "about", "against", "between",
    "into", "through", "during", "before", "after", "above", "below", "to",
    "from", "up", "down", "in", "out", "on", "off", "over", "under", "again",
    "further", "then", "once", "here", "there", "when", "where", "why", "how",
    "nor", "so", "than", "too", "very", "such", "both", "each", "few", "more",
    "most", "other", "some", "no", "not", "only", "own", "same", "all", "any",
    # ── 代词 ──
    "i", "me", "my", "myself", "we", "our", "ours", "ourselves",
    "you", "your", "yours", "yourself", "yourselves",
    "he", "him", "his", "himself", "she", "her", "hers", "herself",
    "it", "its", "itself", "they", "them", "their", "theirs", "themselves",
    "what", "which", "who", "whom", "whose", "this", "that", "these", "those",
    # ── 系动词 / 助动词 ──
    "am", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "having", "do", "does", "did", "doing",
    "will", "would", "should", "could", "ought", "can", "may", "might",
    "must", "shall", "need", "dare",
    # ── 缩写形式 ──
    "i'm", "you're", "he's", "she's", "it's", "they're", "i've", "you've",
    "we've", "they've", "i'd", "you'd", "he'd", "she'd", "we'd", "they'd",
    "i'll", "you'll", "he'll", "she'll", "we'll", "they'll",
    "isn't", "aren't", "wasn't", "weren't", "hasn't", "haven't", "hadn't",
    "doesn't", "don't", "didn't", "won't", "wouldn't", "shan't", "shouldn't",
    "can't", "cannot", "couldn't", "mustn't", "let's", "that's", "who's",
    "what's", "here's", "there's", "when's", "where's", "why's", "how's",
    # ── 其他高频虚词 ──
    "also", "used", "just", "now", "every", "s", "t", "don",
})


def contains_cjk(text: str) -> bool:
    """文本中是否含 CJK 字符。"""
    return bool(CJK_PATTERN.search(text))


def is_cjk_term(term: str) -> bool:
    """该词条是否为 CJK 词条(用于豁免长度与停用词约束)。"""
    return bool(CJK_PATTERN.match(term))


def _tokenize_cjk_segment(segment: str) -> List[str]:
    """切分一段连续 CJK 字符。

    - 长度 ≥ 2:取全部相邻二字组合(滑窗)。「预约技师」→ 预约 / 约技 / 技师
    - 长度 = 1:该单字本身成词。否则「钱」「房」这类单字查询在关键词路径上
      永远无结果

    **跨词边界的噪音 bigram 会自愈**:像「理这」「果仅」这种切出来无意义的
    组合会出现在大量文档中 → 文档频率高 → IDF 低 → BM25 自动给它们极低
    权重。这是选用 bigram 而非词典分词的关键理由之一(见 research.md
    Decision 3)。
    """
    if len(segment) == 1:
        return [segment]
    return [segment[i : i + 2] for i in range(len(segment) - 1)]


def _tokenize_ascii_segment(
    segment: str,
    stop_words: FrozenSet[str],
    min_length: int,
    max_length: int,
) -> List[str]:
    """切分一段非 CJK 文本(小写化 + 取词 + 停用词 + 长度约束)。"""
    return [
        token
        for token in _ASCII_TOKEN_PATTERN.findall(segment.lower())
        if min_length <= len(token) <= max_length and token not in stop_words
    ]


def tokenize(
    text: str,
    stop_words: Optional[FrozenSet[str]] = None,
    min_length: int = MIN_TERM_LENGTH,
    max_length: int = MAX_TERM_LENGTH,
) -> List[str]:
    """把文本切成词条序列。

    **索引端与查询端必须调用同一个函数** —— 这是本模块存在的全部意义。
    两端产出的词条序列对同一段文本必须逐元素相等,否则索引再正确也检索
    不到,而且不会报错(见模块 docstring)。

    Args:
        text: 待切分文本。
        stop_words: 停用词表,默认 :data:`DEFAULT_STOP_WORDS`。**只作用于
            非 CJK 词条**。
        min_length: 非 CJK 词条的最小长度。
        max_length: 非 CJK 词条的最大长度。

    Returns:
        词条序列,**保留出现顺序与重复** —— 索引端要靠重复次数算词频。
        去重、截断这类策略属于调用方。

    Example:
        >>> tokenize("预约技师 API_v2")
        ['预约', '约技', '技师', 'api', 'v2']
        >>> tokenize("hello well-known world")
        ['hello', 'well', 'known', 'world']
    """
    if not text or not text.strip():
        return []

    if stop_words is None:
        stop_words = DEFAULT_STOP_WORDS

    tokens: List[str] = []
    # split 带捕获组时,奇数下标是 CJK 段、偶数下标是其余段
    for index, segment in enumerate(_SEGMENT_PATTERN.split(text)):
        if not segment:
            continue
        if index % 2 == 1:
            tokens.extend(_tokenize_cjk_segment(segment))
        else:
            tokens.extend(
                _tokenize_ascii_segment(segment, stop_words, min_length, max_length)
            )

    return tokens
