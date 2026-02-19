"""MCP Server 启动入口。

启动 Modular RAG MCP Server，通过 Stdio Transport 提供 MCP 协议服务。
"""

import sys


def main() -> None:
    """MCP Server 主入口函数。"""
    print("Modular RAG MCP Server - Starting...", file=sys.stderr)


if __name__ == "__main__":
    main()
