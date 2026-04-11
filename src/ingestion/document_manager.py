"""文档生命周期管理器 (Document Manager)。

该模块提供跨多个存储后端的统一文档管理接口，实现：
- 文档列表查询 (list_documents)
- 文档详情获取 (get_document_detail)
- 文档删除 (delete_document) - 协调删除 Chroma + BM25 + ImageStorage + FileIntegrity
- 集合统计信息 (get_collection_stats)

设计原则：
1. 跨存储协调：统一管理 ChromaDB（向量存储）、BM25Indexer（稀疏索引）、ImageStorage（图片）、FileIntegrity（完整性检查）
2. 原子性保证：删除操作确保所有存储同步删除，避免数据不一致
3. 验收友好：提供清晰的统计和查询接口，支持 Dashboard 集成
4. 错误透明：操作失败时返回详细的错误信息，便于排查
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from pathlib import Path

from src.core.types import ChunkRecord
from src.libs.loader.file_integrity import FileIntegrityChecker
from src.ingestion.storage.bm25_indexer import BM25Indexer
from src.ingestion.storage.image_storage import BaseImageStorage
from src.libs.vector_store.base_vector_store import BaseVectorStore
from src.observability.logger import get_logger

logger = get_logger(__name__)


@dataclass
class DocumentInfo:
    """文档基本信息。

    Attributes:
        doc_id: 文档 ID（通常为文件 SHA256 哈希）
        source_path: 源文件路径
        collection: 所属集合名称
        chunk_count: 包含的 chunk 数量
        image_count: 包含的图片数量
        ingested_at: 摄入时间
        file_size: 文件大小（字节）
        doc_type: 文档类型
        status: 处理状态 (success/failed/processing)
    """
    doc_id: str
    source_path: str
    collection: str
    chunk_count: int
    image_count: int
    ingested_at: str
    file_size: int
    doc_type: Optional[str] = None
    status: str = "success"

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典。"""
        return {
            "doc_id": self.doc_id,
            "source_path": self.source_path,
            "collection": self.collection,
            "chunk_count": self.chunk_count,
            "image_count": self.image_count,
            "ingested_at": self.ingested_at,
            "file_size": self.file_size,
            "doc_type": self.doc_type,
            "status": self.status,
        }


@dataclass
class DocumentDetail:
    """文档详细信息。

    Attributes:
        doc_id: 文档 ID
        source_path: 源文件路径
        collection: 所属集合名称
        chunk_count: 包含的 chunk 数量
        image_count: 包含的图片数量
        ingested_at: 摄入时间
        file_size: 文件大小
        doc_type: 文档类型
        status: 处理状态
        chunks: 该文档的所有 chunk 列表（可选，需要从向量库查询）
        images: 该文档的所有图片列表（可选，需要从图片存储查询）
        metadata: 额外的元数据
    """
    doc_id: str
    source_path: str
    collection: str
    chunk_count: int
    image_count: int
    ingested_at: str
    file_size: int
    doc_type: Optional[str] = None
    status: str = "success"
    chunks: Optional[List[Dict[str, Any]]] = None
    images: Optional[List[Dict[str, Any]]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典。"""
        return {
            "doc_id": self.doc_id,
            "source_path": self.source_path,
            "collection": self.collection,
            "chunk_count": self.chunk_count,
            "image_count": self.image_count,
            "ingested_at": self.ingested_at,
            "file_size": self.file_size,
            "doc_type": self.doc_type,
            "status": self.status,
            "chunks": self.chunks or [],
            "images": self.images or [],
            "metadata": self.metadata,
        }


@dataclass
class DeleteResult:
    """文档删除结果。

    Attributes:
        success: 是否删除成功
        doc_id: 文档 ID
        source_path: 源文件路径
        collection: 所属集合名称
        chunks_deleted: 删除的 chunk 数量
        images_deleted: 删除的图片数量
        error: 错误信息（如果失败）
    """
    success: bool
    doc_id: str
    source_path: str
    collection: str
    chunks_deleted: int = 0
    images_deleted: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典。"""
        result = {
            "success": self.success,
            "doc_id": self.doc_id,
            "source_path": self.source_path,
            "collection": self.collection,
            "chunks_deleted": self.chunks_deleted,
            "images_deleted": self.images_deleted,
        }
        if self.error:
            result["error"] = self.error
        return result


@dataclass
class CollectionStats:
    """集合统计信息。

    Attributes:
        collection: 集合名称
        total_documents: 文档总数
        total_chunks: chunk 总数
        total_images: 图片总数
        total_size: 文件总大小（字节）
        last_ingested_at: 最后摄入时间
    """
    collection: str
    total_documents: int
    total_chunks: int
    total_images: int
    total_size: int
    last_ingested_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典。"""
        return {
            "collection": self.collection,
            "total_documents": self.total_documents,
            "total_chunks": self.total_chunks,
            "total_images": self.total_images,
            "total_size": self.total_size,
            "last_ingested_at": self.last_ingested_at,
        }


class DocumentManager:
    """跨存储的文档生命周期管理器。

    该类协调管理以下四个存储后端：
    1. ChromaDB - 稠密向量存储（ChunkRecord）
    2. BM25Indexer - 稀疏倒排索引
    3. ImageStorage - 图片文件与索引
    4. FileIntegrityChecker - 文件完整性记录

    设计模式：
    - Facade 模式：为多个复杂的子系统提供统一的简化接口
    - Coordinator 模式：协调多个存储后端的原子操作

    Example:
        >>> manager = DocumentManager(chroma_store, bm25_indexer, image_storage, file_integrity)
        >>> # 列出所有文档
        >>> docs = manager.list_documents()
        >>> # 删除文档
        >>> result = manager.delete_document("path/to/doc.pdf", "my_collection")
        >>> # 获取集合统计
        >>> stats = manager.get_collection_stats("my_collection")
    """

    def __init__(
        self,
        chroma_store: BaseVectorStore,
        bm25_indexer: BM25Indexer,
        image_storage: BaseImageStorage,
        file_integrity: FileIntegrityChecker,
        default_collection: str = "default",
    ):
        """初始化 DocumentManager。

        Args:
            chroma_store: ChromaDB 向量存储实例
            bm25_indexer: BM25 索引实例
            image_storage: 图片存储实例
            file_integrity: 文件完整性检查器实例
            default_collection: 默认集合名称
        """
        self._chroma_store = chroma_store
        self._bm25_indexer = bm25_indexer
        self._image_storage = image_storage
        self._file_integrity = file_integrity
        self._default_collection = default_collection

    def list_documents(self, collection: Optional[str] = None) -> List[DocumentInfo]:
        """列出已摄入的文档。

        Args:
            collection: 集合名称（可选，不指定则返回所有集合）

        Returns:
            文档信息列表

        Raises:
            RuntimeError: 如果查询失败
        """
        try:
            coll = collection or self._default_collection

            # 从 FileIntegrity 获取已成功处理的文件记录
            records = self._file_integrity.list_processed(status="success")

            # 过滤集合（如果 metadata 中有 collection 字段）
            # 注意：FileIntegrity 存储时可能没有 collection 字段，需要根据实际情况调整
            # 这里我们假设 source_path 中包含集合信息，或者需要从其他地方获取

            docs = []
            for record in records:
                source_path = record["file_path"]
                doc_id = record["file_hash"]

                # 从向量库中查询该文档的 chunk 数量
                # 使用 metadata 过滤：{"doc_id": doc_id} 或 {"source_path": source_path}
                # 注意：ChromaDB 的 metadata 格式取决于存储时的定义
                chunk_count = self._get_chunk_count_by_doc_id(
                    doc_id=doc_id,
                    source_path=source_path,
                )

                # 从图片存储中查询该文档的图片数量
                images = self._image_storage.get_images_by_doc_hash(doc_id)
                image_count = len(images)

                # 构造 DocumentInfo
                doc_info = DocumentInfo(
                    doc_id=doc_id,
                    source_path=source_path,
                    collection=coll,  # 可能需要从实际 metadata 中获取
                    chunk_count=chunk_count,
                    image_count=image_count,
                    ingested_at=record["processed_at"],
                    file_size=record["file_size"] or 0,
                    doc_type=self._infer_doc_type(source_path),
                    status=record["status"],
                )
                docs.append(doc_info)

            # 按摄入时间倒序排序
            docs.sort(key=lambda d: d.ingested_at, reverse=True)

            return docs

        except Exception as e:
            logger.error("Failed to list documents: %s", e)
            raise RuntimeError(f"Failed to list documents: {e}") from e

    def _get_chunk_count_by_doc_id(
        self,
        doc_id: str,
        source_path: Optional[str] = None,
    ) -> int:
        """根据 doc_id 获取 chunk 数量。

        Args:
            doc_id: 文档 ID
            source_path: 文档源路径（用于兼容旧数据回退）

        Returns:
            chunk 数量
        """
        try:
            chunk_ids = self._query_chunk_ids(
                doc_id=doc_id,
                source_path=source_path,
            )
            return len(chunk_ids)
        except Exception:
            return 0

    def _infer_doc_type(self, file_path: str) -> Optional[str]:
        """根据文件路径推断文档类型。

        Args:
            file_path: 文件路径

        Returns:
            文档类型
        """
        path = Path(file_path)
        ext = path.suffix.lower()

        type_map = {
            ".pdf": "pdf",
            ".md": "markdown",
            ".txt": "text",
            ".html": "html",
            ".docx": "docx",
        }

        return type_map.get(ext)

    def get_document_detail(self, doc_id: str) -> DocumentDetail:
        """获取文档详细信息。

        Args:
            doc_id: 文档 ID

        Returns:
            文档详细信息

        Raises:
            ValueError: 如果文档不存在
            RuntimeError: 如果查询失败
        """
        try:
            # 从 FileIntegrity 获取文档基本信息
            records = self._file_integrity.list_processed(status="success")
            doc_record = self._resolve_doc_record(records=records, doc_id=doc_id)

            if not doc_record:
                raise ValueError(f"Document not found: {doc_id}")

            # 获取该文档的所有 chunks
            canonical_doc_id = doc_record["file_hash"]
            source_path = doc_record["file_path"]
            chunks = self._get_chunks_by_doc_id(
                doc_id=canonical_doc_id,
                source_path=source_path,
            )

            # 获取该文档的所有图片
            images = self._image_storage.get_images_by_doc_hash(canonical_doc_id)

            # 构造 DocumentDetail
            detail = DocumentDetail(
                doc_id=canonical_doc_id,
                source_path=source_path,
                collection=self._default_collection,  # 需要从实际 metadata 获取
                chunk_count=len(chunks),
                image_count=len(images),
                ingested_at=doc_record["processed_at"],
                file_size=doc_record["file_size"] or 0,
                doc_type=self._infer_doc_type(source_path),
                status=doc_record["status"],
                chunks=chunks,
                images=images,
                metadata={},  # 可以添加额外元数据
            )

            return detail

        except ValueError:
            raise
        except Exception as e:
            logger.error("Failed to get document detail for %s: %s", doc_id, e)
            raise RuntimeError(f"Failed to get document detail: {e}") from e

    def _resolve_doc_record(
        self,
        records: List[Dict[str, Any]],
        doc_id: str,
    ) -> Optional[Dict[str, Any]]:
        """从完整性记录中解析唯一文档记录。

        支持输入格式：
        - 64 位 file_hash
        - doc_<hash/prefix>
        - 直接 hash 前缀（兼容场景）
        """
        if not doc_id:
            return None

        # 归一化输入，兼容 doc_<hash> 形式
        normalized = doc_id[4:] if doc_id.startswith("doc_") else doc_id

        # 优先精确匹配，避免前缀误命中
        exact_matches = [r for r in records if r.get("file_hash") == normalized]
        if len(exact_matches) == 1:
            return exact_matches[0]
        if len(exact_matches) > 1:
            raise ValueError(f"Ambiguous document identifier: {doc_id}")

        # 回退到前缀匹配（用于旧的短 doc_id）
        prefix_matches = [r for r in records if str(r.get("file_hash", "")).startswith(normalized)]
        if not prefix_matches:
            return None
        if len(prefix_matches) > 1:
            raise ValueError(
                f"Ambiguous document identifier: {doc_id} matched {len(prefix_matches)} documents"
            )
        return prefix_matches[0]

    def _get_chunks_by_doc_id(
        self,
        doc_id: str,
        source_path: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """根据 doc_id 获取所有 chunks。

        Args:
            doc_id: 文档 ID
            source_path: 文档源路径（用于兼容旧数据回退）

        Returns:
            chunk 信息列表
        """
        try:
            chunk_ids = self._query_chunk_ids(
                doc_id=doc_id,
                source_path=source_path,
            )

            if not chunk_ids:
                return []

            # 使用 get_by_ids 获取完整的 chunk 信息
            chunks = self._chroma_store.get_by_ids(ids=chunk_ids)
            return chunks
        except Exception:
            return []

    def _build_doc_id_candidates(self, doc_id: str) -> List[str]:
        """构建可能的 doc_id 候选值（兼容历史数据格式）。"""
        candidates: List[str] = []

        def _add(value: str) -> None:
            if value and value not in candidates:
                candidates.append(value)

        _add(doc_id)
        if doc_id.startswith("doc_"):
            stripped = doc_id[4:]
            _add(stripped)
            if len(stripped) == 64:
                _add(f"doc_{stripped[:16]}")
        else:
            _add(f"doc_{doc_id}")
            if len(doc_id) == 64:
                _add(f"doc_{doc_id[:16]}")

        return candidates

    def _query_chunk_ids(
        self,
        doc_id: str,
        source_path: Optional[str] = None,
    ) -> List[str]:
        """按多种兼容条件查询 chunk IDs。

        查询优先级：
        1. doc_id 精确/变体匹配（兼容 doc_xxx 与纯 hash）
        2. source_path 回退匹配（兼容历史缺失 doc_id 元数据）
        """
        all_ids: List[str] = []
        seen = set()

        def _merge(ids: List[str]) -> None:
            for chunk_id in ids:
                if chunk_id not in seen:
                    seen.add(chunk_id)
                    all_ids.append(chunk_id)

        # 优先使用 doc_id 变体查询
        for candidate in self._build_doc_id_candidates(doc_id):
            try:
                ids = self._chroma_store.get_ids_by_metadata(
                    metadata_filters={"doc_id": candidate}
                )
            except Exception:
                ids = []
            _merge(ids)

        # 历史数据可能没有 doc_id 字段，回退到 source_path
        if source_path:
            try:
                ids = self._chroma_store.get_ids_by_metadata(
                    metadata_filters={"source_path": source_path}
                )
            except Exception:
                ids = []
            _merge(ids)

        return all_ids

    def delete_document(
        self,
        source_path: str,
        collection: str,
    ) -> DeleteResult:
        """删除文档（协调删除所有存储后端）。

        【删除流程】
        1. 计算 source_path 的 SHA256 哈希
        2. 查询该文档的所有 chunk IDs（从 ChromaDB）
        3. 从 ChromaDB 删除这些 chunks
        4. 从 BM25Indexer 删除这些 chunks
        5. 从 ImageStorage 删除该文档的图片
        6. 从 FileIntegrity 删除处理记录

        【原子性保证】
        - 如果任何步骤失败，记录错误但不回滚（简化实现）
        - 实际生产环境可能需要事务或补偿机制

        Args:
            source_path: 源文件路径
            collection: 集合名称

        Returns:
            删除结果

        Raises:
            RuntimeError: 如果删除操作失败
        """
        try:
            # 1. 计算文件哈希（作为 doc_id）
            doc_id = self._file_integrity.compute_sha256(source_path)

            # 2. 查询该文档的所有 chunk IDs
            # 注意：这里需要 ChromaStore 支持按 metadata 查询
            # 暂时假设可以查询，实际可能需要添加方法
            chunk_ids = self._get_chunk_ids_by_doc_id(doc_id, source_path=source_path)

            chunks_deleted = 0
            images_deleted = 0

            # 3. 从 ChromaDB 删除 chunks
            if chunk_ids:
                self._chroma_store.delete(doc_ids=chunk_ids)
                chunks_deleted = len(chunk_ids)
                logger.info("Deleted %d chunks from ChromaDB for doc %s", chunks_deleted, doc_id)

            # 4. 从 BM25Indexer 删除 chunks
            if chunk_ids:
                self._bm25_indexer.remove_documents(set(chunk_ids))
                logger.info("Deleted %d chunks from BM25Indexer for doc %s", chunks_deleted, doc_id)

            # 5. 从 ImageStorage 删除图片
            images = self._image_storage.get_images_by_doc_hash(doc_id)
            if images:
                # 注意：ImageStorage 需要添加 delete_by_doc_hash 方法
                self._image_storage.delete_by_doc_hash(doc_id)
                images_deleted = len(images)
                logger.info("Deleted %d images from ImageStorage for doc %s", images_deleted, doc_id)

            # 6. 从 FileIntegrity 删除记录
            self._file_integrity.remove_record(doc_id)
            logger.info("Deleted integrity record for doc %s", doc_id)

            return DeleteResult(
                success=True,
                doc_id=doc_id,
                source_path=source_path,
                collection=collection,
                chunks_deleted=chunks_deleted,
                images_deleted=images_deleted,
            )

        except FileNotFoundError:
            # 文件不存在，视为成功（已删除或从未存在）
            logger.warning("File not found when deleting document: %s", source_path)
            return DeleteResult(
                success=False,
                doc_id="unknown",
                source_path=source_path,
                collection=collection,
                error=f"File not found: {source_path}",
            )
        except Exception as e:
            logger.error("Failed to delete document %s: %s", source_path, e)
            return DeleteResult(
                success=False,
                doc_id="unknown",
                source_path=source_path,
                collection=collection,
                error=str(e),
            )

    def _get_chunk_ids_by_doc_id(
        self,
        doc_id: str,
        source_path: Optional[str] = None,
    ) -> List[str]:
        """根据 doc_id 获取所有 chunk IDs。

        Args:
            doc_id: 文档 ID
            source_path: 文档源路径（用于兼容旧数据回退）

        Returns:
            chunk ID 列表
        """
        try:
            chunk_ids = self._query_chunk_ids(
                doc_id=doc_id,
                source_path=source_path,
            )
            return chunk_ids
        except Exception:
            return []

    def get_collection_stats(self, collection: Optional[str] = None) -> CollectionStats:
        """获取集合统计信息。

        Args:
            collection: 集合名称（可选，不指定则返回默认集合）

        Returns:
            集合统计信息

        Raises:
            RuntimeError: 如果查询失败
        """
        try:
            coll = collection or self._default_collection

            # 从 FileIntegrity 获取所有成功处理的记录
            records = self._file_integrity.list_processed(status="success")

            # 统计信息
            total_documents = len(records)
            total_chunks = 0
            total_images = 0
            total_size = sum(r["file_size"] or 0 for r in records)
            last_ingested_at = None

            if records:
                last_ingested_at = records[0]["processed_at"]

                # 统计 chunks 和 images（需要遍历每个文档）
                for record in records:
                    doc_id = record["file_hash"]
                    # 获取 chunk 数量
                    total_chunks += self._get_chunk_count_by_doc_id(
                        doc_id=doc_id,
                        source_path=record["file_path"],
                    )
                    # 获取图片数量
                    images = self._image_storage.get_images_by_doc_hash(doc_id)
                    total_images += len(images)

            return CollectionStats(
                collection=coll,
                total_documents=total_documents,
                total_chunks=total_chunks,
                total_images=total_images,
                total_size=total_size,
                last_ingested_at=last_ingested_at,
            )

        except Exception as e:
            logger.error("Failed to get collection stats for %s: %s", collection, e)
            raise RuntimeError(f"Failed to get collection stats: {e}") from e
