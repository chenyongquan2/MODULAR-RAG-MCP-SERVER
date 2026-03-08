"""JSON-RPC 协议处理。"""

from typing import Any, Callable, Dict

from mcp.types import Tool, TextContent

from observability.logger import get_logger

logger = get_logger(__name__)


class JSONRPCError(Exception):
    """JSON-RPC 2.0 错误。"""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        """初始化 JSON-RPC 错误。

        Args:
            code: 错误码（JSON-RPC 2.0 规范）
            message: 错误消息
            data: 额外的错误数据
        """
        self.code = code
        self.message = message
        self.data = data
        super().__init__(message)


# JSON-RPC 2.0 标准错误码
class ErrorCodes:
    """JSON-RPC 2.0 错误码。"""

    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603


class ProtocolHandler:
    """MCP 协议处理器。

    负责：
    1. 处理 JSON-RPC 2.0 协议消息
    2. 管理工具注册和路由
    3. 能力协商（server info/methods）
    4. 规范的错误处理
    """

    def __init__(self) -> None:
        """初始化 ProtocolHandler。"""
        self._tools: Dict[str, Tool] = {}
        self._tool_handlers: Dict[str, Callable] = {}

    def register_tool(self, tool: Tool, handler: Callable) -> None:
        """注册工具及其处理函数。

        Args:
            tool: 工具定义（包含 name, description, inputSchema）
            handler: 工具处理函数，签名应为 async def handler(arguments: dict) -> Any
        """
        if not tool.name:
            raise ValueError("Tool name is required")

        self._tools[tool.name] = tool
        self._tool_handlers[tool.name] = handler
        logger.info("Registered tool: %s", tool.name)

    def get_tool(self, name: str) -> Tool | None:
        """获取工具定义。

        Args:
            name: 工具名称

        Returns:
            工具定义，如果不存在则返回 None
        """
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        """列出所有已注册的工具。

        Returns:
            工具列表
        """
        return list(self._tools.values())

    async def handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        """处理 initialize 请求。

        Args:
            params: 请求参数

        Returns:
            响应，包含 serverInfo 和 capabilities
        """
        logger.info("Handling initialize request")

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

    def handle_tools_list(self) -> dict[str, Any]:
        """处理 tools/list 请求。

        Returns:
            响应，包含已注册工具的列表
        """
        logger.info("Handling tools/list request")

        tools = []
        for tool in self.list_tools():
            tools.append({
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.inputSchema,
            })

        return {"tools": tools}

    async def handle_tools_call(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> list[TextContent] | dict[str, Any]:
        """处理 tools/call 请求。

        Args:
            name: 工具名称
            arguments: 工具参数

        Returns:
            工具执行结果

        Raises:
            JSONRPCError: 如果工具不存在或执行失败
        """
        logger.info("Handling tools/call request for tool: %s", name)

        # 检查工具是否存在
        if name not in self._tools:
            raise JSONRPCError(
                ErrorCodes.METHOD_NOT_FOUND,
                f"Tool not found: {name}",
            )

        # 检查工具处理函数是否存在
        if name not in self._tool_handlers:
            raise JSONRPCError(
                ErrorCodes.INTERNAL_ERROR,
                f"Tool handler not found: {name}",
            )

        # 调用工具处理函数
        handler = self._tool_handlers[name]

        try:
            result = await handler(arguments)
            logger.info("Tool %s executed successfully", name)
            return result
        except JSONRPCError:
            # 重新抛出 JSON-RPC 错误
            raise
        except ValueError as e:
            # 参数错误
            raise JSONRPCError(
                ErrorCodes.INVALID_PARAMS,
                f"Invalid parameters for tool {name}: {str(e)}",
            )
        except Exception as e:
            # 内部错误，不泄露堆栈
            logger.error(
                "Error executing tool %s: %s",
                name,
                e,
                exc_info=True,
            )
            raise JSONRPCError(
                ErrorCodes.INTERNAL_ERROR,
                f"Internal error executing tool {name}",
            )

    def handle_jsonrpc_error(self, error: JSONRPCError) -> dict[str, Any]:
        """将 JSONRPCError 转换为 JSON-RPC 错误响应。

        Args:
            error: JSON-RPC 错误

        Returns:
            错误响应字典
        """
        error_response = {
            "code": error.code,
            "message": error.message,
        }

        if error.data is not None:
            error_response["data"] = error.data

        return {"error": error_response}
