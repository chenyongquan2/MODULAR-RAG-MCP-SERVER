"""Integration tests for query_knowledge_hub tool."""

import pytest
from unittest.mock import Mock, MagicMock, AsyncMock

from mcp.types import TextContent

from src.core.types import RetrievalResult
from src.core.query_engine.hybrid_search import HybridSearch
from src.core.response.response_builder import ResponseBuilder
from src.core.response.citation_generator import StructuredContent
from src.core.response.multimodal_assembler import MultimodalAssembler
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


def make_mock_assembler() -> MagicMock:
    """构造一个 MultimodalAssembler mock，默认返回 [TextContent, images-dict]（无图场景）。

    测试里可 monkeypatch `.assemble` 改变返回或抛异常。
    """
    assembler = MagicMock(spec=MultimodalAssembler)
    assembler.assemble.side_effect = lambda markdown, results, trace=None, max_images=None: [
        TextContent(type="text", text=markdown),
        {"images": []},
    ]
    return assembler


def make_tool(
    hybrid_search=None,
    response_builder=None,
    multimodal_assembler=None,
    max_images_per_response: int = 10,
) -> QueryKnowledgeHubTool:
    """构造一个带默认 mock 的 QueryKnowledgeHubTool（测试辅助）。"""
    return QueryKnowledgeHubTool(
        hybrid_search or MockHybridSearch(),
        response_builder or MockResponseBuilder(),
        multimodal_assembler or make_mock_assembler(),
        max_images_per_response,
    )


class TestQueryKnowledgeHubTool:
    """测试 QueryKnowledgeHubTool 集成。"""

    @pytest.mark.asyncio
    async def test_execute_with_valid_query(self):
        """测试有效查询的执行（纯检索模式）。"""
        hybrid_search = MockHybridSearch()
        response_builder = MockResponseBuilder()
        tool = make_tool(hybrid_search, response_builder)

        result = await tool.execute({
            "query": "What is RAG?",
            "top_k": 5,
        })

        # feature-002 起：纯检索模式返回 [TextContent, ...ImageContent..., images-dict]
        # 至少包含一个 TextContent（首项），可能还有图片与末尾元数据 dict
        text_items = [c for c in result if isinstance(c, TextContent)]
        assert len(text_items) >= 1
        first_text = text_items[0].text
        # 验证包含格式化结果
        assert "RAG system combines retrieval and generation" in first_text
        assert "chunk_001" in first_text
        assert "chunk_002" in first_text
        # 验证包含 Raw Results JSON
        assert "Raw Results (JSON)" in first_text

    @pytest.mark.asyncio
    async def test_execute_with_llm_mode(self):
        """测试 LLM 总结模式（use_llm=True）。"""
        hybrid_search = MockHybridSearch()
        response_builder = MockResponseBuilder()
        tool = make_tool(hybrid_search, response_builder)

        result = await tool.execute({
            "query": "What is RAG?",
            "top_k": 5,
            "use_llm": True,
        })

        # feature-002 US2 起：LLM 模式也走 MultimodalAssembler
        # 返回列表含 TextContent（含 Citations）+ 可能的 ImageContent + 末尾 images dict
        text_items = [c for c in result if isinstance(c, TextContent)]
        assert len(text_items) >= 1
        assert "Citations" in text_items[0].text

    @pytest.mark.asyncio
    async def test_execute_with_filters(self):
        """测试带过滤条件的查询（纯检索模式）。"""
        hybrid_search = MockHybridSearch()
        response_builder = MockResponseBuilder()
        tool = make_tool(hybrid_search, response_builder)

        result = await tool.execute({
            "query": "test query",
            "top_k": 3,
            "filters": {"collection": "docs"},
        })

        # feature-002 起：返回的列表首项应为 TextContent，且含格式化结果
        text_items = [c for c in result if isinstance(c, TextContent)]
        assert len(text_items) >= 1
        assert "Raw Results (JSON)" in text_items[0].text

    @pytest.mark.asyncio
    async def test_execute_with_default_top_k(self):
        """测试使用默认 top_k 值（纯检索模式）。"""
        hybrid_search = MockHybridSearch()
        response_builder = MockResponseBuilder()
        tool = make_tool(hybrid_search, response_builder)

        result = await tool.execute({
            "query": "test query",
        })

        # feature-002 起：至少含一个 TextContent（可能还有图片元数据 dict）
        text_items = [c for c in result if isinstance(c, TextContent)]
        assert len(text_items) >= 1

    @pytest.mark.asyncio
    async def test_execute_with_empty_query_raises_error(self):
        """测试空查询抛出错误。"""
        hybrid_search = MockHybridSearch()
        response_builder = MockResponseBuilder()
        tool = make_tool(hybrid_search, response_builder)

        with pytest.raises(ValueError, match="Query parameter is required"):
            await tool.execute({"query": ""})

    @pytest.mark.asyncio
    async def test_execute_with_missing_query_raises_error(self):
        """测试缺少查询参数抛出错误。"""
        hybrid_search = MockHybridSearch()
        response_builder = MockResponseBuilder()
        tool = make_tool(hybrid_search, response_builder)

        with pytest.raises(ValueError, match="Query parameter is required"):
            await tool.execute({})

    @pytest.mark.asyncio
    async def test_execute_with_invalid_top_k_raises_error(self):
        """测试无效 top_k 抛出错误。"""
        hybrid_search = MockHybridSearch()
        response_builder = MockResponseBuilder()
        tool = make_tool(hybrid_search, response_builder)

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
            QueryKnowledgeHubTool(None, Mock(), make_mock_assembler(), 10)

    @pytest.mark.asyncio
    async def test_initialization_with_none_response_builder_raises_error(self):
        """测试 None response_builder 抛出错误。"""
        with pytest.raises(ValueError, match="response_builder cannot be None"):
            QueryKnowledgeHubTool(Mock(), None, make_mock_assembler(), 10)

    # --------- feature-002 新增：构造器新参数 + 多模态返图 -----------

    @pytest.mark.asyncio
    async def test_initialization_with_none_multimodal_assembler_raises_error(self):
        """multimodal_assembler=None 必须抛 ValueError（feature-002）。"""
        with pytest.raises(ValueError, match="multimodal_assembler cannot be None"):
            QueryKnowledgeHubTool(Mock(), Mock(), None, 10)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_value", [0, -1, -100])
    async def test_initialization_with_invalid_max_images_raises_error(self, bad_value):
        """max_images_per_response <= 0 必须抛 ValueError（feature-002 FR-004）。"""
        with pytest.raises(ValueError, match="max_images_per_response"):
            QueryKnowledgeHubTool(Mock(), Mock(), make_mock_assembler(), bad_value)

    @pytest.mark.asyncio
    async def test_use_llm_false_calls_assembler_with_max_images(self):
        """feature-002 US1：纯检索模式调用 assembler.assemble 且传入 max_images。"""
        assembler = make_mock_assembler()
        tool = make_tool(multimodal_assembler=assembler, max_images_per_response=7)

        await tool.execute({"query": "hello", "top_k": 5, "use_llm": False})

        # 断言 assembler.assemble 被调用过且 max_images 参数正确
        assert assembler.assemble.call_count == 1
        call_kwargs = assembler.assemble.call_args.kwargs
        assert call_kwargs["max_images"] == 7
        # markdown 应含 `Raw Results (JSON)`（feature-002 保留了原 formatted_with_json 拼接）
        assert "Raw Results (JSON)" in call_kwargs["markdown"]

    @pytest.mark.asyncio
    async def test_use_llm_false_assembler_failure_falls_back_to_text(self):
        """feature-002 FR-006：assembler 抛异常时 fallback 为纯 TextContent。"""
        assembler = make_mock_assembler()
        assembler.assemble.side_effect = RuntimeError("Storage is down")
        tool = make_tool(multimodal_assembler=assembler)

        result = await tool.execute({"query": "hello", "use_llm": False})

        # 降级后应只返回一个 TextContent，内容为原 formatted_with_json
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Raw Results (JSON)" in result[0].text

    @pytest.mark.asyncio
    async def test_use_llm_true_calls_assembler_with_llm_markdown(self):
        """feature-002 US2：LLM 总结模式调用 assembler 一次，markdown 含 Citations 段。"""
        assembler = make_mock_assembler()
        tool = make_tool(multimodal_assembler=assembler, max_images_per_response=5)

        await tool.execute({"query": "hello", "use_llm": True})

        assert assembler.assemble.call_count == 1
        kwargs = assembler.assemble.call_args.kwargs
        # LLM 模式下 markdown = structured_content.markdown + citations_text
        assert "Citations" in kwargs["markdown"]
        # max_images 仍由构造器注入值决定
        assert kwargs["max_images"] == 5

    @pytest.mark.asyncio
    async def test_both_modes_extract_same_image_refs(self):
        """feature-002 US2：两种模式传入 assemble 的 results 相同（同 image_id 集合）。

        通过观察两次 assemble 调用的 results 参数，确认 image 元数据透传一致。
        """
        assembler = make_mock_assembler()
        tool = make_tool(multimodal_assembler=assembler, max_images_per_response=10)

        await tool.execute({"query": "same query", "use_llm": False})
        await tool.execute({"query": "same query", "use_llm": True})

        assert assembler.assemble.call_count == 2
        results_false = assembler.assemble.call_args_list[0].kwargs["results"]
        results_true = assembler.assemble.call_args_list[1].kwargs["results"]
        # 两次的 chunk_id 列表应一致（来自同一 mock HybridSearch）
        assert [r.chunk_id for r in results_false] == [r.chunk_id for r in results_true]

    @pytest.mark.asyncio
    async def test_use_llm_true_assembler_failure_falls_back_to_text(self):
        """feature-002 US2：LLM 模式下 assembler 抛错时 fallback 为纯 TextContent。"""
        assembler = make_mock_assembler()
        assembler.assemble.side_effect = RuntimeError("Storage unavailable")
        tool = make_tool(multimodal_assembler=assembler)

        result = await tool.execute({"query": "hello", "use_llm": True})

        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Citations" in result[0].text