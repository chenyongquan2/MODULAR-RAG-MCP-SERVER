"""引用生成器。"""

from dataclasses import dataclass
from typing import List, Optional

from src.core.types import RetrievalResult


@dataclass
class Citation:
    """引用信息。

    用于标记响应内容中引用的来源，支持可追溯的溯源机制。

    Attributes:
        id: 引用序号 (从1开始，用于文本中的标记如 [1], [2])
        source: 来源文档路径或名称
        page: 来源页码 (可选，适用于PDF等分页文档)
        chunk_id: 对应的 Chunk ID
        score: 相关性分数 (用于评估引用质量)
        text: 引用的原始文本内容

    说明：
        在 Markdown 响应中，使用 [1], [2] 格式标记引用位置。
        citations 数组中，id 与标记一一对应。
    """
    id: int
    source: str
    page: Optional[int]
    chunk_id: str
    score: float
    text: str


@dataclass
class StructuredContent:
    """结构化响应内容。

    用于 MCP 工具返回的结构化数据格式。

    Attributes:
        markdown: Markdown 格式的响应文本，包含 [1], [2] 等引用标记
        citations: 引用列表，与 markdown 中的标记一一对应

    示例：
        markdown = "RAG 系统结合了检索和生成 [1]。"
        citations = [
            Citation(id=1, source="doc.pdf", page=10, chunk_id="...", score=0.95, text="...")
        ]
    """
    markdown: str
    citations: List[Citation]


class CitationGenerator:
    """引用生成器。

    从检索结果生成引用列表，为响应提供可追溯的溯源信息。

    职责：
        - 为每个检索结果分配唯一引用序号
        - 提取来源信息（source_path, page）
        - 保留相关性分数和原始文本
    """

    def generate(self, results: List[RetrievalResult]) -> List[Citation]:
        """从检索结果生成引用列表。

        Args:
            results: HybridSearch + Reranker 返回的检索结果列表

        Returns:
            引用列表，按检索结果顺序分配序号

        说明：
            - 引用序号从 1 开始，与检索结果顺序一致
            - source 字段优先使用 metadata["source"]，
              否则使用 metadata["source_path"]
            - page 字段从 metadata["page"] 提取（可选）
        """
        citations: List[Citation] = []

        for idx, result in enumerate(results, start=1):
            metadata = result.metadata

            # 提取来源信息
            source = metadata.get("source_path", "unknown")
            if "source" in metadata:
                source = metadata["source"]

            # 提取页码（可选）
            page: Optional[int] = None
            if "page" in metadata:
                page = int(metadata["page"]) if metadata["page"] is not None else None

            # 构建引用
            citation = Citation(
                id=idx,
                source=source,
                page=page,
                chunk_id=result.chunk_id,
                score=result.score,
                text=result.text
            )
            citations.append(citation)

        return citations