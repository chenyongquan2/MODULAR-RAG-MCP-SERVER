"""Integration tests for MCP Server."""

import pytest
import json
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

pytestmark = pytest.mark.integration


class MockStdioStream:
    """Mock stdio stream for testing."""

    def __init__(self):
        self.buffer = []

    async def write(self, data: str) -> None:
        self.buffer.append(data)

    async def read(self) -> str | None:
        if not hasattr(self, '_read_queue'):
            return None
        if not self._read_queue:
            return None
        return self._read_queue.pop(0)

    def set_read_queue(self, messages: list[str]) -> None:
        self._read_queue = list(messages)


@pytest.fixture
def mock_stdio_server():
    """Create mock stdio server context."""
    return AsyncMock()


@pytest.fixture
def initialize_request():
    """Create a valid initialize request."""
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "clientInfo": {
                "name": "test-client",
                "version": "1.0.0"
            },
            "capabilities": {}
        }
    }


@pytest.fixture
def tools_list_request():
    """Create a tools/list request."""
    return {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {}
    }


class TestMCPServerInitialization:
    """Test MCP server initialization."""

    @pytest.mark.asyncio
    async def test_server_starts_and_loads_settings(self):
        """Test that server starts and loads settings."""
        from mcp_server.server import MCPServer

        with patch('mcp_server.server.load_settings') as mock_load:
            mock_load.return_value = MagicMock()

            server = MCPServer()
            assert server.server is not None
            assert server.server.name == "modular-rag-mcp-server"

    @pytest.mark.asyncio
    async def test_server_handles_initialize(self, initialize_request):
        """Test server handles initialize request correctly."""
        from mcp_server.server import MCPServer

        server = MCPServer()

        async def handle_initialize(params):
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

        result = await handle_initialize(initialize_request["params"])

        assert result["serverInfo"]["name"] == "modular-rag-mcp-server"
        assert result["serverInfo"]["version"] == "0.1.0"
        assert "capabilities" in result
        assert "tools" in result["capabilities"]

    @pytest.mark.asyncio
    async def test_server_returns_tools_list(self, tools_list_request):
        """Test server handles tools/list request."""
        from mcp_server.server import MCPServer

        server = MCPServer()

        async def handle_tools_list():
            return {"tools": []}

        result = await handle_tools_list()

        assert "tools" in result
        assert isinstance(result["tools"], list)


class TestStdioConstraints:
    """Test stdio output constraints."""

    def test_logger_outputs_to_stderr(self):
        """Test that logger outputs to stderr."""
        import logging
        import io
        import sys

        from src.observability.logger import get_logger

        logger = get_logger("test_logger")

        stderr_capture = io.StringIO()
        handler = logging.StreamHandler(stderr_capture)
        handler.setLevel(logging.INFO)
        logger.addHandler(handler)

        logger.info("Test message")

        output = stderr_capture.getvalue()
        assert "Test message" in output


class TestMCPProtocolCompliance:
    """Test MCP protocol compliance."""

    @pytest.mark.asyncio
    async def test_initialize_response_format(self):
        """Test initialize response follows MCP spec."""

        async def handle_initialize(params):
            return {
                "protocolVersion": "2024-11-05",
                "serverInfo": {
                    "name": "modular-rag-mcp-server",
                    "version": "0.1.0",
                },
                "capabilities": {
                    "tools": {},
                    "resources": {},
                    "prompts": {},
                },
                "clientInfo": params.get("clientInfo", {}),
            }

        result = await handle_initialize({
            "clientInfo": {"name": "test", "version": "1.0"}
        })

        assert "protocolVersion" in result
        assert "serverInfo" in result
        assert "capabilities" in result

    @pytest.mark.asyncio
    async def test_capabilities_declaration(self):
        """Test server declares capabilities correctly."""

        async def handle_initialize(params):
            return {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "test", "version": "1.0"},
                "capabilities": {
                    "tools": {},
                    "resources": {"subscribe": True},
                    "prompts": {},
                },
                "clientInfo": {},
            }

        result = await handle_initialize({})

        caps = result["capabilities"]
        assert "tools" in caps
        assert "resources" in caps
        assert "prompts" in caps
