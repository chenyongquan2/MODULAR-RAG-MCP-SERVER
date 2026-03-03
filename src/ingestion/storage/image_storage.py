"""图片文件存储与索引。

该模块负责：
1. 将图片文件保存到 data/images/{collection}/ 目录
2. 使用 SQLite 记录 image_id → 文件路径映射
3. 支持按 collection 批量查询

设计原则：
1. 使用 SQLite 作为默认索引存储（复用 file_integrity.py 的模式）
2. 支持并发安全（WAL 模式）
3. 图片文件使用 SHA256 命名确保唯一性
"""

import hashlib
import shutil
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime


class BaseImageStorage(ABC):
    """图片存储抽象接口。

    定义了图片存储的核心契约，支持不同的存储后端实现。
    """

    @abstractmethod
    def save_image(
        self,
        source_path: str,
        image_id: str,
        collection: str,
        doc_hash: Optional[str] = None,
        page_num: Optional[int] = None,
    ) -> str:
        """保存图片文件并记录索引。

        Args:
            source_path: 图片源文件路径
            image_id: 全局唯一图片标识符
            collection: 所属集合名称
            doc_hash: 文档哈希（可选）
            page_num: 页码（可选）

        Returns:
            str: 保存后的文件路径

        Raises:
            FileNotFoundError: 源文件不存在
            IOError: 文件复制失败
        """
        pass

    @abstractmethod
    def get_image_path(self, image_id: str) -> Optional[str]:
        """根据 image_id 获取图片文件路径。

        Args:
            image_id: 全局唯一图片标识符

        Returns:
            str: 图片文件路径，如果不存在返回 None
        """
        pass

    @abstractmethod
    def get_images_by_collection(self, collection: str) -> List[Dict]:
        """获取指定集合的所有图片。

        Args:
            collection: 集合名称

        Returns:
            List[Dict]: 图片记录列表
        """
        pass

    @abstractmethod
    def get_images_by_doc_hash(self, doc_hash: str) -> List[Dict]:
        """获取指定文档的所有图片。

        Args:
            doc_hash: 文档哈希

        Returns:
            List[Dict]: 图片记录列表
        """
        pass


class SQLiteImageStorage(BaseImageStorage):
    """基于 SQLite 的图片存储与索引。

    使用 SQLite 数据库存储图片索引，支持按 collection/doc_hash 查询。
    图片文件保存到 data/images/{collection}/ 目录。

    数据库表结构：
        - image_id: 全局唯一图片标识符（主键）
        - file_path: 图片文件存储路径
        - collection: 所属集合名称
        - doc_hash: 文档哈希
        - page_num: 页码
        - created_at: 创建时间

    Args:
        db_path: 索引数据库路径，默认为 data/db/image_index.db
        images_root: 图片存储根目录，默认为 data/images
    """

    def __init__(
        self,
        db_path: str = "data/db/image_index.db",
        images_root: str = "data/images",
    ):
        """初始化 SQLite 图片存储。

        Args:
            db_path: 索引数据库路径
            images_root: 图片存储根目录
        """
        self.db_path = Path(db_path)
        self.images_root = Path(images_root)
        self._ensure_db_exists()

    def _ensure_db_exists(self) -> None:
        """确保数据库文件和表结构存在。"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.images_root.mkdir(parents=True, exist_ok=True)

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS image_index (
                    image_id TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    collection TEXT,
                    doc_hash TEXT,
                    page_num INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_collection
                ON image_index(collection)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_doc_hash
                ON image_index(doc_hash)
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
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def save_image(
        self,
        source_path: str,
        image_id: str,
        collection: str,
        doc_hash: Optional[str] = None,
        page_num: Optional[int] = None,
    ) -> str:
        """保存图片文件并记录索引。

        Args:
            source_path: 图片源文件路径
            image_id: 全局唯一图片标识符
            collection: 所属集合名称
            doc_hash: 文档哈希（可选）
            page_num: 页码（可选）

        Returns:
            str: 保存后的文件路径

        Raises:
            FileNotFoundError: 源文件不存在
            IOError: 文件复制失败
        """
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(f"Image source file not found: {source_path}")

        collection_dir = self.images_root / collection
        collection_dir.mkdir(parents=True, exist_ok=True)

        file_ext = source.suffix.lower()
        if not file_ext:
            file_ext = ".png"
        dest_path = collection_dir / f"{image_id}{file_ext}"

        shutil.copy2(source, dest_path)

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO image_index
                (image_id, file_path, collection, doc_hash, page_num, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                image_id,
                str(dest_path),
                collection,
                doc_hash,
                page_num,
                datetime.now().isoformat(),
            ))
            conn.commit()
        finally:
            conn.close()

        return str(dest_path)

    def get_image_path(self, image_id: str) -> Optional[str]:
        """根据 image_id 获取图片文件路径。

        Args:
            image_id: 全局唯一图片标识符

        Returns:
            str: 图片文件路径，如果不存在返回 None
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT file_path FROM image_index WHERE image_id = ?",
                (image_id,)
            )
            row = cursor.fetchone()
            return row["file_path"] if row else None
        finally:
            conn.close()

    def get_images_by_collection(self, collection: str) -> List[Dict]:
        """获取指定集合的所有图片。

        Args:
            collection: 集合名称

        Returns:
            List[Dict]: 图片记录列表
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM image_index WHERE collection = ? ORDER BY created_at DESC",
                (collection,)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_images_by_doc_hash(self, doc_hash: str) -> List[Dict]:
        """获取指定文档的所有图片。

        Args:
            doc_hash: 文档哈希

        Returns:
            List[Dict]: 图片记录列表
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM image_index WHERE doc_hash = ? ORDER BY page_num, created_at",
                (doc_hash,)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def compute_image_hash(self, file_path: str) -> str:
        """计算图片文件的哈希值（用于生成稳定的 image_id）。

        Args:
            file_path: 图片文件路径

        Returns:
            str: SHA256 哈希值（十六进制字符串）
        """
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
