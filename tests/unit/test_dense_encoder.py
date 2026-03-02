"""DenseEncoder 单元测试。"""

import pytest
from unittest.mock import Mock, MagicMock
from typing import List

from src.core.types import Chunk, ChunkRecord
from src.core.settings import Settings, EmbeddingSettings
from src.ingestion.embedding.dense_encoder import DenseEncoder


@pytest.fixture
def mock_settings() -> Settings:
    """创建测试用 Settings。"""
    settings = Mock(spec=Settings)
    settings.embedding = EmbeddingSettings(provider="openai", model="text-embedding-3-small")
    return settings


@pytest.fixture
def mock_embedding_client():
    """创建 Mock 嵌入客户端。"""
    client = Mock()
    client.get_model_name.return_value = "text-embedding-3-small"
    client.get_dimension.return_value = 1536
    client.embed.return_value = [
        [0.1, 0.2, 0.3] * 512,
        [0.4, 0.5, 0.6] * 512,
        [0.7, 0.8, 0.9] * 512,
    ]
    return client


@pytest.fixture
def sample_chunks() -> List[Chunk]:
    """创建测试用 Chunk 列表。"""
    return [
        Chunk(
            id="doc1_0000_abc123",
            text="This is the first chunk of text.",
            metadata={"source_path": "/test/doc.pdf", "chunk_index": 0},
            start_offset=0,
            end_offset=100,
            source_ref="doc1",
        ),
        Chunk(
            id="doc1_0001_def456",
            text="This is the second chunk of text.",
            metadata={"source_path": "/test/doc.pdf", "chunk_index": 1},
            start_offset=100,
            end_offset=200,
            source_ref="doc1",
        ),
        Chunk(
            id="doc1_0002_ghi789",
            text="This is the third chunk of text.",
            metadata={"source_path": "/test/doc.pdf", "chunk_index": 2},
            start_offset=200,
            end_offset=300,
            source_ref="doc1",
        ),
    ]


class TestDenseEncoderInit:
    """测试 DenseEncoder 初始化。"""

    def test_init_with_embedding_client(self, mock_settings, mock_embedding_client):
        """测试使用注入的嵌入客户端初始化。"""
        encoder = DenseEncoder(mock_settings, embedding_client=mock_embedding_client)
        assert encoder.embedding_client is mock_embedding_client

    def test_init_lazy_loading(self, mock_settings):
        """测试延迟加载嵌入客户端。"""
        encoder = DenseEncoder(mock_settings)
        assert encoder._embedding_client is None

    def test_dimension_property(self, mock_settings, mock_embedding_client):
        """测试 dimension 属性缓存。"""
        encoder = DenseEncoder(mock_settings, embedding_client=mock_embedding_client)
        dim = encoder.dimension
        assert dim == 1536
        mock_embedding_client.get_dimension.assert_called_once()


class TestDenseEncoderEncode:
    """测试 DenseEncoder.encode 方法。"""

    def test_encode_returns_correct_count(
        self, mock_settings, mock_embedding_client, sample_chunks
    ):
        """测试返回的记录数量与输入 chunks 一致。"""
        encoder = DenseEncoder(mock_settings, embedding_client=mock_embedding_client)
        records = encoder.encode(sample_chunks)
        assert len(records) == len(sample_chunks)

    def test_encode_preserves_chunk_id(
        self, mock_settings, mock_embedding_client, sample_chunks
    ):
        """测试保留原始 Chunk ID。"""
        encoder = DenseEncoder(mock_settings, embedding_client=mock_embedding_client)
        records = encoder.encode(sample_chunks)
        for i, chunk in enumerate(sample_chunks):
            assert records[i].id == chunk.id

    def test_encode_preserves_text(
        self, mock_settings, mock_embedding_client, sample_chunks
    ):
        """测试保留原始文本内容。"""
        encoder = DenseEncoder(mock_settings, embedding_client=mock_embedding_client)
        records = encoder.encode(sample_chunks)
        for i, chunk in enumerate(sample_chunks):
            assert records[i].text == chunk.text

    def test_encode_adds_dense_vector(
        self, mock_settings, mock_embedding_client, sample_chunks
    ):
        """测试添加稠密向量。"""
        encoder = DenseEncoder(mock_settings, embedding_client=mock_embedding_client)
        records = encoder.encode(sample_chunks)
        for record in records:
            assert record.dense_vector is not None
            assert isinstance(record.dense_vector, list)
            assert len(record.dense_vector) == 1536

    def test_encode_inherits_metadata(
        self, mock_settings, mock_embedding_client, sample_chunks
    ):
        """测试继承 Chunk 元数据。"""
        encoder = DenseEncoder(mock_settings, embedding_client=mock_embedding_client)
        records = encoder.encode(sample_chunks)
        for i, chunk in enumerate(sample_chunks):
            assert records[i].metadata["source_path"] == chunk.metadata["source_path"]
            assert records[i].metadata["chunk_index"] == chunk.metadata["chunk_index"]

    def test_encode_adds_offset_metadata(
        self, mock_settings, mock_embedding_client, sample_chunks
    ):
        """测试添加偏移量元数据。"""
        encoder = DenseEncoder(mock_settings, embedding_client=mock_embedding_client)
        records = encoder.encode(sample_chunks)
        for i, chunk in enumerate(sample_chunks):
            assert records[i].metadata.get("start_offset") == chunk.start_offset
            assert records[i].metadata.get("end_offset") == chunk.end_offset

    def test_encode_adds_source_ref(
        self, mock_settings, mock_embedding_client, sample_chunks
    ):
        """测试添加 source_ref 元数据。"""
        encoder = DenseEncoder(mock_settings, embedding_client=mock_embedding_client)
        records = encoder.encode(sample_chunks)
        for i, chunk in enumerate(sample_chunks):
            assert records[i].metadata.get("source_ref") == chunk.source_ref

    def test_encode_calls_embedding_client(
        self, mock_settings, mock_embedding_client, sample_chunks
    ):
        """测试调用嵌入客户端。"""
        encoder = DenseEncoder(mock_settings, embedding_client=mock_embedding_client)
        encoder.encode(sample_chunks)
        mock_embedding_client.embed.assert_called_once()

    def test_encode_empty_chunks_raises_error(self, mock_settings, mock_embedding_client):
        """测试空列表抛出异常。"""
        encoder = DenseEncoder(mock_settings, embedding_client=mock_embedding_client)
        with pytest.raises(ValueError, match="Chunks list cannot be empty"):
            encoder.encode([])

    def test_encode_vector_count_mismatch(
        self, mock_settings, sample_chunks
    ):
        """测试向量数量不匹配时抛出异常。"""
        mock_client = Mock()
        mock_client.get_dimension.return_value = 1536
        mock_client.embed.return_value = [[0.1] * 512]
        encoder = DenseEncoder(mock_settings, embedding_client=mock_client)
        with pytest.raises(RuntimeError, match="Vector count mismatch"):
            encoder.encode(sample_chunks)

    def test_encode_order_preserved(
        self, mock_settings, mock_embedding_client, sample_chunks
    ):
        """测试输出顺序与输入一致。"""
        encoder = DenseEncoder(mock_settings, embedding_client=mock_embedding_client)
        records = encoder.encode(sample_chunks)
        for i, chunk in enumerate(sample_chunks):
            assert records[i].id == chunk.id


class TestDenseEncoderEdgeCases:
    """测试边界情况。"""

    def test_encode_single_chunk(self, mock_settings):
        """测试单个 Chunk。"""
        mock_client = Mock()
        mock_client.get_dimension.return_value = 768
        mock_client.embed.return_value = [[0.1] * 768]
        encoder = DenseEncoder(mock_settings, embedding_client=mock_client)

        chunks = [Chunk(id="test_0000", text="Single chunk", metadata={})]
        records = encoder.encode(chunks)

        assert len(records) == 1
        assert records[0].id == "test_0000"
        assert records[0].dense_vector == [0.1] * 768

    def test_encode_with_empty_metadata(self, mock_settings):
        """测试元数据为空的情况。"""
        mock_client = Mock()
        mock_client.get_dimension.return_value = 384
        mock_client.embed.return_value = [[0.5] * 384]
        encoder = DenseEncoder(mock_settings, embedding_client=mock_client)

        chunks = [Chunk(id="test", text="Test text", metadata={})]
        records = encoder.encode(chunks)

        assert records[0].metadata == {}

    def test_encode_with_special_characters(self, mock_settings):
        """测试包含特殊字符的文本。"""
        mock_client = Mock()
        mock_client.get_dimension.return_value = 1536
        mock_client.embed.return_value = [[0.1] * 1536]
        encoder = DenseEncoder(mock_settings, embedding_client=mock_client)

        chunks = [Chunk(id="test", text="Hello 世界! 🌍\n\t", metadata={})]
        records = encoder.encode(chunks)

        assert len(records) == 1
        assert records[0].text == "Hello 世界! 🌍\n\t"
