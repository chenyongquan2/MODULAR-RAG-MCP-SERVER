"""Tests for get_document_summary tool."""

import pytest
from mcp.types import TextContent

from src.mcp_server.tools.get_document_summary import GetDocumentSummaryTool
from src.core.settings import Settings


class MockVectorStore:
    """Mock vector store for testing."""

    def __init__(self, query_results: list[dict] | None = None):
        self.query_results = query_results or []

    def get_backend_name(self) -> str:
        return "mock"

    def query(
        self,
        vector: list[float],
        top_k: int = 10,
        filters: dict | None = None,
        trace: None = None,
        **kwargs: dict,
    ) -> list[dict]:
        """Mock query method."""
        if filters and filters.get("source_ref"):
            # Return filtered results for specific document
            return [
                r for r in self.query_results
                if r.get("metadata", {}).get("source_ref") == filters["source_ref"]
            ]
        return self.query_results[:top_k]


class TestGetDocumentSummaryTool:
    """Test suite for GetDocumentSummaryTool."""

    @pytest.fixture
    def mock_settings(self) -> Settings:
        """Create mock settings for testing."""
        from dataclasses import dataclass, field

        @dataclass
        class LLMSettings:
            provider: str = "openai"
            model: str = "gpt-4"
            azure_endpoint: str = ""
            api_key: str = "test-key"

        @dataclass
        class EmbeddingSettings:
            provider: str = "openai"
            model: str = "text-embedding-3-small"
            api_key: str = "test-key"

        @dataclass
        class VisionLLMSettings:
            provider: str = "azure"
            model: str = "gpt-4o"

        @dataclass
        class VectorStoreSettings:
            backend: str = "mock"
            persist_path: str = "./data/db/mock"

        @dataclass
        class Settings:
            llm: LLMSettings
            embedding: EmbeddingSettings
            vision_llm: VisionLLMSettings
            vector_store: VectorStoreSettings

        return Settings(
            llm=LLMSettings(),
            embedding=EmbeddingSettings(),
            vision_llm=VisionLLMSettings(),
            vector_store=VectorStoreSettings(),
        )

    @pytest.fixture
    def sample_metadata(self) -> dict:
        """Sample metadata for testing."""
        return {
            "source_path": "/path/to/document.pdf",
            "collection": "test-collection",
            "doc_type": "pdf",
            "title": "Test Document Title",
            "summary": "This is a test document summary.",
            "tags": ["test", "document", "sample"],
            "images": [
                {
                    "id": "img_001",
                    "path": "/path/to/image.png",
                    "page": 1,
                },
                {
                    "id": "img_002",
                    "path": "/path/to/image2.png",
                    "page": 2,
                },
            ],
        }

    @pytest.fixture
    def sample_chunk_record(self, sample_metadata: dict) -> dict:
        """Sample chunk record for testing."""
        return {
            "id": "chunk_abc123_0001_a1b2c3d4",
            "score": 0.95,
            "text": "This is sample chunk content.",
            "metadata": {
                "source_ref": "doc_hash_123",
                **sample_metadata,
            },
        }

    @pytest.mark.asyncio
    async def test_get_summary_success(
        self, mock_settings: Settings, sample_chunk_record: dict, monkeypatch
    ):
        """Test successful document summary retrieval."""
        # Mock vector store with sample data
        mock_store = MockVectorStore([sample_chunk_record])

        def mock_create(settings, **kwargs):
            return mock_store

        monkeypatch.setattr(
            "src.mcp_server.tools.get_document_summary.VectorStoreFactory.create",
            mock_create,
        )

        tool = GetDocumentSummaryTool(mock_settings)
        result = await tool.execute({"doc_id": "doc_hash_123"})

        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        text = result[0].text

        # Verify document ID is included
        assert "文档 ID: doc_hash_123" in text

        # Verify title is included
        assert "标题: Test Document Title" in text

        # Verify collection is included
        assert "集合: test-collection" in text

        # Verify doc_type is included
        assert "文档类型: pdf" in text

        # Verify summary is included
        assert "摘要: This is a test document summary." in text

        # Verify tags are included
        assert "标签: test, document, sample" in text

        # Verify chunk count is included
        assert "Chunk 数量: 1" in text

        # Verify images are included
        assert "包含图片: 2 张" in text

    @pytest.mark.asyncio
    async def test_get_summary_minimal_metadata(
        self, mock_settings: Settings, monkeypatch
    ):
        """Test document summary with minimal metadata."""
        # Mock vector store with minimal metadata
        minimal_metadata = {
            "source_path": "/path/to/minimal.pdf",
            "collection": "default",
            "doc_type": "markdown",
        }
        chunk_record = {
            "id": "chunk_minimal_0001_a1b2c3",
            "score": 0.9,
            "text": "Minimal content",
            "metadata": {"source_ref": "minimal_doc", **minimal_metadata},
        }

        mock_store = MockVectorStore([chunk_record])

        def mock_create(settings, **kwargs):
            return mock_store

        monkeypatch.setattr(
            "src.mcp_server.tools.get_document_summary.VectorStoreFactory.create",
            mock_create,
        )

        tool = GetDocumentSummaryTool(mock_settings)
        result = await tool.execute({"doc_id": "minimal_doc"})

        assert len(result) == 1
        text = result[0].text

        # Verify required fields are present
        assert "文档 ID: minimal_doc" in text
        assert "标题: /path/to/minimal.pdf" in text  # Falls back to source_path
        assert "集合: default" in text
        assert "文档类型: markdown" in text
        assert "Chunk 数量: 1" in text

        # Verify optional fields are not present
        assert "摘要:" not in text
        assert "标签:" not in text
        assert "包含图片:" not in text

    @pytest.mark.asyncio
    async def test_get_summary_document_not_found(
        self, mock_settings: Settings, monkeypatch
    ):
        """Test handling of non-existent document."""
        # Mock vector store with no results
        mock_store = MockVectorStore([])

        def mock_create(settings, **kwargs):
            return mock_store

        monkeypatch.setattr(
            "src.mcp_server.tools.get_document_summary.VectorStoreFactory.create",
            mock_create,
        )

        tool = GetDocumentSummaryTool(mock_settings)
        result = await tool.execute({"doc_id": "non_existent"})

        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "未找到文档 ID 为 'non_existent' 的文档" in result[0].text
        assert "请确认文档 ID 是否正确" in result[0].text

    @pytest.mark.asyncio
    async def test_get_summary_empty_doc_id(
        self, mock_settings: Settings, monkeypatch
    ):
        """Test handling of empty doc_id parameter."""
        mock_store = MockVectorStore()

        def mock_create(settings, **kwargs):
            return mock_store

        monkeypatch.setattr(
            "src.mcp_server.tools.get_document_summary.VectorStoreFactory.create",
            mock_create,
        )

        tool = GetDocumentSummaryTool(mock_settings)

        with pytest.raises(ValueError, match="doc_id parameter is required"):
            await tool.execute({"doc_id": ""})

    @pytest.mark.asyncio
    async def test_get_summary_missing_doc_id(
        self, mock_settings: Settings, monkeypatch
    ):
        """Test handling of missing doc_id parameter."""
        mock_store = MockVectorStore()

        def mock_create(settings, **kwargs):
            return mock_store

        monkeypatch.setattr(
            "src.mcp_server.tools.get_document_summary.VectorStoreFactory.create",
            mock_create,
        )

        tool = GetDocumentSummaryTool(mock_settings)

        with pytest.raises(ValueError, match="doc_id parameter is required"):
            await tool.execute({})

    @pytest.mark.asyncio
    async def test_get_summary_invalid_doc_id_type(
        self, mock_settings: Settings, monkeypatch
    ):
        """Test handling of invalid doc_id type."""
        mock_store = MockVectorStore()

        def mock_create(settings, **kwargs):
            return mock_store

        monkeypatch.setattr(
            "src.mcp_server.tools.get_document_summary.VectorStoreFactory.create",
            mock_create,
        )

        tool = GetDocumentSummaryTool(mock_settings)

        with pytest.raises(ValueError, match="doc_id parameter is required"):
            await tool.execute({"doc_id": 123})

    @pytest.mark.asyncio
    async def test_get_summary_multiple_chunks(
        self, mock_settings: Settings, sample_metadata: dict, monkeypatch
    ):
        """Test document summary with multiple chunks."""
        # Mock vector store with multiple chunks for same document
        chunks = [
            {
                "id": f"chunk_abc_{i:04d}_hash",
                "score": 0.9,
                "text": f"Chunk {i} content",
                "metadata": {"source_ref": "multi_chunk_doc", **sample_metadata},
            }
            for i in range(5)
        ]

        mock_store = MockVectorStore(chunks)

        def mock_create(settings, **kwargs):
            return mock_store

        monkeypatch.setattr(
            "src.mcp_server.tools.get_document_summary.VectorStoreFactory.create",
            mock_create,
        )

        tool = GetDocumentSummaryTool(mock_settings)
        result = await tool.execute({"doc_id": "multi_chunk_doc"})

        assert len(result) == 1
        text = result[0].text
        assert "Chunk 数量: 5" in text

    @pytest.mark.asyncio
    async def test_get_summary_with_single_image(
        self, mock_settings: Settings, monkeypatch
    ):
        """Test document summary with single image."""
        metadata = {
            "source_path": "/path/to/single.pdf",
            "collection": "test",
            "doc_type": "pdf",
            "title": "Single Image Doc",
            "images": [
                {
                    "id": "img_001",
                    "path": "/path/to/image.png",
                    "page": 1,
                }
            ],
        }

        chunk = {
            "id": "chunk_single_0001_hash",
            "score": 0.95,
            "text": "Content",
            "metadata": {"source_ref": "single_img", **metadata},
        }

        mock_store = MockVectorStore([chunk])

        def mock_create(settings, **kwargs):
            return mock_store

        monkeypatch.setattr(
            "src.mcp_server.tools.get_document_summary.VectorStoreFactory.create",
            mock_create,
        )

        tool = GetDocumentSummaryTool(mock_settings)
        result = await tool.execute({"doc_id": "single_img"})

        assert len(result) == 1
        text = result[0].text
        assert "包含图片: 1 张" in text

    @pytest.mark.asyncio
    async def test_get_summary_no_images(
        self, mock_settings: Settings, sample_metadata: dict, monkeypatch
    ):
        """Test document summary without images."""
        # Remove images from metadata
        no_img_metadata = {k: v for k, v in sample_metadata.items() if k != "images"}

        chunk = {
            "id": "chunk_no_img_0001_hash",
            "score": 0.9,
            "text": "Content",
            "metadata": {"source_ref": "no_img", **no_img_metadata},
        }

        mock_store = MockVectorStore([chunk])

        def mock_create(settings, **kwargs):
            return mock_store

        monkeypatch.setattr(
            "src.mcp_server.tools.get_document_summary.VectorStoreFactory.create",
            mock_create,
        )

        tool = GetDocumentSummaryTool(mock_settings)
        result = await tool.execute({"doc_id": "no_img"})

        assert len(result) == 1
        text = result[0].text
        assert "包含图片:" not in text

    @pytest.mark.asyncio
    async def test_get_summary_no_tags(
        self, mock_settings: Settings, sample_metadata: dict, monkeypatch
    ):
        """Test document summary without tags."""
        # Remove tags from metadata
        no_tags_metadata = {k: v for k, v in sample_metadata.items() if k != "tags"}

        chunk = {
            "id": "chunk_no_tags_0001_hash",
            "score": 0.9,
            "text": "Content",
            "metadata": {"source_ref": "no_tags", **no_tags_metadata},
        }

        mock_store = MockVectorStore([chunk])

        def mock_create(settings, **kwargs):
            return mock_store

        monkeypatch.setattr(
            "src.mcp_server.tools.get_document_summary.VectorStoreFactory.create",
            mock_create,
        )

        tool = GetDocumentSummaryTool(mock_settings)
        result = await tool.execute({"doc_id": "no_tags"})

        assert len(result) == 1
        text = result[0].text
        assert "标签:" not in text

    @pytest.mark.asyncio
    async def test_get_summary_no_summary_text(
        self, mock_settings: Settings, sample_metadata: dict, monkeypatch
    ):
        """Test document summary without summary text."""
        # Remove summary from metadata
        no_summary_metadata = {
            k: v for k, v in sample_metadata.items() if k != "summary"
        }

        chunk = {
            "id": "chunk_no_sum_0001_hash",
            "score": 0.9,
            "text": "Content",
            "metadata": {"source_ref": "no_sum", **no_summary_metadata},
        }

        mock_store = MockVectorStore([chunk])

        def mock_create(settings, **kwargs):
            return mock_store

        monkeypatch.setattr(
            "src.mcp_server.tools.get_document_summary.VectorStoreFactory.create",
            mock_create,
        )

        tool = GetDocumentSummaryTool(mock_settings)
        result = await tool.execute({"doc_id": "no_sum"})

        assert len(result) == 1
        text = result[0].text
        assert "摘要:" not in text

    def test_get_tool_definition(self):
        """Test getting tool definition."""
        definition = GetDocumentSummaryTool.get_tool_definition()

        assert definition["name"] == "get_document_summary"
        assert "文档" in definition["description"]
        assert "摘要信息" in definition["description"]
        assert "标题" in definition["description"]
        assert "摘要" in definition["description"]
        assert "标签" in definition["description"]

        # Verify input schema
        assert definition["inputSchema"]["type"] == "object"
        assert "doc_id" in definition["inputSchema"]["properties"]
        assert definition["inputSchema"]["properties"]["doc_id"]["type"] == "string"
        assert "文档 ID" in definition["inputSchema"]["properties"]["doc_id"]["description"]
        assert definition["inputSchema"]["required"] == ["doc_id"]

    def test_init_with_none_settings(self):
        """Test that initialization fails with None settings."""
        with pytest.raises(ValueError, match="settings cannot be None"):
            GetDocumentSummaryTool(None)

    @pytest.mark.asyncio
    async def test_vector_store_initialization_error(
        self, mock_settings: Settings, monkeypatch
    ):
        """Test graceful degradation when vector store fails to initialize."""
        # Mock factory to raise exception
        def mock_create(settings, **kwargs):
            raise RuntimeError("Connection failed")

        monkeypatch.setattr(
            "src.mcp_server.tools.get_document_summary.VectorStoreFactory.create",
            mock_create,
        )

        tool = GetDocumentSummaryTool(mock_settings)

        with pytest.raises(RuntimeError, match="Failed to initialize vector store"):
            await tool.execute({"doc_id": "test"})

    @pytest.mark.asyncio
    async def test_lazy_initialization(
        self, mock_settings: Settings, sample_chunk_record: dict, monkeypatch
    ):
        """Test that vector store is lazily initialized."""
        mock_store = MockVectorStore([sample_chunk_record])

        init_count = {"count": 0}

        def mock_create(settings, **kwargs):
            init_count["count"] += 1
            return mock_store

        monkeypatch.setattr(
            "src.mcp_server.tools.get_document_summary.VectorStoreFactory.create",
            mock_create,
        )

        tool = GetDocumentSummaryTool(mock_settings)

        # Vector store should not be initialized yet
        assert init_count["count"] == 0

        # Execute should trigger initialization
        await tool.execute({"doc_id": "doc_hash_123"})

        # Vector store should be initialized once
        assert init_count["count"] == 1

    @pytest.mark.asyncio
    async def test_query_error_handling(
        self, mock_settings: Settings, monkeypatch
    ):
        """Test graceful error handling when query fails."""
        # Mock vector store to raise exception on query
        class FailingVectorStore:
            def get_backend_name(self) -> str:
                return "failing"

            def query(self, **kwargs):
                raise Exception("Query failed unexpectedly")

        mock_store = FailingVectorStore()

        def mock_create(settings, **kwargs):
            return mock_store

        monkeypatch.setattr(
            "src.mcp_server.tools.get_document_summary.VectorStoreFactory.create",
            mock_create,
        )

        tool = GetDocumentSummaryTool(mock_settings)
        result = await tool.execute({"doc_id": "test"})

        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "获取文档摘要时发生错误" in result[0].text