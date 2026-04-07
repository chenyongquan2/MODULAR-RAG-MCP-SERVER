"""Integration tests for query_knowledge_hub tool."""

import pytest
from unittest.mock import Mock, AsyncMock

from src.core.types import RetrievalResult
from src.core.query_engine.hybrid_search import HybridSearch
from src.core.response.response_builder import ResponseBuilder
from src.core.response.citation_generator import StructuredContent
from src.mcp_server.tools.query_knowledge_hub import QueryKnowledgeHubTool

pytestmark = pytest.mark.integration


class MockSettings:
    """Mock settings for testing."""
    llm = Mock()
    llm.provider = "test"
    llm.model = "test-model"


class MockHybridSearch:
    """Mock HybridSearch for testing."""

    def search(self, query, top_k, filters, trace):
        return [
            RetrievalResult(
                chunk_id="chunk_001",
                score=0.95,
                text="RAG system combines retrieval and generation",
                metadata={"source_path": "doc.pdf", "page": 10},
            ),
            RetrievalResult(
                chunk_id="chunk_002",
                score=0.85,
                text="Hybrid search uses dense and sparse retrieval",
                metadata={"source_path": "doc2.pdf", "page": 20},
            ),
        ]


class MockResponseBuilder:
    """Mock ResponseBuilder for testing."""

    def build(self, query, results, trace):
        citations = [
            Mock(id=1, source="doc.pdf", page=10, chunk_id="chunk_001", score=0.95, text="RAG system combines retrieval and generation"),
            Mock(id=2, source="doc2.pdf", page=20, chunk_id="chunk_002", score=0.85, text="Hybrid search uses dense and sparse retrieval"),
        ]
        return StructuredContent(
            markdown="RAG system combines retrieval and generation [1]. Hybrid search uses dense and sparse retrieval [2].",
            citations=citations,
        )


class TestQueryKnowledgeHubTool:
    """测试 QueryKnowledgeHubTool 集成。"""

    @pytest.mark.asyncio
    async def test_execute_with_valid_query(self):
        """测试有效查询的执行（纯检索模式）。"""
        hybrid_search = MockHybridSearch()
        response_builder = MockResponseBuilder()
        tool = QueryKnowledgeHubTool(hybrid_search, response_builder)

        result = await tool.execute({
            "query": "What is RAG?",
            "top_k": 5,
        })

        # 纯检索模式（use_llm=False）只返回一个 TextContent
        assert len(result) == 1
        assert result[0].type == "text"
        # 验证包含格式化结果
        assert "RAG system combines retrieval and generation" in result[0].text
        assert "chunk_001" in result[0].text
        assert "chunk_002" in result[0].text
        # 验证包含 Raw Results JSON
        assert "Raw Results (JSON)" in result[0].text

    @pytest.mark.asyncio
    async def test_execute_with_llm_mode(self):
        """测试 LLM 总结模式（use_llm=True）。"""
        hybrid_search = MockHybridSearch()
        response_builder = MockResponseBuilder()
        tool = QueryKnowledgeHubTool(hybrid_search, response_builder)

        result = await tool.execute({
            "query": "What is RAG?",
            "top_k": 5,
            "use_llm": True,
        })

        # LLM 模式返回一个包含 markdown 和 citations 的 TextContent
        assert len(result) == 1
        assert result[0].type == "text"
        assert "Citations" in result[0].text

    @pytest.mark.asyncio
    async def test_execute_with_filters(self):
        """测试带过滤条件的查询（纯检索模式）。"""
        hybrid_search = MockHybridSearch()
        response_builder = MockResponseBuilder()
        tool = QueryKnowledgeHubTool(hybrid_search, response_builder)

        result = await tool.execute({
            "query": "test query",
            "top_k": 3,
            "filters": {"collection": "docs"},
        })

        # 纯检索模式返回一个 TextContent
        assert len(result) == 1
        assert result[0].type == "text"
        # 验证返回了格式化结果
        assert "Raw Results (JSON)" in result[0].text

    @pytest.mark.asyncio
    async def test_execute_with_default_top_k(self):
        """测试使用默认 top_k 值（纯检索模式）。"""
        hybrid_search = MockHybridSearch()
        response_builder = MockResponseBuilder()
        tool = QueryKnowledgeHubTool(hybrid_search, response_builder)

        result = await tool.execute({
            "query": "test query",
        })

        # 纯检索模式返回单个 TextContent
        assert len(result) == 1
        assert result[0].type == "text"

    @pytest.mark.asyncio
    async def test_execute_with_empty_query_raises_error(self):
        """测试空查询抛出错误。"""
        hybrid_search = MockHybridSearch()
        response_builder = MockResponseBuilder()
        tool = QueryKnowledgeHubTool(hybrid_search, response_builder)

        with pytest.raises(ValueError, match="Query parameter is required"):
            await tool.execute({"query": ""})

    @pytest.mark.asyncio
    async def test_execute_with_missing_query_raises_error(self):
        """测试缺少查询参数抛出错误。"""
        hybrid_search = MockHybridSearch()
        response_builder = MockResponseBuilder()
        tool = QueryKnowledgeHubTool(hybrid_search, response_builder)

        with pytest.raises(ValueError, match="Query parameter is required"):
            await tool.execute({})

    @pytest.mark.asyncio
    async def test_execute_with_invalid_top_k_raises_error(self):
        """测试无效 top_k 抛出错误。"""
        hybrid_search = MockHybridSearch()
        response_builder = MockResponseBuilder()
        tool = QueryKnowledgeHubTool(hybrid_search, response_builder)

        with pytest.raises(ValueError, match="top_k must be a positive integer"):
            await tool.execute({"query": "test", "top_k": 0})

        with pytest.raises(ValueError, match="top_k must be a positive integer"):
            await tool.execute({"query": "test", "top_k": -1})

    @pytest.mark.asyncio
    async def test_get_tool_definition(self):
        """测试工具定义。"""
        tool_def = QueryKnowledgeHubTool.get_tool_definition()

        assert tool_def["name"] == "query_knowledge_hub"
        assert "混合检索" in tool_def["description"]
        assert "Dense + Sparse + RRF" in tool_def["description"]

        schema = tool_def["inputSchema"]
        assert schema["type"] == "object"
        assert "query" in schema["properties"]
        assert "top_k" in schema["properties"]
        assert "filters" in schema["properties"]

        assert schema["required"] == ["query"]
        assert schema["properties"]["query"]["type"] == "string"
        assert schema["properties"]["top_k"]["type"] == "integer"
        assert schema["properties"]["top_k"]["default"] == 10
        assert schema["properties"]["top_k"]["minimum"] == 1
        assert schema["properties"]["top_k"]["maximum"] == 50

    @pytest.mark.asyncio
    async def test_initialization_with_none_hybrid_search_raises_error(self):
        """测试 None hybrid_search 抛出错误。"""
        with pytest.raises(ValueError, match="hybrid_search cannot be None"):
            QueryKnowledgeHubTool(None, Mock())

    @pytest.mark.asyncio
    async def test_initialization_with_none_response_builder_raises_error(self):
        """测试 None response_builder 抛出错误。"""
        with pytest.raises(ValueError, match="response_builder cannot be None"):
            QueryKnowledgeHubTool(Mock(), None)