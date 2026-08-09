"""BM25 索引构建与持久化。

该模块负责：
- 接收 SparseEncoder 输出的稀疏向量（词频统计）
- 计算 IDF (Inverse Document Frequency)
- 构建倒排索引结构
- 支持索引序列化、加载、增量更新与重建
"""

import json
import math
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from src.core.types import ChunkRecord


InvertedIndex = Dict[str, Dict[str, Any]]
PostingList = List[Dict[str, Any]]

#: 索引磁盘格式版本(Feature-004)。
#:
#: v1 把完整 chunk 标识字符串内嵌在每个倒排项里。当标识从 38 字符的
#: ``doc_<hash>_<idx>_<hash>`` 变成 91 字符的绝对路径式,再叠加中文 bigram
#: 带来的约 6 倍倒排项增长,索引会从 38 MB 涨到约 156 MB。
#:
#: v2 把标识提到顶层 ``chunk_ids`` 表,倒排项只存整数下标 —— 每项从 136 B
#: 降到 10 B,总体积回落到约 17 MB。
#:
#: 完整契约见 specs/004-retrieval-infra-fix/contracts/bm25_index.schema.md
INDEX_FORMAT_VERSION = 2


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
        format_version: int = INDEX_FORMAT_VERSION,
    ) -> None:
        """初始化 BM25Indexer。

        Args:
            index_dir: 索引文件存储目录
            k1: BM25 词频饱和参数 (默认 1.5)
            b: 文档长度归一化参数 (默认 0.75)
            format_version: 期望的磁盘格式版本。``load()`` 遇到不匹配的文件会
                抛 ``ValueError`` 而**不是**静默降级(见 ``load`` 的 docstring)。
        """
        self._index_dir = Path(index_dir)
        self._k1 = k1
        self._b = b
        self._format_version = format_version

        self._index: InvertedIndex = {}
        self._doc_lengths: Dict[str, int] = {}
        self._avg_doc_length: float = 0.0
        self._total_documents: int = 0

    def _calculate_idf(self, document_frequency: int) -> float:
        """计算 IDF (Inverse Document Frequency)。
        Note:这里是DF(Document Frequency),而非词频
        【IDF 的作用】
        衡量一个词的"区分度"——越稀有的词，IDF 值越大，搜索权重越高。
        IDF 的直觉：
            如果一个词在所有文档中都出现（如"的"、"是"），它的区分度很低，IDF 值小
            如果一个词只在少数文档中出现（如"量子计算"），它的区分度高，IDF 值大

        【公式】
            IDF(term) = log((N - df + 0.5) / (df + 0.5))

            其中：
            - N  = self._total_documents（文档总数）
            - df = document_frequency（包含该词的文档数）

        【边界情况处理】
        1. df <= 0 或 N <= 0：词不存在或无文档，返回 0
        2. df >= N：词出现在所有文档中，无区分度，返回 0
           （这是 BM25 对原始 IDF 的改进，避免常见词有负 IDF）

        【数值示例】
        假设 N = 100：
        - df = 1  → IDF = log(99.5/1.5) ≈ 4.19  （稀有词，高权重）
        - df = 10 → IDF = log(90.5/10.5) ≈ 2.16
        - df = 50 → IDF = log(50.5/50.5) = 0    （中等频率）
        - df = 100 → 返回 0（常见词，无区分度）

        Args:
            document_frequency: 包含该词项的文档数 (df)

        Returns:
            IDF 值（非负数）
        """
        # 边界情况 1：词不存在或无文档
        if document_frequency <= 0 or self._total_documents <= 0:
            return 0.0

        # 边界情况 2：词出现在所有文档中，无区分度
        # 此时 (N - df + 0.5) / (df + 0.5) = 0.5 / (N + 0.5) < 1
        # log 结果为负，但 BM25 认为这种词无区分度，直接返回 0
        if document_frequency >= self._total_documents:
            return 0.0

        # 正常情况：计算 IDF
        # 公式：log((N - df + 0.5) / (df + 0.5))
        # 加 0.5 是为了平滑，避免极端情况
        return math.log((self._total_documents - document_frequency + 0.5) / (document_frequency + 0.5))

    def _compute_bm25_score(
        self,
        term: str,
        term_frequency: float,
        doc_length: int,
        idf: float,
    ) -> float:
        """计算单个词项的 BM25 得分。

        【BM25 公式】
            score = IDF × (tf × (k1 + 1)) / (tf + k1 × (1 - b + b × (dl / avg_dl)))

        【公式分解】
        1. IDF 部分：词的区分度（已在 _calculate_idf 中计算）
        2. TF 部分：词频饱和函数
           - 分子：tf × (k1 + 1) —— tf 越大，分子越大
           - 分母：tf + k1 × (1 - b + b × (dl / avg_dl)) —— 包含文档长度归一化

        【参数说明】
        - k1（词频饱和参数，默认 1.5）：
          控制 tf 对得分的影响速度。k1 越大，tf 的影响越大。
          典型值范围：1.2 ~ 2.0

          示例（假设 k1=1.5, b=0.75, dl=avg_dl）：
          - tf=1 → TF部分 = 1×2.5/(1+1.5×1) = 2.5/2.5 = 1.0
          - tf=2 → TF部分 = 2×2.5/(2+1.5×1) = 5.0/3.5 ≈ 1.43
          - tf=5 → TF部分 = 5×2.5/(5+1.5×1) = 12.5/6.5 ≈ 1.92
          - tf=10 → TF部分 = 10×2.5/(10+1.5×1) = 25/11.5 ≈ 2.17

          结论：tf 增长到一定程度后，得分增长变慢（饱和效应）

        - b（文档长度归一化参数，默认 0.75）：
          控制文档长度对得分的影响。
          - b=1：完全归一化，长文档被惩罚
          - b=0：不归一化，文档长度不影响得分

          示例（假设 k1=1.5, tf=2, avg_dl=100）：
          - dl=50（短文档） → 分母 = 2 + 1.5×(1-0.75+0.75×0.5) = 2.94
          - dl=100（平均） → 分母 = 2 + 1.5×(1-0.75+0.75×1) = 3.5
          - dl=200（长文档） → 分母 = 2 + 1.5×(1-0.75+0.75×2) = 4.625

          结论：长文档的分母更大，得分更低（因为长文档更容易匹配到词）

        Args:
            term: 词项（用于日志，实际计算中未使用）
            term_frequency: 词频 (TF)，词在文档中出现的次数
            doc_length: 文档长度 (dl)，文档的字符数或词数
            idf: IDF 值（已预计算）

        Returns:
            BM25 得分（IDF × TF部分）
        """
        # 边界情况：词频为 0 或文档长度为 0，得分为 0
        if term_frequency == 0 or doc_length == 0:
            return 0.0

        # 计算分子：tf × (k1 + 1)
        # tf 越大，分子越大，但增长速度受 k1 控制
        numerator = term_frequency * (self._k1 + 1)

        # 计算分母：tf + k1 × (1 - b + b × (dl / avg_dl))
        # 包含文档长度归一化：长文档的分母更大，得分更低
        # max(self._avg_doc_length, 1) 防止除零
        length_ratio = doc_length / max(self._avg_doc_length, 1)
        denominator = term_frequency + self._k1 * (1 - self._b + self._b * length_ratio)

        # 最终得分：IDF × (分子 / 分母)
        # IDF 决定词的区分度，TF部分决定词在文档中的重要性
        return idf * (numerator / denominator)

    def build(
        self,
        records: List[ChunkRecord],
        collection: str = "default",
    ) -> None:
        """构建 BM25 倒排索引。

        【构建流程】
        该方法分两遍扫描文档：
        1. 第一遍：统计每个词的文档频率 (df)，计算 IDF
        2. 第二遍：构建倒排列表 (postings)，记录每个文档中词的 tf 和 doc_length

        【为什么需要两遍扫描？】
        - IDF 的计算需要知道每个词出现在多少个文档中（文档频率 df）
        - 必须先统计完所有文档，才能计算准确的 IDF
        - 所以第一遍统计 df，第二遍构建 postings

        【数据结构】
        构建后的 inverted_index 结构：
        {
            "hello": {
                "idf": 2.34,           # 预计算的 IDF 值
                "postings": [          # 倒排列表（包含该词的所有文档）
                    {"chunk_id": "doc1", "tf": 3, "doc_length": 150},
                    {"chunk_id": "doc3", "tf": 1, "doc_length": 80},
                ]
            },
            ...
        }

        Args:
            records: 带有稀疏向量的 ChunkRecord 列表
            sparse_vector 是一个字典 {"词": 词频}
            collection: 集合名称（用于索引文件命名）
        """
        # 过滤出有 sparse_vector 的有效记录
        valid_records = [r for r in records if r.sparse_vector]

        # 边界情况：无有效记录，清空索引
        if not valid_records:
            self._index = {}
            self._doc_lengths = {}
            self._total_documents = 0
            self._avg_doc_length = 0.0
            return

        # 记录文档总数 N（用于 IDF 计算）
        self._total_documents = len(valid_records)

        # ========== 第一遍扫描：统计文档频率 (df) ==========
        # term_document_freq 记录每个词出现在多少个文档中
        term_document_freq: Dict[str, int] = defaultdict(int)
        doc_lengths: Dict[str, int] = {}
        inverted_index: InvertedIndex = {}

        for record in valid_records:
            if not record.sparse_vector:
                continue

            # 记录文档长度（用于 BM25 的文档长度归一化）
            doc_length = len(record.text)
            doc_lengths[record.id] = doc_length

            # 【关键】使用 set() 去重！
            # 因为这是IDF统计一个词在所有文档中出现的次数，在一个文档出现多词，也应该当作1次来看待，
            # 注意和词频的区别
            # 例如：文档中 "hello" 出现 5 次，df 只 +1
            unique_terms = set(record.sparse_vector.keys())
            for term in unique_terms:
                term_document_freq[term] += 1

        # ========== 计算 IDF 并初始化倒排索引 ==========
        for term, df in term_document_freq.items():
            # 调用 _calculate_idf 计算 IDF 值
            idf = self._calculate_idf(df)
            # 初始化该词的索引条目
            inverted_index[term] = {"idf": idf, "postings": []}

        # ========== 第二遍扫描：构建倒排列表 ==========
        for record in valid_records:
            if not record.sparse_vector:
                continue

            doc_length = doc_lengths.get(record.id, len(record.text))

            # 遍历该文档中的每个词及其词频
            for term, tf in record.sparse_vector.items():
                if term in inverted_index:
                    # 创建 posting 记录
                    posting: Dict[str, Any] = {
                        "chunk_id": record.id,   # 文档 ID
                        "tf": tf,                 # 词频 (Term Frequency)
                        "doc_length": doc_length, # 文档长度
                    }
                    # 添加到该词的倒排列表
                    inverted_index[term]["postings"].append(posting)

        # 保存构建结果
        self._index = inverted_index
        self._doc_lengths = doc_lengths
        # 计算平均文档长度（用于 BM25 的长度归一化）
        self._avg_doc_length = sum(doc_lengths.values()) / len(doc_lengths) if doc_lengths else 0.0

    def query(
        self,
        keywords: List[str],
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """查询 BM25 索引。

        【查询流程】
        1. 对每个查询词，从倒排索引中获取 IDF 和 postings
        2. 对每个 posting，计算 BM25 得分
        3. 累加所有查询词的得分
        4. 按得分排序，返回 top_k 结果

        【得分累加】
        如果查询是 "hello world"，则：
        - 查找 "hello" 的所有文档，计算 BM25 得分
        - 查找 "world" 的所有文档，计算 BM25 得分
        - 同一文档的得分累加

        【示例】
        假设查询 ["hello", "world"]：
        - doc1 包含 "hello"(tf=3) 和 "world"(tf=2)
          → score = BM25("hello", doc1) + BM25("world", doc1)
        - doc2 只包含 "hello"(tf=1)
          → score = BM25("hello", doc2)

        Args:
            keywords: 查询关键词列表
            top_k: 返回前 K 个结果

        Returns:
            按 BM25 得分排序的结果列表 [{"chunk_id": str, "score": float}, ...]
        """
        if not keywords or top_k <= 0:
            return []

        # 用于累加每个文档的得分
        scores: Dict[str, float] = defaultdict(float)

        # 遍历每个查询词
        for keyword in keywords:
            # 转小写（索引中的词都是小写）
            term = keyword.lower()

            # 如果词不在索引中，跳过
            if term not in self._index:
                continue

            # 获取该词的索引数据
            term_data = self._index[term]
            idf = term_data["idf"]      # 预计算的 IDF 值
            postings = term_data["postings"]  # 倒排列表

            # 遍历所有包含该词的文档
            for posting in postings:
                chunk_id = posting["chunk_id"]
                tf = posting["tf"]           # 词频
                doc_length = posting["doc_length"]  # 文档长度

                # 计算 BM25 得分
                score = self._compute_bm25_score(term, tf, doc_length, idf)
                # 累加到该文档的总得分
                scores[chunk_id] += score

        # 按得分降序排序
        sorted_results = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        # 返回 top_k 结果
        return [
            {"chunk_id": chunk_id, "score": score}
            for chunk_id, score in sorted_results[:top_k]
        ]

    def _serialize(self) -> Dict[str, Any]:
        """把内存中的倒排索引编码成 v2 磁盘格式。

        内存结构保持 v1 的冗长形态(``postings`` 是 dict 列表),只在落盘时
        压缩 —— 这样 ``query()`` / ``add_documents()`` / ``remove_documents()``
        全部无需改动。

        v2 的三处瘦身:

        1. **chunk 标识字典化**:标识提到顶层 ``chunk_ids`` 表,倒排项存整数
           下标。这是主要收益 —— 标识平均 91 字符,而下标只要几个字符
        2. **去掉倒排项内的 doc_length**:顶层 ``doc_lengths`` 已有完整映射,
           每个倒排项再存一份纯属重复
        3. **tf 存整数**:v1 存的是 ``5.0`` 这样的浮点
        """
        # 顺序即身份:下标一旦写出就不能重排
        chunk_ids: List[str] = list(self._doc_lengths.keys())
        id_to_index = {chunk_id: i for i, chunk_id in enumerate(chunk_ids)}
        doc_lengths = [int(self._doc_lengths[chunk_id]) for chunk_id in chunk_ids]

        index: Dict[str, Any] = {}
        for term, entry in self._index.items():
            postings: List[List[int]] = []
            for posting in entry.get("postings", []):
                chunk_id = posting.get("chunk_id")
                # 防御:postings 里出现 doc_lengths 中没有的标识说明索引已损坏,
                # 静默丢弃会让问题继续潜伏 —— 直接暴露
                if chunk_id not in id_to_index:
                    raise ValueError(
                        f"Index corruption: term {term!r} references unknown "
                        f"chunk_id {chunk_id!r} that is absent from doc_lengths"
                    )
                postings.append([id_to_index[chunk_id], int(posting.get("tf", 0))])

            index[term] = {"idf": entry.get("idf", 0.0), "postings": postings}

        return {
            "_format_version": self._format_version,
            "chunk_ids": chunk_ids,
            "doc_lengths": doc_lengths,
            "index": index,
            "total_documents": self._total_documents,
            "avg_doc_length": self._avg_doc_length,
            "k1": self._k1,
            "b": self._b,
        }

    def _deserialize(self, data: Dict[str, Any]) -> None:
        """把 v2 磁盘格式还原成内存中的冗长结构。"""
        chunk_ids: List[str] = data.get("chunk_ids", [])
        raw_lengths: List[int] = data.get("doc_lengths", [])

        if len(chunk_ids) != len(raw_lengths):
            raise ValueError(
                f"Index corruption: chunk_ids ({len(chunk_ids)}) and doc_lengths "
                f"({len(raw_lengths)}) length mismatch"
            )

        self._doc_lengths = {
            chunk_id: int(length) for chunk_id, length in zip(chunk_ids, raw_lengths)
        }

        index: InvertedIndex = {}
        for term, entry in data.get("index", {}).items():
            postings: PostingList = []
            for chunk_index, tf in entry.get("postings", []):
                if not 0 <= chunk_index < len(chunk_ids):
                    raise ValueError(
                        f"Index corruption: term {term!r} references chunk index "
                        f"{chunk_index} out of range [0, {len(chunk_ids)})"
                    )
                chunk_id = chunk_ids[chunk_index]
                postings.append(
                    {
                        "chunk_id": chunk_id,
                        "tf": float(tf),
                        # doc_length 不再落盘,从顶层映射还原
                        "doc_length": self._doc_lengths[chunk_id],
                    }
                )
            index[term] = {"idf": entry.get("idf", 0.0), "postings": postings}

        self._index = index
        self._total_documents = data.get("total_documents", 0)
        self._avg_doc_length = data.get("avg_doc_length", 0.0)
        self._k1 = data.get("k1", 1.5)
        self._b = data.get("b", 0.75)

    def save(self, collection: str = "default") -> Path:
        """保存索引到文件(v2 格式,原子替换)。

        **原子写**:先写同目录临时文件,完整后 ``os.replace`` 重命名。重建
        5 万条量级的索引要跑一会儿,中途失败若直接破坏了现有可用索引,
        系统会处于「新的没建好、旧的没了」的状态(FR-003)。

        Args:
            collection: 集合名称

        Returns:
            保存的文件路径
        """
        self._index_dir.mkdir(parents=True, exist_ok=True)

        index_file = self._index_dir / f"{collection}.json"
        data = self._serialize()

        # 临时文件必须与目标同目录,os.replace 才能保证原子性(跨文件系统不行)
        fd, tmp_path_str = tempfile.mkstemp(
            prefix=f".{collection}.", suffix=".tmp", dir=str(self._index_dir)
        )
        tmp_path = Path(tmp_path_str)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp_path, index_file)
        except Exception:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            raise

        return index_file

    def load(self, collection: str = "default") -> bool:
        """从文件加载索引。

        Args:
            collection: 集合名称

        Returns:
            是否加载成功。文件不存在或 JSON 损坏时返回 ``False``(沿用 v1 行为)。

        Raises:
            ValueError: 磁盘格式版本与期望不符时。

        Note:
            **版本不匹配为什么必须抛异常而不是静默重建或降级**:

            Feature-004 修复的三个缺陷全部属于「静默失效」—— 不报错、不告警,
            只是结果悄悄变空(关键词索引与向量库标识不相交、中文被丢弃、
            两路集合范围不一致)。若这里再留一条静默降级路径,等于在刚修好
            的地方重新埋雷。宪法原则三(快速失败校验,禁止静默回退默认值)
            也直接要求如此。
        """
        index_file = self._index_dir / f"{collection}.json"

        if not index_file.exists():
            return False

        try:
            with open(index_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            return False

        file_version = data.get("_format_version")
        if file_version != self._format_version:
            raise ValueError(
                f"Unsupported BM25 index format in {index_file}: "
                f"found _format_version={file_version!r}, expected {self._format_version}. "
                "Run `python scripts/rebuild_bm25_index.py` to rebuild the index. "
                "(拒绝静默降级 —— 见 Feature-004 contracts/bm25_index.schema.md)"
            )

        self._deserialize(data)
        return True

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

    def remove_document(self, chunk_ids: Set[str]) -> None:
        """从索引中移除指定文档（别名方法）。

        该方法是 remove_documents 的别名，保持命名一致性。

        Args:
            chunk_ids: 要移除的 chunk_id 集合
        """
        self.remove_documents(chunk_ids)

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
