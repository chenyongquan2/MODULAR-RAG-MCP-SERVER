"""Dense Encoder - 将文本块编码为稠密向量。

该模块负责将 Chunk 列表转换为带有稠密向量的 ChunkRecord 列表，
为向量存储和检索提供支持。
"""

from typing import TYPE_CHECKING, List, Optional, Any

from src.core.types import Chunk, ChunkRecord
from src.core.settings import Settings
from src.libs.embedding.base_embedding import BaseEmbedding
from src.libs.embedding.embedding_factory import EmbeddingFactory

if TYPE_CHECKING:
    from src.core.trace.trace_context import TraceContext


class DenseEncoder:
    """稠密向量编码器。

    将 Chunk 列表批量编码为带有稠密向量的 ChunkRecord 列表。
    依赖 EmbeddingFactory 创建的嵌入客户端完成实际的向量编码。

    Attributes:
        embedding_client: 嵌入客户端实例
        dimension: 向量维度

    Example:
        >>> encoder = DenseEncoder(settings)
        >>> chunks = [Chunk(id="1", text="Hello world", metadata={})]
        >>> records = encoder.encode(chunks)
        >>> len(records) == 1
        True
        >>> records[0].dense_vector is not None
        True
    """

    def __init__(
        self,
        settings: Settings,
        embedding_client: Optional[BaseEmbedding] = None,
    ) -> None:
        """初始化 DenseEncoder。

        Args:
            settings: 全局配置对象
            embedding_client: 可选的嵌入客户端（用于测试注入）
        """
        self._settings = settings
        self._embedding_client = embedding_client
        self._dimension: Optional[int] = None

    @property
    def embedding_client(self) -> BaseEmbedding:
        """获取嵌入客户端实例（延迟初始化）。"""
        if self._embedding_client is None:
            self._embedding_client = EmbeddingFactory.create(self._settings)
        return self._embedding_client

    @property
    def dimension(self) -> int:
        """获取向量维度。"""
        if self._dimension is None:
            self._dimension = self.embedding_client.get_dimension()
        return self._dimension

    def encode(
        self,
        chunks: List[Chunk],
        trace: Optional["TraceContext"] = None,
    ) -> List[ChunkRecord]:
        """将 Chunk 列表编码为带有稠密向量的 ChunkRecord 列表。

        Args:
            chunks: 待编码的 Chunk 列表
            trace: 可选的跟踪上下文

        Returns:
            带有稠密向量的 ChunkRecord 列表，数量和顺序与输入 chunks 一致

        Raises:
            ValueError: chunks 列表为空
            RuntimeError: 嵌入服务调用失败
        """
        if not chunks:
            raise ValueError("Chunks list cannot be empty")

        texts = [chunk.text for chunk in chunks]

        vectors = self.embedding_client.embed(texts, trace=trace)

        if len(vectors) != len(chunks):
            raise RuntimeError(
                f"Vector count mismatch: expected {len(chunks)}, got {len(vectors)}"
            )

        records = []
        for i, chunk in enumerate(chunks):
            record = ChunkRecord(
                id=chunk.id,
                text=chunk.text,
                metadata=chunk.metadata.copy(),
                dense_vector=vectors[i],
            )
            if chunk.start_offset is not None:
                record.metadata["start_offset"] = chunk.start_offset
            if chunk.end_offset is not None:
                record.metadata["end_offset"] = chunk.end_offset
            if chunk.source_ref is not None:
                record.metadata["source_ref"] = chunk.source_ref

            records.append(record)

        return records
