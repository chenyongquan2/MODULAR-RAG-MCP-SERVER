"""MCP Server 入口 (Stdio Transport)。

遵循标准：stdout 只输出 MCP 消息，日志到 stderr。
"""

import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
    GetPromptResult,
    PromptMessage,
    Prompt,
    Resource,
    ResourceTemplate,
)

from core.settings import load_settings, SettingsError
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
        self._setup_handlers()

    def _setup_handlers(self) -> None:
        """设置 MCP 协议处理器。"""
        self.server.request_handlers.clear()

    async def run(self) -> None:
        """运行 MCP Server。"""
        logger.info("Starting MCP Server on stdio transport...")

        async def handle_initialize(params: Any) -> dict[str, Any]:
            logger.info("MCP Server initializing...")
            return {
                "protocolVersion": "2024-11-05",
                "serverInfo": {
                    "name": "modular-rag-mcp-server",
                    "version": "0.1.0",
                },
                "capabilities": {
                    "tools": {},
                    "resources": {"subscribe": True},
                    "prompts": {},
                },
                "clientInfo": params.get("clientInfo", {}),
            }

        async def handle_tools_list() -> dict[str, Any]:
            logger.info("Listing available tools...")
            return {"tools": []}

        async def handle_tools_call(
            name: str,
            arguments: Any,
        ) -> list[TextContent]:
            logger.info("Calling tool: %s", name)
            return [TextContent(type="text", text=f"Tool '{name}' is not implemented yet")]

        async def handle_prompts_list() -> dict[str, Any]:
            return {"prompts": []}

        async def handle_resources_list() -> dict[str, Any]:
            return {"resources": [], "resourceTemplates": []}

        self.server.request_handlers[
            self.server._protocol.initialize
        ] = handle_initialize
        self.server.request_handlers[
            self.server._protocol.tools_list
        ] = handle_tools_list
        self.server.request_handlers[
            self.server._protocol.tools_call
        ] = handle_tools_call
        self.server.request_handlers[
            self.server._protocol.prompts_list
        ] = handle_prompts_list
        self.server.request_handlers[
            self.server._protocol.resources_list
        ] = handle_resources_list

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
