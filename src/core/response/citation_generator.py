"""引用生成器。"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

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
        language_consistency: 问答两端的语言归类与一致性结论（可选）。
            含 ``question_language`` / ``answer_language`` / ``threshold`` /
            ``measured``，且**仅当** ``measured`` 为真时才有 ``consistent``。

            为什么要把它放在返回值里而不是只打 trace：MCP 调用方拿到的就是
            ``StructuredContent``，而 trace 可能没开。只留一处会让另一条路
            看不见 —— 把观测通道当数据通道，本项目在分路径指标那里已经拒绝过
            一次。

            为什么要记：**答案语言错了与答案质量差，在最终指标上表现相同** ——
            两者都只是分数变低。没有这个字段就无法区分这两件事，而它们的处置
            完全不同（改提示词 / 改检索或模型）。本项目的这个缺陷存在了数月而
            无人发现，正是因为没有任何地方直接说出「这次答错语言了」。

    示例：
        markdown = "RAG 系统结合了检索和生成 [1]。"
        citations = [
            Citation(id=1, source="doc.pdf", page=10, chunk_id="...", score=0.95, text="...")
        ]
    """
    markdown: str
    citations: List[Citation]
    language_consistency: Optional[Dict[str, Any]] = None


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