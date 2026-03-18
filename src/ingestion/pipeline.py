"""Pipeline 主流程编排。

该模块负责串联完整的 Ingestion Pipeline：
1. Integrity Check (文件完整性检查)
2. Load (文档加载)
3. Split (文档切分)
4. Transform (ChunkRefiner + MetadataEnricher + ImageCaptioner)
5. Encode (DenseEncoder + SparseEncoder + BatchProcessor)
6. Store (VectorUpserter + BM25Indexer + ImageStorage)

设计原则：
- 配置驱动：通过 settings.yaml 控制各组件
- 失败透明：每个阶段失败抛出明确异常
- 可追踪：集成 TraceContext（预留）
"""

from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Dict, Any

from src.core.settings import Settings
from src.core.types import Document, Chunk, ChunkRecord, ImageReference
from src.libs.loader.file_integrity import SQLiteIntegrityChecker
from src.libs.loader.base_loader import BaseLoader
from src.libs.loader.pdf_loader import PdfLoader
from src.ingestion.chunking.document_chunker import DocumentChunker
from src.ingestion.transform.base_transform import BaseTransform
from src.ingestion.transform.chunk_refiner import ChunkRefiner
from src.ingestion.transform.metadata_enricher import MetadataEnricher
from src.ingestion.transform.image_captioner import ImageCaptioner
from src.ingestion.embedding.dense_encoder import DenseEncoder
from src.ingestion.embedding.sparse_encoder import SparseEncoder
from src.ingestion.embedding.batch_processor import BatchProcessor
from src.ingestion.storage.vector_upserter import VectorUpserter
from src.ingestion.storage.bm25_indexer import BM25Indexer
from src.ingestion.storage.image_storage import SQLiteImageStorage
from src.observability.logger import get_logger

if TYPE_CHECKING:
    from src.core.trace.trace_context import TraceContext

logger = get_logger(__name__)


class IngestionPipeline:
    """Ingestion Pipeline 编排器。

    串联整个离线数据摄取流程，从源文件到向量库/BM25索引。

    Pipeline 流程：
        integrity_check → load → split → transform → encode → store

    属性:
        settings: 全局配置对象
        collection: 目标集合名称

    Example:
        >>> from src.core.settings import load_settings
        >>> settings = load_settings()
        >>> pipeline = IngestionPipeline(settings, collection="my_docs")
        >>> result = pipeline.run("path/to/document.pdf")
    """

    def __init__(
        self,
        settings: Settings,
        collection: str = "default",
        loader: Optional[BaseLoader] = None,
        chunker: Optional[DocumentChunker] = None,
        transform: Optional[BaseTransform] = None,
        metadata_enricher: Optional[MetadataEnricher] = None,
        image_captioner: Optional[ImageCaptioner] = None,
        dense_encoder: Optional[DenseEncoder] = None,
        sparse_encoder: Optional[SparseEncoder] = None,
        batch_processor: Optional[BatchProcessor] = None,
        vector_upserter: Optional[VectorUpserter] = None,
        bm25_indexer: Optional[BM25Indexer] = None,
        image_storage: Optional[SQLiteImageStorage] = None,
        integrity_checker: Optional[SQLiteIntegrityChecker] = None,
    ):
        """初始化 IngestionPipeline。

        Args:
            settings: 全局配置对象
            collection: 目标集合名称
            其他参数: 可选的组件实例（用于测试注入）
        """
        self._settings = settings
        self._collection = collection

        self._loader = loader
        self._chunker = chunker
        self._transform = transform
        self._metadata_enricher = metadata_enricher
        self._image_captioner = image_captioner
        self._dense_encoder = dense_encoder
        self._sparse_encoder = sparse_encoder
        self._batch_processor = batch_processor
        self._vector_upserter = vector_upserter
        self._bm25_indexer = bm25_indexer
        self._image_storage = image_storage
        self._integrity_checker = integrity_checker

        logger.info(f"IngestionPipeline initialized for collection: {collection}")

    @property
    def collection(self) -> str:
        return self._collection

    @property
    def loader(self) -> BaseLoader:
        return self._loader

    def _get_loader(self, file_path: str) -> BaseLoader:
        """Get appropriate loader based on file extension."""
        suffix = Path(file_path).suffix.lower()
        if suffix == ".pdf":
            return PdfLoader(collection=self._collection)
        elif suffix in [".md", ".markdown"]:
            from src.libs.loader.markdown_loader import MarkdownLoader
            return MarkdownLoader(collection=self._collection)
        else:
            raise ValueError(f"Unsupported file type: {suffix}")

    @property
    def chunker(self) -> DocumentChunker:
        if self._chunker is None:
            self._chunker = DocumentChunker(self._settings)
        return self._chunker

    @property
    def transform(self) -> BaseTransform:
        if self._transform is None:
            self._transform = ChunkRefiner(self._settings)
        return self._transform

    @property
    def metadata_enricher(self) -> MetadataEnricher:
        if self._metadata_enricher is None:
            self._metadata_enricher = MetadataEnricher(self._settings)
        return self._metadata_enricher

    @property
    def image_captioner(self) -> ImageCaptioner:
        if self._image_captioner is None:
            self._image_captioner = ImageCaptioner(self._settings)
        return self._image_captioner

    @property
    def dense_encoder(self) -> DenseEncoder:
        if self._dense_encoder is None:
            self._dense_encoder = DenseEncoder(self._settings)
        return self._dense_encoder

    @property
    def sparse_encoder(self) -> SparseEncoder:
        if self._sparse_encoder is None:
            self._sparse_encoder = SparseEncoder()
        return self._sparse_encoder

    @property
    def batch_processor(self) -> BatchProcessor:
        if self._batch_processor is None:
            self._batch_processor = BatchProcessor(self._settings)
        return self._batch_processor

    @property
    def vector_upserter(self) -> VectorUpserter:
        if self._vector_upserter is None:
            self._vector_upserter = VectorUpserter(self._settings)
        return self._vector_upserter

    @property
    def bm25_indexer(self) -> BM25Indexer:
        if self._bm25_indexer is None:
            self._bm25_indexer = BM25Indexer(index_dir="data/db/bm25")
        return self._bm25_indexer

    @property
    def image_storage(self) -> SQLiteImageStorage:
        if self._image_storage is None:
            self._image_storage = SQLiteImageStorage()
        return self._image_storage

    @property
    def integrity_checker(self) -> SQLiteIntegrityChecker:
        if self._integrity_checker is None:
            self._integrity_checker = SQLiteIntegrityChecker()
        return self._integrity_checker

    def run(
        self,
        file_path: str,
        force: bool = False,
        trace: Optional["TraceContext"] = None,
    ) -> Dict[str, Any]:
        """运行完整的 Ingestion Pipeline。

        Pipeline 流程：
        1. Integrity Check - 检查文件是否已处理
        2. Load - 加载文档
        3. Split - 切分为 chunks
        4. Transform - 精炼和元数据增强
        5. Encode - 稠密和稀疏编码
        6. Store - 向量存储和索引

        Args:
            file_path: 源文件路径
            force: 是否强制重新处理（忽略完整性检查）
            trace: 可选的追踪上下文

        Returns:
            Dict[str, Any]: 处理结果，包含各阶段统计信息

        Raises:
            FileNotFoundError: 文件不存在
            RuntimeError: 处理过程中发生错误
        """
        file_path = str(Path(file_path).resolve())

        logger.info(f"Starting ingestion pipeline for: {file_path}")
        result = {
            "file_path": file_path,
            "collection": self._collection,
            "stages": {},
        }

        try:
            # Stage 1: Integrity Check
            self._stage_integrity(file_path, force, result, trace)

            # Stage 2: Load
            document = self._stage_load(file_path, result, trace)

            # Stage 3: Split
            chunks = self._stage_split(document, result, trace)

            # Stage 4: Transform
            chunks = self._stage_transform(chunks, document, result, trace)

            # Stage 5: Encode
            records = self._stage_encode(chunks, result, trace)

            # Stage 6: Store
            self._stage_store(records, result, trace)

            # Mark as success
            self._mark_success(file_path, result)
            result["status"] = "success"

            logger.info(
                f"Ingestion pipeline completed: {file_path} -> "
                f"{result['stages']['store']['chunk_count']} chunks indexed"
            )

        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
            self._mark_failed(file_path, str(e))
            logger.error(f"Ingestion pipeline failed: {file_path} - {str(e)}")
            raise

        return result

    def _stage_integrity(
        self,
        file_path: str,
        force: bool,
        result: Dict[str, Any],
        trace: Optional["TraceContext"],
    ) -> None:
        """Stage 1: 完整性检查。

        Args:
            file_path: 文件路径
            force: 是否强制重新处理
            result: 结果字典
            trace: 追踪上下文
        """
        logger.debug(f"Stage 1: Integrity check for {file_path}")

        file_hash = self.integrity_checker.compute_sha256(file_path)
        should_skip = not force and self.integrity_checker.should_skip(file_hash)

        result["stages"]["integrity"] = {
            "file_hash": file_hash,
            "should_skip": should_skip,
        }

        if should_skip:
            result["status"] = "skipped"
            logger.info(f"File already processed, skipping: {file_path}")
            raise RuntimeError("SKIP: File already processed (use force=True to reprocess)")

    def _stage_load(
        self,
        file_path: str,
        result: Dict[str, Any],
        trace: Optional["TraceContext"],
    ) -> Document:
        """Stage 2: 文档加载。

        Args:
            file_path: 文件路径
            result: 结果字典
            trace: 追踪上下文

        Returns:
            Document: 加载的文档
        """
        logger.debug(f"Stage 2: Loading document from {file_path}")

        loader = self._get_loader(file_path)
        document = loader.load(file_path)
        document.metadata["collection"] = self._collection

        # 存储文档中的图片
        doc_hash = document.id.replace("doc_", "")  # 从 doc_id 提取 hash
        if document.metadata.get("images"):
            try:
                updated_images = self._store_document_images(
                    document=document,
                    collection=self._collection,
                    doc_hash=doc_hash,
                )
                document.metadata["images"] = updated_images
                logger.info(f"Stored {len(updated_images)} images for document {document.id}")

                # 清理临时目录（图片已持久化存储）
                if hasattr(loader, 'cleanup_temp_dirs'):
                    loader.cleanup_temp_dirs()
            except Exception as e:
                logger.warning(f"Failed to store images: {e}")
                # 清理临时目录（即使存储失败也要清理）
                if hasattr(loader, 'cleanup_temp_dirs'):
                    loader.cleanup_temp_dirs()

        result["stages"]["load"] = {
            "doc_id": document.id,
            "text_length": len(document.text),
            "image_count": len(document.metadata.get("images", [])),
        }

        return document

    def _stage_split(
        self,
        document: Document,
        result: Dict[str, Any],
        trace: Optional["TraceContext"],
    ) -> List[Chunk]:
        """Stage 3: 文档切分。

        Args:
            document: 文档对象
            result: 结果字典
            trace: 追踪上下文

        Returns:
            List[Chunk]: 切分后的 chunks
        """
        logger.debug(f"Stage 3: Splitting document {document.id}")

        chunks = self.chunker.split_document(document, trace=trace)

        result["stages"]["split"] = {
            "chunk_count": len(chunks),
        }

        return chunks

    def _stage_transform(
        self,
        chunks: List[Chunk],
        document: Document,
        result: Dict[str, Any],
        trace: Optional["TraceContext"],
    ) -> List[Chunk]:
        """Stage 4: Transform (精炼 + 元数据增强 + 图片描述)。

        Args:
            chunks: chunks 列表
            document: 源文档
            result: 结果字典
            trace: 追踪上下文

        Returns:
            List[Chunk]: 转换后的 chunks
        """
        logger.debug(f"Stage 4: Transforming {len(chunks)} chunks")

        transformed_chunks = chunks

        try:
            transformed_chunks = self.transform.transform(transformed_chunks, trace=trace)
        except Exception as e:
            logger.warning(f"ChunkRefiner failed, using original chunks: {e}")

        try:
            transformed_chunks = self.metadata_enricher.transform(transformed_chunks, trace=trace)
        except Exception as e:
            logger.warning(f"MetadataEnricher failed, continuing: {e}")

        if document.metadata.get("images"):
            try:
                transformed_chunks = self.image_captioner.transform(transformed_chunks, trace=trace)
            except Exception as e:
                logger.warning(f"ImageCaptioner failed, continuing: {e}")

        result["stages"]["transform"] = {
            "chunk_count": len(transformed_chunks),
        }

        return transformed_chunks

    def _stage_encode(
        self,
        chunks: List[Chunk],
        result: Dict[str, Any],
        trace: Optional["TraceContext"],
    ) -> List[ChunkRecord]:
        """Stage 5: Encode (稠密 + 稀疏编码)。

        Args:
            chunks: chunks 列表
            result: 结果字典
            trace: 追踪上下文

        Returns:
            List[ChunkRecord]: 编码后的记录
        """
        logger.debug(f"Stage 5: Encoding {len(chunks)} chunks")

        dense_records = self.dense_encoder.encode(chunks, trace=trace)

        sparse_records = self.sparse_encoder.encode(chunks, trace=trace)

        for i, record in enumerate(dense_records):
            if i < len(sparse_records):
                record.sparse_vector = sparse_records[i].sparse_vector

        result["stages"]["encode"] = {
            "record_count": len(dense_records),
        }

        return dense_records

    def _stage_store(
        self,
        records: List[ChunkRecord],
        result: Dict[str, Any],
        trace: Optional["TraceContext"],
    ) -> None:
        """Stage 6: Store (向量存储 + BM25 索引)。

        Args:
            records: 编码后的记录
            result: 结果字典
            trace: 追踪上下文
        """
        logger.debug(f"Stage 6: Storing {len(records)} records")

        self.vector_upserter.upsert(records, trace=trace)

        self.bm25_indexer.build(records, collection=self._collection)

        result["stages"]["store"] = {
            "chunk_count": len(records),
        }

    def _mark_success(self, file_path: str, result: Dict[str, Any]) -> None:
        """标记文件处理成功。

        Args:
            file_path: 文件路径
            result: 处理结果
        """
        file_hash = result["stages"]["integrity"]["file_hash"]
        file_size = Path(file_path).stat().st_size
        chunk_count = result["stages"]["store"]["chunk_count"]

        self.integrity_checker.mark_success(
            file_hash=file_hash,
            file_path=file_path,
            file_size=file_size,
            chunk_count=chunk_count,
        )

    def _mark_failed(self, file_path: str, error_msg: str) -> None:
        """标记文件处理失败。

        Args:
            file_path: 文件路径
            error_msg: 错误消息
        """
        try:
            file_hash = self.integrity_checker.compute_sha256(file_path)
            self.integrity_checker.mark_failed(
                file_hash=file_hash,
                file_path=file_path,
                error_msg=error_msg,
            )
        except Exception as e:
            logger.warning(f"Failed to mark file as failed: {e}")

    def _store_document_images(
        self,
        document: Document,
        collection: str,
        doc_hash: str,
    ) -> List[ImageReference]:
        """存储文档中的图片到 ImageStorage。

        从 document.metadata["images"] 获取图片引用，
        调用 image_storage.save_image() 存储图片，
        返回更新后的 ImageReference 列表。

        Args:
            document: 文档对象
            collection: 集合名称
            doc_hash: 文档哈希值

        Returns:
            List[ImageReference]: 更新后的图片引用列表
        """
        images = document.metadata.get("images", [])
        if not images:
            return []

        updated_refs = []
        for img_ref in images:
            try:
                # 处理 ImageReference 对象和字典两种格式
                if isinstance(img_ref, ImageReference):
                    image_id = img_ref.id
                    source_path = img_ref.path
                    page_num = img_ref.page
                elif isinstance(img_ref, dict):
                    image_id = img_ref.get("id", "")
                    source_path = img_ref.get("path", "")
                    page_num = img_ref.get("page")
                else:
                    logger.warning(f"Unknown image reference type: {type(img_ref)}")
                    continue

                # 检查源文件是否存在
                if not Path(source_path).exists():
                    logger.warning(f"Image source file not found: {source_path}")
                    continue

                # 存储图片
                stored_path = self.image_storage.save_image(
                    source_path=source_path,
                    image_id=image_id,
                    collection=collection,
                    doc_hash=doc_hash,
                    page_num=page_num,
                )

                # 创建更新后的 ImageReference
                updated_ref = ImageReference(
                    id=image_id,
                    path=stored_path,
                    text_offset=img_ref.text_offset if isinstance(img_ref, ImageReference) else 0,
                    text_length=img_ref.text_length if isinstance(img_ref, ImageReference) else 0,
                    page=page_num,
                    position=img_ref.position if isinstance(img_ref, ImageReference) else img_ref.get("position"),
                )
                updated_refs.append(updated_ref)

                logger.debug(f"Stored image: {image_id} -> {stored_path}")

            except Exception as e:
                logger.warning(f"Failed to store image {img_ref.id if isinstance(img_ref, ImageReference) else img_ref.get('id', 'unknown')}: {e}")
                continue

        return updated_refs
