"""Tests for Pipeline image storage functionality.

测试 IngestionPipeline 中的图片存储功能：
1. 从 document.metadata["images"] 获取图片引用
2. 调用 ImageStorage.save_image() 存储图片
3. 更新 ImageReference.path 为实际存储路径
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.ingestion.pipeline import IngestionPipeline
from src.ingestion.storage.image_storage import SQLiteImageStorage
from src.core.types import Document, Chunk, ImageReference
from src.core.settings import Settings


@pytest.fixture
def mock_settings():
    """Create mock settings."""
    settings = MagicMock(spec=Settings)
    settings.ingestion = MagicMock()
    settings.ingestion.chunk_size = 500
    settings.ingestion.chunk_overlap = 50
    settings.embedding = MagicMock()
    settings.embedding.provider = "mock"
    return settings


@pytest.fixture
def temp_dirs():
    """Create temporary directories for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield {
            "tmpdir": tmpdir,
            "db_path": Path(tmpdir) / "db",
            "images_root": Path(tmpdir) / "images",
        }


@pytest.fixture
def sample_image_file(temp_dirs):
    """Create a sample image file for testing."""
    img_path = Path(temp_dirs["tmpdir"]) / "sample.png"
    img_path.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)
    return str(img_path)


class TestPipelineImageStorage:
    """Test Pipeline image storage functionality."""

    def test_store_images_from_document(
        self, mock_settings, temp_dirs, sample_image_file
    ):
        """Test storing images from document metadata."""
        image_storage = SQLiteImageStorage(
            db_path=str(temp_dirs["db_path"] / "image_index.db"),
            images_root=str(temp_dirs["images_root"]),
        )

        pipeline = IngestionPipeline(
            settings=mock_settings,
            collection="test_collection",
            image_storage=image_storage,
        )

        img_ref = ImageReference(
            id="img_test_001",
            path=sample_image_file,
            text_offset=0,
            text_length=20,
            page=0,
        )

        document = Document(
            id="doc_test",
            text="Test content",
            metadata={
                "source_path": str(Path(temp_dirs["tmpdir"]) / "test.pdf"),
                "images": [img_ref],
            },
        )

        updated_images = pipeline._store_document_images(
            document=document,
            collection="test_collection",
            doc_hash="doc_hash_123",
        )

        assert len(updated_images) == 1
        assert updated_images[0].id == "img_test_001"

        stored_path = image_storage.get_image_path("img_test_001")
        assert stored_path is not None
        assert Path(stored_path).exists()

    def test_store_images_with_doc_hash(
        self, mock_settings, temp_dirs, sample_image_file
    ):
        """Test storing images with doc_hash association."""
        image_storage = SQLiteImageStorage(
            db_path=str(temp_dirs["db_path"] / "image_index.db"),
            images_root=str(temp_dirs["images_root"]),
        )

        pipeline = IngestionPipeline(
            settings=mock_settings,
            collection="test_collection",
            image_storage=image_storage,
        )

        img_ref = ImageReference(
            id="img_hash_test",
            path=sample_image_file,
            text_offset=0,
            text_length=20,
            page=1,
        )

        document = Document(
            id="doc_hash_test",
            text="Content",
            metadata={
                "source_path": str(Path(temp_dirs["tmpdir"]) / "test.pdf"),
                "images": [img_ref],
            },
        )

        pipeline._store_document_images(
            document=document,
            collection="test_collection",
            doc_hash="doc_hash_abc123",
        )

        images = image_storage.get_images_by_doc_hash("doc_hash_abc123")
        assert len(images) == 1
        assert images[0]["image_id"] == "img_hash_test"
        assert images[0]["page_num"] == 1

    def test_store_multiple_images(self, mock_settings, temp_dirs):
        """Test storing multiple images."""
        image_storage = SQLiteImageStorage(
            db_path=str(temp_dirs["db_path"] / "image_index.db"),
            images_root=str(temp_dirs["images_root"]),
        )

        pipeline = IngestionPipeline(
            settings=mock_settings,
            collection="test_collection",
            image_storage=image_storage,
        )

        image_refs = []
        for i in range(3):
            img_path = Path(temp_dirs["tmpdir"]) / f"image_{i}.png"
            img_path.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * (100 + i))
            image_refs.append(ImageReference(
                id=f"img_multi_{i}",
                path=str(img_path),
                text_offset=0,
                text_length=20,
                page=i,
            ))

        document = Document(
            id="doc_multi",
            text="Content with multiple images",
            metadata={
                "source_path": str(Path(temp_dirs["tmpdir"]) / "test.pdf"),
                "images": image_refs,
            },
        )

        updated_images = pipeline._store_document_images(
            document=document,
            collection="test_collection",
            doc_hash="doc_multi_hash",
        )

        assert len(updated_images) == 3

        for i, ref in enumerate(updated_images):
            stored_path = image_storage.get_image_path(f"img_multi_{i}")
            assert stored_path == ref.path
            assert Path(stored_path).exists()

    def test_document_without_images(self, mock_settings, temp_dirs):
        """Test handling document without images."""
        image_storage = SQLiteImageStorage(
            db_path=str(temp_dirs["db_path"] / "image_index.db"),
            images_root=str(temp_dirs["images_root"]),
        )

        pipeline = IngestionPipeline(
            settings=mock_settings,
            collection="test_collection",
            image_storage=image_storage,
        )

        document = Document(
            id="doc_no_images",
            text="Document without any images",
            metadata={
                "source_path": str(Path(temp_dirs["tmpdir"]) / "test.pdf"),
            },
        )

        updated_images = pipeline._store_document_images(
            document=document,
            collection="test_collection",
            doc_hash="doc_no_img_hash",
        )

        assert updated_images == []

    def test_image_storage_failure_does_not_block(
        self, mock_settings, temp_dirs, sample_image_file
    ):
        """Test that image storage failure does not block pipeline."""
        mock_storage = MagicMock(spec=SQLiteImageStorage)
        mock_storage.save_image.side_effect = IOError("Storage failed")

        pipeline = IngestionPipeline(
            settings=mock_settings,
            collection="test_collection",
            image_storage=mock_storage,
        )

        img_ref = ImageReference(
            id="img_fail_test",
            path=sample_image_file,
            text_offset=0,
            text_length=20,
            page=0,
        )

        document = Document(
            id="doc_fail",
            text="Content",
            metadata={
                "source_path": str(Path(temp_dirs["tmpdir"]) / "test.pdf"),
                "images": [img_ref],
            },
        )

        result = pipeline._store_document_images(
            document=document,
            collection="test_collection",
            doc_hash="doc_fail_hash",
        )

        mock_storage.save_image.assert_called_once()
        assert result == []

    def test_image_source_not_found(self, mock_settings, temp_dirs):
        """Test handling when image source file does not exist."""
        image_storage = SQLiteImageStorage(
            db_path=str(temp_dirs["db_path"] / "image_index.db"),
            images_root=str(temp_dirs["images_root"]),
        )

        pipeline = IngestionPipeline(
            settings=mock_settings,
            collection="test_collection",
            image_storage=image_storage,
        )

        img_ref = ImageReference(
            id="img_not_found",
            path="/nonexistent/image.png",
            text_offset=0,
            text_length=20,
            page=0,
        )

        document = Document(
            id="doc_not_found",
            text="Content",
            metadata={
                "source_path": str(Path(temp_dirs["tmpdir"]) / "test.pdf"),
                "images": [img_ref],
            },
        )

        result = pipeline._store_document_images(
            document=document,
            collection="test_collection",
            doc_hash="doc_not_found_hash",
        )

        assert result == []
