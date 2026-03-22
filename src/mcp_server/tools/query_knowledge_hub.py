"""主检索工具 - query_knowledge_hub。"""

from __future__ import annotations

from typing import Any, Dict

from mcp.types import TextContent

from src.core.query_engine.fusion import HybridSearch
from src.core.response.response_builder import ResponseBuilder
from src.core.response.citation_generator import StructuredContent
from src.core.types import RetrievalResult

from observability.logger import get_logger

logger = get_logger(__name__)


class QueryKnowledgeHubTool:
    """知识库查询工具。

    这是 MCP Server 的核心工具，负责：
    1. 调用 HybridSearch 进行混合检索（Dense + Sparse + RRF + Rerank）
    2. 调用 ResponseBuilder 生成响应（LLM + 引用）
    3. 返回结构化的响应内容（Markdown + Citations）

    Design Principles Applied:
    - Pluggable: 所有组件通过注入提供
    - Fail-Fast: 验证输入参数
    - Graceful Degradation: 检索失败时返回友好提示

    Example:
        >>> tool = QueryKnowledgeHubTool(hybrid_search, response_builder)
        >>> result = await tool.execute({"query": "How to configure LLM?", "top_k": 5})
        >>> result[0].text  # Markdown 内容
        >>> result[1]  # citations 结构
    """

    def __init__(
        self,
        hybrid_search: HybridSearch,
        response_builder: ResponseBuilder,
    ) -> None:
        """初始化 QueryKnowledgeHubTool。

        Args:
            hybrid_search: 混合检索引擎实例
            response_builder: 响应构建器实例

        Raises:
            ValueError: 如果参数为 None
        """
        if hybrid_search is None:
            raise ValueError("hybrid_search cannot be None")
        if response_builder is None:
            raise ValueError("response_builder cannot be None")

        self._hybrid_search = hybrid_search
        self._response_builder = response_builder

    async def execute(self, arguments: Dict[str, Any]) -> list[TextContent | dict[str, Any]]:
        """执行知识库查询。

        Args:
            arguments: 工具参数，包含：
                - query (str, required): 用户查询
                - top_k (int, optional): 返回结果数量，默认 10
                - filters (dict, optional): 元数据过滤条件

        Returns:
            包含 Markdown 内容和引用列表的响应

        Raises:
            ValueError: 如果参数无效
        """
        # 1. 验证参数
        query: str = arguments.get("query", "")
        if not query or not query.strip():
            raise ValueError("Query parameter is required and cannot be empty")

        top_k: int = arguments.get("top_k", 10)
        if not isinstance(top_k, int) or top_k <= 0:
            raise ValueError("top_k must be a positive integer")

        filters: Dict[str, Any] = arguments.get("filters", {})

        logger.info(
            "Executing query_knowledge_hub: query='%s', top_k=%d, filters=%s",
            query,
            top_k,
            filters,
        )

        try:
            # 2. 执行混合检索
            results: list[RetrievalResult] = self._hybrid_search.search(
                query=query,
                top_k=top_k,
                filters=filters,
                trace=None,
            )

            logger.info("HybridSearch returned %d results", len(results))

            if not results:
                # 无结果时返回友好提示
                return [
                    TextContent(
                        type="text",
                        text="未找到相关内容。请尝试使用不同的关键词或确认已摄取相关文档。",
                    )
                ]

            # 3. 构建响应（LLM 生成 + 引用）
            structured_content: StructuredContent = self._response_builder.build(
                query=query,
                results=results,
                trace=None,
            )

            logger.info(
                "Response built: %d characters, %d citations",
                len(structured_content.markdown),
                len(structured_content.citations),
            )

            # 4. 构建返回格式
            # MCP 工具返回格式：[TextContent, dict(citations)]
            return [
                TextContent(
                    type="text",
                    text=structured_content.markdown,
                ),
                {
                    "citations": [
                        {
                            "id": c.id,
                            "source": c.source,
                            "page": c.page,
                            "chunk_id": c.chunk_id,
                            "score": c.score,
                            "text": c.text,
                        }
                        for c in structured_content.citations
                    ]
                },
            ]

        except ValueError:
            # 重新抛出参数验证错误
            raise
        except Exception as e:
            # 其他错误记录日志并返回友好提示
            logger.error("Error executing query_knowledge_hub: %s", e, exc_info=True)
            return [
                TextContent(
                    type="text",
                    text=f"查询过程中发生错误：{str(e)}。请稍后重试。",
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
            "name": "query_knowledge_hub",
            "description": (
                "基于混合检索（Dense + Sparse + RRF + Rerank）"
                "查询知识库，并生成包含引用的响应。\n\n"
                "## 可用的 metadata 过滤字段\n\n"
                "你可以根据用户问题的特征，自动推断合适的 filters：\n\n"
                "| 字段 | 说明 | 示例值 |\n"
                "|------|------|--------|\n"
                "| collection | 文档所属集合 | 'docs', 'wiki', 'manual' |\n"
                "| doc_type | 文档类型 | 'pdf', 'markdown' |\n"
                "| source_path | 源文件路径 | '/docs/api.pdf' |\n"
                "| title | 文档标题 | 'API Reference' |\n"
                "| tags | 标签（数组） | ['API', 'configuration'] |\n"
                "| author | 作者 | '张三' |\n\n"
                "## 自动推断示例\n\n"
                "- 用户问「PDF 文档中关于 API 的内容」→ filters={\"doc_type\": \"pdf\"}\n"
                "- 用户问「在 wiki 集合中查找配置方法」→ filters={\"collection\": \"wiki\"}\n"
                "- 用户问「张三写的文档」→ filters={\"author\": \"张三\"}\n"
                "- 用户无明确限定 → 不传 filters（全库搜索）\n\n"
                "注意：先调用 list_collections 获取可用集合列表。"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "用户查询问题",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回结果数量，默认 10",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 50,
                    },
                    "filters": {
                        "type": "object",
                        "description": (
                            "元数据过滤条件。根据用户问题自动推断：\n"
                            "- collection: 集合名称（先调用 list_collections 获取可用值）\n"
                            "- doc_type: 文档类型，如 'pdf', 'markdown'\n"
                            "- source_path: 源文件路径\n"
                            "- title: 文档标题关键词\n"
                            "- tags: 标签数组\n"
                            "- author: 作者名称\n"
                            "示例：{\"collection\": \"docs\", \"doc_type\": \"pdf\"}"
                        ),
                        "properties": {
                            "collection": {
                                "type": "string",
                                "description": "文档集合名称，如 'docs', 'wiki'",
                            },
                            "doc_type": {
                                "type": "string",
                                "description": "文档类型：'pdf' 或 'markdown'",
                                "enum": ["pdf", "markdown"],
                            },
                            "source_path": {
                                "type": "string",
                                "description": "源文件路径（部分匹配）",
                            },
                            "title": {
                                "type": "string",
                                "description": "文档标题关键词",
                            },
                            "author": {
                                "type": "string",
                                "description": "文档作者",
                            },
                        },
                        "additionalProperties": {
                            "type": "string",
                        },
                    },
                },
                "required": ["query"],
            },
        }