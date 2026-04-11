"""测试文档生命周期管理器。

测试 DocumentManager 跨多个存储后端的协调功能。
"""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.core.types import ChunkRecord
from src.ingestion.document_manager import (
    DocumentManager,
    DocumentInfo,
    DocumentDetail,
    DeleteResult,
    CollectionStats,
)
from src.libs.loader.file_integrity import SQLiteIntegrityChecker
from src.ingestion.storage.image_storage import SQLiteImageStorage
from src.ingestion.storage.bm25_indexer import BM25Indexer


@pytest.fixture
def mock_vector_store():
    """Mock 向量存储。"""
    mock = MagicMock()
    mock.get_backend_name.return_value = "mock_chroma"
    return mock


@pytest.fixture
def mock_bm25_indexer():
    """Mock BM25 索引器。"""
    mock = MagicMock()
    return mock


@pytest.fixture
def mock_image_storage():
    """Mock 图片存储。"""
    mock = MagicMock()
    return mock


@pytest.fixture
def temp_file_integrity():
    """临时文件完整性检查器。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_integrity.db"
        yield SQLiteIntegrityChecker(db_path=str(db_path))


@pytest.fixture
def document_manager(mock_vector_store, mock_bm25_indexer, mock_image_storage, temp_file_integrity):
    """DocumentManager fixture。"""
    return DocumentManager(
        chroma_store=mock_vector_store,
        bm25_indexer=mock_bm25_indexer,
        image_storage=mock_image_storage,
        file_integrity=temp_file_integrity,
        default_collection="test_collection",
    )


@pytest.fixture
def sample_document():
    """样例文档 fixture。"""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.md') as f:
        f.write("# Sample Document\n\nThis is a test document for testing DocumentManager.")
        temp_path = f.name
    yield temp_path
    # 清理临时文件
    Path(temp_path).unlink(missing_ok=True)


class TestDocumentManagerInit:
    """测试 DocumentManager 初始化。"""

    def test_initialization_with_dependencies(self, mock_vector_store, mock_bm25_indexer, mock_image_storage, temp_file_integrity):
        """测试使用所有依赖正确初始化。"""
        manager = DocumentManager(
            chroma_store=mock_vector_store,
            bm25_indexer=mock_bm25_indexer,
            image_storage=mock_image_storage,
            file_integrity=temp_file_integrity,
            default_collection="custom_collection",
        )

        assert manager._chroma_store == mock_vector_store
        assert manager._bm25_indexer == mock_bm25_indexer
        assert manager._image_storage == mock_image_storage
        assert manager._file_integrity == temp_file_integrity
        assert manager._default_collection == "custom_collection"


class TestListDocuments:
    """测试 list_documents 方法。"""

    def test_list_empty_documents(self, document_manager):
        """测试列出空文档列表。"""
        docs = document_manager.list_documents()
        assert docs == []

    def test_list_single_document(self, document_manager, sample_document, mock_vector_store, mock_image_storage):
        """测试列出单个文档。"""
        # 设置 mock 返回值
        mock_vector_store.get_ids_by_metadata.return_value = ["chunk_001", "chunk_002"]
        mock_image_storage.get_images_by_doc_hash.return_value = []

        # 计算文档哈希并标记成功
        doc_hash = document_manager._file_integrity.compute_sha256(sample_document)
        file_size = Path(sample_document).stat().st_size
        document_manager._file_integrity.mark_success(doc_hash, sample_document, file_size, chunk_count=2)

        # 列出文档
        docs = document_manager.list_documents()

        assert len(docs) == 1
        doc = docs[0]
        assert doc.doc_id == doc_hash
        assert doc.source_path == sample_document
        assert doc.collection == "test_collection"
        assert doc.chunk_count == 2
        assert doc.image_count == 0
        assert doc.status == "success"
        assert doc.doc_type == "markdown"

        # 验证调用了 doc_id 查询（兼容模式下会有多次查询）
        mock_vector_store.get_ids_by_metadata.assert_any_call(metadata_filters={"doc_id": doc_hash})
        mock_image_storage.get_images_by_doc_hash.assert_called_once_with(doc_hash)

    def test_list_multiple_documents(self, document_manager, sample_document, mock_vector_store, mock_image_storage):
        """测试列出多个多个文档。"""
        # 创建第二个文档
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("Second test document content.")
            doc2_path = f.name

        try:
            # 为第一个文档设置 mock
            doc1_hash = document_manager._file_integrity.compute_sha256(sample_document)
            mock_vector_store.get_ids_by_metadata.side_effect = [
                ["chunk_001"],  # 第一个文档
                ["chunk_002"],  # 第二个文档
            ]
            mock_image_storage.get_images_by_doc_hash.side_effect = [[], []]

            # 标记第一个文档
            doc1_size = Path(sample_document).stat().st_size
            document_manager._file_integrity.mark_success(doc1_hash, sample_document, doc1_size, chunk_count=1)

            # 标记第二个文档
            doc2_hash = document_manager._file_integrity.compute_sha256(doc2_path)
            doc2_size = Path(doc2_path).stat().st_size
            document_manager._file_integrity.mark_success(doc2_hash, doc2_path, doc2_size, chunk_count=1)

            # 列出文档
            docs = document_manager.list_documents()

            assert len(docs) == 2

            # 验证文档按时间倒序排序（后添加的在前）
            assert docs[0].source_path == doc2_path
            assert docs[1].source_path == sample_document

        finally:
            Path(doc2_path).unlink(missing_ok=True)

    def test_list_documents_with_images(self, document_manager, sample_document, mock_vector_store, mock_image_storage):
        """测试列出带图片的文档。"""
        # 设置 mock 返回值
        mock_vector_store.get_ids_by_metadata.return_value = ["chunk_001"]
        mock_image_storage.get_images_by_doc_hash.return_value = [
            {"image_id": "img_001", "file_path": "/path/img1.png"},
            {"image_id": "img_002", "file_path": "/path/img2.png"},
        ]

        # 标记文档
        doc_hash = document_manager._file_integrity.compute_sha256(sample_document)
        file_size = Path(sample_document).stat().st_size
        document_manager._file_integrity.mark_success(doc_hash, sample_document, file_size, chunk_count=1)

        # 列出文档
        docs = document_manager.list_documents()

        assert len(docs) == 1
        assert docs[0].image_count == 2

    def test_list_documents_custom_collection(self, document_manager, sample_document, mock_vector_store, mock_image_storage):
        """测试列出指定集合的文档。"""
        mock_vector_store.get_ids_by_metadata.return_value = []
        mock_image_storage.get_images_by_doc_hash.return_value = []

        # 标记文档
        doc_hash = document_manager._file_integrity.compute_sha256(sample_document)
        file_size = Path(sample_document).stat().st_size
        document_manager._file_integrity.mark_success(doc_hash, sample_document, file_size, chunk_count=0)

        # 指定集合名称列出
        docs = document_manager.list_documents(collection="custom_collection")

        assert len(docs) == 1
        # 注意：由于 FileIntegrity 不存储 collection 信息，这里使用参数传入
        assert docs[0].collection == "custom_collection"

    def test_list_documents_only_success(self, document_manager, sample_document, mock_vector_store, mock_image_storage):
        """测试只列出成功处理的文档。"""
        mock_vector_store.get_ids_by_metadata.return_value = []
        mock_image_storage.get_images_by_doc_hash.return_value = []

        # 标记成功文档
        doc_hash = document_manager._file_integrity.compute_sha256(sample_document)
        file_size = Path(sample_document).stat().st_size
        document_manager._file_integrity.mark_success(doc_hash, sample_document, file_size, chunk_count=0)

        # 标记失败文档
        failed_hash = "failed_doc_hash"
        document_manager._file_integrity.mark_failed(failed_hash, "failed.pdf", "Test error")

        # 列出文档（只应返回成功的）
        docs = document_manager.list_documents()

        assert len(docs) == 1
        assert docs[0].doc_id == doc_hash
        assert docs[0].status == "success"


class TestGetDocumentDetail:
    """测试 get_document_detail 方法。"""

    def test_get_detail_existing_document(self, document_manager, sample_document, mock_vector_store, mock_image_storage):
        """测试获取已存在文档的详细信息。"""
        # 设置 mock 返回值
        chunk_ids = ["chunk_001", "chunk_002", "chunk_003"]
        mock_vector_store.get_ids_by_metadata.return_value = chunk_ids
        mock_vector_store.get_by_ids.return_value = [
            {"id": "chunk_001", "text": "First chunk", "metadata": {"doc_id": "doc1"}},
            {"id": "chunk_002", "text": "Second chunk", "metadata": {"doc_id": "doc1"}},
            {"id": "chunk_003", "text": "Third chunk", "metadata": {"doc_id": "doc1"}},
        ]
        mock_image_storage.get_images_by_doc_hash.return_value = [
            {"image_id": "img_001", "file_path": "/path/img1.png"},
        ]

        # 标记文档
        doc_hash = document_manager._file_integrity.compute_sha256(sample_document)
        file_size = Path(sample_document).stat().st_size
        document_manager._file_integrity.mark_success(doc_hash, sample_document, file_size, chunk_count=3)

        # 获取详细信息
        detail = document_manager.get_document_detail(doc_hash)

        assert detail.doc_id == doc_hash
        assert detail.source_path == sample_document
        assert detail.collection == "test_collection"
        assert detail.chunk_count == 3
        assert detail.image_count == 1
        assert detail.status == "success"
        assert detail.doc_type == "markdown"
        assert len(detail.chunks) == 3
        assert len(detail.images) == 1

        # 验证 chunks 内容
        assert detail.chunks[0]["text"] == "First chunk"

    def test_get_detail_nonexistent_document(self, document_manager):
        """测试获取不存在文档时抛出异常。"""
        with pytest.raises(ValueError, match="Document not found"):
            document_manager.get_document_detail("nonexistent_hash")

    def test_get_detail_ambiguous_prefix_raises_error(self, document_manager, mock_vector_store):
        """测试短前缀匹配多个文档时抛出歧义错误。"""
        document_manager._file_integrity.list_processed = MagicMock(
            return_value=[
                {
                    "file_hash": "abcd111122223333444455556666777788889999aaaabbbbccccddddeeeeffff",
                    "file_path": "/tmp/doc1.md",
                    "processed_at": "2026-04-10T10:00:00",
                    "file_size": 100,
                    "status": "success",
                },
                {
                    "file_hash": "abcd9999000011112222333344445555666677778888aaaabbbbccccddddeeee",
                    "file_path": "/tmp/doc2.md",
                    "processed_at": "2026-04-10T10:05:00",
                    "file_size": 120,
                    "status": "success",
                },
            ]
        )

        with pytest.raises(ValueError, match="Ambiguous document identifier"):
            document_manager.get_document_detail("doc_abcd")

        mock_vector_store.get_by_ids.assert_not_called()

    def test_get_detail_with_no_chunks(self, document_manager, sample_document, mock_vector_store, mock_image_storage):
        """测试获取没有 chunks 的文档详细信息。"""
        # 设置 mock 返回值
        mock_vector_store.get_ids_by_metadata.return_value = []
        mock_image_storage.get_images_by_doc_hash.return_value = []

        # 标记文档
        doc_hash = document_manager._file_integrity.compute_sha256(sample_document)
        file_size = Path(sample_document).stat().st_size
        document_manager._file_integrity.mark_success(doc_hash, sample_document, file_size, chunk_count=0)

        # 获取详细信息
        detail = document_manager.get_document_detail(doc_hash)

        assert detail.chunk_count == 0
        assert detail.chunks == []

    def test_get_detail_with_no_images(self, document_manager, sample_document, mock_vector_store, mock_image_storage):
        """测试获取没有图片的文档详细信息。"""
        # 设置 mock 返回值
        mock_vector_store.get_ids_by_metadata.return_value = ["chunk_001"]
        mock_vector_store.get_by_ids.return_value = [
            {"id": "chunk_001", "text": "First chunk", "metadata": {"doc_id": "doc1"}},
        ]
        mock_image_storage.get_images_by_doc_hash.return_value = []

        # 标记文档
        doc_hash = document_manager._file_integrity.compute_sha256(sample_document)
        file_size = Path(sample_document).stat().st_size
        document_manager._file_integrity.mark_success(doc_hash, sample_document, file_size, chunk_count=1)

        # 获取详细信息
        detail = document_manager.get_document_detail(doc_hash)

        assert detail.image_count == 0
        assert detail.images == []


class TestDeleteDocument:
    """测试 delete_document 方法。"""

    def test_delete_document_success(self, document_manager, sample_document, mock_vector_store, mock_bm25_indexer, mock_image_storage):
        """测试成功删除文档。"""
        # 设置 mock 返回值
        chunk_ids = ["chunk_001", "chunk_002"]
        mock_vector_store.get_ids_by_metadata.return_value = chunk_ids
        mock_image_storage.get_images_by_doc_hash.return_value = [
            {"image_id": "img_001", "file_path": "/path/img1.png"},
        ]

        # 标记文档
        doc_hash = document_manager._file_integrity.compute_sha256(sample_document)
        file_size = Path(sample_document).stat().st_size
        document_manager._file_integrity.mark_success(doc_hash, sample_document, file_size, chunk_count=2)

        # 删除文档
        result = document_manager.delete_document(sample_document, "test_collection")

        # 验证删除结果
        assert result.success is True
        assert result.doc_id == doc_hash
        assert result.source_path == sample_document
        assert result.collection == "test_collection"
        assert result.chunks_deleted == 2
        assert result.images_deleted == 1
        assert result.error is None

        # 验证所有存储后端都被正确调用
        mock_vector_store.get_ids_by_metadata.assert_any_call(metadata_filters={"doc_id": doc_hash})
        mock_vector_store.delete.assert_called_once_with(doc_ids=chunk_ids)
        mock_bm25_indexer.remove_documents.assert_called_once_with(set(chunk_ids))
        mock_image_storage.get_images_by_doc_hash.assert_called_with(doc_hash)
        mock_image_storage.delete_by_doc_hash.assert_called_once_with(doc_hash)

        # 验证 FileIntegrity 记录已删除
        assert not document_manager._file_integrity.should_skip(doc_hash)

    def test_delete_document_with_no_chunks(self, document_manager, sample_document, mock_vector_store, mock_bm25_indexer, mock_image_storage):
        """测试删除没有 chunks 的文档。"""
        # 设置 mock 返回值
        mock_vector_store.get_ids_by_metadata.return_value = []
        mock_image_storage.get_images_by_doc_hash.return_value = []

        # 标记文档
        doc_hash = document_manager._file_integrity.compute_sha256(sample_document)
        file_size = Path(sample_document).stat().st_size
        document_manager._file_integrity.mark_success(doc_hash, sample_document, file_size, chunk_count=0)

        # 删除文档
        result = document_manager.delete_document(sample_document, "test_collection")

        assert result.success is True
        assert result.chunks_deleted == 0
        assert result.images_deleted == 0

        # 验证 delete 不应该被调用（没有 chunks）
        mock_vector_store.delete.assert_not_called()
        mock_bm25_indexer.remove_documents.assert_not_called()

    def test_delete_document_file_not_found(self, document_manager, mock_vector_store):
        """测试删除不存在的文件。"""
        result = document_manager.delete_document("nonexistent_file.pdf", "test_collection")

        assert result.success is False
        assert result.error is not None
        assert "File not found" in result.error

        # 验证没有调用任何删除操作
        mock_vector_store.delete.assert_not_called()

    def test_delete_vector_store_error(self, document_manager, sample_document, mock_vector_store, mock_bm25_indexer, mock_image_storage):
        """测试向量存储删除失败时的错误处理。"""
        # 设置 mock 抛出异常
        mock_vector_store.get_ids_by_metadata.return_value = ["chunk_001"]
        mock_vector_store.delete.side_effect = RuntimeError("ChromaDB connection failed")
        mock_image_storage.get_images_by_doc_hash.return_value = []

        # 标记文档
        doc_hash = document_manager._file_integrity.compute_sha256(sample_document)
        file_size = Path(sample_document).stat().st_size
        document_manager._file_integrity.mark_success(doc_hash, sample_document, file_size, chunk_count=1)

        # 删除文档（应该捕获错误并返回失败结果）
        result = document_manager.delete_document(sample_document, "test_collection")

        assert result.success is False
        assert result.error is not None
        assert "ChromaDB connection failed" in result.error

    def test_delete_after_verify_not_in_list(self, document_manager, sample_document, mock_vector_store, mock_bm25_indexer, mock_image_storage):
        """测试删除后文档不在列表中。"""
        # 设置 mock 返回值
        chunk_ids = ["chunk_001"]
        mock_vector_store.get_ids_by_metadata.return_value = chunk_ids
        mock_image_storage.get_images_by_doc_hash.return_value = []

        # 标记文档
        doc_hash = document_manager._file_integrity.compute_sha256(sample_document)
        file_size = Path(sample_document).stat().st_size
        document_manager._file_integrity.mark_success(doc_hash, sample_document, file_size, chunk_count=1)

        # 验证文档在列表中
        docs_before = document_manager.list_documents()
        assert len(docs_before) == 1
        assert docs_before[0].doc_id == doc_hash

        # 删除文档
        result = document_manager.delete_document(sample_document, "test_collection")
        assert result.success is True

        # 验证文档不在列表中
        docs_after = document_manager.list_documents()
        assert len(docs_after) == 0
        assert all(d.doc_id != doc_hash for d in docs_after)


class TestGetCollectionStats:
    """测试 get_collection_stats 方法。"""

    def test_stats_empty_collection(self, document_manager):
        """测试空集合的统计信息。"""
        stats = document_manager.get_collection_stats()

        assert stats.collection == "test_collection"
        assert stats.total_documents == 0
        assert stats.total_chunks == 0
        assert stats.total_images == 0
        assert stats.total_size == 0
        assert stats.last_ingested_at is None

    def test_stats_single_document(self, document_manager, sample_document, mock_vector_store, mock_image_storage):
        """测试单个文档的统计信息。"""
        # 设置 mock 返回值
        mock_vector_store.get_ids_by_metadata.return_value = ["chunk_001", "chunk_002"]
        mock_image_storage.get_images_by_doc_hash.return_value = [
            {"image_id": "img_001"},
            {"image_id": "img_002"},
        ]

        # 标记文档
        doc_hash = document_manager._file_integrity.compute_sha256(sample_document)
        file_size = Path(sample_document).stat().st_size
        document_manager._file_integrity.mark_success(doc_hash, sample_document, file_size, chunk_count=2)

        # 获取统计信息
        stats = document_manager.get_collection_stats()

        assert stats.collection == "test_collection"
        assert stats.total_documents == 1
        assert stats.total_chunks == 2
        assert stats.total_images == 2
        assert stats.total_size == file_size
        assert stats.last_ingested_at is not None

    def test_stats_multiple_documents(self, document_manager, sample_document, mock_vector_store, mock_image_storage):
        """测试多个文档的统计信息。"""
        # 创建第二个文档
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("Second test document.")
            doc2_path = f.name

        try:
            # 设置 mock 返回值
            chunk_sizes = [3, 5]  # 第一个文档3个chunk，第二个文档5个chunk
            mock_vector_store.get_ids_by_metadata.side_effect = [
                ["chunk_001", "chunk_002", "chunk_003"],  # 第一个文档
                ["chunk_004", "chunk_005", "chunk_006", "chunk_007", "chunk_008"],  # 第二个文档
            ]
            mock_image_storage.get_images_by_doc_hash.side_effect = [
                [{"image_id": "img_001"}],  # 第一个文档1张图片
                [{"image_id": "img_002"}, {"image_id": "img_003"}],  # 第二个文档2张图片
            ]

            # 标记第一个文档
            doc1_hash = document_manager._file_integrity.compute_sha256(sample_document)
            doc1_size = Path(sample_document).stat().st_size
            document_manager._file_integrity.mark_success(doc1_hash, sample_document, doc1_size, chunk_count=3)

            # 标记第二个文档
            doc2_hash = document_manager._file_integrity.compute_sha256(doc2_path)
            doc2_size = Path(doc2_path).stat().st_size
            document_manager._file_integrity.mark_success(doc2_hash, doc2_path, doc2_size, chunk_count=5)

            # 获取统计信息
            stats = document_manager.get_collection_stats()

            assert stats.total_documents == 2
            assert stats.total_chunks == 8  # 3 + 5
            assert stats.total_images == 3   # 1 + 2
            assert stats.total_size == doc1_size + doc2_size

        finally:
            Path(doc2_path).unlink(missing_ok=True)

    def test_stats_custom_collection(self, document_manager, sample_document):
        """测试指定集合名称的统计信息。"""
        # 标记文档
        mock_vector_store = MagicMock()
        mock_vector_store.get_ids_by_metadata.return_value = []
        mock_image_storage = MagicMock()
        mock_image_storage.get_images_by_doc_hash.return_value = []

        doc_hash = document_manager._file_integrity.compute_sha256(sample_document)
        file_size = Path(sample_document).stat().st_size
        document_manager._file_integrity.mark_success(doc_hash, sample_document, file_size, chunk_count=0)

        # 获取指定集合统计（注意：实际实现中 FileIntetry 不支持集合过滤）
        stats = document_manager.get_collection_stats(collection="my_collection")

        assert stats.collection == "my_collection"


class TestLegacyChunkLookupFallback:
    """测试历史数据兼容查询（缺失 doc_id 时回退 source_path）。"""

    def test_get_chunks_fallback_to_source_path(
        self,
        document_manager,
        sample_document,
        mock_vector_store,
        mock_image_storage,
    ):
        """当 metadata 不含 doc_id 时，仍可通过 source_path 查询到 chunk。"""
        # 3 次 doc_id 变体查询都失败，第 4 次 source_path 查询成功
        mock_vector_store.get_ids_by_metadata.side_effect = [
            [],
            [],
            [],
            ["legacy_chunk_001"],
        ]
        mock_vector_store.get_by_ids.return_value = [
            {"id": "legacy_chunk_001", "text": "legacy text", "metadata": {"source_path": sample_document}},
        ]
        mock_image_storage.get_images_by_doc_hash.return_value = []

        doc_hash = document_manager._file_integrity.compute_sha256(sample_document)
        file_size = Path(sample_document).stat().st_size
        document_manager._file_integrity.mark_success(doc_hash, sample_document, file_size, chunk_count=1)

        detail = document_manager.get_document_detail(doc_hash)

        assert detail.chunk_count == 1
        assert detail.chunks[0]["id"] == "legacy_chunk_001"
        mock_vector_store.get_ids_by_metadata.assert_any_call(
            metadata_filters={"source_path": sample_document}
        )


class TestDataclasses:
    """测试数据类的序列化功能。"""

    def test_document_info_to_dict(self):
        """测试 DocumentInfo 序列化。"""
        info = DocumentInfo(
            doc_id="abc123",
            source_path="/path/to/doc.pdf",
            collection="test",
            chunk_count=10,
            image_count=2,
            ingested_at="2026-04-09",
            file_size=1024,
            doc_type="pdf",
            status="success",
        )

        result = info.to_dict()

        assert result["doc_id"] == "abc123"
        assert result["source_path"] == "/path/to/doc.pdf"
        assert result["collection"] == "test"
        assert result["chunk_count"] == 10
        assert result["image_count"] == 2
        assert result["ingested_at"] == "2026-04-09"
        assert result["file_size"] == 1024
        assert result["doc_type"] == "pdf"
        assert result["status"] == "success"

    def test_document_detail_to_dict(self):
        """测试 DocumentDetail 序列化。"""
        detail = DocumentDetail(
            doc_id="abc123",
            source_path="/path/to/doc.pdf",
            collection="test",
            chunk_count=10,
            image_count=2,
            ingested_at="2026-04-09",
            file_size=1024,
            doc_type="pdf",
            status="success",
            chunks=[{"id": "c1", "text": "chunk1"}],
            images=[{"image_id": "i1"}],
            metadata={"author": "test"},
        )

        result = detail.to_dict()

        assert result["doc_id"] == "abc123"
        assert len(result["chunks"]) == 1
        assert len(result["images"]) == 1
        assert result["metadata"]["author"] == "test"

    def test_delete_result_to_dict_success(self):
        """测试 DeleteResult 成功序列化。"""
        result = DeleteResult(
            success=True,
            doc_id="abc123",
            source_path="/path/to/doc.pdf",
            collection="test",
            chunks_deleted=10,
            images_deleted=2,
        )

        dict_result = result.to_dict()

        assert dict_result["success"] is True
        assert dict_result["chunks_deleted"] == 10
        assert dict_result["images_deleted"] == 2
        assert "error" not in dict_result

    def test_delete_result_to_dict_failure(self):
        """测试 DeleteResult 失败序列化。"""
        result = DeleteResult(
            success=False,
            doc_id="abc123",
            source_path="/path/to/doc.pdf",
            collection="test",
            error="File not found",
        )

        dict_result = result.to_dict()

        assert dict_result["success"] is False
        assert dict_result["error"] == "File not found"

    def test_collection_stats_to_dict(self):
        """测试 CollectionStats 序列化。"""
        stats = CollectionStats(
            collection="test",
            total_documents=10,
            total_chunks=100,
            total_images=20,
            total_size=10240,
            last_ingested_at="2026-04-09",
        )

        result = stats.to_dict()

        assert result["collection"] == "test"
        assert result["total_documents"] == 10
        assert result["total_chunks"] == 100
        assert result["total_images"] == 20
        assert result["total_size"] == 10240
        assert result["last_ingested_at"] == "2026-04-09"
