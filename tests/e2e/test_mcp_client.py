"""MCP Client 端到端测试。

通过子进程启动 MCP Server（stdio transport），模拟客户端执行：
1. initialize
2. tools/list
3. tools/call(query_knowledge_hub)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def _write_mock_server_script(script_path: Path) -> None:
    """写入用于 E2E 测试的 MCP Server 启动脚本。

    说明：
        为保证测试稳定，不依赖真实 LLM/Embedding/向量库，本脚本会在
        子进程中 monkeypatch `src.mcp_server.server` 的依赖实现。
    """
    script_path.write_text(
        """
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from src.core.response.citation_generator import Citation, StructuredContent
from src.core.types import RetrievalResult
import src.mcp_server.server as server_mod


class _FakeSettings:
    def __init__(self) -> None:
        self.llm = SimpleNamespace(provider="fake", model="fake-model")
        self.embedding = SimpleNamespace(provider="fake", model="fake-embedding")
        self.vector_store = SimpleNamespace(backend="fake-store")


class _FakeHybridSearch:
    def __init__(self, settings: object) -> None:
        self._settings = settings

    def search(
        self,
        query: str,
        top_k: int,
        filters: dict[str, str] | None = None,
        trace: object | None = None,
    ) -> list[RetrievalResult]:
        del filters, trace
        return [
            RetrievalResult(
                chunk_id="chunk-test-001",
                score=0.98,
                text=f"mock result for: {query}",
                metadata={"source_path": "tests/fixtures/sample_documents/mock.pdf", "page": 1},
            )
        ][:top_k]


class _FakeResponseBuilder:
    def __init__(self, settings: object) -> None:
        self._settings = settings

    def build(
        self,
        query: str,
        results: list[RetrievalResult],
        trace: object | None = None,
    ) -> StructuredContent:
        del trace
        first = results[0]
        return StructuredContent(
            markdown=f"answer for '{query}' [1]",
            citations=[
                Citation(
                    id=1,
                    source=first.metadata.get("source_path", "unknown"),
                    page=first.metadata.get("page"),
                    chunk_id=first.chunk_id,
                    score=first.score,
                    text=first.text,
                )
            ],
        )


def _fake_load_settings() -> _FakeSettings:
    return _FakeSettings()


async def _main() -> None:
    server_mod.load_settings = _fake_load_settings
    server_mod.HybridSearch = _FakeHybridSearch
    server_mod.ResponseBuilder = _FakeResponseBuilder
    server = server_mod.MCPServer()
    await server.run()


if __name__ == "__main__":
    asyncio.run(_main())
""".strip()
        + "\n",
        encoding="utf-8",
    )


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_mcp_client_can_list_and_call_query_tool(tmp_path: Path) -> None:
    """验证 MCP 客户端可通过 stdio 调用服务端工具。"""
    script_path = tmp_path / "mock_mcp_server.py"
    _write_mock_server_script(script_path)

    env = os.environ.copy()
    project_root = str(Path.cwd())
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = project_root + (
        os.pathsep + existing_pythonpath if existing_pythonpath else ""
    )

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(script_path)],
        cwd=project_root,
        env=env,
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            init_result = await session.initialize()
            assert init_result.serverInfo.name == "modular-rag-mcp-server"

            tools_result = await session.list_tools()
            tool_names = {tool.name for tool in tools_result.tools}
            assert "query_knowledge_hub" in tool_names

            call_result = await session.call_tool(
                "query_knowledge_hub",
                {"query": "what is modular rag", "top_k": 1, "use_llm": True},
            )
            assert call_result.content, "Tool call should return at least one content block"

            text_blocks = [
                block.text
                for block in call_result.content
                if getattr(block, "type", "") == "text"
            ]
            merged_text = "\n".join(text_blocks)
            assert "answer for 'what is modular rag'" in merged_text
            assert "=== Citations ===" in merged_text
            assert "chunk-test-001" in merged_text
