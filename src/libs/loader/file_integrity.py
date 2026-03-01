"""文件完整性检查 (SHA256 哈希)。

该模块实现了基于 SHA256 哈希的文件完整性检查，用于增量摄取场景。
通过记录已处理文件的哈希和状态，避免重复处理未变更的文件。

设计原则：
1. 使用 SQLite 作为默认存储，支持轻量级部署
2. 支持并发安全（WAL 模式）
3. 抽象接口设计，支持后续扩展为 Redis/PostgreSQL
4. 显式状态管理（success/failed/processing）
"""

import hashlib
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
from datetime import datetime


class FileIntegrityChecker(ABC):
    """文件完整性检查器抽象接口。

    定义了文件完整性检查的核心契约，支持不同的存储后端实现。
    """

    @abstractmethod
    def compute_sha256(self, file_path: str) -> str:
        """计算文件的 SHA256 哈希值。

        Args:
            file_path: 文件路径

        Returns:
            str: 文件的 SHA256 哈希值（十六进制字符串）

        Raises:
            FileNotFoundError: 文件不存在
            IOError: 文件读取错误
        """
        pass

    @abstractmethod
    def should_skip(self, file_hash: str) -> bool:
        """判断是否应跳过该文件的处理。

        Args:
            file_hash: 文件的 SHA256 哈希值

        Returns:
            bool: True 表示文件已成功处理过，应跳过；False 表示需要处理
        """
        pass

    @abstractmethod
    def mark_success(
        self,
        file_hash: str,
        file_path: str,
        file_size: int,
        chunk_count: int
    ) -> None:
        """标记文件处理成功。

        Args:
            file_hash: 文件的 SHA256 哈希值
            file_path: 文件路径
            file_size: 文件大小（字节）
            chunk_count: 生成的 chunk 数量
        """
        pass

    @abstractmethod
    def mark_failed(self, file_hash: str, file_path: str, error_msg: str) -> None:
        """标记文件处理失败。

        Args:
            file_hash: 文件的 SHA256 哈希值
            file_path: 文件路径
            error_msg: 错误消息
        """
        pass

    @abstractmethod
    def remove_record(self, file_hash: str) -> None:
        """删除文件处理记录。

        Args:
            file_hash: 文件的 SHA256 哈希值
        """
        pass

    @abstractmethod
    def list_processed(self, status: Optional[str] = None) -> list:
        """列出已处理的文件记录。

        Args:
            status: 可选，过滤特定状态的记录（success/failed/processing）

        Returns:
            list: 文件记录列表，每条记录为字典
        """
        pass


class SQLiteIntegrityChecker(FileIntegrityChecker):
    """基于 SQLite 的文件完整性检查器。

    使用 SQLite 数据库存储文件哈希记录，支持增量摄取和并发安全。

    数据库表结构：
        - file_hash: 文件的 SHA256 哈希值（主键）
        - file_path: 文件路径
        - file_size: 文件大小（字节）
        - status: 处理状态（success/failed/processing）
        - processed_at: 处理时间
        - error_msg: 错误消息（仅失败时记录）
        - chunk_count: 生成的 chunk 数量

    Args:
        db_path: 数据库文件路径，默认为 data/db/ingestion_history.db
    """

    def __init__(self, db_path: str = "data/db/ingestion_history.db"):
        """初始化 SQLite 完整性检查器。

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = Path(db_path)
        self._ensure_db_exists()

    def _ensure_db_exists(self) -> None:
        """确保数据库文件和表结构存在。"""
        # 创建父目录（如果不存在）
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # 连接数据库并创建表
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ingestion_history (
                    file_hash TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    file_size INTEGER,
                    status TEXT NOT NULL CHECK(status IN ('success', 'failed', 'processing')),
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    error_msg TEXT,
                    chunk_count INTEGER
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_status
                ON ingestion_history(status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_processed_at
                ON ingestion_history(processed_at)
            """)
            conn.commit()
        finally:
            conn.close()

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接（启用 WAL 模式以支持并发）。

        Returns:
            sqlite3.Connection: 数据库连接对象
        """
        conn = sqlite3.connect(str(self.db_path))
        # 启用 WAL (Write-Ahead Logging) 模式以支持并发读写
        conn.execute("PRAGMA journal_mode=WAL")
        # 返回字典格式的结果
        conn.row_factory = sqlite3.Row
        return conn

    def compute_sha256(self, file_path: str) -> str:
        """计算文件的 SHA256 哈希值。

        Args:
            file_path: 文件路径

        Returns:
            str: 文件的 SHA256 哈希值（十六进制字符串）

        Raises:
            FileNotFoundError: 文件不存在
            IOError: 文件读取错误
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        sha256_hash = hashlib.sha256()
        with open(path, "rb") as f:
            # 分块读取，避免大文件占用过多内存
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def should_skip(self, file_hash: str) -> bool:
        """判断是否应跳过该文件的处理。

        Args:
            file_hash: 文件的 SHA256 哈希值

        Returns:
            bool: True 表示文件已成功处理过，应跳过；False 表示需要处理
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT status FROM ingestion_history WHERE file_hash = ? AND status = 'success'",
                (file_hash,)
            )
            result = cursor.fetchone()
            return result is not None
        finally:
            conn.close()

    def mark_success(
        self,
        file_hash: str,
        file_path: str,
        file_size: int,
        chunk_count: int
    ) -> None:
        """标记文件处理成功。

        Args:
            file_hash: 文件的 SHA256 哈希值
            file_path: 文件路径
            file_size: 文件大小（字节）
            chunk_count: 生成的 chunk 数量
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO ingestion_history
                (file_hash, file_path, file_size, status, processed_at, chunk_count, error_msg)
                VALUES (?, ?, ?, 'success', ?, ?, NULL)
            """, (file_hash, file_path, file_size, datetime.now().isoformat(), chunk_count))
            conn.commit()
        finally:
            conn.close()

    def mark_failed(self, file_hash: str, file_path: str, error_msg: str) -> None:
        """标记文件处理失败。

        Args:
            file_hash: 文件的 SHA256 哈希值
            file_path: 文件路径
            error_msg: 错误消息
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO ingestion_history
                (file_hash, file_path, status, processed_at, error_msg, file_size, chunk_count)
                VALUES (?, ?, 'failed', ?, ?, NULL, NULL)
            """, (file_hash, file_path, datetime.now().isoformat(), error_msg))
            conn.commit()
        finally:
            conn.close()

    def remove_record(self, file_hash: str) -> None:
        """删除文件处理记录。

        Args:
            file_hash: 文件的 SHA256 哈希值
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM ingestion_history WHERE file_hash = ?", (file_hash,))
            conn.commit()
        finally:
            conn.close()

    def list_processed(self, status: Optional[str] = None) -> list:
        """列出已处理的文件记录。

        Args:
            status: 可选，过滤特定状态的记录（success/failed/processing）

        Returns:
            list: 文件记录列表，每条记录为字典
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            if status:
                cursor.execute(
                    "SELECT * FROM ingestion_history WHERE status = ? ORDER BY processed_at DESC",
                    (status,)
                )
            else:
                cursor.execute("SELECT * FROM ingestion_history ORDER BY processed_at DESC")

            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()
