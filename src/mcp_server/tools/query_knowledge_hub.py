"""主检索工具 - query_knowledge_hub。

基于混合检索（Dense + Sparse + RRF + Rerank）查询知识库，
支持纯检索模式和 LLM 总结模式。

自 feature-002 起：纯检索模式同时附加命中 chunk 的图片（MCP ImageContent）。
LLM 总结模式的图片附加由 feature-002 US2 实现（本文件 use_llm=True 分支目前仍返回纯文本）。
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from mcp.types import ImageContent, TextContent

from src.core.query_engine.hybrid_search import HybridSearch
from src.core.response.multimodal_assembler import MultimodalAssembler
from src.core.response.response_builder import ResponseBuilder
from src.core.response.citation_generator import StructuredContent
from src.core.trace.trace_collector import TraceCollector
from src.core.trace.trace_context import TraceContext
from src.core.types import RetrievalResult

from src.observability.logger import get_logger

logger = get_logger(__name__)


class QueryKnowledgeHubTool:
    """知识库查询工具。

    这是 MCP Server 的核心工具，负责：
    1. 调用 HybridSearch 进行混合检索（Dense + Sparse + RRF + Rerank）
    2. 支持纯检索模式和 LLM 总结模式（通过 use_llm 参数控制）
    3. 纯检索模式返回格式化的检索结果，不调用 LLM
    4. LLM 总结模式调用 ResponseBuilder 生成响应（LLM + 引用）

    Design Principles Applied:
    - Pluggable: 所有组件通过注入提供
    - Fail-Fast: 验证输入参数
    - Graceful Degradation: 检索失败时返回友好提示
    - 职责清晰: 检索层和生成层通过参数解耦

    Example:
        >>> tool = QueryKnowledgeHubTool(hybrid_search, response_builder)
        >>> # 纯检索模式
        >>> result = await tool.execute({"query": "HistoryRequest", "top_k": 5, "use_llm": False})
        >>> # LLM 总结模式
        >>> result = await tool.execute({"query": "What is RAG?", "top_k": 5, "use_llm": True})
    """

    def __init__(
        self,
        hybrid_search: HybridSearch,
        response_builder: ResponseBuilder,
        multimodal_assembler: MultimodalAssembler,
        max_images_per_response: int,
        trace_collector: Optional[TraceCollector] = None,
    ) -> None:
        """初始化 QueryKnowledgeHubTool。

        Args:
            hybrid_search: 混合检索引擎实例
            response_builder: 响应构建器实例
            multimodal_assembler: 多模态响应组装器（feature-002 新增）
            max_images_per_response: 单次响应附带图片数量上限（来自 settings.query.max_images_per_response）
            trace_collector: 可选的 trace 持久化器（feature-002 US3）；
                None 表示不 flush trace 到 jsonl（测试场景使用），
                生产侧 server.py 应传入 TraceCollector() 实例。

        Raises:
            ValueError: 如果 hybrid_search/response_builder/multimodal_assembler 为 None，
                或 max_images_per_response <= 0
        """
        if hybrid_search is None:
            raise ValueError("hybrid_search cannot be None")
        if response_builder is None:
            raise ValueError("response_builder cannot be None")
        if multimodal_assembler is None:
            raise ValueError("multimodal_assembler cannot be None")
        if not isinstance(max_images_per_response, int) or max_images_per_response <= 0:
            raise ValueError(
                "max_images_per_response must be a positive integer, "
                f"got {max_images_per_response!r}"
            )

        self._hybrid_search = hybrid_search
        self._response_builder = response_builder
        self._multimodal_assembler = multimodal_assembler
        self._max_images_per_response = max_images_per_response
        self._trace_collector = trace_collector

    async def execute(self, arguments: Dict[str, Any]) -> list[TextContent | ImageContent]:
        """执行知识库查询。

        Args:
            arguments: 工具参数，包含：
                - query (str, required): 用户查询
                - top_k (int, optional): 返回结果数量，默认 10
                - use_llm (bool, optional): 是否启用 LLM 生成，默认 False（纯检索模式）
                - filters (dict, optional): 元数据过滤条件

        Returns:
            列表，包含 TextContent 与 0~N 个 ImageContent：
            - use_llm=True: LLM 生成的 Markdown + 引用信息（ImageContent 附加由 US2 完成，当前仍为纯文本）
            - use_llm=False: 格式化的检索结果 + 命中 chunk 关联图片（feature-002 US1）

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

        use_llm: bool = bool(arguments.get("use_llm", False))

        filters: Dict[str, Any] = arguments.get("filters", {})

        logger.info(
            "Executing query_knowledge_hub: query='%s', top_k=%d, use_llm=%s, filters=%s",
            query,
            top_k,
            use_llm,
            filters,
        )

        # feature-002 US3：为本次查询创建 trace 上下文，供 assembler 写入 stage；
        # 若构造器注入了 trace_collector 则在 finally flush 到 jsonl。
        trace = TraceContext(trace_type="query")
        trace.add_metadata("query", query)
        trace.add_metadata("top_k", top_k)
        trace.add_metadata("use_llm", use_llm)

        try:
            # 2. 执行混合检索
            results: list[RetrievalResult] = self._hybrid_search.search(
                query=query,
                top_k=top_k,
                filters=filters,
                trace=trace,
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

            # 3. 根据模式决定返回内容
            if use_llm:
                # LLM 总结模式：调用 LLM 生成响应（feature-002 US2：同时附加命中 chunk 关联图片）
                structured_content: StructuredContent = self._response_builder.build(
                    query=query,
                    results=results,
                    trace=trace,
                )

                logger.info(
                    "Response built: %d characters, %d citations",
                    len(structured_content.markdown),
                    len(structured_content.citations),
                )

                # 将 citations 信息附加到文本末尾
                citations_text = "\n\n=== Citations ===\n"
                for c in structured_content.citations:
                    citations_text += f"\n[{c.id}] Source: {c.source}\n"
                    if c.page is not None:
                        citations_text += f"Page: {c.page}\n"
                    citations_text += f"Chunk ID: {c.chunk_id}\n"
                    citations_text += f"Score: {c.score:.4f}\n"
                    citations_text += f"Text: {c.text[:100]}...\n"

                llm_markdown = structured_content.markdown + citations_text

                # 调用 MultimodalAssembler 附加图片；若失败，降级为纯 TextContent（FR-006）
                try:
                    return self._multimodal_assembler.assemble(
                        markdown=llm_markdown,
                        results=results,
                        trace=trace,
                        max_images=self._max_images_per_response,
                    )
                except Exception as assemble_err:
                    logger.error(
                        "MultimodalAssembler.assemble failed in use_llm=True branch: %s. "
                        "Falling back to text-only response.",
                        assemble_err,
                        exc_info=True,
                    )
                    return [
                        TextContent(type="text", text=llm_markdown),
                    ]
            else:
                # 纯检索模式：返回格式化检索结果 + 命中 chunk 关联图片（feature-002 US1）
                formatted: str = self._format_search_results(results)

                logger.info("Formatted search results: %d characters", len(formatted))

                # MCP 协议要求返回值必须是 TextContent/ImageContent
                # 将 raw_results 作为 JSON 字符串附加到文本末尾
                raw_results_json = self._serialize_results(results)
                formatted_with_json = (
                    formatted + "\n\n=== Raw Results (JSON) ===\n" + json.dumps(raw_results_json, ensure_ascii=False, indent=2)
                )

                # 调用 MultimodalAssembler 附加图片；若 assembler 失败，降级为纯 TextContent（FR-006）
                try:
                    return self._multimodal_assembler.assemble(
                        markdown=formatted_with_json,
                        results=results,
                        trace=trace,
                        max_images=self._max_images_per_response,
                    )
                except Exception as assemble_err:
                    logger.error(
                        "MultimodalAssembler.assemble failed in use_llm=False branch: %s. "
                        "Falling back to text-only response.",
                        assemble_err,
                        exc_info=True,
                    )
                    return [
                        TextContent(type="text", text=formatted_with_json),
                    ]

        except ValueError:
            # 重新抛出参数验证错误；在 trace 里留痕以便区分"参数错误查询"与"成功查询"
            trace.add_metadata("error_type", "ValueError")
            raise
        except Exception as e:
            # 其他错误记录日志并返回友好提示
            logger.error("Error executing query_knowledge_hub: %s", e, exc_info=True)
            trace.add_metadata("error", str(e))
            return [
                TextContent(
                    type="text",
                    text=f"查询过程中发生错误：{str(e)}。请稍后重试。",
                )
            ]
        finally:
            # feature-002 US3：结束 trace 并（若配置了 collector）flush 到 jsonl
            trace.finish()
            if self._trace_collector is not None:
                try:
                    self._trace_collector.collect(trace)
                except Exception as collect_err:
                    # 观测失败不应影响主流程
                    logger.warning(
                        "Failed to collect query trace: %s",
                        collect_err,
                        exc_info=True,
                    )

    def _format_search_results(self, results: list[RetrievalResult]) -> str:
        """格式化检索结果（类似 CLI 输出格式）。

        Args:
            results: 检索结果列表

        Returns:
            格式化的文本字符串
        """
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"[{i}] Score: {r.score:.4f}")
            lines.append(f"    Chunk ID: {r.chunk_id}")
            if r.metadata.get("collection"):
                lines.append(f"    Collection: {r.metadata['collection']}")
            # 文本预览：最多显示 200 字符
            preview = r.text[:200] + "..." if len(r.text) > 200 else r.text
            lines.append(f"    Text: {preview}")
            lines.append("")
        return "\n".join(lines)

    def _serialize_results(self, results: list[RetrievalResult]) -> list[dict]:
        """序列化检索结果为 JSON 列表。

        Args:
            results: 检索结果列表

        Returns:
            序列化后的字典列表
        """
        return [
            {
                "chunk_id": r.chunk_id,
                "text": r.text,
                "score": r.score,
                "metadata": r.metadata,
            }
            for r in results
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
                    "use_llm": {
                        "type": "boolean",
                        "description": (
                            "是否启用 LLM 生成总结："
                            "false = 仅返回检索结果（纯检索模式），"
                            "true = 调用 LLM 生成答案（LLM 总结模式）。"
                            "默认 false，适合需要原始检索结果或快速响应的场景。"
                        ),
                        "default": False,
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