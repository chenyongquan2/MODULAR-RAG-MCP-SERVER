"""MCP Server 入口 (Stdio Transport)。

遵循标准：stdout 只输出 MCP 消息，日志到 stderr。
"""

from __future__ import annotations

import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
)

from src.core.settings import load_settings, SettingsError
from src.core.query_engine.fusion import HybridSearch
from src.core.response.response_builder import ResponseBuilder
from src.mcp_server.tools.query_knowledge_hub import QueryKnowledgeHubTool
from src.mcp_server.tools.list_collections import ListCollectionsTool
from src.mcp_server.tools.get_document_summary import GetDocumentSummaryTool
from observability.logger import get_logger

logger = get_logger(__name__)


class MCPServer:
    """MCP Server 主类，负责初始化和处理 MCP 协议消息。"""

    def __init__(self) -> None:
        """初始化 MCP Server。"""
        self.server = Server(
            name="modular-rag-mcp-server",
            version="0.1.0",
        )
        self._query_tool: QueryKnowledgeHubTool | None = None
        self._list_collections_tool: ListCollectionsTool | None = None
        self._get_document_summary_tool: GetDocumentSummaryTool | None = None
        self._tools: list[Tool] = []

    async def run(self) -> None:
        """运行 MCP Server。"""
        logger.info("Starting MCP Server on stdio transport...")

        # Initialize RAG components
        try:
            settings = load_settings()
            logger.info(
                "Initializing RAG components: llm=%s/%s, embedding=%s/%s, vector_store=%s",
                settings.llm.provider,
                settings.llm.model,
                settings.embedding.provider,
                settings.embedding.model,
                settings.vector_store.backend,
            )

            hybrid_search = HybridSearch(settings=settings)
            response_builder = ResponseBuilder(settings=settings)
            self._query_tool = QueryKnowledgeHubTool(hybrid_search, response_builder)

            # Initialize list_collections tool
            try:
                self._list_collections_tool = ListCollectionsTool(settings)
                list_tool_def = ListCollectionsTool.get_tool_definition()
                self._tools.append(Tool(**list_tool_def))
                logger.info("Prepared tool: list_collections")
            except Exception as e:
                logger.warning("Failed to initialize list_collections tool: %s", e)

            # Initialize get_document_summary tool
            try:
                self._get_document_summary_tool = GetDocumentSummaryTool(settings)
                summary_tool_def = GetDocumentSummaryTool.get_tool_definition()
                self._tools.append(Tool(**summary_tool_def))
                logger.info("Prepared tool: get_document_summary")
            except Exception as e:
                logger.warning("Failed to initialize get_document_summary tool: %s", e)

            # Register query_knowledge_hub tool
            query_tool_def = QueryKnowledgeHubTool.get_tool_definition()
            self._tools.append(Tool(**query_tool_def))
            logger.info("Prepared tool: query_knowledge_hub")

        except Exception as e:
            logger.error("Failed to initialize RAG components: %s", e, exc_info=True)
            # Continue without RAG tools for graceful degradation

        # Register handlers using decorators (MCP SDK 1.26+ pattern)
        @self.server.list_tools()
        async def handle_list_tools() -> list[Tool]:
            """返回可用工具列表。"""
            logger.info("Listing available tools: %s", [t.name for t in self._tools])
            return self._tools

        @self.server.call_tool()
        async def handle_call_tool(
            name: str, arguments: dict
        ) -> list[TextContent | dict]:
            """处理工具调用。"""
            logger.info("Calling tool: %s with arguments: %s", name, arguments)

            try:
                if name == "query_knowledge_hub" and self._query_tool:
                    return await self._query_tool.execute(arguments or {})

                elif name == "list_collections" and self._list_collections_tool:
                    return await self._list_collections_tool.execute(arguments or {})

                elif name == "get_document_summary" and self._get_document_summary_tool:
                    return await self._get_document_summary_tool.execute(arguments or {})

                else:
                    logger.warning("Unknown tool requested: %s", name)
                    return [
                        TextContent(
                            type="text",
                            text=f"Unknown tool: {name}. Available tools: {[t.name for t in self._tools]}",
                        )
                    ]

            except ValueError as e:
                logger.error("Validation error in tool %s: %s", name, e)
                return [TextContent(type="text", text=f"参数错误: {str(e)}")]

            except Exception as e:
                logger.error("Error executing tool %s: %s", name, e, exc_info=True)
                return [
                    TextContent(
                        type="text",
                        text=f"工具执行错误: {str(e)}",
                    )
                ]

        # Run the server
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options(),
            )


async def main() -> None:
    """MCP Server 主入口。"""
    try:
        settings = load_settings()
    except SettingsError as exc:
        logger.error("Failed to load settings: %s", exc)
        sys.exit(1)

    logger.info(
        "Settings loaded: llm=%s/%s, embedding=%s/%s, vector_store=%s",
        settings.llm.provider,
        settings.llm.model,
        settings.embedding.provider,
        settings.embedding.model,
        settings.vector_store.backend,
    )

    server = MCPServer()
    await server.run()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
