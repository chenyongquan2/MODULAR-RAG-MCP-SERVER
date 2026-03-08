"""MCP Server 启动入口。

启动 Modular RAG MCP Server，通过 Stdio Transport 提供 MCP 协议服务。
"""

import sys
import asyncio

from core.settings import SettingsError, load_settings
from mcp_server.server import MCPServer
from observability.logger import get_logger

logger = get_logger(__name__)


async def main() -> None:
    """MCP Server 主入口函数。"""
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
    logger.info("Modular RAG MCP Server - Starting on stdio transport...")

    server = MCPServer()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())
