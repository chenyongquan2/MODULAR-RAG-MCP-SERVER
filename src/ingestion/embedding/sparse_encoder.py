"""稀疏向量编码 (BM25 统计)。

该模块负责为 BM25 检索生成词项统计信息，
包括词频 (TF)、文档频率 (DF) 等，供 BM25Indexer 使用。

================================================================================
【稀疏向量与 BM25 的关系】
================================================================================

【什么是稀疏向量？】
稀疏向量是一种高维向量，其中大部分维度为 0。
在文本检索中，每个词对应一个维度，词频作为值。

示例：
    文本: "hello world hello"
    稀疏向量: {"hello": 2, "world": 1}

    对应的稠密向量（假设词表大小为 10000）：
    [0, 0, 2, 0, 0, ..., 1, 0, 0, ...]  # 只有 2 个位置非零

【稀疏向量 vs 稠密向量】
| 特性 | 稀疏向量 | 稠密向量 |
|------|----------|----------|
| 维度 | 词表大小（可能几十万） | 固定（如 768, 1024） |
| 存储 | 只存非零值 | 存储所有值 |
| 语义 | 无语义理解 | 有语义理解 |
| 用途 | 关键词匹配 | 语义相似度 |

【BM25 的输入】
BM25 算法需要两个输入：
1. 词频 (TF): 词在文档中出现的次数 → 由 SparseEncoder 计算
2. 文档频率 (DF): 包含该词的文档数 → 由 BM25Indexer.build() 计算

【数据流】
┌─────────────┐    ┌──────────────┐    ┌─────────────────┐
│ Chunk       │ → │ SparseEncoder│ → │ ChunkRecord     │
│ (text)      │    │ 计算 TF      │    │ (sparse_vector) │
└─────────────┘    └──────────────┘    └─────────────────┘
                                              │
                                              ▼
                                       ┌─────────────────┐
                                       │ BM25Indexer     │
                                       │ 计算 IDF        │
                                       │ 构建倒排索引    │
                                       └─────────────────┘

================================================================================
"""

from collections import Counter
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Any

from src.core.text.tokenizer import DEFAULT_STOP_WORDS as SHARED_STOP_WORDS
from src.core.text.tokenizer import tokenize
from src.core.types import Chunk, ChunkRecord

if TYPE_CHECKING:
    from src.core.trace.trace_context import TraceContext


class SparseEncoder:
    """稀疏向量编码器 (BM25 统计)。

    将 Chunk 列表转换为带有稀疏向量（词项权重）的 ChunkRecord 列表。
    生成 BM25 所需的词频 (TF) 和文档频率 (DF) 统计信息。

    Attributes:
        stop_words: 停用词集合（可选，用于过滤常见词）
        min_term_length: 最小词项长度（默认 2）
        max_term_length: 最大词项长度（默认 50）

    Example:
        >>> encoder = SparseEncoder()
        >>> chunks = [Chunk(id="1", text="Hello world hello", metadata={})]
        >>> result = encoder.encode(chunks)
        >>> len(result) == 1
        True
        >>> result[0].sparse_vector is not None
        True
    """

    #: 停用词表 —— 指向共享实现（feature-004 T026）。
    #:
    #: 此前这里是一份 89 词的本地表，而 ``query_processor.py`` 有另一份
    #: 181 词的表。9 个词只在索引端被过滤，于是查询会去搜索引里根本没有的
    #: 词条 —— 白搜，且不报错。现在两端共用并集。
    DEFAULT_STOP_WORDS: Set[str] = set(SHARED_STOP_WORDS)

    def __init__(
        self,
        stop_words: Optional[Set[str]] = None,
        min_term_length: int = 2,
        max_term_length: int = 50,
    ) -> None:
        """初始化 SparseEncoder。

        Args:
            stop_words: 停用词集合（默认使用英文停用词）
            min_term_length: 最小词项长度（默认 2）
            max_term_length: 最大词项长度（默认 50）
        """
        if stop_words is None:
            self._stop_words = self.DEFAULT_STOP_WORDS
        else:
            self._stop_words = stop_words
        self._min_term_length = min_term_length
        self._max_term_length = max_term_length
        self._document_frequency: Counter = Counter()

    def _tokenize(self, text: str) -> List[str]:
        """分词：将文本转换为词项列表。

        **委托给 ``src.core.text.tokenizer``**（feature-004 T026）。

        此前这里有一份本地实现 ``re.findall(r'\\b[a-z0-9]+\\b', text)``，
        与 ``query_processor.py`` 的另一份实现在三处不一致（CJK 字符、
        停用词表、连字符处理），导致索引里的词条与查询切出的词条对不上 ——
        而这种失败**不报错，只是召回恒为空**（缺陷 D3）。

        现在两端共用同一个函数，口径漂移由
        ``tests/unit/test_tokenizer.py::TestBothEndsAgree`` 守住。

        Args:
            text: 输入文本

        Returns:
            词项列表（保留顺序与重复 —— 词频统计要用）
        """
        return tokenize(
            text,
            stop_words=self._stop_words,
            min_length=self._min_term_length,
            max_length=self._max_term_length,
        )

    def _compute_term_frequencies(self, text: str) -> Dict[str, int]:
        """计算词频 (TF)。

        【词频 (Term Frequency) 定义】
        词频是指一个词在文档中出现的次数。

        【示例】
        文本: "hello world hello python"
        分词后: ["hello", "world", "hello", "python"]
        词频: {"hello": 2, "world": 1, "python": 1}

        【BM25 中的使用】
        词频是 BM25 公式的一部分：
        BM25 = IDF × (tf × (k1 + 1)) / (tf + k1 × ...)

        词频越高，BM25 得分越高，但存在饱和效应（由 k1 参数控制）。

        Args:
            text: 输入文本

        Returns:
            词频字典 {term: count}
        """
        tokens = self._tokenize(text)
        if not tokens:
            return {}

        # Counter 统计每个词出现的次数
        return dict(Counter(tokens))

    def encode(
        self,
        chunks: List[Chunk],
        trace: Optional["TraceContext"] = None,
    ) -> List[ChunkRecord]:
        """将 Chunk 列表编码为带有稀疏向量的 ChunkRecord 列表。

        【编码流程】
        1. 对每个 chunk 的文本进行分词
        2. 统计每个词的词频 (TF)
        3. 将词频存入 sparse_vector 字段

        【输出格式】
        ChunkRecord.sparse_vector = {"hello": 2.0, "world": 1.0, ...}

        【与 BM25Indexer 的关系】
        SparseEncoder 只计算词频 (TF)。
        文档频率 (DF) 和 IDF 由 BM25Indexer.build() 计算。

        为什么分开？
        - TF 是文档级别的，每个文档独立计算
        - DF 是集合级别的，需要知道所有文档才能计算
        - IDF 依赖于 DF 和文档总数 N

        Args:
            chunks: 待编码的 Chunk 列表
            trace: 可选的跟踪上下文

        Returns:
            带有稀疏向量的 ChunkRecord 列表，数量和顺序与输入 chunks 一致

        Raises:
            ValueError: chunks 列表为空
        """
        if not chunks:
            raise ValueError("Chunks list cannot be empty")

        # 重置文档频率统计
        self._document_frequency = Counter()
        chunk_term_freqs: List[Dict[str, int]] = []

        # 第一遍：计算每个 chunk 的词频
        for chunk in chunks:
            term_freqs = self._compute_term_frequencies(chunk.text)
            chunk_term_freqs.append(term_freqs)

            # 更新文档频率（每个词在每个文档中只计数一次）
            for term in term_freqs:
                self._document_frequency[term] += 1

        # 第二遍：创建 ChunkRecord
        records = []
        for i, chunk in enumerate(chunks):
            term_freqs = chunk_term_freqs[i]

            # 创建 ChunkRecord，sparse_vector 存储词频
            record = ChunkRecord(
                id=chunk.id,
                text=chunk.text,
                metadata=chunk.metadata.copy(),
                # 将词频转换为 float（BM25 计算需要）
                sparse_vector={k: float(v) for k, v in term_freqs.items()} if term_freqs else None,
            )

            # 保留原始 chunk 的元数据
            if chunk.start_offset is not None:
                record.metadata["start_offset"] = chunk.start_offset
            if chunk.end_offset is not None:
                record.metadata["end_offset"] = chunk.end_offset
            if chunk.source_ref is not None:
                record.metadata["source_ref"] = chunk.source_ref

            # 添加词频统计信息到元数据
            record.metadata["term_count"] = sum(term_freqs.values())  # 总词数
            record.metadata["unique_terms"] = len(term_freqs)  # 唯一词数

            records.append(record)

        return records

    def get_document_frequency(self) -> Dict[str, int]:
        """获取文档频率统计。

        Returns:
            文档频率字典 {term: df}，df 表示包含该词项的文档数
        """
        return dict(self._document_frequency)

    def get_total_documents(self) -> int:
        """获取已处理的文档总数。

        Returns:
            处理的 Chunk 总数
        """
        return sum(self._document_frequency.values())
