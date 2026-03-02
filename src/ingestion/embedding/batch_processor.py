"""批处理优化。

该模块负责将大量 Chunk 分批处理，驱动 DenseEncoder 和 SparseEncoder 进行向量化编码，
并记录每个批次的处理耗时，为 Trace 系统提供性能数据。
"""

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional, Callable

from src.core.types import Chunk, ChunkRecord
from src.core.settings import Settings

if TYPE_CHECKING:
    from src.core.trace.trace_context import TraceContext
    from src.ingestion.embedding.dense_encoder import DenseEncoder
    from src.ingestion.embedding.sparse_encoder import SparseEncoder


@dataclass
class BatchResult:
    """单批次编码结果。

    Attributes:
        batch_index: 批次序号（从0开始）
        chunks: 当前批次的原始 Chunk 列表
        records: 当前批次编码后的 ChunkRecord 列表
        duration_ms: 批次处理耗时（毫秒）
    """
    batch_index: int
    chunks: List[Chunk]
    records: List[ChunkRecord]
    duration_ms: float


@dataclass
class BatchProcessingResult:
    """完整批处理结果。

    Attributes:
        total_chunks: 输入的 Chunk 总数
        batch_count: 生成的批次数
        results: 各批次的处理结果
        total_duration_ms: 总处理耗时（毫秒）
    """
    total_chunks: int
    batch_count: int
    results: List[BatchResult] = field(default_factory=list)
    total_duration_ms: float = 0.0


class BatchProcessor:
    """批处理器。

    将 Chunk 列表分批处理，驱动 DenseEncoder 和 SparseEncoder 进行向量化编码，
    并记录每个批次的处理耗时。

    Attributes:
        settings: 全局配置对象
        dense_encoder: 稠密向量编码器
        sparse_encoder: 稀疏向量编码器
        batch_size: 每批次处理的 Chunk 数量

    Example:
        >>> processor = BatchProcessor(settings, batch_size=2)
        >>> chunks = [
        ...     Chunk(id="1", text="Hello world", metadata={}),
        ...     Chunk(id="2", text="Foo bar", metadata={}),
        ...     Chunk(id="3", text="Test data", metadata={}),
        ... ]
        >>> result = processor.process_batches(chunks)
        >>> result.batch_count  # 5 chunks with batch_size=2 = 3 batches
        3
    """

    def __init__(
        self,
        settings: Settings,
        dense_encoder: Optional["DenseEncoder"] = None,
        sparse_encoder: Optional["SparseEncoder"] = None,
        batch_size: int = 32,
    ) -> None:
        """初始化 BatchProcessor。

        Args:
            settings: 全局配置对象
            dense_encoder: 稠密向量编码器（可选，用于测试注入）
            sparse_encoder: 稀疏向量编码器（可选，用于测试注入）
            batch_size: 每批次处理的 Chunk 数量（默认 32）
        """
        from src.ingestion.embedding.dense_encoder import DenseEncoder
        from src.ingestion.embedding.sparse_encoder import SparseEncoder

        self._settings = settings
        self._batch_size = batch_size
        self._dense_encoder = dense_encoder
        self._sparse_encoder = sparse_encoder

        self._dense_encoder_initialized: bool = False
        self._sparse_encoder_initialized: bool = False

    @property
    def dense_encoder(self) -> "DenseEncoder":
        """获取稠密向量编码器（延迟初始化）。"""
        if self._dense_encoder is None:
            from src.ingestion.embedding.dense_encoder import DenseEncoder
            self._dense_encoder = DenseEncoder(self._settings)
        return self._dense_encoder

    @property
    def sparse_encoder(self) -> "SparseEncoder":
        """获取稀疏向量编码器（延迟初始化）。"""
        if self._sparse_encoder is None:
            from src.ingestion.embedding.sparse_encoder import SparseEncoder
            self._sparse_encoder = SparseEncoder()
        return self._sparse_encoder

    @property
    def batch_size(self) -> int:
        """获取批次大小。"""
        return self._batch_size

    def _create_batches(self, chunks: List[Chunk]) -> List[List[Chunk]]:
        """将 Chunk 列表分割成批次。

        Args:
            chunks: 待分批的 Chunk 列表

        Returns:
            批次列表，每个批次是一个 Chunk 列表
        """
        if not chunks:
            return []

        batches: List[List[Chunk]] = []
        for i in range(0, len(chunks), self._batch_size):
            batches.append(chunks[i:i + self._batch_size])

        return batches

    def _process_single_batch(
        self,
        batch: List[Chunk],
        batch_index: int,
        trace: Optional["TraceContext"] = None,
    ) -> BatchResult:
        """处理单个批次。

        Args:
            batch: 当前批次的 Chunk 列表
            batch_index: 批次序号
            trace: 可选的跟踪上下文

        Returns:
            批次处理结果
        """
        start_time = time.perf_counter()

        dense_records = self.dense_encoder.encode(batch, trace=trace)
        sparse_records = self.sparse_encoder.encode(batch, trace=trace)

        records: List[ChunkRecord] = []
        for i, chunk in enumerate(batch):
            record = dense_records[i]
            if sparse_records[i].sparse_vector:
                record.sparse_vector = sparse_records[i].sparse_vector
            records.append(record)

        duration_ms = (time.perf_counter() - start_time) * 1000

        return BatchResult(
            batch_index=batch_index,
            chunks=batch,
            records=records,
            duration_ms=duration_ms,
        )

    def process_batches(
        self,
        chunks: List[Chunk],
        trace: Optional["TraceContext"] = None,
    ) -> BatchProcessingResult:
        """将 Chunk 列表分批处理并编码。

        Args:
            chunks: 待处理的 Chunk 列表
            trace: 可选的跟踪上下文

        Returns:
            包含所有批次处理结果的 BatchProcessingResult

        Raises:
            ValueError: chunks 列表为空
        """
        if not chunks:
            raise ValueError("Chunks list cannot be empty")

        batches = self._create_batches(chunks)
        results: List[BatchResult] = []
        total_start_time = time.perf_counter()

        for batch_index, batch in enumerate(batches):
            batch_result = self._process_single_batch(batch, batch_index, trace=trace)
            results.append(batch_result)

        total_duration_ms = (time.perf_counter() - total_start_time) * 1000

        return BatchProcessingResult(
            total_chunks=len(chunks),
            batch_count=len(batches),
            results=results,
            total_duration_ms=total_duration_ms,
        )

    def process_batches_with_callback(
        self,
        chunks: List[Chunk],
        on_batch_complete: Callable[[BatchResult], None],
        trace: Optional["TraceContext"] = None,
    ) -> BatchProcessingResult:
        """带回调的批次处理。

        每次批次完成后调用回调函数，适用于需要实时处理进度的场景。

        Args:
            chunks: 待处理的 Chunk 列表
            on_batch_complete: 批次完成回调函数，接收 BatchResult 参数
            trace: 可选的跟踪上下文

        Returns:
            包含所有批次处理结果的 BatchProcessingResult

        Raises:
            ValueError: chunks 列表为空
        """
        if not chunks:
            raise ValueError("Chunks list cannot be empty")

        batches = self._create_batches(chunks)
        results: List[BatchResult] = []
        total_start_time = time.perf_counter()

        for batch_index, batch in enumerate(batches):
            batch_result = self._process_single_batch(batch, batch_index, trace=trace)
            results.append(batch_result)
            on_batch_complete(batch_result)

        total_duration_ms = (time.perf_counter() - total_start_time) * 1000

        return BatchProcessingResult(
            total_chunks=len(chunks),
            batch_count=len(batches),
            results=results,
            total_duration_ms=total_duration_ms,
        )
