"""Unit tests for DataService.

Tests data browsing functionality including:
- Document listing and filtering
- Document detail retrieval
- Chunk retrieval
- Image retrieval
- Collection operations
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

import pytest

from src.core.types import ChunkRecord
from src.observability.dashboard.services.data_service import (
    DataService,
    ChunkDisplay,
    ImageDisplay,
)
from src.ingestion.document_manager import DocumentInfo, DocumentDetail


@pytest.fixture
def mock_settings():
    """Mock settings object."""
    settings = Mock()
    settings.vector_store.collection_name = "test_collection"
    return settings


@pytest.fixture
def mock_vector_store():
    """Mock vector store."""
    store = Mock()
    store.get_backend_name.return_value = "chromadb"
    store.get_ids_by_metadata.return_value = []
    store.get_by_ids.return_value = []
    return store


@pytest.fixture
def mock_image_storage():
    """Mock image storage."""
    storage = Mock()
    storage.get_images_by_doc_hash.return_value = []
    storage.get_image_path.return_value = None
    return storage


@pytest.fixture
def mock_file_integrity():
    """Mock file integrity checker."""
    checker = Mock()
    checker.list_processed.return_value = []
    checker.compute_sha256.return_value = "test_hash"
    return checker


@pytest.fixture
def mock_bm25_indexer():
    """Mock BM25 indexer."""
    indexer = Mock()
    return indexer


@pytest.fixture
def service(
    mock_settings,
    mock_vector_store,
    mock_image_storage,
    mock_file_integrity,
    mock_bm25_indexer,
):
    """Create DataService instance with mocked dependencies."""
    service = DataService(mock_settings)

    # 注入 mocked 依赖
    service._vector_store = mock_vector_store
    service._image_storage = mock_image_storage
    service._file_integrity = mock_file_integrity
    service._bm25_indexer = mock_bm25_indexer

    return service


class TestDataService:
    """Test suite for DataService."""

    def test_list_documents_empty(self, service):
        """Test listing documents when no documents exist."""
        service._file_integrity.list_processed.return_value = []

        docs = service.list_documents()

        assert docs == []
        service._file_integrity.list_processed.assert_called_once_with(status="success")

    def test_list_documents_with_data(self, service):
        """Test listing documents with data."""
        # Mock 文件完整性记录
        service._file_integrity.list_processed.return_value = [
            {
                "file_path": "test/docs/document1.pdf",
                "file_hash": "hash1",
                "processed_at": "2026-01-01T12:00:00",
                "file_size": 102400,
                "status": "success",
            },
            {
                "file_path": "test/docs/document2.md",
                "file_hash": "hash2",
                "processed_at": "2026-01-02T14:30:00",
                "file_size": 204800,
                "status": "success",
            },
        ]

        # Mock chunk 数量查询（兼容查询会多次按不同 metadata 条件调用）
        def _mock_get_ids_by_metadata(*, metadata_filters):
            if metadata_filters == {"doc_id": "hash1"}:
                return ["chunk1", "chunk2"]
            if metadata_filters == {"doc_id": "hash2"}:
                return ["chunk3"]
            return []

        service._vector_store.get_ids_by_metadata.side_effect = _mock_get_ids_by_metadata

        docs = service.list_documents()

        assert len(docs) == 2
        assert docs[0].source_path == "test/docs/document2.md"  # 应该按时间倒序
        assert docs[0].doc_type == "markdown"
        assert docs[0].chunk_count == 1
        assert docs[1].source_path == "test/docs/document1.pdf"
        assert docs[1].doc_type == "pdf"
        assert docs[1].chunk_count == 2

    def test_list_documents_filter_by_type(self, service):
        """Test filtering documents by type."""
        service._file_integrity.list_processed.return_value = [
            {
                "file_path": "test/docs/doc1.pdf",
                "file_hash": "hash1",
                "processed_at": "2026-01-01T00:00:00",
                "file_size": 1000,
                "status": "success",
            },
            {
                "file_path": "test/docs/doc2.md",
                "file_hash": "hash2",
                "processed_at": "2026-01-02T00:00:00",
                "file_size": 2000,
                "status": "success",
            },
        ]
        service._vector_store.get_ids_by_metadata.return_value = []

        # 只查询 pdf 类型
        docs = service.list_documents(doc_type="pdf")

        assert len(docs) == 1
        assert docs[0].doc_type == "pdf"
        assert docs[0].source_path == "test/docs/doc1.pdf"

    def test_list_documents_error_handling(self, service):
        """Test error handling when listing documents fails."""
        service._file_integrity.list_processed.side_effect = Exception("DB error")

        docs = service.list_documents()

        assert docs == []

    def test_get_document_detail_not_found(self, service):
        """Test getting document detail for non-existent document."""
        service._file_integrity.list_processed.return_value = []

        detail = service.get_document_detail("nonexistent_hash")

        assert detail is None

    def test_get_document_detail_success(self, service):
        """Test getting document detail successfully."""
        doc_hash = "test_hash"

        # Mock 文档记录
        service._file_integrity.list_processed.return_value = [
            {
                "file_path": "test/docs/document.pdf",
                "file_hash": doc_hash,
                "processed_at": "2026-01-01T00:00:00",
                "file_size": 1000,
                "status": "success",
            },
        ]

        # Mock chunks
        service._vector_store.get_ids_by_metadata.return_value = ["chunk1", "chunk2"]
        service._vector_store.get_by_ids.return_value = [
            {"id": "chunk1", "text": "Content 1", "metadata": {"page": 1}},
            {"id": "chunk2", "text": "Content 2", "metadata": {"page": 2}},
        ]

        # Mock images
        service._image_storage.get_images_by_doc_hash.return_value = [
            {"image_id": "img1", "file_path": "data/images/img1.png", "page_num": 1},
        ]

        detail = service.get_document_detail(doc_hash)

        assert detail is not None
        assert detail.doc_id == doc_hash
        assert len(detail.chunks) == 2
        assert len(detail.images) == 1

    def test_get_chunks_by_doc_id_empty(self, service):
        """Test getting chunks when document has no chunks."""
        service._file_integrity.list_processed.return_value = []
        service._image_storage.get_images_by_doc_hash.return_value = []

        chunks = service.get_chunks_by_doc_id("test_hash")

        assert chunks == []

    def test_get_chunks_by_doc_id_with_data(self, service):
        """Test getting chunks successfully."""
        doc_hash = "test_hash"

        # 使用 patch 来创建一个 mock 的 get_document_detail
        with patch.object(service, "get_document_detail", return_value=DocumentDetail(
            doc_id=doc_hash,
            source_path="test.pdf",
            collection="default",
            chunk_count=2,
            image_count=0,
            ingested_at="2026-01-01T00:00:00",
            file_size=1000,
            doc_type="pdf",
            status="success",
            chunks=[
                {"id": "chunk1", "text": "Content 1", "metadata": {}},
                {"id": "chunk2", "text": "Content 2", "metadata": {}},
            ],
            images=[],
        )):
            chunks = service.get_chunks_by_doc_id(doc_hash)

            assert len(chunks) == 2
            assert chunks[0].chunk_id == "chunk1"
            assert chunks[0].content == "Content 1"
            assert chunks[1].chunk_id == "chunk2"
            assert chunks[1].content == "Content 2"

    def test_get_document_images_empty(self, service):
        """Test getting images when document has no images."""
        service._image_storage.get_images_by_doc_hash.return_value = []

        images = service.get_document_images("test_hash")

        assert images == []

    def test_get_document_images_with_data(self, service):
        """Test getting images successfully."""
        service._image_storage.get_images_by_doc_hash.return_value = [
            {
                "image_id": "img1",
                "file_path": "data/images/img1.png",
                "page_num": 1,
            },
            {
                "image_id": "img2",
                "file_path": "data/images/img2.png",
                "page_num": 2,
            },
        ]

        images = service.get_document_images("test_hash")

        assert len(images) == 2
        assert images[0].image_id == "img1"
        assert images[0].file_path == "data/images/img1.png"
        assert images[0].page_num == 1
        assert images[1].image_id == "img2"
        assert images[1].page_num == 2

    def test_get_image_path(self, service):
        """Test getting image path."""
        service._image_storage.get_image_path.return_value = "data/images/img1.png"

        path = service.get_image_path("img1")

        assert path == "data/images/img1.png"
        service._image_storage.get_image_path.assert_called_once_with("img1")

    def test_search_documents_no_match(self, service):
        """Test searching documents with no matches."""
        service._file_integrity.list_processed.return_value = [
            {
                "file_path": "test/docs/document1.pdf",
                "file_hash": "hash1",
                "processed_at": "2026-01-01T00:00:00",
                "file_size": 1000,
                "status": "success",
            },
        ]
        service._vector_store.get_ids_by_metadata.return_value = []

        result = service.search_documents("nonexistent")

        assert result == []

    def test_search_documents_with_match(self, service):
        """Test searching documents with matches."""
        service._file_integrity.list_processed.return_value = [
            {
                "file_path": "test/docs/important_doc.pdf",
                "file_hash": "hash1",
                "processed_at": "2026-01-01T00:00:00",
                "file_size": 1000,
                "status": "success",
            },
            {
                "file_path": "test/docs/other.md",
                "file_hash": "hash2",
                "processed_at": "2026-01-02T00:00:00",
                "file_size": 2000,
                "status": "success",
            },
        ]
        service._vector_store.get_ids_by_metadata.return_value = []

        result = service.search_documents("important")

        assert len(result) == 1
        assert "important" in result[0].source_path.lower()

    def test_get_collections(self, service):
        """Test getting collections."""
        collections = service.get_collections()

        assert collections == ["test_collection"]

    def test_get_collection_stats(self, service):
        """Test getting collection statistics."""
        service._vector_store.get_collection_stats.return_value = {
            "name": "test_collection",
            "count": 100,
        }

        stats = service.get_collection_stats("test_collection")

        assert stats["name"] == "test_collection"
        assert stats["count"] == 100
        service._vector_store.get_collection_stats.assert_called_once_with(
            collection_name="test_collection"
        )

    def test_get_collection_stats_error(self, service):
        """Test error handling when getting collection stats fails."""
        service._vector_store.get_collection_stats.side_effect = Exception("Test error")

        stats = service.get_collection_stats("test_collection")

        assert stats["name"] == "test_collection"
        assert stats["count"] == 0


class TestChunkDisplay:
    """Test suite for ChunkDisplay dataclass."""

    def test_chunk_display_creation(self):
        """Test creating ChunkDisplay."""
        chunk = ChunkDisplay(
            chunk_id="chunk1",
            content="Test content",
            metadata={"page": 1, "section": "intro"},
            images=[],
        )

        assert chunk.chunk_id == "chunk1"
        assert chunk.content == "Test content"
        assert chunk.metadata["page"] == 1
        assert chunk.images == []


class TestImageDisplay:
    """Test suite for ImageDisplay dataclass."""

    def test_image_display_creation(self):
        """Test creating ImageDisplay."""
        image = ImageDisplay(
            image_id="img1",
            file_path="data/images/img1.png",
            page_num=1,
        )

        assert image.image_id == "img1"
        assert image.file_path == "data/images/img1.png"
        assert image.page_num == 1

    def test_image_display_without_page_num(self):
        """Test creating ImageDisplay without page number."""
        image = ImageDisplay(
            image_id="img1",
            file_path="data/images/img1.png",
            page_num=None,
        )

        assert image.page_num is None
