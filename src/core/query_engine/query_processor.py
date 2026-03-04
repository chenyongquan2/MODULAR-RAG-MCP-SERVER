"""查询预处理 (关键词提取 + filters 结构)。

该模块负责对用户查询进行预处理，提取关键词并解析过滤条件，
为后续的 SparseRetriever (BM25) 提供查询词。
"""

import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

from ..types import ProcessedQuery


DEFAULT_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "has", "he", "in", "is", "it", "its", "of", "on", "that", "the",
    "to", "was", "were", "will", "with", "this", "but", "they", "have",
    "had", "what", "when", "where", "who", "which", "why", "how",
    "all", "each", "every", "both", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same", "so",
    "than", "too", "very", "can", "just", "should", "now",
    "i", "me", "my", "myself", "we", "our", "ours", "ourselves",
    "you", "your", "yours", "yourself", "yourselves",
    "he", "him", "his", "himself", "she", "her", "hers", "herself",
    "it", "its", "itself", "they", "them", "their", "theirs", "themselves",
    "what", "which", "who", "whom", "this", "that", "these", "those",
    "am", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "having", "do", "does", "did", "doing",
    "would", "could", "ought", "i'm", "you're", "he's", "she's", "it's",
    "they're", "i've", "you've", "we've", "they've", "i'd", "you'd",
    "he'd", "she'd", "we'd", "they'd", "i'll", "you'll", "he'll",
    "she'll", "we'll", "they'll", "isn't", "aren't", "wasn't", "weren't",
    "hasn't", "haven't", "hadn't", "doesn't", "don't", "didn't", "won't",
    "wouldn't", "shan't", "shouldn't", "can't", "cannot", "couldn't",
    "mustn't", "let's", "that's", "who's", "what's", "here's", "there's",
    "when's", "where's", "why's", "how's", "a", "an", "the", "and",
    "but", "if", "or", "because", "as", "until", "while", "of", "at",
    "by", "for", "with", "about", "against", "between", "into", "through",
    "during", "before", "after", "above", "below", "to", "from", "up",
    "down", "in", "out", "on", "off", "over", "under", "again",
    "further", "then", "once", "here", "there", "when", "where", "why",
    "how", "all", "any", "both", "each", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same", "so",
    "than", "too", "very", "s", "t", "can", "will", "just", "don",
    "should", "now",
})


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
    ) -> None:
        """初始化 QueryProcessor。

        Args:
            config: 处理器配置，默认使用 QueryProcessorConfig()
            stopwords: 停用词集合，默认使用 DEFAULT_STOPWORDS
        """
        self.config = config or QueryProcessorConfig()
        self.stopwords = stopwords or DEFAULT_STOPWORDS

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

        parsed_filters = self._parse_filters(filters)

        return ProcessedQuery(
            original_query=original_query,
            keywords=keywords,
            filters=parsed_filters,
        )

    def _extract_keywords(self, query: str) -> List[str]:
        """从查询中提取关键词。

        使用规则进行分词和清洗：
        1. 转小写
        2. 移除非字母字符（保留空格和连字符）
        3. 分词
        4. 过滤停用词
        5. 过滤短词
        6. 限制最大数量

        Args:
            query: 查询文本

        Returns:
            关键词列表
        """
        normalized = query.lower()

        normalized = re.sub(r"[^a-z0-9\s-]", " ", normalized)

        tokens = normalized.split()

        tokens = [
            token.strip("-")
            for token in tokens
            if token.strip("-")
        ]

        if self.config.use_stopwords:
            tokens = [
                token for token in tokens
                if token not in self.stopwords
            ]

        tokens = [
            token for token in tokens
            if len(token) >= self.config.min_keyword_length
        ]

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
