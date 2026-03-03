"""测试图片存储。

测试 SQLiteImageStorage 接口和实现。
"""

import pytest
import tempfile
from pathlib import Path

from src.ingestion.storage.image_storage import (
    BaseImageStorage,
    SQLiteImageStorage,
)


@pytest.fixture
def temp_dirs():
    """临时目录 fixture。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_image_index.db"
        images_root = Path(tmpdir) / "images"
        yield str(db_path), str(images_root)


@pytest.fixture
def storage(temp_dirs):
    """图片存储 fixture。"""
    db_path, images_root = temp_dirs
    return SQLiteImageStorage(db_path=db_path, images_root=images_root)


@pytest.fixture
def sample_image():
    """样例图片 fixture（创建临时 PNG 文件）。"""
    with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as f:
        f.write(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01')
        temp_path = f.name
    yield temp_path
    Path(temp_path).unlink(missing_ok=True)


class TestBaseImageStorage:
    """测试 BaseImageStorage 接口契约。"""

    def test_save_and_get_image(self, storage, sample_image):
        """测试保存和获取图片。"""
        image_id = "test_image_001"
        collection = "test_collection"
        doc_hash = "abc123"
        page_num = 1

        # 保存图片
        saved_path = storage.save_image(
            source_path=sample_image,
            image_id=image_id,
            collection=collection,
            doc_hash=doc_hash,
            page_num=page_num,
        )

        # 验证返回路径
        assert saved_path is not None
        assert image_id in saved_path
        assert Path(saved_path).exists()

        # 获取图片路径
        retrieved_path = storage.get_image_path(image_id)
        assert retrieved_path == saved_path

    def test_get_image_path_not_found(self, storage):
        """测试获取不存在的图片路径。"""
        path = storage.get_image_path("nonexistent_image_id")
        assert path is None

    def test_save_image_file_not_found(self, storage):
        """测试保存不存在的源文件。"""
        with pytest.raises(FileNotFoundError):
            storage.save_image(
                source_path="nonexistent_image.png",
                image_id="test_001",
                collection="test",
            )

    def test_get_images_by_collection(self, storage, sample_image):
        """测试按集合查询图片。"""
        collection = "test_collection"

        # 保存多张图片到同一集合
        for i in range(3):
            storage.save_image(
                source_path=sample_image,
                image_id=f"collection_test_{i}",
                collection=collection,
                doc_hash=f"doc_{i}",
                page_num=i,
            )

        # 保存到另一集合
        storage.save_image(
            source_path=sample_image,
            image_id="other_collection_1",
            collection="other_collection",
            doc_hash="doc_other",
        )

        # 查询指定集合
        images = storage.get_images_by_collection(collection)
        assert len(images) == 3

        # 查询另一集合
        other_images = storage.get_images_by_collection("other_collection")
        assert len(other_images) == 1

    def test_get_images_by_doc_hash(self, storage, sample_image):
        """测试按文档哈希查询图片。"""
        doc_hash = "shared_doc_hash"

        # 保存多张图片到同一文档
        for i in range(2):
            storage.save_image(
                source_path=sample_image,
                image_id=f"doc_test_{i}",
                collection="test",
                doc_hash=doc_hash,
                page_num=i,
            )

        # 保存到不同文档
        storage.save_image(
            source_path=sample_image,
            image_id="other_doc_1",
            collection="test",
            doc_hash="other_doc_hash",
            page_num=0,
        )

        # 查询指定文档
        images = storage.get_images_by_doc_hash(doc_hash)
        assert len(images) == 2

        # 查询其他文档
        other_images = storage.get_images_by_doc_hash("other_doc_hash")
        assert len(other_images) == 1

    def test_save_image_idempotency(self, storage, sample_image):
        """测试保存图片的幂等性（同一 image_id 覆盖）。"""
        image_id = "idempotent_test"

        # 第一次保存
        path1 = storage.save_image(
            source_path=sample_image,
            image_id=image_id,
            collection="test",
        )

        # 第二次保存（应覆盖）
        path2 = storage.save_image(
            source_path=sample_image,
            image_id=image_id,
            collection="test",
        )

        # 验证路径相同
        assert path1 == path2

        # 验证只有一条记录
        images = storage.get_images_by_collection("test")
        assert len(images) == 1

    def test_compute_image_hash(self, storage, sample_image):
        """测试计算图片哈希。"""
        hash1 = storage.compute_image_hash(sample_image)
        hash2 = storage.compute_image_hash(sample_image)

        assert hash1 == hash2
        assert len(hash1) == 64
        assert all(c in '0123456789abcdef' for c in hash1)


class TestSQLiteImageStorage:
    """测试 SQLiteImageStorage 特有功能。"""

    def test_db_creation(self, temp_dirs):
        """测试数据库自动创建。"""
        db_path, images_root = temp_dirs
        db_path = Path(db_path)
        images_root = Path(images_root)

        assert not db_path.exists()
        assert not images_root.exists()

        storage = SQLiteImageStorage(db_path=str(db_path), images_root=str(images_root))

        assert db_path.exists()
        assert images_root.exists()

    def test_db_parent_directory_creation(self):
        """测试父目录自动创建。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "nested" / "dir" / "test.db"
            images_root = Path(tmpdir) / "nested" / "images"
            assert not db_path.parent.exists()

            storage = SQLiteImageStorage(db_path=str(db_path), images_root=str(images_root))

            assert db_path.parent.exists()
            assert db_path.exists()
            assert images_root.exists()

    def test_collection_directory_creation(self, storage, sample_image):
        """测试按集合创建子目录。"""
        collection = "new_collection"
        storage.save_image(
            source_path=sample_image,
            image_id="dir_test_001",
            collection=collection,
        )

        collection_dir = storage.images_root / collection
        assert collection_dir.exists()
        assert collection_dir.is_dir()

    def test_empty_collection_list(self, storage):
        """测试空集合列表查询。"""
        images = storage.get_images_by_collection("empty_collection")
        assert images == []

    def test_empty_doc_hash_list(self, storage):
        """测试空文档哈希列表查询。"""
        images = storage.get_images_by_doc_hash("empty_hash")
        assert images == []

    def test_concurrent_save_safety(self, storage, sample_image):
        """测试并发保存安全性。"""
        image_id = "concurrent_test"

        # 第一次保存
        path1 = storage.save_image(
            source_path=sample_image,
            image_id=image_id,
            collection="test",
        )

        # 创建第二个存储实例（模拟并发连接）
        storage2 = SQLiteImageStorage(
            db_path=str(storage.db_path),
            images_root=str(storage.images_root),
        )

        # 验证第二个实例可以读取数据
        path2 = storage2.get_image_path(image_id)
        assert path2 == path1

        # 验证第二个实例可以保存数据
        path3 = storage2.save_image(
            source_path=sample_image,
            image_id="concurrent_test_2",
            collection="test",
        )
        assert Path(path3).exists()

    def test_page_num_nullable(self, storage, sample_image):
        """测试页码可为 None。"""
        image_id = "page_num_test"

        # 保存时不指定页码
        saved_path = storage.save_image(
            source_path=sample_image,
            image_id=image_id,
            collection="test",
            doc_hash="doc123",
            page_num=None,
        )

        assert saved_path is not None

        # 查询验证
        path = storage.get_image_path(image_id)
        images = storage.get_images_by_doc_hash("doc123")
        assert len(images) == 1
        assert images[0]["page_num"] is None
