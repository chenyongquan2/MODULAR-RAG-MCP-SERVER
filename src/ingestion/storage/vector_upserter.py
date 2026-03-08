"""向量库 Upsert。

该模块负责将编码后的 ChunkRecord 列表写入向量数据库，
支持幂等性保证，确保同一内容重复写入不产生重复记录。
"""

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Any

from src.core.types import ChunkRecord
from src.core.settings import Settings
from src.libs.vector_store.base_vector_store import BaseVectorStore
from src.libs.vector_store.vector_store_factory import VectorStoreFactory

if TYPE_CHECKING:
    from src.core.trace.trace_context import TraceContext


class VectorUpserter:
    """向量存储 Upserter。

    负责将编码后的 ChunkRecord 列表批量写入向量数据库。
    支持幂等性：同一内容重复写入会产生相同的记录 ID。

    Attributes:
        vector_store: 向量存储后端实例

    Example:
        >>> from src.core.types import ChunkRecord
        >>> from src.core.settings import Settings
        >>> settings = Settings()
        >>> upsert = VectorUpserter(settings)
        >>> records = [
        ...     ChunkRecord(
        ...         id="chunk_001",
        ...         text="Hello world",
        ...         metadata={"source": "test.pdf"},
        ...         dense_vector=[0.1, 0.2, 0.3]
        ...     )
        ... ]
        >>> upsert.upsert(records)
    """

    def __init__(
        self,
        settings: Settings,
        vector_store: Optional[BaseVectorStore] = None,
    ) -> None:
        """初始化 VectorUpserter。

        Args:
            settings: 全局配置对象
            vector_store: 可选的向量存储后端（用于测试注入）
        """
        self._settings = settings
        self._vector_store = vector_store

    @property
    def vector_store(self) -> BaseVectorStore:
        """获取向量存储后端实例（延迟初始化）。"""
        if self._vector_store is None:
            self._vector_store = VectorStoreFactory.create(self._settings)
        return self._vector_store

    def upsert(
        self,
        records: List[ChunkRecord],
        trace: Optional["TraceContext"] = None,
    ) -> None:
        """将 ChunkRecord 列表写入向量数据库。

        将编码后的 ChunkRecord 转换为向量存储所需的格式，
        并调用向量存储后端进行写入。支持幂等写入。

        Args:
            records: 待写入的 ChunkRecord 列表
            trace: 可选的跟踪上下文

        Raises:
            ValueError: records 列表为空
            RuntimeError: 向量存储写入失败
        """
        if not records:
            raise ValueError("Records list cannot be empty")

        store_records = []
        for record in records:
            stable_id = self._generate_stable_id(record)
            metadata = record.metadata.copy()
            metadata.pop("sparse_vector", None)
            if "tags" in metadata and (not metadata["tags"] or metadata["tags"] == []):
                metadata.pop("tags", None)
            store_record = {
                "id": stable_id,
                "vector": record.dense_vector,
                "text": record.text,
                "metadata": metadata,
            }
            store_records.append(store_record)

        self.vector_store.upsert(store_records, trace=trace)

    def _generate_stable_id(self, record: ChunkRecord) -> str:
        """生成稳定的记录 ID。

        基于源路径、chunk 索引和内容哈希生成确定性 ID，
        确保同一内容始终产生相同的 ID。

        Args:
            record: ChunkRecord 实例

        Returns:
            稳定的记录 ID
        """
        source_path = record.metadata.get("source_path", "")
        chunk_index = record.metadata.get("chunk_index", 0)
        content_hash = hashlib.md5(record.text.encode()).hexdigest()[:8]

        stable_id = f"{source_path}_{chunk_index}_{content_hash}"
        return stable_id
