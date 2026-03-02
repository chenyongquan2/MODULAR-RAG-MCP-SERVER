"""稀疏向量编码 (BM25 统计)。

该模块负责为 BM25 检索生成词项统计信息，
包括词频 (TF)、文档频率 (DF) 等，供 BM25Indexer 使用。
"""

import re
from collections import Counter
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Any

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

    DEFAULT_STOP_WORDS: Set[str] = {
        "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "as", "is", "was", "are", "were", "been",
        "be", "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "must", "shall", "can", "need",
        "dare", "ought", "used", "it", "its", "this", "that", "these",
        "those", "i", "you", "he", "she", "we", "they", "what", "which",
        "who", "whom", "whose", "where", "when", "why", "how", "all", "each",
        "every", "both", "few", "more", "most", "other", "some", "such",
        "no", "nor", "not", "only", "own", "same", "so", "than", "too",
        "very", "just", "also", "now", "here", "there", "then", "once",
    }

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

        Args:
            text: 输入文本

        Returns:
            词项列表（小写化，去除标点）
        """
        if not text or not text.strip():
            return []

        text = text.lower()
        tokens = re.findall(r'\b[a-z0-9]+\b', text)

        filtered_tokens = [
            t for t in tokens
            if self._min_term_length <= len(t) <= self._max_term_length
            and t not in self._stop_words
        ]

        return filtered_tokens

    def _compute_term_frequencies(self, text: str) -> Dict[str, int]:
        """计算词频 (TF)。

        Args:
            text: 输入文本

        Returns:
            词频字典 {term: count}
        """
        tokens = self._tokenize(text)
        if not tokens:
            return {}

        return dict(Counter(tokens))

    def encode(
        self,
        chunks: List[Chunk],
        trace: Optional["TraceContext"] = None,
    ) -> List[ChunkRecord]:
        """将 Chunk 列表编码为带有稀疏向量的 ChunkRecord 列表。

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

        self._document_frequency = Counter()
        chunk_term_freqs: List[Dict[str, int]] = []

        for chunk in chunks:
            term_freqs = self._compute_term_frequencies(chunk.text)
            chunk_term_freqs.append(term_freqs)

            for term in term_freqs:
                self._document_frequency[term] += 1

        records = []
        for i, chunk in enumerate(chunks):
            term_freqs = chunk_term_freqs[i]

            record = ChunkRecord(
                id=chunk.id,
                text=chunk.text,
                metadata=chunk.metadata.copy(),
                sparse_vector={k: float(v) for k, v in term_freqs.items()} if term_freqs else None,
            )
            if chunk.start_offset is not None:
                record.metadata["start_offset"] = chunk.start_offset
            if chunk.end_offset is not None:
                record.metadata["end_offset"] = chunk.end_offset
            if chunk.source_ref is not None:
                record.metadata["source_ref"] = chunk.source_ref

            record.metadata["term_count"] = sum(term_freqs.values())
            record.metadata["unique_terms"] = len(term_freqs)

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
