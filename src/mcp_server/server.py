"""MCP Server 入口（支持 Stdio / SSE Transport）。

遵循标准：stdout 只输出 MCP 消息，日志到 stderr。
"""

from __future__ import annotations

import asyncio
import sys

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
    ImageContent,
)
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route
import uvicorn

from src.core.settings import Settings, load_settings, SettingsError, VALID_TRANSPORTS
from src.core.query_engine.hybrid_search import HybridSearch
from src.core.response.response_builder import ResponseBuilder
from src.core.response.multimodal_assembler import MultimodalAssembler
from src.core.trace.trace_collector import TraceCollector
from src.ingestion.storage.image_storage import SQLiteImageStorage
from src.mcp_server.tools.query_knowledge_hub import QueryKnowledgeHubTool
from src.mcp_server.tools.list_collections import ListCollectionsTool
from src.mcp_server.tools.get_document_summary import GetDocumentSummaryTool
from src.observability.logger import get_logger

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
        self._runtime_initialized = False
        # 防止并发调用 _initialize_runtime() 时重复注册 handler
        self._init_lock = asyncio.Lock()

    async def _initialize_runtime(self) -> None:
        """初始化 RAG 组件并注册 MCP handlers。"""
        async with self._init_lock:
            if self._runtime_initialized:
                return
            await self._do_initialize_runtime()

    async def _do_initialize_runtime(self) -> None:
        """实际执行初始化（由 _initialize_runtime 在锁内调用）。"""

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
            # feature-002: 装配多模态返回链路（ImageStorage + MultimodalAssembler + TraceCollector）
            image_storage = SQLiteImageStorage()
            multimodal_assembler = MultimodalAssembler(image_storage=image_storage)
            # observability.enabled=true 时启用 trace 持久化（US3）
            trace_collector: TraceCollector | None = (
                TraceCollector() if settings.observability.enabled else None
            )
            self._query_tool = QueryKnowledgeHubTool(
                hybrid_search,
                response_builder,
                multimodal_assembler,
                settings.query.max_images_per_response,
                trace_collector,
            )

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
        ) -> list[TextContent | ImageContent]:
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
        self._runtime_initialized = True

    async def run(self) -> None:
        """运行 MCP Server（stdio transport）。"""
        logger.info("Starting MCP Server on stdio transport...")
        await self._initialize_runtime()

        # Run the server
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options(),
            )

    async def run_sse(
        self,
        host: str,
        port: int,
        sse_path: str,
        message_path: str,
    ) -> None:
        """运行 MCP Server（SSE transport）。

        Args:
            host: HTTP 监听地址。
            port: HTTP 监听端口。
            sse_path: SSE 连接路径（GET）。
            message_path: 客户端消息上行路径（POST mount 前缀）。
        """
        await self._initialize_runtime()

        normalized_sse_path = self._normalize_path(sse_path, trailing_slash=False)
        normalized_message_path = self._normalize_path(
            message_path,
            trailing_slash=True,
        )
        logger.info(
            "Starting MCP Server on SSE transport at http://%s:%s%s",
            host,
            port,
            normalized_sse_path,
        )

        sse_transport = SseServerTransport(normalized_message_path)

        async def handle_sse(request: Request) -> Response:
            # MCP SDK SSE transport 需要原始 ASGI send callable。
            # Starlette Request 通过私有属性 _send 暴露它；这是 MCP SDK
            # 官方示例的标准用法，但属于私有 API，升级 Starlette 时需验证。
            # 追踪：https://github.com/modelcontextprotocol/python-sdk
            try:
                async with sse_transport.connect_sse(
                    request.scope,
                    request.receive,
                    request._send,  # type: ignore[attr-defined]
                ) as streams:
                    await self.server.run(
                        streams[0],
                        streams[1],
                        self.server.create_initialization_options(),
                    )
            except Exception as exc:
                # 客户端主动断开会触发正常异常，记录 INFO 级别；
                # 其他未预期错误记录 ERROR 便于排查。
                logger.info("SSE connection closed: %s", exc)
            return Response()

        app = Starlette(
            routes=[
                Route(normalized_sse_path, endpoint=handle_sse, methods=["GET"]),
                Mount(normalized_message_path, app=sse_transport.handle_post_message),
            ]
        )

        uvicorn_config = uvicorn.Config(
            app=app,
            host=host,
            port=port,
            log_level="info",
        )
        uvicorn_server = uvicorn.Server(uvicorn_config)
        await uvicorn_server.serve()

    async def run_from_settings(self, settings: Settings) -> None:
        """根据 settings.mcp_server.transport 选择传输模式并运行。

        这是唯一的 transport 调度入口，main.py 与 server.py 的 main() 均委托此处，
        避免调度逻辑散落在多个文件中。

        Args:
            settings: 已加载并校验过的全局配置。

        Raises:
            ValueError: transport 值不在 VALID_TRANSPORTS 中时抛出
                        （正常情况下 validate_settings 已拦截）。
        """
        transport = settings.mcp_server.transport
        if transport == "stdio":
            await self.run()
        elif transport == "sse":
            await self.run_sse(
                host=settings.mcp_server.host,
                port=settings.mcp_server.port,
                sse_path=settings.mcp_server.sse_path,
                message_path=settings.mcp_server.message_path,
            )
        else:
            # 兜底：validate_settings 已校验，此处仅防御性处理
            raise ValueError(
                f"Unsupported mcp_server.transport: {transport!r}. "
                f"Expected one of: {sorted(VALID_TRANSPORTS)}"
            )

    @staticmethod
    def _normalize_path(path: str, trailing_slash: bool) -> str:
        """规范化 HTTP 路径，确保以 '/' 开头。"""
        normalized = (path or "").strip()
        if not normalized:
            raise ValueError("Path must not be empty")
        if not normalized.startswith("/"):
            normalized = f"/{normalized}"

        if trailing_slash:
            if not normalized.endswith("/"):
                normalized = f"{normalized}/"
        elif len(normalized) > 1 and normalized.endswith("/"):
            normalized = normalized.rstrip("/")

        return normalized


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
    await server.run_from_settings(settings)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
