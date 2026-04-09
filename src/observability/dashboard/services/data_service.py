"""数据浏览服务。

封装文档和 Chunk 的读取逻辑，为 Dashboard 提供数据访问接口。

Design Principles Applied:
- Pluggable: 通过 DocumentManager 访问，支持任意存储后端
- Observable: 提供结构化数据用于 UI 展示
- Fail-Safe: 错误时返回空列表，不影响 UI 渲染
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from src.core.settings import Settings
from src.libs.vector_store.vector_store_factory import VectorStoreFactory
from src.libs.vector_store.base_vector_store import BaseVectorStore
from src.libs.loader.file_integrity import FileIntegrityChecker
from src.ingestion.storage.bm25_indexer import BM25Indexer
from src.ingestion.storage.image_storage import BaseImageStorage
from src.ingestion.storage.image_storage import SQLiteImageStorage
from src.ingestion.document_manager import DocumentManager, DocumentInfo, DocumentDetail
from src.observability.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ChunkDisplay:
    """ Chunk 显示信息。

    Attributes:
        chunk_id: Chunk ID
        content: Chunk 文本内容
        metadata: 元数据字典
        images: 关联的图片列表
    """

    chunk_id: str
    content: str
    metadata: Dict[str, Any]
    images: List[Dict[str, Any]]


@dataclass
class ImageDisplay:
    """图片显示信息。

    Attributes:
        image_id: 图片 ID
        file_path: 图片文件路径
        page_num: 页码（如果有）
    """

    image_id: str
    file_path: str
    page_num: Optional[int]


class DataService:
    """数据浏览服务。

    封装文档、Chunk 和图片的读取逻辑，为 Dashboard 提供统一访问接口。

    该服务依赖于 DocumentManager 进行跨存储的数据协调：
    - 文档列表来自 DocumentManager.list_documents()
    - 文档详情来自 DocumentManager.get_document_detail()
    - 图片列表来自 ImageStorage.get_images_by_doc_hash()
    """

    def __init__(self, settings: Settings) -> None:
        """初始化数据浏览服务。

        Args:
            settings: 应用配置对象。
        """
        self._settings = settings
        # 延迟初始化各个存储实例
        self._vector_store: Optional[BaseVectorStore] = None
        self._image_storage: Optional[BaseImageStorage] = None
        self._file_integrity: Optional[FileIntegrityChecker] = None
        self._bm25_indexer: Optional[BM25Indexer] = None
        self._document_manager: Optional[DocumentManager] = None

    def _get_vector_store(self) -> BaseVectorStore:
        """获取向量存储实例（延迟初始化）。

        Returns:
            向量存储实例。
        """
        if self._vector_store is None:
            self._vector_store = VectorStoreFactory.create(self._settings)
        return self._vector_store

    def _get_image_storage(self) -> BaseImageStorage:
        """获取图片存储实例（延迟初始化）。

        Returns:
            图片存储实例。
        """
        if self._image_storage is None:
            self._image_storage = SQLiteImageStorage()
        return self._image_storage

    def _get_file_integrity(self) -> FileIntegrityChecker:
        """获取文件完整性检查器实例（延迟初始化）。

        Returns:
            文件完整性检查器实例。
        """
        if self._file_integrity is None:
            self._file_integrity = FileIntegrityChecker()
        return self._file_integrity

    def _get_bm25_indexer(self) -> BM25Indexer:
        """获取 BM25 索引器实例（延迟初始化）。

        Returns:
            BM25 索引器实例。
        """
        if self._bm25_indexer is None:
            self._bm25_indexer = BM25Indexer()
        return self._bm25_indexer

    def _get_document_manager(self) -> DocumentManager:
        """获取文档管理器实例（延迟初始化）。

        Returns:
            文档管理器实例。
        """
        if self._document_manager is None:
            self._document_manager = DocumentManager(
                chroma_store=self._get_vector_store(),
                bm25_indexer=self._get_bm25_indexer(),
                image_storage=self._get_image_storage(),
                file_integrity=self._get_file_integrity(),
            )
        return self._document_manager

    def list_documents(
        self,
        collection: Optional[str] = None,
        doc_type: Optional[str] = None,
    ) -> List[DocumentInfo]:
        """获取文档列表。

        Args:
            collection: 集合名称（可选，用于过滤）
            doc_type: 文档类型（可选，用于过滤）

        Returns:
            文档信息列表。
        """
        try:
            document_manager = self._get_document_manager()
            docs = document_manager.list_documents(collection=collection)

            # 按 doc_type 过滤
            if doc_type:
                docs = [d for d in docs if d.doc_type == doc_type]

            return docs
        except Exception as e:
            logger.error("Failed to list documents: %s", e)
            return []

    def get_document_detail(self, doc_id: str) -> Optional[DocumentDetail]:
        """获取文档详细信息。

        Args:
            doc_id: 文档 ID。

        Returns:
            文档详细信息，如果文档不存在则返回 None。
        """
        try:
            document_manager = self._get_document_manager()
            return document_manager.get_document_detail(doc_id)
        except ValueError:
            # 文档不存在，返回 None
            return None
        except Exception as e:
            logger.error("Failed to get document detail for %s: %s", doc_id, e)
            return None

    def get_chunks_by_doc_id(
        self,
        doc_id: str,
        include_images: bool = True,
    ) -> List[ChunkDisplay]:
        """获取文档的所有 Chunk。

        Args:
            doc_id: 文档 ID。
            include_images: 是否包含关联图片。

        Returns:
            Chunk 显示信息列表。
        """
        try:
            # 通过 DocumentManager 查询
            detail = self.get_document_detail(doc_id)
            if not detail or not detail.chunks:
                return []

            chunks: List[ChunkDisplay] = []
            for chunk_data in detail.chunks:
                # 构造 ChunkDisplay
                chunk_display = ChunkDisplay(
                    chunk_id=chunk_data.get("id", ""),
                    content=chunk_data.get("text", ""),
                    metadata=chunk_data.get("metadata", {}),
                    images=[],
                )

                # 如果需要包含图片，查询关联图片
                if include_images:
                    chunk_images = self._get_chunk_images(chunk_id=chunk_display.chunk_id)
                    chunk_display.images = chunk_images

                chunks.append(chunk_display)

            return chunks
        except Exception as e:
            logger.error("Failed to get chunks for doc %s: %s", doc_id, e)
            return []

    def _get_chunk_images(
        self,
        chunk_id: str,
    ) -> List[Dict[str, Any]]:
        """获取 Chunk 关联的图片。

        注意：当前实现中没有存储 chunk 和图片的直接关联关系，
        这里返回空列表。如果需要此功能，需要在元数据中添加 image_ids 字段。

        Args:
            chunk_id: Chunk ID。

        Returns:
            图片信息列表（当前返回空列表）。
        """
        # TODO: 如果需要 Chunk 和图片的关联，可以在 Chunk metadata 中存储 image_ids
        return []

    def get_document_images(self, doc_id: str) -> List[ImageDisplay]:
        """获取文档的所有图片。

        Args:
            doc_id: 文档 ID。

        Returns:
            图片显示信息列表。
        """
        try:
            image_storage = self._get_image_storage()
            images_data = image_storage.get_images_by_doc_hash(doc_id)

            image_displays = []
            for img_data in images_data:
                image_display = ImageDisplay(
                    image_id=img_data.get("image_id", ""),
                    file_path=img_data.get("file_path", ""),
                    page_num=img_data.get("page_num"),
                )
                image_displays.append(image_display)

            return image_displays
        except Exception as e:
            logger.error("Failed to get images for doc %s: %s", doc_id, e)
            return []

    def get_image_path(self, image_id: str) -> Optional[str]:
        """根据图片 ID 获取图片路径。

        Args:
            image_id: 图片 ID。

        Returns:
            图片文件路径，如果不存在则返回 None。
        """
        try:
            image_storage = self._get_image_storage()
            return image_storage.get_image_path(image_id)
        except Exception as e:
            logger.error("Failed to get image path for %s: %s", image_id, e)
            return None

    def search_documents(
        self,
        keyword: str,
        collection: Optional[str] = None,
    ) -> List[DocumentInfo]:
        """根据关键词搜索文档。

        Args:
            keyword: 搜索关键词。
            collection: 集合名称（可选，用于过滤）。

        Returns:
            匹配的文档信息列表。
        """
        try:
            # 获取所有文档
            all_docs = self.list_documents(collection=collection)

            # 过滤：关键词匹配 source_path 或 metadata
            keyword_lower = keyword.lower()
            matched_docs = []
            for doc in all_docs:
                # 检查文件名是否包含关键词
                if keyword_lower in doc.source_path.lower():
                    matched_docs.append(doc)
                    continue

            return matched_docs
        except Exception as e:
            logger.error("Failed to search documents: %s", e)
            return []

    def get_collections(self) -> List[str]:
        """获取所有集合名称。

        Returns:
            集合名称列表。
        """
        try:
            vector_store = self._get_vector_store()
            # 获取所有集合名称（从 VectorStore 直接获取）
            # ChromaStore 当前只支持单个 collection，这里返回配置的 collection 名称
            collection_name = getattr(
                self._settings.vector_store,
                "collection_name",
                "knowledge_base",
            )
            return [collection_name] if collection_name else []
        except Exception as e:
            logger.error("Failed to get collections: %s", e)
            return []

    def get_collection_stats(self, collection: str) -> Dict[str, Any]:
        """获取集合统计信息。

        Args:
            collection: 集合名称。

        Returns:
            集合统计信息字典。
        """
        try:
            vector_store = self._get_vector_store()
            # 获取指定集合的统计信息
            stats = vector_store.get_collection_stats(collection_name=collection)
            return stats
        except Exception as e:
            logger.error("Failed to get stats for collection %s: %s", collection, e)
            return {
                "name": collection,
                "count": 0,
            }