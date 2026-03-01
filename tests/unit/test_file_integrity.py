"""测试文件完整性检查器。

测试 FileIntegrityChecker 接口和 SQLiteIntegrityChecker 实现。
"""

import pytest
import tempfile
from pathlib import Path

from src.libs.loader.file_integrity import (
    FileIntegrityChecker,
    SQLiteIntegrityChecker,
)


@pytest.fixture
def temp_db():
    """临时数据库 fixture。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_ingestion_history.db"
        yield str(db_path)


@pytest.fixture
def checker(temp_db):
    """完整性检查器 fixture。"""
    return SQLiteIntegrityChecker(db_path=temp_db)


@pytest.fixture
def sample_file():
    """样例文件 fixture。"""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("Sample content for testing SHA256 hash computation.")
        temp_path = f.name
    yield temp_path
    # 清理临时文件
    Path(temp_path).unlink(missing_ok=True)


class TestFileIntegrityChecker:
    """测试 FileIntegrityChecker 接口契约。"""

    def test_compute_sha256_success(self, checker, sample_file):
        """测试计算文件 SHA256 哈希成功。"""
        hash_value = checker.compute_sha256(sample_file)
        # 验证哈希值格式（64 个十六进制字符）
        assert isinstance(hash_value, str)
        assert len(hash_value) == 64
        assert all(c in '0123456789abcdef' for c in hash_value)

    def test_compute_sha256_deterministic(self, checker, sample_file):
        """测试同一文件多次计算哈希值一致。"""
        hash1 = checker.compute_sha256(sample_file)
        hash2 = checker.compute_sha256(sample_file)
        assert hash1 == hash2

    def test_compute_sha256_file_not_found(self, checker):
        """测试文件不存在时抛出异常。"""
        with pytest.raises(FileNotFoundError):
            checker.compute_sha256("nonexistent_file.txt")

    def test_should_skip_new_file(self, checker, sample_file):
        """测试新文件不应跳过。"""
        file_hash = checker.compute_sha256(sample_file)
        assert not checker.should_skip(file_hash)

    def test_should_skip_after_mark_success(self, checker, sample_file):
        """测试标记成功后应跳过。"""
        file_hash = checker.compute_sha256(sample_file)
        file_size = Path(sample_file).stat().st_size

        # 标记成功
        checker.mark_success(file_hash, sample_file, file_size, chunk_count=10)

        # 验证应跳过
        assert checker.should_skip(file_hash)

    def test_should_not_skip_after_mark_failed(self, checker, sample_file):
        """测试标记失败后不应跳过。"""
        file_hash = checker.compute_sha256(sample_file)

        # 标记失败
        checker.mark_failed(file_hash, sample_file, "Test error")

        # 验证不应跳过（失败的记录不影响 should_skip）
        assert not checker.should_skip(file_hash)

    def test_mark_success_stores_metadata(self, checker, sample_file):
        """测试标记成功存储完整元数据。"""
        file_hash = checker.compute_sha256(sample_file)
        file_size = Path(sample_file).stat().st_size
        chunk_count = 15

        checker.mark_success(file_hash, sample_file, file_size, chunk_count)

        # 验证记录存在
        records = checker.list_processed(status="success")
        assert len(records) == 1
        record = records[0]

        assert record["file_hash"] == file_hash
        assert record["file_path"] == sample_file
        assert record["file_size"] == file_size
        assert record["status"] == "success"
        assert record["chunk_count"] == chunk_count
        assert record["error_msg"] is None

    def test_mark_failed_stores_error(self, checker, sample_file):
        """测试标记失败存储错误消息。"""
        file_hash = checker.compute_sha256(sample_file)
        error_msg = "Failed to parse PDF: invalid format"

        checker.mark_failed(file_hash, sample_file, error_msg)

        # 验证记录存在
        records = checker.list_processed(status="failed")
        assert len(records) == 1
        record = records[0]

        assert record["file_hash"] == file_hash
        assert record["file_path"] == sample_file
        assert record["status"] == "failed"
        assert record["error_msg"] == error_msg
        assert record["chunk_count"] is None

    def test_mark_success_overwrites_failed(self, checker, sample_file):
        """测试标记成功可覆盖失败记录。"""
        file_hash = checker.compute_sha256(sample_file)
        file_size = Path(sample_file).stat().st_size

        # 先标记失败
        checker.mark_failed(file_hash, sample_file, "Initial error")
        assert not checker.should_skip(file_hash)

        # 再标记成功
        checker.mark_success(file_hash, sample_file, file_size, chunk_count=5)
        assert checker.should_skip(file_hash)

        # 验证只有一条记录，状态为 success
        records = checker.list_processed()
        assert len(records) == 1
        assert records[0]["status"] == "success"

    def test_remove_record(self, checker, sample_file):
        """测试删除记录。"""
        file_hash = checker.compute_sha256(sample_file)
        file_size = Path(sample_file).stat().st_size

        # 添加记录
        checker.mark_success(file_hash, sample_file, file_size, chunk_count=10)
        assert checker.should_skip(file_hash)

        # 删除记录
        checker.remove_record(file_hash)
        assert not checker.should_skip(file_hash)

        # 验证记录不存在
        records = checker.list_processed()
        assert len(records) == 0

    def test_list_processed_no_filter(self, checker, sample_file):
        """测试列出所有记录（无过滤）。"""
        file_hash = checker.compute_sha256(sample_file)
        file_size = Path(sample_file).stat().st_size

        # 添加成功记录
        checker.mark_success(file_hash, sample_file, file_size, chunk_count=10)

        # 添加失败记录（不同哈希）
        failed_hash = "fake_hash_for_failed_record"
        checker.mark_failed(failed_hash, "fake_path.pdf", "Test error")

        # 验证列出所有记录
        records = checker.list_processed()
        assert len(records) == 2
        statuses = {r["status"] for r in records}
        assert statuses == {"success", "failed"}

    def test_list_processed_with_filter(self, checker, sample_file):
        """测试列出记录（带状态过滤）。"""
        file_hash = checker.compute_sha256(sample_file)
        file_size = Path(sample_file).stat().st_size

        # 添加成功记录
        checker.mark_success(file_hash, sample_file, file_size, chunk_count=10)

        # 添加失败记录
        failed_hash = "fake_hash_for_failed_record"
        checker.mark_failed(failed_hash, "fake_path.pdf", "Test error")

        # 验证只列出成功记录
        success_records = checker.list_processed(status="success")
        assert len(success_records) == 1
        assert success_records[0]["status"] == "success"

        # 验证只列出失败记录
        failed_records = checker.list_processed(status="failed")
        assert len(failed_records) == 1
        assert failed_records[0]["status"] == "failed"


class TestSQLiteIntegrityChecker:
    """测试 SQLiteIntegrityChecker 特有功能。"""

    def test_db_creation(self, temp_db):
        """测试数据库自动创建。"""
        db_path = Path(temp_db)
        assert not db_path.exists()

        # 初始化检查器
        checker = SQLiteIntegrityChecker(db_path=temp_db)

        # 验证数据库文件已创建
        assert db_path.exists()

    def test_db_parent_directory_creation(self):
        """测试父目录自动创建。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "nested" / "dir" / "test.db"
            assert not db_path.parent.exists()

            # 初始化检查器
            checker = SQLiteIntegrityChecker(db_path=str(db_path))

            # 验证父目录和数据库文件已创建
            assert db_path.parent.exists()
            assert db_path.exists()

    def test_concurrent_write_safety(self, checker, sample_file):
        """测试并发写入安全性（WAL 模式）。"""
        file_hash = checker.compute_sha256(sample_file)
        file_size = Path(sample_file).stat().st_size

        # 模拟并发写入（实际测试中可用多线程）
        checker.mark_success(file_hash, sample_file, file_size, chunk_count=10)

        # 创建第二个检查器实例（模拟并发连接）
        checker2 = SQLiteIntegrityChecker(db_path=checker.db_path)

        # 验证第二个实例可以读取数据
        assert checker2.should_skip(file_hash)

        # 验证第二个实例可以写入数据
        failed_hash = "concurrent_write_test_hash"
        checker2.mark_failed(failed_hash, "test.pdf", "Concurrent test")

        # 验证第一个实例可以读取第二个实例写入的数据
        records = checker.list_processed(status="failed")
        assert len(records) == 1
        assert records[0]["file_hash"] == failed_hash

    def test_empty_database_list(self, checker):
        """测试空数据库列表查询。"""
        records = checker.list_processed()
        assert records == []

    def test_hash_uniqueness_constraint(self, checker, sample_file):
        """测试哈希唯一性约束（同一哈希重复插入会覆盖）。"""
        file_hash = checker.compute_sha256(sample_file)
        file_size = Path(sample_file).stat().st_size

        # 第一次标记成功
        checker.mark_success(file_hash, sample_file, file_size, chunk_count=10)

        # 第二次标记成功（应覆盖）
        checker.mark_success(file_hash, sample_file, file_size, chunk_count=20)

        # 验证只有一条记录，且 chunk_count 为最新值
        records = checker.list_processed()
        assert len(records) == 1
        assert records[0]["chunk_count"] == 20
