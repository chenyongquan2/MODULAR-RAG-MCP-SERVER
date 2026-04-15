"""MCP Server transport 相关单元测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import main as main_module
from src.mcp_server.server import MCPServer


def _fake_settings(transport: str) -> SimpleNamespace:
    """构造最小可用 settings mock。"""
    return SimpleNamespace(
        llm=SimpleNamespace(provider="fake", model="fake"),
        embedding=SimpleNamespace(provider="fake", model="fake"),
        vector_store=SimpleNamespace(backend="fake"),
        mcp_server=SimpleNamespace(
            transport=transport,
            host="0.0.0.0",
            port=18080,
            sse_path="/stream",
            message_path="/ingress/",
        ),
    )


class TestPathNormalize:
    """路径规范化测试。"""

    def test_normalize_sse_path(self) -> None:
        """SSE 路径应补充前导斜杠并去掉尾斜杠。"""
        normalized = MCPServer._normalize_path("sse/", trailing_slash=False)
        assert normalized == "/sse"

    def test_normalize_message_path(self) -> None:
        """message 路径应补充前导/尾部斜杠。"""
        normalized = MCPServer._normalize_path("messages", trailing_slash=True)
        assert normalized == "/messages/"

    def test_empty_path_raises(self) -> None:
        """空路径应抛出 ValueError。"""
        with pytest.raises(ValueError, match="Path must not be empty"):
            MCPServer._normalize_path(" ", trailing_slash=False)


@pytest.mark.asyncio
async def test_run_sse_wires_uvicorn_and_transport() -> None:
    """run_sse 应正确创建 SSE transport 并启动 uvicorn。"""
    server = MCPServer()
    server._initialize_runtime = AsyncMock()  # type: ignore[method-assign]

    with (
        patch("src.mcp_server.server.SseServerTransport") as mock_transport_cls,
        patch("src.mcp_server.server.uvicorn.Config") as mock_config_cls,
        patch("src.mcp_server.server.uvicorn.Server") as mock_server_cls,
    ):
        mock_uvicorn_server = mock_server_cls.return_value
        mock_uvicorn_server.serve = AsyncMock(return_value=True)

        await server.run_sse(
            host="0.0.0.0",
            port=18080,
            sse_path="stream",
            message_path="ingress",
        )

        mock_transport_cls.assert_called_once_with("/ingress/")
        _, kwargs = mock_config_cls.call_args
        assert kwargs["host"] == "0.0.0.0"
        assert kwargs["port"] == 18080
        mock_uvicorn_server.serve.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_from_settings_dispatches_sse() -> None:
    """run_from_settings 在 sse 配置下应调用 run_sse。"""
    server = MCPServer()
    server.run = AsyncMock()  # type: ignore[method-assign]
    server.run_sse = AsyncMock()  # type: ignore[method-assign]

    settings = _fake_settings("sse")
    await server.run_from_settings(settings)  # type: ignore[arg-type]

    server.run.assert_not_called()
    server.run_sse.assert_awaited_once_with(
        host="0.0.0.0",
        port=18080,
        sse_path="/stream",
        message_path="/ingress/",
    )


@pytest.mark.asyncio
async def test_run_from_settings_dispatches_stdio() -> None:
    """run_from_settings 在 stdio 配置下应调用 run。"""
    server = MCPServer()
    server.run = AsyncMock()  # type: ignore[method-assign]
    server.run_sse = AsyncMock()  # type: ignore[method-assign]

    settings = _fake_settings("stdio")
    await server.run_from_settings(settings)  # type: ignore[arg-type]

    server.run.assert_awaited_once()
    server.run_sse.assert_not_called()


@pytest.mark.asyncio
async def test_run_from_settings_raises_on_unknown_transport() -> None:
    """run_from_settings 遇到未知 transport 应抛出 ValueError。"""
    server = MCPServer()
    settings = _fake_settings("websocket")

    with pytest.raises(ValueError, match="websocket"):
        await server.run_from_settings(settings)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_main_calls_run_from_settings() -> None:
    """main.main 应加载配置并委托给 run_from_settings。"""
    settings = _fake_settings("stdio")

    with (
        patch("main.load_settings", return_value=settings),
        patch("main.MCPServer") as mock_server_cls,
    ):
        server_instance = mock_server_cls.return_value
        server_instance.run_from_settings = AsyncMock()

        await main_module.main()

        server_instance.run_from_settings.assert_awaited_once_with(settings)
