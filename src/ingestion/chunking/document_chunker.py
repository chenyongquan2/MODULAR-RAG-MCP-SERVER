"""Document → Chunks 转换（调用 libs.splitter）。

该模块实现 DocumentChunker，作为 libs.splitter 和 Ingestion Pipeline 之间的适配器层，
负责将 Document 对象转换为符合 core/types 契约的 Chunk 对象列表。

核心职责：
1. Chunk ID 生成：为每个文本片段生成唯一且确定性的 ID
2. 元数据继承：将 Document.metadata 复制到每个 Chunk.metadata
3. 添加 chunk_index：记录 chunk 在文档中的序号
4. 建立 source_ref：记录 Chunk.source_ref 指向父 Document.id
5. 类型转换：将 libs.splitter 的 List[str] 转换为 List[Chunk]
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, List, Optional, Any

from src.core.types import Document, Chunk
from src.libs.splitter.base_splitter import BaseSplitter
from src.libs.splitter.splitter_factory import SplitterFactory
from src.observability.logger import get_logger

if TYPE_CHECKING:
    from src.core.settings import Settings

logger = get_logger(__name__)


class DocumentChunker:
    """文档切分适配器。

    将 Document 对象转换为 List[Chunk] 对象，调用 libs.splitter 进行文本切分，
    并添加业务逻辑（元数据继承、ID 生成、溯源链接等）。

    设计原则：
    - 配置驱动：通过 settings.yaml 控制切分策略
    - 可测试：依赖注入，支持 Mock
    - 可观测：集成 TraceContext（预留）
    """

    def __init__(
        self,
        settings: Settings,
        splitter: Optional[BaseSplitter] = None,
    ):
        """初始化 DocumentChunker。

        Args:
            settings: 应用配置（包含 splitter 配置）
            splitter: 可选的 BaseSplitter 实例（用于测试注入）

        Raises:
            ValueError: 如果 settings 缺少必要配置
        """
        self._settings = settings
        self._splitter = splitter or SplitterFactory.create(settings)
        logger.info(
            f"DocumentChunker initialized with splitter strategy: "
            f"{self._splitter.get_strategy_name()}"
        )

    def split_document(
        self,
        document: Document,
        trace: Optional[Any] = None,
    ) -> List[Chunk]:
        """将 Document 转换为 Chunk 列表。

        Args:
            document: 待切分的 Document 对象
            trace: 可选的 TraceContext（预留）

        Returns:
            List[Chunk]: 切分后的 Chunk 列表

        Raises:
            ValueError: 如果 document 无效
        """
        if not isinstance(document, Document):
            raise ValueError(
                f"document must be a Document instance (got: {type(document).__name__})"
            )

        if not document.text.strip():
            logger.warning(
                f"Document {document.id} has empty text, returning empty chunk list"
            )
            return []

        logger.debug(
            f"Splitting document {document.id} "
            f"(text length: {len(document.text)} chars)"
        )

        try:
            raw_chunks = self._splitter.split_text(document.text, trace=trace)
        except Exception as e:
            error_msg = (
                f"Failed to split document {document.id}: {str(e)}"
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

        if not raw_chunks:
            logger.warning(
                f"Splitter returned empty list for document {document.id}"
            )
            return []

        chunks: List[Chunk] = []
        inherited_metadata = self._inherit_metadata(document)

        for idx, text in enumerate(raw_chunks):
            chunk_id = self._generate_chunk_id(
                doc_id=document.id,
                index=idx,
                text=text,
            )

            chunk = Chunk(
                id=chunk_id,
                text=text,
                metadata=inherited_metadata.copy(),
                start_offset=None,
                end_offset=None,
                source_ref=document.id,
            )

            chunk.metadata["chunk_index"] = idx

            chunks.append(chunk)

        logger.info(
            f"Split document {document.id} into {len(chunks)} chunks "
            f"(strategy: {self._splitter.get_strategy_name()})"
        )

        if trace:
            trace.record_stage(
                "chunk",
                method=self._splitter.get_strategy_name(),
                chunk_count=len(chunks),
                input_length=len(document.text),
            )

        return chunks

    def _generate_chunk_id(
        self,
        doc_id: str,
        index: int,
        text: str,
    ) -> str:
        """生成稳定的 Chunk ID。

        格式：{doc_id}_{index:04d}_{hash_8chars}

        Args:
            doc_id: 父 Document ID
            index: Chunk 序号
            text: Chunk 文本内容

        Returns:
            唯一且确定性的 Chunk ID
        """
        content_hash = hashlib.md5(text.encode("utf-8")).hexdigest()[:8]
        return f"{doc_id}_{index:04d}_{content_hash}"

    def _inherit_metadata(self, document: Document) -> dict:
        """从 Document 继承元数据。

        将 Document.metadata 复制到 Chunk.metadata，添加业务相关字段。

        Args:
            document: 源 Document 对象

        Returns:
            继承后的元数据字典
        """
        metadata = document.metadata.copy()

        if "source_path" in metadata:
            metadata["source_path"] = metadata["source_path"]

        return metadata

    def get_splitter(self) -> BaseSplitter:
        """获取底层 Splitter 实例（用于测试）。

        Returns:
            BaseSplitter 实例
        """
        return self._splitter
