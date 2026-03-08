"""Tests for list_collections tool."""

import pytest
from mcp.types import TextContent

from src.mcp_server.tools.list_collections import ListCollectionsTool
from src.core.settings import Settings


class MockVectorStore:
    """Mock vector store for testing."""

    def __init__(self, collections: list[str] | None = None):
        self.collections = collections or []

    def get_backend_name(self) -> str:
        return "mock"

    def get_collection_names(self) -> list[str]:
        return self.collections


class TestListCollectionsTool:
    """Test suite for ListCollectionsTool."""

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

    @pytest.mark.asyncio
    async def test_list_collections_empty(self, mock_settings: Settings, monkeypatch):
        """Test listing collections when none exist."""
        # Mock vector store with empty collections
        mock_store = MockVectorStore([])

        def mock_create(settings, **kwargs):
            return mock_store

        monkeypatch.setattr(
            "src.mcp_server.tools.list_collections.VectorStoreFactory.create",
            mock_create,
        )

        tool = ListCollectionsTool(mock_settings)
        result = await tool.execute({})

        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "没有可用的集合" in result[0].text
        assert "请先使用摄取功能" in result[0].text

    @pytest.mark.asyncio
    async def test_list_collections_single(self, mock_settings: Settings, monkeypatch):
        """Test listing a single collection."""
        # Mock vector store with one collection
        mock_store = MockVectorStore(["docs"])

        def mock_create(settings, **kwargs):
            return mock_store

        monkeypatch.setattr(
            "src.mcp_server.tools.list_collections.VectorStoreFactory.create",
            mock_create,
        )

        tool = ListCollectionsTool(mock_settings)
        result = await tool.execute({})

        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "可用的集合" in result[0].text
        assert "共 1 个" in result[0].text
        assert "- docs" in result[0].text

    @pytest.mark.asyncio
    async def test_list_collections_multiple(
        self, mock_settings: Settings, monkeypatch
    ):
        """Test listing multiple collections."""
        # Mock vector store with multiple collections
        collections = ["docs", "guides", "faq"]
        mock_store = MockVectorStore(collections)

        def mock_create(settings, **kwargs):
            return mock_store

        monkeypatch.setattr(
            "src.mcp_server.tools.list_collections.VectorStoreFactory.create",
            mock_create,
        )

        tool = ListCollectionsTool(mock_settings)
        result = await tool.execute({})

        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "可用的集合" in result[0].text
        assert "共 3 个" in result[0].text
        assert "- docs" in result[0].text
        assert "- guides" in result[0].text
        assert "- faq" in result[0].text

    @pytest.mark.asyncio
    async def test_list_collections_sorted(
        self, mock_settings: Settings, monkeypatch
    ):
        """Test that collections are returned in sorted order."""
        # Mock vector store with unsorted collections
        collections = ["zebra", "alpha", "beta"]
        mock_store = MockVectorStore(collections)

        def mock_create(settings, **kwargs):
            return mock_store

        monkeypatch.setattr(
            "src.mcp_server.tools.list_collections.VectorStoreFactory.create",
            mock_create,
        )

        tool = ListCollectionsTool(mock_settings)
        result = await tool.execute({})

        # Check sorted order
        lines = result[0].text.split("\n")
        collection_lines = [line for line in lines if line.startswith("- ")]

        assert collection_lines[0] == "- alpha"
        assert collection_lines[1] == "- beta"
        assert collection_lines[2] == "- zebra"

    @pytest.mark.asyncio
    async def test_list_collections_with_filters_hint(
        self, mock_settings: Settings, monkeypatch
    ):
        """Test that result includes hint about using filters."""
        mock_store = MockVectorStore(["test-collection"])

        def mock_create(settings, **kwargs):
            return mock_store

        monkeypatch.setattr(
            "src.mcp_server.tools.list_collections.VectorStoreFactory.create",
            mock_create,
        )

        tool = ListCollectionsTool(mock_settings)
        result = await tool.execute({})

        assert "filters 参数指定集合名称" in result[0].text
        assert "query_knowledge_hub" in result[0].text

    def test_get_tool_definition(self):
        """Test getting tool definition."""
        definition = ListCollectionsTool.get_tool_definition()

        assert definition["name"] == "list_collections"
        assert "集合" in definition["description"]
        assert definition["inputSchema"]["type"] == "object"
        assert len(definition["inputSchema"]["properties"]) == 0
        assert len(definition["inputSchema"]["required"]) == 0

    def test_init_with_none_settings(self):
        """Test that initialization fails with None settings."""
        with pytest.raises(ValueError, match="settings cannot be None"):
            ListCollectionsTool(None)

    @pytest.mark.asyncio
    async def test_vector_store_initialization_error(
        self, mock_settings: Settings, monkeypatch
    ):
        """Test graceful degradation when vector store fails to initialize."""
        # Mock factory to raise exception
        def mock_create(settings, **kwargs):
            raise RuntimeError("Connection failed")

        monkeypatch.setattr(
            "src.mcp_server.tools.list_collections.VectorStoreFactory.create",
            mock_create,
        )

        tool = ListCollectionsTool(mock_settings)

        with pytest.raises(RuntimeError, match="Failed to initialize vector store"):
            await tool.execute({})
