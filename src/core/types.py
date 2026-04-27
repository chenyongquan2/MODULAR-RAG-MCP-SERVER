"""核心数据类型/契约 (Document/Chunk/ChunkRecord/评估实体)。

该模块定义了全链路 (ingestion → retrieval → mcp tools) 共用的核心数据结构,
以及 Feature-001 引入的评估系统实体(TestCase / GoldenTestSet / EvaluationReport
扩展字段 / Baseline / DeltaReport / AcceptanceStatus)。所有类型均可序列化为
dict/json,支持整个 RAG 系统的数据流转。

设计原则:
1. 类型稳定:核心字段不可随意修改,保持向后兼容
2. 可序列化:支持 dict/json 序列化,便于存储和传输
3. 可扩展:metadata 字段允许增量扩展,但不得破坏兼容性
4. 显式契约:字段含义明确,避免散落在各子模块导致耦合
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional, Any, Literal
from datetime import datetime


@dataclass
class ImageReference:
    """图片引用信息。

    用于记录文档中嵌入图片的位置和元数据，支持多模态检索与展示。

    Attributes:
        id: 全局唯一图片标识符 (建议格式: {doc_hash}_{page}_{seq})
        path: 图片文件存储路径 (约定: data/images/{collection}/{image_id}.png)
        page: 图片在原文档中的页码 (可选，适用于PDF等分页文档)
        text_offset: 占位符在 Document.text 中的起始字符位置 (从0开始)
        text_length: 占位符的字符长度 (通常为 len("[IMAGE: {image_id}]"))
        position: 图片在原文档中的物理位置信息 (可选，如PDF坐标、像素位置、尺寸等)

    说明：
        通过 text_offset 和 text_length 可精确定位图片在文本中的位置，
        支持同一图片多次出现的场景。
    """
    id: str
    path: str
    text_offset: int
    text_length: int
    page: Optional[int] = None
    position: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典 (过滤 None 值)。"""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class Document:
    """原始文档。

    表示从 Loader 加载的原始文档，包含完整文本和元数据。

    Attributes:
        id: 文档唯一标识符 (建议使用 SHA256 哈希或 UUID)
        text: 文档完整文本内容 (图片位置使用 [IMAGE: {image_id}] 占位符标记)
        metadata: 文档元数据 (必须包含 source_path，其余字段可扩展)

    metadata 必填字段：
        source_path: 源文件路径 (str)

    metadata 可选字段：
        collection: 所属集合名称 (str)
        doc_type: 文档类型，如 "pdf", "markdown" (str)
        title: 文档标题 (str)
        author: 文档作者 (str)
        created_at: 创建时间 (str, ISO 8601 格式)
        page_count: 页数 (int, 适用于PDF等分页文档)
        images: 图片引用列表 (List[ImageReference])，遵循 ImageReference 规范

    文本中图片占位符规范：
        在 Document.text 中，图片位置使用 [IMAGE: {image_id}] 格式标记。
    """
    id: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """验证必填字段。"""
        if "source_path" not in self.metadata:
            raise ValueError("metadata must contain 'source_path' field")

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典。"""
        result = asdict(self)
        # 转换 ImageReference 对象为字典
        if "images" in result["metadata"]:
            result["metadata"]["images"] = [
                img.to_dict() if isinstance(img, ImageReference) else img
                for img in result["metadata"]["images"]
            ]
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Document":
        """从字典反序列化。"""
        metadata = data.get("metadata", {})
        # 转换 images 字段为 ImageReference 对象
        if "images" in metadata:
            metadata["images"] = [
                ImageReference(**img) if isinstance(img, dict) else img
                for img in metadata["images"]
            ]
        return cls(
            id=data["id"],
            text=data["text"],
            metadata=metadata
        )


@dataclass
class Chunk:
    """文档切分后的片段。

    表示文档经过 Splitter 切分后的单个片段，包含位置信息和溯源链接。

    Attributes:
        id: Chunk 唯一标识符 (建议格式: {doc_id}_{index:04d}_{hash_8chars})
        text: Chunk 文本内容
        metadata: Chunk 元数据 (继承自 Document.metadata，并添加 chunk_index)
        start_offset: Chunk 在原文档中的起始字符位置 (可选)
        end_offset: Chunk 在原文档中的结束字符位置 (可选)
        source_ref: 父 Document.id，用于溯源

    metadata 额外字段：
        chunk_index: Chunk 在文档中的序号 (int, 从0开始)，用于排序和定位
        refined_by: Chunk 精炼方法 (str, "rule" | "llm" | None)，标记是否经过智能重写
        enriched: 是否经过元数据增强 (bool)
    """
    id: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    start_offset: Optional[int] = None
    end_offset: Optional[int] = None
    source_ref: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典 (过滤 None 值)。"""
        result = asdict(self)
        # 转换 ImageReference 对象为字典
        if "images" in result["metadata"]:
            result["metadata"]["images"] = [
                img.to_dict() if isinstance(img, ImageReference) else img
                for img in result["metadata"]["images"]
            ]
        return {k: v for k, v in result.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Chunk":
        """从字典反序列化。"""
        metadata = data.get("metadata", {})
        # 转换 images 字段为 ImageReference 对象
        if "images" in metadata:
            metadata["images"] = [
                ImageReference(**img) if isinstance(img, dict) else img
                for img in metadata["images"]
            ]
        return cls(
            id=data["id"],
            text=data["text"],
            metadata=metadata,
            start_offset=data.get("start_offset"),
            end_offset=data.get("end_offset"),
            source_ref=data.get("source_ref")
        )


@dataclass
class ChunkRecord:
    """用于存储和检索的载体。

    表示准备写入向量数据库的 Chunk 记录，包含向量化后的稠密/稀疏向量。

    Attributes:
        id: Chunk ID (与 Chunk.id 一致)
        text: Chunk 文本内容
        metadata: Chunk 元数据
        dense_vector: 稠密向量 (List[float], 可选，由 DenseEncoder 生成)
        sparse_vector: 稀疏向量 (Dict[str, float], 可选，由 SparseEncoder 生成)

    说明：
        ChunkRecord 是 Chunk 的扩展，添加了向量化后的数据，
        用于向量数据库存储和检索。按后续 C8~C12 演进，
        dense_vector 和 sparse_vector 字段会在实际摄取流程中填充。
    """
    id: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    dense_vector: Optional[List[float]] = None
    sparse_vector: Optional[Dict[str, float]] = None

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典 (过滤 None 值)。"""
        result = asdict(self)
        # 转换 ImageReference 对象为字典
        if "images" in result["metadata"]:
            result["metadata"]["images"] = [
                img.to_dict() if isinstance(img, ImageReference) else img
                for img in result["metadata"]["images"]
            ]
        return {k: v for k, v in result.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChunkRecord":
        """从字典反序列化。"""
        metadata = data.get("metadata", {})
        # 转换 images 字段为 ImageReference 对象
        if "images" in metadata:
            metadata["images"] = [
                ImageReference(**img) if isinstance(img, dict) else img
                for img in metadata["images"]
            ]
        return cls(
            id=data["id"],
            text=data["text"],
            metadata=metadata,
            dense_vector=data.get("dense_vector"),
            sparse_vector=data.get("sparse_vector")
        )

    @classmethod
    def from_chunk(cls, chunk: Chunk) -> "ChunkRecord":
        """从 Chunk 创建 ChunkRecord (向量字段为空)。"""
        return cls(
            id=chunk.id,
            text=chunk.text,
            metadata=chunk.metadata.copy()
        )


@dataclass
class RetrievalResult:
    """检索结果。

    表示单条检索结果，包含 chunk 信息和相关性分数。

    Attributes:
        chunk_id: Chunk ID
        score: 相关性分数 (float, 分数越高越相关)
        text: Chunk 文本内容
        metadata: Chunk 元数据

    说明：
        用于 DenseRetriever、SparseRetriever、Reranker 的输出，
        以及 HybridSearch 的最终返回结果。
    """
    chunk_id: str
    score: float
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典。"""
        result = asdict(self)
        # 转换 ImageReference 对象为字典
        if "images" in result["metadata"]:
            result["metadata"]["images"] = [
                img.to_dict() if isinstance(img, ImageReference) else img
                for img in result["metadata"]["images"]
            ]
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RetrievalResult":
        """从字典反序列化。"""
        metadata = data.get("metadata", {})
        # 转换 images 字段为 ImageReference 对象
        if "images" in metadata:
            metadata["images"] = [
                ImageReference(**img) if isinstance(img, dict) else img
                for img in metadata["images"]
            ]
        return cls(
            chunk_id=data["chunk_id"],
            score=data["score"],
            text=data["text"],
            metadata=metadata
        )


@dataclass
class ProcessedQuery:
    """处理后的查询。

    表示经过 QueryProcessor 处理后的查询，包含关键词提取和过滤条件。

    Attributes:
        original_query: 原始查询文本
        keywords: 提取的关键词列表 (用于 BM25 稀疏检索)
        filters: 过滤条件字典 (可选，如 collection、doc_type 等)
        rewritten_query: 改写后的查询 (可选，如 query expansion)

    说明：
        用于 QueryProcessor 的输出，作为 HybridSearch 的输入。
    """
    original_query: str
    keywords: List[str] = field(default_factory=list)
    filters: Dict[str, Any] = field(default_factory=dict)
    rewritten_query: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典 (过滤 None 值)。"""
        result = asdict(self)
        return {k: v for k, v in result.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProcessedQuery":
        """从字典反序列化。"""
        return cls(
            original_query=data["original_query"],
            keywords=data.get("keywords", []),
            filters=data.get("filters", {}),
            rewritten_query=data.get("rewritten_query")
        )


# ---------------------------------------------------------------------------
# Feature-001 评估系统实体
# ---------------------------------------------------------------------------
# 见 specs/001-rag-acceptance/data-model.md § 2 与 spec.md § Key Entities
# ---------------------------------------------------------------------------


class AcceptanceStatus(str, Enum):
    """评估报告的验收结论标识 (FR-013)。

    PASS:8 个主聚合指标全部满足该次评估生效的阈值。
    FAIL:任一主聚合指标低于阈值。

    继承 str 让 JSON 序列化天然产出字符串值。
    """

    PASS = "pass"
    FAIL = "fail"


@dataclass
class TestCaseTags:
    """测试用例的标签维度 (FR-014)。

    标签用于:
    1. by-tag 切片聚合(FR-015):按 content_type / difficulty 维度独立计算指标
    2. 文档形态扩展时的回归红线(SC-008):按 doc_version 过滤 v1 子集复跑

    Attributes:
        content_type: 用例覆盖的内容类型(text/code/table/mixed)
        difficulty: 用例难度(simple 事实题 / reasoning 推理题 / multi_context 跨段综合)
        language: 语种(zh/en),用于双语评估区分
        doc_version: 测试集版本(MVP 阶段固定 "v1",未来文档形态扩展时递增)
    """

    content_type: Literal["text", "code", "table", "mixed"]
    difficulty: Literal["simple", "reasoning", "multi_context"]
    language: Literal["zh", "en"]
    doc_version: str = "v1"

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TestCaseTags":
        """从字典反序列化。"""
        return cls(
            content_type=data["content_type"],
            difficulty=data["difficulty"],
            language=data["language"],
            doc_version=data.get("doc_version", "v1"),
        )


@dataclass
class TestCase:
    """单条评估用例 (FR-006, FR-014)。

    Attributes:
        query: 用户查询文本 (非空)
        expected_chunk_ids: 期望命中的 chunk ID 列表(必须在 vector store 中存在,FR-007)
        expected_sources: 期望命中的源文档名(可空)
        ground_truth: 参考答案文本(US2 后强制非空,US1 占位允许空)
        tags: 用例标签(US1 占位允许 None,US2 后必填)
    """

    query: str
    expected_chunk_ids: List[str]
    expected_sources: List[str] = field(default_factory=list)
    ground_truth: str = ""
    tags: Optional[TestCaseTags] = None

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典(tags 为 None 时不输出该字段)。"""
        result: Dict[str, Any] = {
            "query": self.query,
            "expected_chunk_ids": list(self.expected_chunk_ids),
            "expected_sources": list(self.expected_sources),
            "ground_truth": self.ground_truth,
        }
        if self.tags is not None:
            result["tags"] = self.tags.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TestCase":
        """从字典反序列化。"""
        tags_raw = data.get("tags")
        return cls(
            query=data["query"],
            expected_chunk_ids=list(data.get("expected_chunk_ids", [])),
            expected_sources=list(data.get("expected_sources", [])),
            ground_truth=data.get("ground_truth", ""),
            tags=TestCaseTags.from_dict(tags_raw) if isinstance(tags_raw, dict) else None,
        )


@dataclass
class GoldenTestSet:
    """金标测试集 (data-model.md § 2.3)。

    一份语种维度的金标用例集合,作为 EvaluationReport 的输入。

    Attributes:
        language: 语种(zh/en/mixed,mixed 仅占位文件可用)
        version: 语义化版本(形如 "v1.0")
        cases: 测试用例列表(US2 后 ≥ 40 条,US1 占位阶段不限)
        created_at: 创建时间(ISO-8601)
        source_corpus_collection: 该金标对应的 vector store collection
    """

    language: Literal["zh", "en", "mixed"]
    version: str
    cases: List[TestCase]
    created_at: str = ""
    source_corpus_collection: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典(顶层包含 _schema_version 与 test_cases 字段)。"""
        return {
            "_schema_version": 1,
            "language": self.language,
            "version": self.version,
            "created_at": self.created_at,
            "source_corpus_collection": self.source_corpus_collection,
            "test_cases": [case.to_dict() for case in self.cases],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GoldenTestSet":
        """从字典反序列化。

        Raises:
            ValueError: _schema_version 不支持时抛出。
        """
        schema_version = data.get("_schema_version", 1)
        if schema_version != 1:
            raise ValueError(
                f"Unsupported golden_test_set _schema_version={schema_version} "
                "(this build supports version 1)"
            )
        cases_raw = data.get("test_cases", [])
        return cls(
            language=data.get("language", "mixed"),
            version=data.get("version", "v1.0"),
            cases=[TestCase.from_dict(case) for case in cases_raw],
            created_at=data.get("created_at", ""),
            source_corpus_collection=data.get("source_corpus_collection", ""),
        )


@dataclass
class Baseline:
    """评估基线标记 (FR-008, data-model.md § 2.6)。

    指向一份已归档的 EvaluationReport,作为后续回归对比的基准。

    Attributes:
        report_id: 指向已归档报告的 UUID4
        collection: 该基线绑定的 collection
        marked_at: 标记时间(ISO-8601)
        marked_by: 标记者标识(MVP 阶段默认 "manual")
        acceptance_status: 该报告的 pass/fail 标识(冗余存储,便于面板查询时不必再读 report)
    """

    report_id: str
    collection: str
    marked_at: str = ""
    marked_by: str = "manual"
    acceptance_status: AcceptanceStatus = AcceptanceStatus.FAIL

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典。"""
        return {
            "report_id": self.report_id,
            "collection": self.collection,
            "marked_at": self.marked_at,
            "marked_by": self.marked_by,
            "acceptance_status": self.acceptance_status.value,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Baseline":
        """从字典反序列化。"""
        return cls(
            report_id=data["report_id"],
            collection=data["collection"],
            marked_at=data.get("marked_at", ""),
            marked_by=data.get("marked_by", "manual"),
            acceptance_status=AcceptanceStatus(data.get("acceptance_status", "fail")),
        )


@dataclass
class DeltaReport:
    """当前评估与基线之间的 delta 对比 (FR-009, data-model.md § 2.8)。

    delta = current - baseline,正数表示提升,负数表示退化。

    本对象作为 EvaluationReport 的子结构嵌入(不归档独立文件)。

    Attributes:
        current_report_id: 当前评估的 run_id
        baseline_report_id: 对比基线的 run_id
        per_metric_delta: 8 项主聚合指标各自的 delta
        per_tag_delta: by-tag 切片各自的 delta(切片缺失/skipped 时该 entry 为 None)
    """

    current_report_id: str
    baseline_report_id: str
    per_metric_delta: Dict[str, float] = field(default_factory=dict)
    per_tag_delta: Dict[str, Dict[str, Optional[Dict[str, float]]]] = field(
        default_factory=dict
    )

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典。"""
        return {
            "current_report_id": self.current_report_id,
            "baseline_report_id": self.baseline_report_id,
            "per_metric_delta": dict(self.per_metric_delta),
            "per_tag_delta": dict(self.per_tag_delta),
        }
