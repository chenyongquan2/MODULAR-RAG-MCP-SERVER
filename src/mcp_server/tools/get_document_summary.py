"""文档摘要工具 - get_document_summary。

用于获取指定文档的摘要信息，包括标题、摘要和标签等元数据。
"""

from __future__ import annotations

from typing import Any, Dict

from mcp.types import TextContent

from src.core.settings import Settings
from src.libs.vector_store.base_vector_store import BaseVectorStore
from src.libs.vector_store.vector_store_factory import VectorStoreFactory

from src.observability.logger import get_logger

logger = get_logger(__name__)


class GetDocumentSummaryTool:
    """获取文档摘要的工具。

    用于根据文档 ID 获取文档的元数据摘要，包括标题、摘要、标签等信息。

    Design Principles Applied:
    - Pluggable: 通过 VectorStoreFactory 支持不同后端
    - Fail-Fast: 验证文档 ID 是否有效
    - Graceful Degradation: 查询失败时返回友好提示

    Example:
        >>> tool = GetDocumentSummaryTool(settings)
        >>> result = await tool.execute({"doc_id": "abc123"})
        >>> result[0].text  # 返回文档摘要信息的文本
    """

    def __init__(self, settings: Settings) -> None:
        """初始化 GetDocumentSummaryTool。

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
        """执行获取文档摘要操作。

        Args:
            arguments: 工具参数，包含：
                - doc_id (str, required): 文档 ID

        Returns:
            包含文档摘要信息的 TextContent

        Raises:
            ValueError: 如果参数无效或文档不存在
            RuntimeError: 如果向量存储初始化失败
        """
        # 验证参数
        doc_id = arguments.get("doc_id", "")
        if not doc_id or not isinstance(doc_id, str):
            raise ValueError("doc_id parameter is required and must be a string")

        logger.info("Executing get_document_summary for doc_id: %s", doc_id)

        try:
            # 初始化向量存储
            self._init_vector_store()

            # 查询文档（通过 metadata 中的 source_ref 过滤）
            results = self._vector_store.query(
                vector=[0.0] * 1536,  # Dummy vector for metadata-only query
                top_k=1,
                filters={"source_ref": doc_id},
                trace=None,
            )

            if not results:
                return [
                    TextContent(
                        type="text",
                        text=f"未找到文档 ID 为 '{doc_id}' 的文档。"
                        "请确认文档 ID 是否正确或文档是否已被摄取。",
                    )
                ]

            # 提取第一个结果的元数据
            metadata = results[0].get("metadata", {})

            # 构建文档摘要信息
            summary_parts = []
            summary_parts.append(f"文档 ID: {doc_id}")

            # 提取 title
            title = metadata.get("title") or metadata.get("source_path", "未知")
            summary_parts.append(f"标题: {title}")

            # 提取 collection
            collection = metadata.get("collection", "默认集合")
            summary_parts.append(f"集合: {collection}")

            # 提取 doc_type
            doc_type = metadata.get("doc_type", "unknown")
            summary_parts.append(f"文档类型: {doc_type}")

            # 提取 summary（如果有）
            summary_text = metadata.get("summary")
            if summary_text:
                summary_parts.append(f"摘要: {summary_text}")

            # 提取 tags（如果有）
            tags = metadata.get("tags", [])
            if tags:
                tags_str = ", ".join(tags) if isinstance(tags, list) else str(tags)
                summary_parts.append(f"标签: {tags_str}")

            # 提取 chunk 数量（通过查询该文档的所有 chunks）
            all_chunks = self._vector_store.query(
                vector=[0.0] * 1536,
                top_k=100,  # 获取更多 chunks 以统计数量
                filters={"source_ref": doc_id},
                trace=None,
            )
            chunk_count = len(all_chunks)
            summary_parts.append(f"Chunk 数量: {chunk_count}")

            # 提取图片信息（如果有）
            images = metadata.get("images", [])
            if images:
                image_count = len(images)
                summary_parts.append(f"包含图片: {image_count} 张")

            response_text = "\n".join(summary_parts)

            logger.info(
                "Document summary retrieved for doc_id=%s: title=%s, chunks=%d",
                doc_id,
                title,
                chunk_count,
            )

            return [TextContent(type="text", text=response_text)]

        except ValueError:
            # 重新抛出参数验证错误
            raise
        except RuntimeError:
            # 重新抛出初始化错误
            raise
        except Exception as e:
            # 其他错误记录日志并返回友好提示
            logger.error(
                "Error executing get_document_summary for doc_id=%s: %s",
                doc_id,
                e,
                exc_info=True,
            )
            return [
                TextContent(
                    type="text",
                    text=f"获取文档摘要时发生错误：{str(e)}。请稍后重试。",
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
            "name": "get_document_summary",
            "description": (
                "获取指定文档的摘要信息，包括标题、摘要、标签、"
                "集合、文档类型、Chunk 数量等元数据。"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": "文档 ID（通常是文档的 SHA256 哈希值）",
                    },
                },
                "required": ["doc_id"],
            },
        }