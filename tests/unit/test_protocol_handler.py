"""单元测试：Protocol Handler。"""

import pytest

from mcp.types import Tool, TextContent

from mcp_server.protocol_handler import (
    ErrorCodes,
    JSONRPCError,
    ProtocolHandler,
)


class TestProtocolHandler:
    """ProtocolHandler 单元测试。"""

    @pytest.fixture
    def handler(self) -> ProtocolHandler:
        """创建 ProtocolHandler 实例。"""
        return ProtocolHandler()

    @pytest.mark.asyncio
    async def test_register_tool(self, handler: ProtocolHandler) -> None:
        """测试工具注册。"""
        # 创建工具定义
        tool = Tool(
            name="test_tool",
            description="A test tool",
            inputSchema={"type": "object"},
        )

        # 创建处理函数
        async def mock_handler(arguments: dict) -> list[TextContent]:
            return [TextContent(type="text", text="test result")]

        # 注册工具
        handler.register_tool(tool, mock_handler)

        # 验证工具已注册
        assert handler.get_tool("test_tool") == tool
        assert len(handler.list_tools()) == 1

    def test_register_tool_without_name(self, handler: ProtocolHandler) -> None:
        """测试注册没有名称的工具应该抛出异常。"""
        tool = Tool(
            name="",
            description="A tool without name",
            inputSchema={"type": "object"},
        )

        async def mock_handler(arguments: dict) -> list[TextContent]:
            return [TextContent(type="text", text="test result")]

        with pytest.raises(ValueError, match="Tool name is required"):
            handler.register_tool(tool, mock_handler)

    @pytest.mark.asyncio
    async def test_get_nonexistent_tool(self, handler: ProtocolHandler) -> None:
        """测试获取不存在的工具应该返回 None。"""
        assert handler.get_tool("nonexistent") is None

    @pytest.mark.asyncio
    async def test_handle_initialize(self, handler: ProtocolHandler) -> None:
        """测试处理 initialize 请求。"""
        params = {"clientInfo": {"name": "test-client", "version": "1.0.0"}}

        result = await handler.handle_initialize(params)

        assert result["protocolVersion"] == "2024-11-05"
        assert result["serverInfo"]["name"] == "modular-rag-mcp-server"
        assert result["serverInfo"]["version"] == "0.1.0"
        assert "tools" in result["capabilities"]
        assert result["clientInfo"]["name"] == "test-client"

    def test_handle_tools_list_empty(self, handler: ProtocolHandler) -> None:
        """测试处理 tools/list 请求（无工具）。"""
        result = handler.handle_tools_list()

        assert "tools" in result
        assert result["tools"] == []

    @pytest.mark.asyncio
    async def test_handle_tools_list_with_tools(self, handler: ProtocolHandler) -> None:
        """测试处理 tools/list 请求（有工具）。"""
        # 注册工具
        tool = Tool(
            name="test_tool",
            description="A test tool",
            inputSchema={"type": "object", "properties": {"query": {"type": "string"}}},
        )

        async def mock_handler(arguments: dict) -> list[TextContent]:
            return [TextContent(type="text", text="test result")]

        handler.register_tool(tool, mock_handler)

        # 调用 tools/list
        result = handler.handle_tools_list()

        assert len(result["tools"]) == 1
        assert result["tools"][0]["name"] == "test_tool"
        assert result["tools"][0]["description"] == "A test tool"
        assert result["tools"][0]["inputSchema"]["type"] == "object"

    @pytest.mark.asyncio
    async def test_handle_tools_call_success(self, handler: ProtocolHandler) -> None:
        """测试成功调用工具。"""
        # 注册工具
        tool = Tool(
            name="test_tool",
            description="A test tool",
            inputSchema={"type": "object"},
        )

        async def mock_handler(arguments: dict) -> list[TextContent]:
            return [TextContent(type="text", text=f"Result: {arguments.get('data')}")]

        handler.register_tool(tool, mock_handler)

        # 调用工具
        result = await handler.handle_tools_call("test_tool", {"data": "test"})

        assert len(result) == 1
        assert result[0].type == "text"
        assert result[0].text == "Result: test"

    @pytest.mark.asyncio
    async def test_handle_tools_call_tool_not_found(
        self,
        handler: ProtocolHandler,
    ) -> None:
        """测试调用不存在的工具应该抛出 METHOD_NOT_FOUND 错误。"""
        with pytest.raises(JSONRPCError) as exc_info:
            await handler.handle_tools_call("nonexistent_tool", {})

        assert exc_info.value.code == ErrorCodes.METHOD_NOT_FOUND
        assert "Tool not found" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_handle_tools_call_invalid_params(
        self,
        handler: ProtocolHandler,
    ) -> None:
        """测试参数错误应该抛出 INVALID_PARAMS 错误。"""
        # 注册工具
        tool = Tool(
            name="test_tool",
            description="A test tool",
            inputSchema={"type": "object"},
        )

        async def mock_handler(arguments: dict) -> list[TextContent]:
            # 验证参数
            if "required_field" not in arguments:
                raise ValueError("Missing required_field")
            return [TextContent(type="text", text="OK")]

        handler.register_tool(tool, mock_handler)

        # 调用工具（缺少必需参数）
        with pytest.raises(JSONRPCError) as exc_info:
            await handler.handle_tools_call("test_tool", {})

        assert exc_info.value.code == ErrorCodes.INVALID_PARAMS
        assert "Invalid parameters" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_handle_tools_call_internal_error(
        self,
        handler: ProtocolHandler,
    ) -> None:
        """测试内部错误应该抛出 INTERNAL_ERROR 错误。"""
        # 注册工具
        tool = Tool(
            name="test_tool",
            description="A test tool",
            inputSchema={"type": "object"},
        )

        async def mock_handler(arguments: dict) -> list[TextContent]:
            raise RuntimeError("Something went wrong")

        handler.register_tool(tool, mock_handler)

        # 调用工具
        with pytest.raises(JSONRPCError) as exc_info:
            await handler.handle_tools_call("test_tool", {})

        assert exc_info.value.code == ErrorCodes.INTERNAL_ERROR
        assert "Internal error" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_handle_tools_call_jsonrpc_error_not_wrapped(
        self,
        handler: ProtocolHandler,
    ) -> None:
        """测试工具抛出 JSONRPCError 时应该直接重新抛出。"""
        # 注册工具
        tool = Tool(
            name="test_tool",
            description="A test tool",
            inputSchema={"type": "object"},
        )

        async def mock_handler(arguments: dict) -> list[TextContent]:
            raise JSONRPCError(
                ErrorCodes.METHOD_NOT_FOUND,
                "Custom JSON-RPC error",
            )

        handler.register_tool(tool, mock_handler)

        # 调用工具
        with pytest.raises(JSONRPCError) as exc_info:
            await handler.handle_tools_call("test_tool", {})

        assert exc_info.value.code == ErrorCodes.METHOD_NOT_FOUND
        assert exc_info.value.message == "Custom JSON-RPC error"

    def test_handle_jsonrpc_error(self, handler: ProtocolHandler) -> None:
        """测试将 JSONRPCError 转换为错误响应。"""
        error = JSONRPCError(
            ErrorCodes.METHOD_NOT_FOUND,
            "Tool not found",
            {"tool_name": "nonexistent"},
        )

        result = handler.handle_jsonrpc_error(error)

        assert "error" in result
        assert result["error"]["code"] == ErrorCodes.METHOD_NOT_FOUND
        assert result["error"]["message"] == "Tool not found"
        assert result["error"]["data"]["tool_name"] == "nonexistent"

    def test_handle_jsonrpc_error_without_data(self, handler: ProtocolHandler) -> None:
        """测试没有额外数据的错误响应。"""
        error = JSONRPCError(
            ErrorCodes.INTERNAL_ERROR,
            "Internal error",
        )

        result = handler.handle_jsonrpc_error(error)

        assert "error" in result
        assert result["error"]["code"] == ErrorCodes.INTERNAL_ERROR
        assert result["error"]["message"] == "Internal error"
        assert "data" not in result["error"]


class TestErrorCodes:
    """ErrorCodes 常量测试。"""

    def test_error_codes(self) -> None:
        """测试所有错误码都已定义。"""
        assert ErrorCodes.PARSE_ERROR == -32700
        assert ErrorCodes.INVALID_REQUEST == -32600
        assert ErrorCodes.METHOD_NOT_FOUND == -32601
        assert ErrorCodes.INVALID_PARAMS == -32602
        assert ErrorCodes.INTERNAL_ERROR == -32603


class TestJSONRPCError:
    """JSONRPCError 类测试。"""

    def test_jsonrpc_error_creation(self) -> None:
        """测试创建 JSONRPCError。"""
        error = JSONRPCError(
            ErrorCodes.METHOD_NOT_FOUND,
            "Method not found",
            {"method": "unknown"},
        )

        assert error.code == ErrorCodes.METHOD_NOT_FOUND
        assert error.message == "Method not found"
        assert error.data == {"method": "unknown"}

    def test_jsonrpc_error_without_data(self) -> None:
        """测试创建没有额外数据的 JSONRPCError。"""
        error = JSONRPCError(
            ErrorCodes.INTERNAL_ERROR,
            "Internal error",
        )

        assert error.code == ErrorCodes.INTERNAL_ERROR
        assert error.message == "Internal error"
        assert error.data is None
