"""同义词 / 术语扩展改写器。

**做法**：把关键词按一张词表展开成同义词、缩写、别名。

    "怎么设置止损"  →  keywords: [设置, 止损]
                    →  扩展后: [设置, 止损, SL, stop loss, stoploss]

**为什么是这四种策略里第一个做的**（本项目的选型依据）：

| 维度 | 同义词扩展 | Multi-Query | HyDE |
|---|---|---|---|
| LLM 调用 | **0** | 1 | 1 |
| 延迟 | **~0（查表）** | +1-2s | +1-3s |
| Token | **0** | 中 | 高 |
| 主要受益路径 | **sparse** | sparse | dense（且**对 sparse 有害**）|

HyDE 是这几个里名气最大的，却是对本项目最不对症的一个：它让 dense 拿一段
LLM 编出来的「假想答案」去检索，而那段散文会引入语料里根本不存在的词 ——
喂给 BM25 只是加噪。**选型看的是路径匹配，不是知名度。**

**为什么只改 keywords、不改原始查询**：稠密路吃的是原始查询文本，而它的
embedding 本就对同义词鲁棒（「止损」与「stop loss」的向量本来就近）。往那边
塞同义词不会带来增益，只会把一个干净的语义信号稀释成一串并列词。稀疏路吃的
是 keywords，它才是字面匹配、才需要更多词面。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml

from src.core.text.tokenizer import tokenize
from src.libs.query_rewriter.base_query_rewriter import BaseQueryRewriter
from src.observability.logger import get_logger

logger = get_logger(__name__)


def _load_synonym_groups(path: str) -> List[Tuple[str, ...]]:
    """把词表文件读成「同义词组」的列表。

    词表写作 ``词 -> 同义词列表``，但语义上是**一组等价词面**：

        止损: [SL, stop loss]

    表示「止损 / SL / stop loss」三者互为同义。命中其中**任一个**都应展开出
    整组 —— 用户既可能写术语也可能写缩写，单向展开会漏掉一半情形。

    Args:
        path: 词表文件路径。内容合法性已由 ``load_settings()`` 在启动期校验。

    Returns:
        每组一个元组，组内元素保持词表里的书写顺序（键在最前）。
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    groups: List[Tuple[str, ...]] = []
    for term, synonyms in raw.items():
        members = [str(term)] + [str(s) for s in (synonyms or [])]
        # 去掉空白项与组内重复，但保持顺序
        seen: set[str] = set()
        ordered: List[str] = []
        for member in members:
            text = member.strip()
            if not text or text in seen:
                continue
            seen.add(text)
            ordered.append(text)
        if len(ordered) >= 2:  # 单元素组没有扩展意义
            groups.append(tuple(ordered))
    return groups


class SynonymQueryRewriter(BaseQueryRewriter):
    """按词表做同义词 / 术语扩展。**零 LLM 调用、零延迟、零 token。**

    Attributes:
        settings: 应用配置。
    """

    def __init__(self, settings: Any = None, **kwargs: Any) -> None:
        """初始化。

        词表在**构造时一次性读入**，不在每次查询时读盘 —— 检索是热路径，
        每查询一次读一次文件既慢又会让结果依赖磁盘状态。

        Args:
            settings: 应用配置，读 ``query_rewrite.synonym_dict``。
            **kwargs: ``synonym_dict`` 可覆盖路径（供测试与特殊场景使用）。
        """
        self.settings = settings
        dict_path = kwargs.get("synonym_dict")
        if dict_path is None and settings is not None:
            dict_path = settings.query_rewrite.synonym_dict
        if not dict_path:
            # 正常情况下 load_settings() 已经挡住了；这里是防止绕过配置直接
            # 构造的调用方拿到一个「什么都不做但看起来在做」的改写器 ——
            # 那正是本项目要消灭的形态。
            raise ValueError(
                "SynonymQueryRewriter requires a synonym dictionary path "
                "(query_rewrite.synonym_dict). There is deliberately no default: "
                "an empty rewriter would silently behave like 'none'."
            )

        self._groups = _load_synonym_groups(str(dict_path))
        # 词面 -> 该词面所属的组。查表用小写做键,让 "SL" / "sl" 都能命中。
        self._index: Dict[str, Tuple[str, ...]] = {}
        for group in self._groups:
            for member in group:
                self._index.setdefault(member.lower(), group)

        logger.info(
            "SynonymQueryRewriter 就绪:%d 组同义词、%d 个可匹配词面(来自 %s)",
            len(self._groups),
            len(self._index),
            dict_path,
        )

    def get_strategy_name(self) -> str:
        return "synonym"

    @property
    def group_count(self) -> int:
        """词表里的同义词组数 —— 供追踪与验收记录使用。"""
        return len(self._groups)

    def rewrite_keywords(
        self,
        keywords: Sequence[str],
        query: str = "",
        trace: Optional[Any] = None,
    ) -> List[str]:
        """把命中词表的关键词展开成整组同义词。

        三条口径：

        1. **原关键词全部保留且顺序不变**，扩展词追加在后面。原查询词是用户
           的真实措辞，不该被替换掉。
        2. **扩展词也要过 tokenizer**：词表里写的是「stop loss」这种自然写法，
           而索引端存的是切分后的词条。不切分就等于往查询里塞了一个索引里
           永远不存在的词 —— 这类失败是**静默的**（不报错，只是永远不命中）。
        3. **去重但不排序**：同一个词面可能由多个关键词各自引出。

        Args:
            keywords: 原始关键词，顺序有意义。
            query: 未使用（本策略不需要上下文）。
            trace: 未使用（打点由调用方在 ``QueryProcessor`` 侧完成，
                那里才知道改写前后的完整对照）。

        Returns:
            原关键词 + 扩展词（去重、保持首次出现顺序）。
        """
        result: List[str] = []
        seen: set[str] = set()

        def _append(word: str) -> None:
            text = word.strip()
            if not text:
                return
            key = text.lower()
            if key in seen:
                return
            seen.add(key)
            result.append(text)

        for keyword in keywords:
            _append(keyword)

        # 扩展词统一追加在原关键词之后 —— 先把用户自己的词说完,再补词面。
        for keyword in keywords:
            group = self._index.get(str(keyword).strip().lower())
            if group is None:
                continue
            for member in group:
                # 这里是关键：扩展词与索引端共用 src/core/text/tokenizer.py。
                # 词表写「stop loss」,索引里存的是切分后的词条,不切就永远
                # 匹配不上,而且不会报错 —— 本项目已因两端口径漂移踩过一次。
                for token in tokenize(member):
                    _append(token)

        return result
