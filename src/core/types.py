"""核心数据类型/契约 (Document/Chunk/ChunkRecord)。

该模块定义了全链路 (ingestion → retrieval → mcp tools) 共用的核心数据结构。
所有类型均可序列化为 dict/json，支持整个 RAG 系统的数据流转。

设计原则：
1. 类型稳定：核心字段不可随意修改，保持向后兼容
2. 可序列化：支持 dict/json 序列化，便于存储和传输
3. 可扩展：metadata 字段允许增量扩展，但不得破坏兼容性
4. 显式契约：字段含义明确，避免散落在各子模块导致耦合
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
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
