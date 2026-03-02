"""BatchProcessor 单元测试。"""

import pytest
from unittest.mock import Mock, MagicMock
from typing import List

from src.core.types import Chunk, ChunkRecord
from src.core.settings import Settings, EmbeddingSettings
from src.ingestion.embedding.batch_processor import BatchProcessor, BatchResult, BatchProcessingResult


@pytest.fixture
def mock_settings() -> Settings:
    """创建测试用 Settings。"""
    settings = Mock(spec=Settings)
    settings.embedding = EmbeddingSettings(provider="openai", model="text-embedding-3-small")
    return settings


@pytest.fixture
def mock_dense_encoder():
    """创建 Mock 稠密编码器。"""
    encoder = Mock()
    encoder.encode.return_value = [
        ChunkRecord(
            id="chunk_0",
            text="Text 0",
            metadata={},
            dense_vector=[0.1, 0.2, 0.3],
        ),
        ChunkRecord(
            id="chunk_1",
            text="Text 1",
            metadata={},
            dense_vector=[0.4, 0.5, 0.6],
        ),
    ]
    return encoder


@pytest.fixture
def mock_sparse_encoder():
    """创建 Mock 稀疏编码器。"""
    encoder = Mock()
    encoder.encode.return_value = [
        ChunkRecord(
            id="chunk_0",
            text="Text 0",
            metadata={},
            sparse_vector={"word": 1.0},
        ),
        ChunkRecord(
            id="chunk_1",
            text="Text 1",
            metadata={},
            sparse_vector={"term": 2.0},
        ),
    ]
    return encoder


@pytest.fixture
def sample_chunks() -> List[Chunk]:
    """创建测试用 Chunk 列表（5个）。"""
    return [
        Chunk(
            id=f"chunk_{i}",
            text=f"Text {i}",
            metadata={"chunk_index": i},
        )
        for i in range(5)
    ]


class TestBatchProcessorCreation:
    """BatchProcessor 创建测试。"""

    def test_default_batch_size(self, mock_settings):
        """测试默认批次大小。"""
        processor = BatchProcessor(mock_settings)
        assert processor.batch_size == 32

    def test_custom_batch_size(self, mock_settings):
        """测试自定义批次大小。"""
        processor = BatchProcessor(mock_settings, batch_size=10)
        assert processor.batch_size == 10

    def test_with_injected_encoders(self, mock_settings, mock_dense_encoder, mock_sparse_encoder):
        """测试注入编码器。"""
        processor = BatchProcessor(
            mock_settings,
            dense_encoder=mock_dense_encoder,
            sparse_encoder=mock_sparse_encoder,
            batch_size=2,
        )
        assert processor.batch_size == 2


class TestCreateBatches:
    """批次创建测试。"""

    def test_empty_chunks(self, mock_settings):
        """测试空列表。"""
        processor = BatchProcessor(mock_settings, batch_size=2)
        batches = processor._create_batches([])
        assert batches == []

    def test_single_chunk(self, mock_settings):
        """测试单个 Chunk。"""
        processor = BatchProcessor(mock_settings, batch_size=2)
        chunks = [Chunk(id="1", text="test", metadata={})]
        batches = processor._create_batches(chunks)
        assert len(batches) == 1
        assert len(batches[0]) == 1

    def test_batch_size_2_five_chunks(self, mock_settings):
        """测试 batch_size=2 时 5 个 chunks 分成 3 批。

        验收标准：batch_size=2 时对 5 chunks 分成 3 批，且顺序稳定。
        """
        processor = BatchProcessor(mock_settings, batch_size=2)
        chunks = [Chunk(id=f"chunk_{i}", text=f"Text {i}", metadata={}) for i in range(5)]
        batches = processor._create_batches(chunks)

        assert len(batches) == 3
        assert len(batches[0]) == 2
        assert len(batches[1]) == 2
        assert len(batches[2]) == 1

        assert batches[0][0].id == "chunk_0"
        assert batches[0][1].id == "chunk_1"
        assert batches[1][0].id == "chunk_2"
        assert batches[1][1].id == "chunk_3"
        assert batches[2][0].id == "chunk_4"

    def test_batch_size_3_five_chunks(self, mock_settings):
        """测试 batch_size=3 时 5 个 chunks 分成 2 批。"""
        processor = BatchProcessor(mock_settings, batch_size=3)
        chunks = [Chunk(id=f"chunk_{i}", text=f"Text {i}", metadata={}) for i in range(5)]
        batches = processor._create_batches(chunks)

        assert len(batches) == 2
        assert len(batches[0]) == 3
        assert len(batches[1]) == 2

    def test_exact_batch_size(self, mock_settings):
        """测试恰好整除的批次。"""
        processor = BatchProcessor(mock_settings, batch_size=2)
        chunks = [Chunk(id=f"chunk_{i}", text=f"Text {i}", metadata={}) for i in range(4)]
        batches = processor._create_batches(chunks)

        assert len(batches) == 2
        assert len(batches[0]) == 2
        assert len(batches[1]) == 2

    def test_order_stability(self, mock_settings):
        """测试顺序稳定性：多次调用返回相同批次顺序。"""
        processor = BatchProcessor(mock_settings, batch_size=2)
        chunks = [Chunk(id=f"chunk_{i}", text=f"Text {i}", metadata={}) for i in range(5)]

        batches1 = processor._create_batches(chunks)
        batches2 = processor._create_batches(chunks)

        assert len(batches1) == len(batches2)
        for b1, b2 in zip(batches1, batches2):
            assert [c.id for c in b1] == [c.id for c in b2]


class TestProcessBatches:
    """批次处理测试。"""

    def test_empty_chunks_raises_error(self, mock_settings):
        """测试空列表抛出异常。"""
        processor = BatchProcessor(mock_settings, batch_size=2)
        with pytest.raises(ValueError, match="Chunks list cannot be empty"):
            processor.process_batches([])

    def test_process_batches_returns_correct_count(
        self,
        mock_settings,
        mock_dense_encoder,
        mock_sparse_encoder,
    ):
        """测试处理返回正确的批次和 Chunk 数量。"""
        processor = BatchProcessor(
            mock_settings,
            dense_encoder=mock_dense_encoder,
            sparse_encoder=mock_sparse_encoder,
            batch_size=2,
        )

        chunks = [
            Chunk(id="chunk_0", text="Text 0", metadata={}),
            Chunk(id="chunk_1", text="Text 1", metadata={}),
            Chunk(id="chunk_2", text="Text 2", metadata={}),
        ]

        result = processor.process_batches(chunks)

        assert result.total_chunks == 3
        assert result.batch_count == 2

    def test_process_batches_with_5_chunks_2_batch_size(
        self,
        mock_settings,
        mock_dense_encoder,
        mock_sparse_encoder,
    ):
        """测试 batch_size=2 时 5 个 chunks 的处理。"""
        processor = BatchProcessor(
            mock_settings,
            dense_encoder=mock_dense_encoder,
            sparse_encoder=mock_sparse_encoder,
            batch_size=2,
        )

        chunks = [
            Chunk(id=f"chunk_{i}", text=f"Text {i}", metadata={"chunk_index": i})
            for i in range(5)
        ]

        result = processor.process_batches(chunks)

        assert result.total_chunks == 5
        assert result.batch_count == 3

    def test_process_batches_records_have_vectors(
        self,
        mock_settings,
        mock_dense_encoder,
        mock_sparse_encoder,
    ):
        """测试编码结果包含稠密和稀疏向量。"""
        processor = BatchProcessor(
            mock_settings,
            dense_encoder=mock_dense_encoder,
            sparse_encoder=mock_sparse_encoder,
            batch_size=2,
        )

        chunks = [
            Chunk(id="chunk_0", text="Text 0", metadata={}),
            Chunk(id="chunk_1", text="Text 1", metadata={}),
        ]

        result = processor.process_batches(chunks)

        all_records = [r for batch in result.results for r in batch.records]
        for record in all_records:
            assert record.dense_vector is not None
            assert record.sparse_vector is not None

    def test_process_batches_duration_recorded(
        self,
        mock_settings,
        mock_dense_encoder,
        mock_sparse_encoder,
    ):
        """测试批次耗时被记录。"""
        processor = BatchProcessor(
            mock_settings,
            dense_encoder=mock_dense_encoder,
            sparse_encoder=mock_sparse_encoder,
            batch_size=2,
        )

        chunks = [
            Chunk(id="chunk_0", text="Text 0", metadata={}),
            Chunk(id="chunk_1", text="Text 1", metadata={}),
        ]

        result = processor.process_batches(chunks)

        assert result.total_duration_ms > 0
        for batch_result in result.results:
            assert batch_result.duration_ms >= 0


class TestProcessBatchesWithCallback:
    """带回调的批次处理测试。"""

    def test_callback_called_per_batch(
        self,
        mock_settings,
        mock_dense_encoder,
        mock_sparse_encoder,
    ):
        """测试每个批次完成后回调被调用。"""
        processor = BatchProcessor(
            mock_settings,
            dense_encoder=mock_dense_encoder,
            sparse_encoder=mock_sparse_encoder,
            batch_size=2,
        )

        chunks = [
            Chunk(id=f"chunk_{i}", text=f"Text {i}", metadata={})
            for i in range(5)
        ]

        callback_results: List[BatchResult] = []

        def on_batch_complete(batch_result: BatchResult):
            callback_results.append(batch_result)

        result = processor.process_batches_with_callback(chunks, on_batch_complete)

        assert len(callback_results) == 3
        assert callback_results[0].batch_index == 0
        assert callback_results[1].batch_index == 1
        assert callback_results[2].batch_index == 2

    def test_callback_receives_correct_batch_data(
        self,
        mock_settings,
        mock_dense_encoder,
        mock_sparse_encoder,
    ):
        """测试回调接收正确的批次数据。"""
        processor = BatchProcessor(
            mock_settings,
            dense_encoder=mock_dense_encoder,
            sparse_encoder=mock_sparse_encoder,
            batch_size=2,
        )

        chunks = [
            Chunk(id="chunk_0", text="Text 0", metadata={}),
            Chunk(id="chunk_1", text="Text 1", metadata={}),
        ]

        callback_results: List[BatchResult] = []

        def on_batch_complete(batch_result: BatchResult):
            callback_results.append(batch_result)

        processor.process_batches_with_callback(chunks, on_batch_complete)

        assert len(callback_results) == 1
        assert callback_results[0].batch_index == 0
        assert len(callback_results[0].chunks) == 2
        assert len(callback_results[0].records) == 2


class TestBatchResult:
    """BatchResult 数据类测试。"""

    def test_batch_result_creation(self):
        """测试 BatchResult 创建。"""
        chunks = [Chunk(id="1", text="test", metadata={})]
        records = [ChunkRecord(id="1", text="test", metadata={}, dense_vector=[0.1])]

        result = BatchResult(
            batch_index=0,
            chunks=chunks,
            records=records,
            duration_ms=10.5,
        )

        assert result.batch_index == 0
        assert len(result.chunks) == 1
        assert len(result.records) == 1
        assert result.duration_ms == 10.5


class TestBatchProcessingResult:
    """BatchProcessingResult 数据类测试。"""

    def test_batch_processing_result_creation(self):
        """测试 BatchProcessingResult 创建。"""
        result = BatchProcessingResult(
            total_chunks=10,
            batch_count=3,
            total_duration_ms=100.0,
        )

        assert result.total_chunks == 10
        assert result.batch_count == 3
        assert result.total_duration_ms == 100.0
        assert result.results == []
