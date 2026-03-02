"""SparseEncoder 单元测试。"""

import pytest
from src.core.types import Chunk
from src.ingestion.embedding.sparse_encoder import SparseEncoder


class TestSparseEncoderTokenization:
    """分词测试。"""

    def test_tokenize_basic(self):
        """测试基本分词。"""
        encoder = SparseEncoder()
        tokens = encoder._tokenize("Hello world")
        assert "hello" in tokens
        assert "world" in tokens

    def test_tokenize_lowercase(self):
        """测试小写化。"""
        encoder = SparseEncoder()
        tokens = encoder._tokenize("HELLO World")
        assert "hello" in tokens
        assert "world" in tokens

    def test_tokenize_removes_punctuation(self):
        """测试去除标点。"""
        encoder = SparseEncoder()
        tokens = encoder._tokenize("Hello, world! How are you?")
        assert "," not in tokens
        assert "!" not in tokens
        assert "?" not in tokens

    def test_tokenize_filters_stop_words(self):
        """测试过滤停用词。"""
        encoder = SparseEncoder()
        tokens = encoder._tokenize("the hello world")
        assert "the" not in tokens
        assert "hello" in tokens
        assert "world" in tokens

    def test_tokenize_empty_string(self):
        """测试空字符串。"""
        encoder = SparseEncoder()
        tokens = encoder._tokenize("")
        assert tokens == []

    def test_tokenize_min_length_filter(self):
        """测试最小词项长度过滤。"""
        encoder = SparseEncoder(min_term_length=3)
        tokens = encoder._tokenize("a be hello world")
        assert "a" not in tokens
        assert "be" not in tokens
        assert "hello" in tokens
        assert "world" in tokens


class TestSparseEncoderTermFrequency:
    """词频计算测试。"""

    def test_compute_term_frequencies_single_term(self):
        """测试单次出现词项。"""
        encoder = SparseEncoder()
        tf = encoder._compute_term_frequencies("hello world")
        assert tf.get("hello") == 1
        assert tf.get("world") == 1

    def test_compute_term_frequencies_multiple_terms(self):
        """测试多次出现词项。"""
        encoder = SparseEncoder()
        tf = encoder._compute_term_frequencies("hello hello world")
        assert tf.get("hello") == 2
        assert tf.get("world") == 1

    def test_compute_term_frequencies_empty_text(self):
        """测试空文本。"""
        encoder = SparseEncoder()
        tf = encoder._compute_term_frequencies("")
        assert tf == {}

    def test_compute_term_frequencies_whitespace_only(self):
        """测试仅空白字符。"""
        encoder = SparseEncoder()
        tf = encoder._compute_term_frequencies("   \t\n   ")
        assert tf == {}


class TestSparseEncoderEncode:
    """encode 方法测试。"""

    def test_encode_single_chunk(self):
        """测试单 chunk 编码。"""
        encoder = SparseEncoder()
        chunks = [Chunk(id="chunk_001", text="hello world", metadata={})]
        records = encoder.encode(chunks)

        assert len(records) == 1
        assert records[0].id == "chunk_001"
        assert records[0].sparse_vector is not None
        assert "hello" in records[0].sparse_vector
        assert "world" in records[0].sparse_vector

    def test_encode_multiple_chunks(self):
        """测试多 chunk 编码。"""
        encoder = SparseEncoder()
        chunks = [
            Chunk(id="chunk_001", text="hello world", metadata={}),
            Chunk(id="chunk_002", text="foo bar", metadata={}),
        ]
        records = encoder.encode(chunks)

        assert len(records) == 2
        assert records[0].id == "chunk_001"
        assert records[1].id == "chunk_002"

    def test_encode_preserves_chunk_metadata(self):
        """测试保留 chunk 元数据。"""
        encoder = SparseEncoder()
        metadata = {"source_path": "/test/doc.pdf", "chunk_index": 0}
        chunks = [Chunk(id="chunk_001", text="hello world", metadata=metadata)]
        records = encoder.encode(chunks)

        assert records[0].metadata["source_path"] == "/test/doc.pdf"
        assert records[0].metadata["chunk_index"] == 0

    def test_encode_adds_term_stats(self):
        """测试添加词项统计。"""
        encoder = SparseEncoder()
        chunks = [Chunk(id="chunk_001", text="hello world hello", metadata={})]
        records = encoder.encode(chunks)

        assert records[0].metadata["term_count"] == 3
        assert records[0].metadata["unique_terms"] == 2

    def test_encode_empty_text_chunk(self):
        """测试空文本 chunk。"""
        encoder = SparseEncoder()
        chunks = [
            Chunk(id="chunk_001", text="hello world", metadata={}),
            Chunk(id="chunk_002", text="", metadata={}),
        ]
        records = encoder.encode(chunks)

        assert len(records) == 2
        assert records[1].sparse_vector is None

    def test_encode_duplicate_terms_in_chunk(self):
        """测试 chunk 内重复词项。"""
        encoder = SparseEncoder()
        chunks = [Chunk(id="chunk_001", text="test test test test", metadata={})]
        records = encoder.encode(chunks)

        assert records[0].sparse_vector.get("test") == 4.0

    def test_encode_empty_chunks_raises_error(self):
        """测试空列表抛出错误。"""
        encoder = SparseEncoder()
        with pytest.raises(ValueError, match="Chunks list cannot be empty"):
            encoder.encode([])


class TestSparseEncoderDocumentFrequency:
    """文档频率测试。"""

    def test_get_document_frequency(self):
        """测试文档频率统计。"""
        encoder = SparseEncoder()
        chunks = [
            Chunk(id="chunk_001", text="hello world", metadata={}),
            Chunk(id="chunk_002", text="hello foo", metadata={}),
            Chunk(id="chunk_003", text="world bar", metadata={}),
        ]
        encoder.encode(chunks)

        df = encoder.get_document_frequency()
        assert df.get("hello") == 2
        assert df.get("world") == 2
        assert df.get("foo") == 1
        assert df.get("bar") == 1

    def test_get_total_documents(self):
        """测试文档总数。"""
        encoder = SparseEncoder()
        chunks = [
            Chunk(id="chunk_001", text="hello world", metadata={}),
            Chunk(id="chunk_002", text="hello foo", metadata={}),
        ]
        encoder.encode(chunks)

        assert encoder.get_total_documents() == 4

    def test_document_frequency_empty_corpus(self):
        """测试空语料库。"""
        encoder = SparseEncoder()
        df = encoder.get_document_frequency()
        assert df == {}


class TestSparseEncoderCustomStopWords:
    """自定义停用词测试。"""

    def test_custom_stop_words(self):
        """测试自定义停用词。"""
        custom_stops = {"hello", "world"}
        encoder = SparseEncoder(stop_words=custom_stops)
        tokens = encoder._tokenize("hello world foo bar")

        assert "hello" not in tokens
        assert "world" not in tokens
        assert "foo" in tokens
        assert "bar" in tokens

    def test_empty_stop_words(self):
        """测试空停用词集合。"""
        encoder = SparseEncoder(stop_words=set())
        tokens = encoder._tokenize("the hello world")

        assert "the" in tokens
        assert "hello" in tokens
        assert "world" in tokens
