"""响应构建器。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.core.settings import Settings
from src.core.types import RetrievalResult
from src.libs.llm.base_llm import BaseLLM
from src.libs.llm.llm_factory import LLMFactory

from .citation_generator import Citation, CitationGenerator, StructuredContent


class ResponseBuilder:
    """响应构建器。

    职责：
        - 调用 LLM 基于查询和检索结果生成响应
        - 将检索结果转换为上下文
        - 集成 CitationGenerator 生成引用信息
        - 返回包含引用的 StructuredContent

    设计原则：
        - 配置驱动：LLM provider 通过 Settings 配置
        - 可插拔：通过 LLMFactory 支持不同 LLM 后端
        - 类型安全：返回结构化的 StructuredContent
    """

    def __init__(self, settings: Settings):
        """初始化响应构建器。

        Args:
            settings: 应用配置，包含 LLM 配置信息
        """
        self.settings = settings
        self.llm: BaseLLM = LLMFactory.create(settings=settings)
        self.citation_generator = CitationGenerator()

        # 从 settings 中读取响应生成配置
        # 默认配置：使用通用 RAG 提示词
        self.prompt_template: str = self._load_default_prompt()

    def build(
        self,
        query: str,
        results: List[RetrievalResult],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> StructuredContent:
        """构建包含引用的响应。

        Args:
            query: 用户查询
            results: HybridSearch + Reranker 返回的检索结果
            trace: 可选的 TraceContext 用于可观测性
            **kwargs: LLM 调用的额外参数（如 temperature, max_tokens）

        Returns:
            StructuredContent，包含 markdown 文本和引用列表

        说明：
            - 将检索结果转换为上下文文本
            - 调用 LLM 生成响应
            - 生成引用列表
            - 返回 StructuredContent
        """
        # 1. 生成引用列表
        citations: List[Citation] = self.citation_generator.generate(results)

        # 2. 构建上下文（带引用序号）
        context: str = self._build_context(results, citations)

        # 3. 构建 LLM 提示词
        prompt: str = self._build_prompt(query, context)

        # 4. 调用 LLM 生成响应
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": "你是一个专业的知识助手，能够基于提供的上下文回答用户的问题。"},
            {"role": "user", "content": prompt},
        ]
        response_text: str = self.llm.chat(messages=messages, trace=trace, **kwargs)

        # 5. 构建并返回 StructuredContent
        return StructuredContent(markdown=response_text, citations=citations)

    def _build_context(
        self,
        results: List[RetrievalResult],
        citations: List[Citation],
    ) -> str:
        """构建上下文文本。

        将检索结果转换为带引用序号的上下文文本。

        Args:
            results: 检索结果列表
            citations: 引用列表

        Returns:
            上下文文本，格式为：
                [1] 来源文档：source_path
                    文本内容...

                [2] 来源文档：source_path
                    文本内容...
        """
        if not results:
            return "没有找到相关内容。"

        context_parts: List[str] = []

        for citation, result in zip(citations, results):
            source_path: str = citation.source
            page_str: str = f" (页 {citation.page})" if citation.page is not None else ""

            context_part: str = (
                f"[{citation.id}] 来源文档：{source_path}{page_str}\n"
                f"    文本内容：{result.text}\n"
            )
            context_parts.append(context_part)

        return "\n\n".join(context_parts)

    def _build_prompt(self, query: str, context: str) -> str:
        """构建 LLM 提示词。

        Args:
            query: 用户查询
            context: 上下文文本

        Returns:
            提示词文本
        """
        # 使用模板构建提示词
        return self.prompt_template.format(query=query, context=context)

    def _load_default_prompt(self) -> str:
        """加载默认的 RAG 提示词模板。

        Returns:
            提示词模板字符串，包含 {query} 和 {context} 占位符
        """
        return """请基于以下上下文回答用户的问题。如果上下文中没有相关信息，请明确说明。

上下文：
{context}

问题：
{query}

请提供准确、清晰的回答，并在回答中使用 [1], [2] 等引用标记指出信息来源。"""