"""测试 MCP Server 连接（支持 stdio / SSE）。

示例：
    python scripts/test_mcp_connection.py --transport stdio
    python scripts/test_mcp_connection.py --transport sse --server-url http://127.0.0.1:8000/sse
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client


def _build_arg_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="MCP Server 连通性测试")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="连接方式：stdio 或 sse（默认 stdio）",
    )
    parser.add_argument(
        "--server-command",
        default=sys.executable,
        help="stdio 模式下用于启动 server 的命令（默认当前 Python）",
    )
    parser.add_argument(
        "--server-script",
        default="main.py",
        help="stdio 模式下 server 启动脚本（默认 main.py）",
    )
    parser.add_argument(
        "--server-url",
        default="http://127.0.0.1:8000/sse",
        help="sse 模式下服务端 SSE URL（默认 http://127.0.0.1:8000/sse）",
    )
    parser.add_argument(
        "--query",
        default="北极星",
        help="用于测试 query_knowledge_hub 的查询文本",
    )
    parser.add_argument(
        "--collection",
        default="default",
        help="用于测试 query_knowledge_hub 的集合名",
    )
    parser.add_argument(
        "--skip-query",
        action="store_true",
        help="仅验证 initialize/list_tools/list_collections，不调用 query_knowledge_hub",
    )
    return parser


def _print_text_blocks(result: Any) -> None:
    """打印 MCP 工具返回中的 text blocks。"""
    for content in getattr(result, "content", []):
        text = getattr(content, "text", None)
        if isinstance(text, str):
            print(text)


async def _run_session_checks(
    session: ClientSession,
    query: str,
    collection: str,
    skip_query: bool,
) -> None:
    """执行统一的 MCP 会话检查流程。"""
    print("初始化会话...")
    init_result = await session.initialize()
    print(
        f"初始化成功: server={init_result.serverInfo.name} "
        f"version={init_result.serverInfo.version}"
    )

    print("\n列出可用工具:")
    tools = await session.list_tools()
    for tool in tools.tools:
        print(f"  - {tool.name}: {tool.description}")

    print("\n调用 list_collections 工具:")
    try:
        result = await session.call_tool("list_collections", {})
        _print_text_blocks(result)
    except Exception as exc:
        print(f"list_collections 调用失败: {exc}")

    if skip_query:
        return

    print(f"\n调用 query_knowledge_hub 工具 (查询 '{query}'):")
    try:
        result = await session.call_tool(
            "query_knowledge_hub",
            {"query": query, "top_k": 5, "collection": collection},
        )
        _print_text_blocks(result)
    except Exception as exc:
        print(f"query_knowledge_hub 调用失败: {exc}")


async def test_mcp_server(args: argparse.Namespace) -> None:
    """按指定 transport 连接 MCP Server 并测试核心方法。"""
    if args.transport == "stdio":
        project_root = Path(__file__).parent.parent.resolve()
        server_script = str((project_root / args.server_script).resolve())
        server_params = StdioServerParameters(
            command=args.server_command,
            args=[server_script],
            cwd=str(project_root),
        )
        print(f"启动 stdio MCP Server: {args.server_command} {server_script}")
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await _run_session_checks(
                    session, args.query, args.collection, args.skip_query
                )
    else:
        print(f"连接 SSE MCP Server: {args.server_url}")
        async with sse_client(args.server_url) as (read, write):
            async with ClientSession(read, write) as session:
                await _run_session_checks(
                    session, args.query, args.collection, args.skip_query
                )


if __name__ == "__main__":
    cli_args = _build_arg_parser().parse_args()
    print("=" * 60)
    print(f"MCP Server 连接测试（transport={cli_args.transport}）")
    print("=" * 60)
    asyncio.run(test_mcp_server(cli_args))
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
