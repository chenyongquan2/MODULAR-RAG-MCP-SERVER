"""查询预处理 (关键词提取 + filters 结构)。

该模块负责对用户查询进行预处理，提取关键词并解析过滤条件，
为后续的 SparseRetriever (BM25) 提供查询词。
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

from ..text.tokenizer import DEFAULT_STOP_WORDS as SHARED_STOP_WORDS
from ..text.tokenizer import tokenize
from ..types import ProcessedQuery


#: 停用词表 —— 指向共享实现（feature-004 T027）。
#:
#: 此前这里是一份 181 词的本地表，而 ``sparse_encoder.py`` 有另一份 89 词的
#: 表。9 个词只在索引端过滤，查询会去搜索引里根本没有的词条；101 个词只在
#: 查询端过滤，白占索引空间。现在两端共用并集。
DEFAULT_STOPWORDS: frozenset[str] = SHARED_STOP_WORDS


@dataclass
class QueryProcessorConfig:
    """QueryProcessor 配置。

    Attributes:
        use_stopwords: 是否使用停用词过滤，默认 True
        min_keyword_length: 最小关键词长度，默认 2
        max_keywords: 最大关键词数量，默认 10
    """
    use_stopwords: bool = True
    min_keyword_length: int = 2
    max_keywords: int = 10


class QueryProcessor:
    """查询预处理器。

    负责对用户查询进行预处理：
    1. 关键词提取（基于规则/分词 + 停用词过滤）
    2. 过滤条件解析

    Attributes:
        config: 处理器配置
        stopwords: 停用词集合

    Example:
        >>> processor = QueryProcessor()
        >>> result = processor.process("How to configure LLM in settings?")
        >>> print(result.keywords)  # ['configure', 'llm', 'settings']
    """

    def __init__(
        self,
        config: Optional[QueryProcessorConfig] = None,
        stopwords: Optional[frozenset[str]] = None,
        query_rewriter: Optional[Any] = None,
    ) -> None:
        """初始化 QueryProcessor。

        Args:
            config: 处理器配置，默认使用 QueryProcessorConfig()
            stopwords: 停用词集合，默认使用 DEFAULT_STOPWORDS
            query_rewriter: 查询改写器，默认「不改写」。
                注意默认值是 ``NoneQueryRewriter`` 实例而**不是 None** ——
                这样 ``process()`` 里不必写 ``if self._rewriter is not None``，
                关闭与启用走同一条代码路径，少一个分支就少一处漂移的可能。
        """
        self.config = config or QueryProcessorConfig()
        self.stopwords = stopwords or DEFAULT_STOPWORDS
        if query_rewriter is None:
            from src.libs.query_rewriter.base_query_rewriter import NoneQueryRewriter

            query_rewriter = NoneQueryRewriter()
        self._query_rewriter = query_rewriter

    def process(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
    ) -> ProcessedQuery:
        """处理查询，提取关键词并解析过滤条件。

        Args:
            query: 原始查询文本
            filters: 过滤条件字典 (可选)，如 {"collection": "docs", "doc_type": "pdf"}

        Returns:
            ProcessedQuery: 包含原始查询、关键词和过滤条件的对象

        Raises:
            ValueError: 当 query 为空或 None 时
        """
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")

        original_query = query.strip()

        keywords = self._extract_keywords(original_query)

        # 改写发生在**关键词提取之后**（design D3）。
        #
        # 顺序不能颠倒：作用在原始文本上的话，扩展会命中本该被停用词过滤掉
        # 的词，把噪音带进 BM25 查询 —— 而这不会报错，只会让 sparse 更吵。
        #
        # 只改 keywords，不改 original_query：稠密路吃的是原始查询，它的
        # embedding 本就对同义词鲁棒，往那边塞同义词只是稀释语义信号。
        expanded_keywords = list(
            self._query_rewriter.rewrite_keywords(keywords, query=original_query)
        )
        strategy = self._query_rewriter.get_strategy_name()
        added = [w for w in expanded_keywords if w not in keywords]

        # 未改写时同样留痕 —— 省略会让「没启用」与「启用了但没匹配到任何词」
        # 在数据上无法区分，而这两件事的处置完全相反。
        rewrite_info = {
            "strategy": strategy,
            "original_keywords": list(keywords),
            "expanded_keywords": list(expanded_keywords),
            "added_count": len(added),
        }
        # rewritten_query 只在真的产生了新词时才填 —— 它表示「稀疏路实际用的
        # 查询」，没变化时留 None，保持与改写前逐条相同的序列化形态。
        rewritten_query = " ".join(expanded_keywords) if added else None

        parsed_filters = self._parse_filters(filters)

        return ProcessedQuery(
            original_query=original_query,
            keywords=expanded_keywords,
            filters=parsed_filters,
            rewritten_query=rewritten_query,
            rewrite_info=rewrite_info,
        )

    def _tokenize_shared(self, query: str) -> List[str]:
        """走共享切分实现（feature-004 T027）。

        单独拆成一个方法，是为了让
        ``tests/unit/test_tokenizer.py::TestBothEndsAgree`` 能把它与索引端的
        ``SparseEncoder._tokenize`` 直接对比 —— 两者对同一段文本必须逐元素
        相等。这是本 feature 的核心不变量（FR-009）。
        """
        return tokenize(
            query,
            stop_words=self.stopwords if self.config.use_stopwords else frozenset(),
            min_length=self.config.min_keyword_length,
        )

    def _extract_keywords(self, query: str) -> List[str]:
        """从查询中提取关键词。

        流程拆成两层：

        1. **切分**（``_tokenize_shared``）—— 与索引端共用同一实现。
           此前这里有一份本地正则 ``re.sub(r"[^a-z0-9\\s-]", " ", ...)``，
           与 ``sparse_encoder.py`` 的实现在三处不一致：它丢弃全部汉字、
           用一份 181 词的停用词表（索引端只有 89 词）、把 ``well-known``
           当作一个整词（索引端切成 ``well`` + ``known``）。三处都会让查询
           切出的词条**永远匹配不上**索引里的词条，而且不报错（缺陷 D3）。
        2. **查询侧策略** —— 去重 + 截断到 ``max_keywords``。这两步属于
           调用方策略而非切分：索引端要保留重复来算词频，查询端不需要。

        Args:
            query: 查询文本

        Returns:
            关键词列表（去重，保留首次出现顺序，最多 ``max_keywords`` 个）
        """
        tokens = self._tokenize_shared(query)

        unique_tokens = []
        seen = set()
        for token in tokens:
            if token not in seen:
                unique_tokens.append(token)
                seen.add(token)

        return unique_tokens[: self.config.max_keywords]

    def _parse_filters(
        self,
        filters: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """解析过滤条件。

        Args:
            filters: 原始过滤条件字典

        Returns:
            解析后的过滤条件字典（保证不为 None）
        """
        if filters is None:
            return {}
        return dict(filters)
