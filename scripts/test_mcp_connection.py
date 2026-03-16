"""测试 MCP Server 连接。

此脚本通过 stdio 协议连接到本地 MCP Server，测试 list_collections 工具。
"""

import asyncio
import json
import sys
from pathlib import Path

# 将 src 目录添加到 Python 路径
src_path = Path(__file__).parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_mcp_server():
    """测试 MCP Server 连接。"""
    server_params = StdioServerParameters(
        command="python",
        args=["C:/workspace/MODULAR-RAG-MCP-SERVER/main.py"],
    )

    print("启动 MCP Server...")
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # 初始化
            print("初始化会话...")
            await session.initialize()

            # 列出可用工具
            print("\n列出可用工具:")
            tools = await session.list_tools()
            for tool in tools.tools:
                print(f"  - {tool.name}: {tool.description}")

            # 测试 list_collections 工具
            print("\n调用 list_collections 工具:")
            try:
                result = await session.call_tool("list_collections", {})
                for content in result.content:
                    if hasattr(content, "text"):
                        print(content.text)
            except Exception as e:
                print(f"错误: {e}")

            # 测试 query_knowledge_hub 工具
            print("\n调用 query_knowledge_hub 工具 (查询 '北极星'):")
            try:
                result = await session.call_tool(
                    "query_knowledge_hub",
                    {
                        "query": "北极星",
                        "top_k": 5,
                        "collection": "default"
                    }
                )
                for content in result.content:
                    if hasattr(content, "text"):
                        print(content.text)
            except Exception as e:
                print(f"错误: {e}")


if __name__ == "__main__":
    print("=" * 60)
    print("MCP Server 连接测试")
    print("=" * 60)
    asyncio.run(test_mcp_server())
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)