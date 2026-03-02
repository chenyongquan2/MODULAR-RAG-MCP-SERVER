"""BM25 索引构建与持久化。

该模块负责：
- 接收 SparseEncoder 输出的稀疏向量（词频统计）
- 计算 IDF (Inverse Document Frequency)
- 构建倒排索引结构
- 支持索引序列化、加载、增量更新与重建
"""

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from src.core.types import ChunkRecord


InvertedIndex = Dict[str, Dict[str, Any]]
PostingList = List[Dict[str, Any]]


class BM25Indexer:
    """BM25 索引构建器。

    接收 SparseEncoder 输出的 ChunkRecord 列表，构建倒排索引，
    支持查询、持久化和增量更新。

    Attributes:
        index_dir: 索引文件存储目录
        k1: BM25 参数 k1（控制词频饱和度，默认 1.5）
        b: BM25 参数 b（控制文档长度归一化，默认 0.75）

    Example:
        >>> indexer = BM25Indexer(index_dir="data/db/bm25")
        >>> records = [ChunkRecord(id="1", text="hello world", metadata={}, sparse_vector={"hello": 1, "world": 1})]
        >>> indexer.build(records, collection="test")
        >>> results = indexer.query(["hello"], top_k=10)
        >>> len(results) > 0
        True
    """

    def __init__(
        self,
        index_dir: str = "data/db/bm25",
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        """初始化 BM25Indexer。

        Args:
            index_dir: 索引文件存储目录
            k1: BM25 词频饱和参数 (默认 1.5)
            b: 文档长度归一化参数 (默认 0.75)
        """
        self._index_dir = Path(index_dir)
        self._k1 = k1
        self._b = b

        self._index: InvertedIndex = {}
        self._doc_lengths: Dict[str, int] = {}
        self._avg_doc_length: float = 0.0
        self._total_documents: int = 0

    def _calculate_idf(self, document_frequency: int) -> float:
        """计算 IDF (Inverse Document Frequency)。

        Formula: IDF(term) = log((N - df + 0.5) / (df + 0.5))

        Args:
            document_frequency: 包含该词项的文档数

        Returns:
            IDF 值
        """
        if document_frequency <= 0 or self._total_documents <= 0:
            return 0.0
        if document_frequency >= self._total_documents:
            return 0.0
        return math.log((self._total_documents - document_frequency + 0.5) / (document_frequency + 0.5))

    def _compute_bm25_score(
        self,
        term: str,
        term_frequency: float,
        doc_length: int,
        idf: float,
    ) -> float:
        """计算单个词项的 BM25 得分。

        Formula: IDF * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * (dl / avg_dl)))

        Args:
            term: 词项
            term_frequency: 词频 (TF)
            doc_length: 文档长度
            idf: IDF 值

        Returns:
            BM25 得分
        """
        if term_frequency == 0 or doc_length == 0:
            return 0.0

        numerator = term_frequency * (self._k1 + 1)
        denominator = term_frequency + self._k1 * (1 - self._b + self._b * (doc_length / max(self._avg_doc_length, 1)))

        return idf * (numerator / denominator)

    def build(
        self,
        records: List[ChunkRecord],
        collection: str = "default",
    ) -> None:
        """构建 BM25 倒排索引。

        Args:
            records: 带有稀疏向量的 ChunkRecord 列表
            collection: 集合名称（用于索引文件命名）
        """
        valid_records = [r for r in records if r.sparse_vector]

        if not valid_records:
            self._index = {}
            self._doc_lengths = {}
            self._total_documents = 0
            self._avg_doc_length = 0.0
            return

        self._total_documents = len(valid_records)

        term_document_freq: Dict[str, int] = defaultdict(int)
        doc_lengths: Dict[str, int] = {}
        inverted_index: InvertedIndex = {}

        for record in valid_records:
            if not record.sparse_vector:
                continue

            doc_length = len(record.text)
            doc_lengths[record.id] = doc_length

            unique_terms = set(record.sparse_vector.keys())
            for term in unique_terms:
                term_document_freq[term] += 1

        for term, df in term_document_freq.items():
            idf = self._calculate_idf(df)
            inverted_index[term] = {"idf": idf, "postings": []}

        for record in valid_records:
            if not record.sparse_vector:
                continue

            doc_length = doc_lengths.get(record.id, len(record.text))

            for term, tf in record.sparse_vector.items():
                if term in inverted_index:
                    posting: Dict[str, Any] = {
                        "chunk_id": record.id,
                        "tf": tf,
                        "doc_length": doc_length,
                    }
                    inverted_index[term]["postings"].append(posting)

        self._index = inverted_index
        self._doc_lengths = doc_lengths
        self._avg_doc_length = sum(doc_lengths.values()) / len(doc_lengths) if doc_lengths else 0.0

    def query(
        self,
        keywords: List[str],
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """查询 BM25 索引。

        Args:
            keywords: 查询关键词列表
            top_k: 返回前 K 个结果

        Returns:
            按 BM25 得分排序的结果列表 [{"chunk_id": str, "score": float}, ...]
        """
        if not keywords or top_k <= 0:
            return []

        scores: Dict[str, float] = defaultdict(float)

        for keyword in keywords:
            term = keyword.lower()
            if term not in self._index:
                continue

            term_data = self._index[term]
            idf = term_data["idf"]
            postings = term_data["postings"]

            for posting in postings:
                chunk_id = posting["chunk_id"]
                tf = posting["tf"]
                doc_length = posting["doc_length"]

                score = self._compute_bm25_score(term, tf, doc_length, idf)
                scores[chunk_id] += score

        sorted_results = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [
            {"chunk_id": chunk_id, "score": score}
            for chunk_id, score in sorted_results[:top_k]
        ]

    def save(self, collection: str = "default") -> Path:
        """保存索引到文件。

        Args:
            collection: 集合名称

        Returns:
            保存的文件路径
        """
        self._index_dir.mkdir(parents=True, exist_ok=True)

        index_file = self._index_dir / f"{collection}.json"

        data = {
            "index": self._index,
            "doc_lengths": self._doc_lengths,
            "total_documents": self._total_documents,
            "avg_doc_length": self._avg_doc_length,
            "k1": self._k1,
            "b": self._b,
        }

        with open(index_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

        return index_file

    def load(self, collection: str = "default") -> bool:
        """从文件加载索引。

        Args:
            collection: 集合名称

        Returns:
            是否加载成功
        """
        index_file = self._index_dir / f"{collection}.json"

        if not index_file.exists():
            return False

        try:
            with open(index_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._index = data.get("index", {})
            self._doc_lengths = data.get("doc_lengths", {})
            self._total_documents = data.get("total_documents", 0)
            self._avg_doc_length = data.get("avg_doc_length", 0.0)
            self._k1 = data.get("k1", 1.5)
            self._b = data.get("b", 0.75)

            return True
        except (json.JSONDecodeError, IOError):
            return False

    def add_documents(
        self,
        records: List[ChunkRecord],
    ) -> None:
        """增量添加文档到现有索引。

        Args:
            records: 新增的 ChunkRecord 列表
        """
        if not records:
            return

        old_total = self._total_documents
        old_doc_lengths = dict(self._doc_lengths)
        old_index = dict(self._index)

        self.build(records)

        new_total = self._total_documents
        new_doc_lengths = dict(self._doc_lengths)

        for term, term_data in old_index.items():
            if term in self._index:
                existing_postings = {p["chunk_id"]: p for p in self._index[term]["postings"]}
                for p in term_data["postings"]:
                    if p["chunk_id"] not in existing_postings:
                        self._index[term]["postings"].append(p)
                self._index[term]["idf"] = self._calculate_idf(
                    len(self._index[term]["postings"])
                )
            else:
                self._index[term] = term_data
                self._index[term]["idf"] = self._calculate_idf(
                    len(term_data["postings"])
                )

        for chunk_id, length in old_doc_lengths.items():
            if chunk_id not in new_doc_lengths:
                self._doc_lengths[chunk_id] = length

        self._total_documents = old_total + new_total
        if self._total_documents > 0:
            self._avg_doc_length = sum(self._doc_lengths.values()) / self._total_documents

    def remove_documents(self, chunk_ids: Set[str]) -> None:
        """从索引中移除指定文档。

        Args:
            chunk_ids: 要移除的 chunk_id 集合
        """
        if not chunk_ids:
            return

        for term in self._index:
            self._index[term]["postings"] = [
                p for p in self._index[term]["postings"]
                if p["chunk_id"] not in chunk_ids
            ]
            self._index[term]["idf"] = self._calculate_idf(
                len(self._index[term]["postings"])
            )

        for chunk_id in chunk_ids:
            self._doc_lengths.pop(chunk_id, None)

        self._total_documents = len(self._doc_lengths)
        self._avg_doc_length = sum(self._doc_lengths.values()) / self._total_documents if self._total_documents > 0 else 0.0

    @property
    def _avg_doc_length_value(self) -> float:
        return self._avg_doc_length

    @property
    def stats(self) -> Dict[str, Any]:
        """获取索引统计信息。

        Returns:
            统计信息字典
        """
        return {
            "total_documents": self._total_documents,
            "total_terms": len(self._index),
            "avg_doc_length": self._avg_doc_length,
            "indexed_documents": list(self._doc_lengths.keys()),
        }
