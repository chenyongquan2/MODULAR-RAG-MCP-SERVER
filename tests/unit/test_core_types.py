"""单元测试：核心数据类型 (Document/Chunk/ChunkRecord)。

测试核心数据类型的序列化、反序列化、字段验证等功能。
"""

import pytest
from src.core.types import (
    Document,
    Chunk,
    ChunkRecord,
    RetrievalResult,
    ProcessedQuery,
    ImageReference
)


class TestImageReference:
    """测试 ImageReference 类型。"""

    def test_basic_creation(self):
        """测试基本创建。"""
        img_ref = ImageReference(
            id="doc123_page1_img0",
            path="data/images/test_collection/doc123_page1_img0.png",
            text_offset=100,
            text_length=30
        )
        assert img_ref.id == "doc123_page1_img0"
        assert img_ref.path == "data/images/test_collection/doc123_page1_img0.png"
        assert img_ref.text_offset == 100
        assert img_ref.text_length == 30
        assert img_ref.page is None
        assert img_ref.position is None

    def test_full_creation_with_optional_fields(self):
        """测试包含可选字段的创建。"""
        img_ref = ImageReference(
            id="doc123_page2_img1",
            path="data/images/test_collection/doc123_page2_img1.png",
            text_offset=500,
            text_length=35,
            page=2,
            position={"x": 100, "y": 200, "width": 300, "height": 400}
        )
        assert img_ref.page == 2
        assert img_ref.position == {"x": 100, "y": 200, "width": 300, "height": 400}

    def test_serialization(self):
        """测试序列化 (过滤 None 值)。"""
        img_ref = ImageReference(
            id="doc123_page1_img0",
            path="data/images/test_collection/doc123_page1_img0.png",
            text_offset=100,
            text_length=30
        )
        data = img_ref.to_dict()
        assert "id" in data
        assert "path" in data
        assert "text_offset" in data
        assert "text_length" in data
        assert "page" not in data  # None 值应被过滤
        assert "position" not in data


class TestDocument:
    """测试 Document 类型。"""

    def test_basic_creation(self):
        """测试基本创建。"""
        doc = Document(
            id="doc123",
            text="Sample document text",
            metadata={"source_path": "/path/to/doc.pdf"}
        )
        assert doc.id == "doc123"
        assert doc.text == "Sample document text"
        assert doc.metadata["source_path"] == "/path/to/doc.pdf"

    def test_missing_source_path_raises_error(self):
        """测试缺少 source_path 抛出错误。"""
        with pytest.raises(ValueError, match="metadata must contain 'source_path'"):
            Document(
                id="doc123",
                text="Sample text",
                metadata={}
            )

    def test_with_images_metadata(self):
        """测试包含图片引用的 metadata。"""
        img_ref = ImageReference(
            id="doc123_page1_img0",
            path="data/images/collection/doc123_page1_img0.png",
            text_offset=100,
            text_length=30,
            page=1
        )
        doc = Document(
            id="doc123",
            text="Sample text [IMAGE: doc123_page1_img0] more text",
            metadata={
                "source_path": "/path/to/doc.pdf",
                "images": [img_ref]
            }
        )
        assert len(doc.metadata["images"]) == 1
        assert doc.metadata["images"][0].id == "doc123_page1_img0"

    def test_serialization(self):
        """测试序列化。"""
        img_ref = ImageReference(
            id="doc123_page1_img0",
            path="data/images/collection/doc123_page1_img0.png",
            text_offset=100,
            text_length=30
        )
        doc = Document(
            id="doc123",
            text="Sample text [IMAGE: doc123_page1_img0]",
            metadata={
                "source_path": "/path/to/doc.pdf",
                "collection": "test_collection",
                "title": "Test Document",
                "images": [img_ref]
            }
        )
        data = doc.to_dict()
        assert data["id"] == "doc123"
        assert data["text"] == "Sample text [IMAGE: doc123_page1_img0]"
        assert data["metadata"]["source_path"] == "/path/to/doc.pdf"
        assert data["metadata"]["collection"] == "test_collection"
        assert len(data["metadata"]["images"]) == 1
        assert isinstance(data["metadata"]["images"][0], dict)
        assert data["metadata"]["images"][0]["id"] == "doc123_page1_img0"

    def test_deserialization(self):
        """测试反序列化。"""
        data = {
            "id": "doc123",
            "text": "Sample text [IMAGE: doc123_page1_img0]",
            "metadata": {
                "source_path": "/path/to/doc.pdf",
                "images": [
                    {
                        "id": "doc123_page1_img0",
                        "path": "data/images/collection/doc123_page1_img0.png",
                        "text_offset": 100,
                        "text_length": 30,
                        "page": 1
                    }
                ]
            }
        }
        doc = Document.from_dict(data)
        assert doc.id == "doc123"
        assert len(doc.metadata["images"]) == 1
        assert isinstance(doc.metadata["images"][0], ImageReference)
        assert doc.metadata["images"][0].id == "doc123_page1_img0"

    def test_serialization_roundtrip(self):
        """测试序列化-反序列化往返。"""
        img_ref = ImageReference(
            id="doc123_page1_img0",
            path="data/images/collection/doc123_page1_img0.png",
            text_offset=100,
            text_length=30,
            page=1
        )
        doc_original = Document(
            id="doc123",
            text="Sample text [IMAGE: doc123_page1_img0]",
            metadata={
                "source_path": "/path/to/doc.pdf",
                "title": "Test Document",
                "images": [img_ref]
            }
        )
        data = doc_original.to_dict()
        doc_restored = Document.from_dict(data)
        assert doc_restored.id == doc_original.id
        assert doc_restored.text == doc_original.text
        assert doc_restored.metadata["source_path"] == doc_original.metadata["source_path"]
        assert len(doc_restored.metadata["images"]) == 1
        assert isinstance(doc_restored.metadata["images"][0], ImageReference)
        assert doc_restored.metadata["images"][0].id == img_ref.id


class TestChunk:
    """测试 Chunk 类型。"""

    def test_basic_creation(self):
        """测试基本创建。"""
        chunk = Chunk(
            id="doc123_0001_abc12345",
            text="Chunk text content",
            metadata={
                "source_path": "/path/to/doc.pdf",
                "chunk_index": 0
            },
            source_ref="doc123"
        )
        assert chunk.id == "doc123_0001_abc12345"
        assert chunk.text == "Chunk text content"
        assert chunk.metadata["chunk_index"] == 0
        assert chunk.source_ref == "doc123"

    def test_with_offset_info(self):
        """测试包含偏移量信息。"""
        chunk = Chunk(
            id="doc123_0001_abc12345",
            text="Chunk text",
            metadata={"source_path": "/path/to/doc.pdf", "chunk_index": 0},
            start_offset=0,
            end_offset=10,
            source_ref="doc123"
        )
        assert chunk.start_offset == 0
        assert chunk.end_offset == 10

    def test_serialization_filters_none(self):
        """测试序列化过滤 None 值。"""
        chunk = Chunk(
            id="doc123_0001_abc12345",
            text="Chunk text",
            metadata={"source_path": "/path/to/doc.pdf", "chunk_index": 0}
        )
        data = chunk.to_dict()
        assert "start_offset" not in data
        assert "end_offset" not in data
        assert "source_ref" not in data

    def test_deserialization(self):
        """测试反序列化。"""
        data = {
            "id": "doc123_0001_abc12345",
            "text": "Chunk text",
            "metadata": {
                "source_path": "/path/to/doc.pdf",
                "chunk_index": 0,
                "images": [
                    {
                        "id": "doc123_page1_img0",
                        "path": "data/images/collection/doc123_page1_img0.png",
                        "text_offset": 5,
                        "text_length": 30
                    }
                ]
            },
            "start_offset": 0,
            "end_offset": 10,
            "source_ref": "doc123"
        }
        chunk = Chunk.from_dict(data)
        assert chunk.id == "doc123_0001_abc12345"
        assert chunk.start_offset == 0
        assert chunk.end_offset == 10
        assert chunk.source_ref == "doc123"
        assert len(chunk.metadata["images"]) == 1
        assert isinstance(chunk.metadata["images"][0], ImageReference)


class TestChunkRecord:
    """测试 ChunkRecord 类型。"""

    def test_basic_creation(self):
        """测试基本创建。"""
        record = ChunkRecord(
            id="doc123_0001_abc12345",
            text="Chunk text",
            metadata={"source_path": "/path/to/doc.pdf", "chunk_index": 0}
        )
        assert record.id == "doc123_0001_abc12345"
        assert record.dense_vector is None
        assert record.sparse_vector is None

    def test_with_dense_vector(self):
        """测试包含稠密向量。"""
        record = ChunkRecord(
            id="doc123_0001_abc12345",
            text="Chunk text",
            metadata={"source_path": "/path/to/doc.pdf", "chunk_index": 0},
            dense_vector=[0.1, 0.2, 0.3]
        )
        assert record.dense_vector == [0.1, 0.2, 0.3]

    def test_with_sparse_vector(self):
        """测试包含稀疏向量。"""
        record = ChunkRecord(
            id="doc123_0001_abc12345",
            text="Chunk text",
            metadata={"source_path": "/path/to/doc.pdf", "chunk_index": 0},
            sparse_vector={"word1": 0.5, "word2": 0.3}
        )
        assert record.sparse_vector == {"word1": 0.5, "word2": 0.3}

    def test_from_chunk(self):
        """测试从 Chunk 创建 ChunkRecord。"""
        chunk = Chunk(
            id="doc123_0001_abc12345",
            text="Chunk text",
            metadata={"source_path": "/path/to/doc.pdf", "chunk_index": 0},
            source_ref="doc123"
        )
        record = ChunkRecord.from_chunk(chunk)
        assert record.id == chunk.id
        assert record.text == chunk.text
        assert record.metadata == chunk.metadata
        assert record.dense_vector is None
        assert record.sparse_vector is None

    def test_serialization(self):
        """测试序列化 (过滤 None 值)。"""
        record = ChunkRecord(
            id="doc123_0001_abc12345",
            text="Chunk text",
            metadata={"source_path": "/path/to/doc.pdf", "chunk_index": 0},
            dense_vector=[0.1, 0.2, 0.3]
        )
        data = record.to_dict()
        assert "dense_vector" in data
        assert "sparse_vector" not in data  # None 值应被过滤

    def test_deserialization(self):
        """测试反序列化。"""
        data = {
            "id": "doc123_0001_abc12345",
            "text": "Chunk text",
            "metadata": {"source_path": "/path/to/doc.pdf", "chunk_index": 0},
            "dense_vector": [0.1, 0.2, 0.3],
            "sparse_vector": {"word1": 0.5}
        }
        record = ChunkRecord.from_dict(data)
        assert record.id == "doc123_0001_abc12345"
        assert record.dense_vector == [0.1, 0.2, 0.3]
        assert record.sparse_vector == {"word1": 0.5}


class TestRetrievalResult:
    """测试 RetrievalResult 类型。"""

    def test_basic_creation(self):
        """测试基本创建。"""
        result = RetrievalResult(
            chunk_id="doc123_0001_abc12345",
            score=0.95,
            text="Chunk text",
            metadata={"source_path": "/path/to/doc.pdf", "chunk_index": 0}
        )
        assert result.chunk_id == "doc123_0001_abc12345"
        assert result.score == 0.95
        assert result.text == "Chunk text"

    def test_serialization(self):
        """测试序列化。"""
        result = RetrievalResult(
            chunk_id="doc123_0001_abc12345",
            score=0.95,
            text="Chunk text",
            metadata={
                "source_path": "/path/to/doc.pdf",
                "images": [
                    ImageReference(
                        id="doc123_page1_img0",
                        path="data/images/collection/doc123_page1_img0.png",
                        text_offset=5,
                        text_length=30
                    )
                ]
            }
        )
        data = result.to_dict()
        assert data["chunk_id"] == "doc123_0001_abc12345"
        assert isinstance(data["metadata"]["images"][0], dict)

    def test_deserialization(self):
        """测试反序列化。"""
        data = {
            "chunk_id": "doc123_0001_abc12345",
            "score": 0.95,
            "text": "Chunk text",
            "metadata": {
                "source_path": "/path/to/doc.pdf",
                "images": [
                    {
                        "id": "doc123_page1_img0",
                        "path": "data/images/collection/doc123_page1_img0.png",
                        "text_offset": 5,
                        "text_length": 30
                    }
                ]
            }
        }
        result = RetrievalResult.from_dict(data)
        assert result.chunk_id == "doc123_0001_abc12345"
        assert isinstance(result.metadata["images"][0], ImageReference)


class TestProcessedQuery:
    """测试 ProcessedQuery 类型。"""

    def test_basic_creation(self):
        """测试基本创建。"""
        query = ProcessedQuery(
            original_query="What is RAG?",
            keywords=["rag", "retrieval", "augmented", "generation"]
        )
        assert query.original_query == "What is RAG?"
        assert len(query.keywords) == 4
        assert query.filters == {}
        assert query.rewritten_query is None

    def test_with_filters(self):
        """测试包含过滤条件。"""
        query = ProcessedQuery(
            original_query="What is RAG?",
            keywords=["rag"],
            filters={"collection": "tech_docs", "doc_type": "pdf"}
        )
        assert query.filters["collection"] == "tech_docs"
        assert query.filters["doc_type"] == "pdf"

    def test_with_rewritten_query(self):
        """测试包含改写查询。"""
        query = ProcessedQuery(
            original_query="What is RAG?",
            keywords=["rag"],
            rewritten_query="Explain retrieval augmented generation"
        )
        assert query.rewritten_query == "Explain retrieval augmented generation"

    def test_serialization(self):
        """测试序列化 (过滤 None 值)。"""
        query = ProcessedQuery(
            original_query="What is RAG?",
            keywords=["rag"]
        )
        data = query.to_dict()
        assert "original_query" in data
        assert "keywords" in data
        assert "rewritten_query" not in data  # None 值应被过滤

    def test_deserialization(self):
        """测试反序列化。"""
        data = {
            "original_query": "What is RAG?",
            "keywords": ["rag", "retrieval"],
            "filters": {"collection": "tech_docs"},
            "rewritten_query": "Explain RAG"
        }
        query = ProcessedQuery.from_dict(data)
        assert query.original_query == "What is RAG?"
        assert len(query.keywords) == 2
        assert query.filters["collection"] == "tech_docs"
        assert query.rewritten_query == "Explain RAG"


class TestMetadataExtensibility:
    """测试 metadata 字段的可扩展性。"""

    def test_document_custom_metadata_fields(self):
        """测试 Document 自定义 metadata 字段。"""
        doc = Document(
            id="doc123",
            text="Sample text",
            metadata={
                "source_path": "/path/to/doc.pdf",
                "custom_field1": "value1",
                "custom_field2": 123,
                "custom_nested": {"key": "value"}
            }
        )
        assert doc.metadata["custom_field1"] == "value1"
        assert doc.metadata["custom_field2"] == 123
        assert doc.metadata["custom_nested"]["key"] == "value"

    def test_chunk_inherits_metadata_from_document(self):
        """测试 Chunk 继承 Document 的 metadata。"""
        doc = Document(
            id="doc123",
            text="Sample text",
            metadata={
                "source_path": "/path/to/doc.pdf",
                "collection": "test_collection",
                "title": "Test Document"
            }
        )
        chunk = Chunk(
            id="doc123_0001_abc12345",
            text="Chunk text",
            metadata={
                **doc.metadata,
                "chunk_index": 0
            },
            source_ref=doc.id
        )
        assert chunk.metadata["source_path"] == doc.metadata["source_path"]
        assert chunk.metadata["collection"] == doc.metadata["collection"]
        assert chunk.metadata["title"] == doc.metadata["title"]
        assert chunk.metadata["chunk_index"] == 0


class TestTypeStability:
    """测试类型稳定性 (向后兼容)。"""

    def test_document_required_fields_cannot_be_removed(self):
        """测试 Document 必填字段不可移除。"""
        # id, text, metadata.source_path 为必填字段
        with pytest.raises(TypeError):
            # 缺少 id
            Document(text="Sample text", metadata={"source_path": "/path"})  # type: ignore

        with pytest.raises(TypeError):
            # 缺少 text
            Document(id="doc123", metadata={"source_path": "/path"})  # type: ignore

        with pytest.raises(ValueError):
            # metadata 缺少 source_path
            Document(id="doc123", text="Sample text", metadata={})

    def test_chunk_required_fields_cannot_be_removed(self):
        """测试 Chunk 必填字段不可移除。"""
        # id, text 为必填字段
        with pytest.raises(TypeError):
            # 缺少 id
            Chunk(text="Chunk text")  # type: ignore

        with pytest.raises(TypeError):
            # 缺少 text
            Chunk(id="chunk123")  # type: ignore

    def test_chunk_record_required_fields_cannot_be_removed(self):
        """测试 ChunkRecord 必填字段不可移除。"""
        # id, text 为必填字段
        with pytest.raises(TypeError):
            # 缺少 id
            ChunkRecord(text="Chunk text")  # type: ignore

        with pytest.raises(TypeError):
            # 缺少 text
            ChunkRecord(id="chunk123")  # type: ignore
