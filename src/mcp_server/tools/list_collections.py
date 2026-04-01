"""列出集合工具 - list_collections。"""

from __future__ import annotations

from typing import Any, Dict

from mcp.types import TextContent

from src.core.settings import Settings
from src.libs.vector_store.base_vector_store import BaseVectorStore
from src.libs.vector_store.vector_store_factory import VectorStoreFactory

from src.observability.logger import get_logger

logger = get_logger(__name__)


class ListCollectionsTool:
    """列出可用集合的工具。

    用于列出知识库中可用的文档集合，并提供统计信息。

    Design Principles Applied:
    - Pluggable: 通过 VectorStoreFactory 支持不同后端
    - Fail-Fast: 验证组件初始化
    - Graceful Degradation: 后端失败时返回友好提示

    Example:
        >>> tool = ListCollectionsTool(settings)
        >>> result = await tool.execute({})
        >>> result[0].text  # 返回集合列表的文本
    """

    def __init__(self, settings: Settings) -> None:
        """初始化 ListCollectionsTool。

        Args:
            settings: 应用程序配置

        Raises:
            ValueError: 如果 settings 为 None
            RuntimeError: 如果向量存储初始化失败
        """
        if settings is None:
            raise ValueError("settings cannot be None")

        self._settings = settings
        self._vector_store: BaseVectorStore | None = None

    def _init_vector_store(self) -> None:
        """延迟初始化向量存储。"""
        if self._vector_store is None:
            try:
                self._vector_store = VectorStoreFactory.create(self._settings)
                logger.info(
                    "Vector store initialized: %s",
                    self._vector_store.get_backend_name(),
                )
            except Exception as e:
                logger.error("Failed to initialize vector store: %s", e, exc_info=True)
                raise RuntimeError(f"Failed to initialize vector store: {e}") from e

    async def execute(self, arguments: Dict[str, Any]) -> list[TextContent]:
        """执行列出集合操作。

        Args:
            arguments: 工具参数（当前无必需参数）

        Returns:
            包含集合列表和统计信息的 TextContent

        Raises:
            RuntimeError: 如果向量存储初始化失败
        """
        logger.info("Executing list_collections")

        try:
            # 初始化向量存储
            self._init_vector_store()

            # 获取集合列表
            collections = self._vector_store.get_collection_names()

            if not collections:
                # 无集合时返回友好提示
                return [
                    TextContent(
                        type="text",
                        text="当前没有可用的集合。请先使用摄取功能导入文档。",
                    )
                ]

            # 构建返回文本
            collection_list = "\n".join(
                f"- {col}" for col in sorted(collections)
            )

            response_text = (
                f"可用的集合（共 {len(collections)} 个）：\n\n"
                f"{collection_list}\n\n"
                "提示：使用 query_knowledge_hub 工具时，"
                "可以通过 filters 参数指定集合名称进行过滤。"
            )

            logger.info(
                "Listed %d collections: %s",
                len(collections),
                ", ".join(sorted(collections)),
            )

            return [TextContent(type="text", text=response_text)]

        except RuntimeError:
            # 重新抛出初始化错误
            raise
        except Exception as e:
            # 其他错误记录日志并返回友好提示
            logger.error("Error executing list_collections: %s", e, exc_info=True)
            return [
                TextContent(
                    type="text",
                    text=f"获取集合列表时发生错误：{str(e)}。请稍后重试。",
                )
            ]

    @staticmethod
    def get_tool_definition() -> Dict[str, Any]:
        """获取工具定义。

        返回符合 MCP Tool 规范的定义。

        Returns:
            工具定义字典
        """
        return {
            "name": "list_collections",
            "description": (
                "列出知识库中所有可用的文档集合。\n\n"
                "## 使用场景\n\n"
                "在调用 query_knowledge_hub 之前，先调用此工具获取可用集合列表，"
                "以便根据用户问题推断合适的 collection filter。\n\n"
                "## 示例流程\n\n"
                "1. 用户问「在技术文档中查找 API 配置」\n"
                "2. 先调用 list_collections 获取：['tech_docs', 'wiki', 'manual']\n"
                "3. 推断 'tech_docs' 最相关\n"
                "4. 调用 query_knowledge_hub(query='API 配置', filters={'collection': 'tech_docs'})"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        }
