"""文本增强器 (TextEnricher)。

该模块将图片描述融合到 chunk 正文中，使其能够被 Embedding 向量化后可被检索。

功能：
1. 从 metadata["image_captions"] 提取图片描述
2. 将描述按配置格式追加到 chunk.text 末尾
3. 记录融合标记到 metadata["caption_enriched"]

设计原则：
- 配置驱动：通过 settings.ingestion.text_enricher 控制开关和格式
- 幂等性：重复调用不会重复融合
- 可追溯：融合后的 chunk 记录原始文本长度
"""

from typing import List, Optional, Dict

from src.core.types import Chunk
from src.core.trace.trace_context import TraceContext
from src.ingestion.transform.base_transform import BaseTransform
from src.core.settings import Settings
from src.observability.logger import get_logger

logger = get_logger(__name__)


class TextEnricher(BaseTransform):
    """文本增强器。

    将图片描述融合到 chunk 正文中，实现多模态内容的文本检索。

    Attributes:
        settings: 配置对象
        enabled: 是否启用文本增强
        caption_format: 描述文本格式模板
    """

    def __init__(self, settings: Settings):
        """初始化 TextEnricher。

        Args:
            settings: 配置对象
        """
        self._settings = settings

        # 从配置读取参数
        self._enabled = True
        self._caption_format = "[图片描述: {caption}]"

        if hasattr(settings.ingestion, 'text_enricher'):
            self._enabled = settings.ingestion.text_enricher.enabled
            self._caption_format = settings.ingestion.text_enricher.caption_format

    def transform(
        self,
        chunks: List[Chunk],
        trace: Optional[TraceContext] = None
    ) -> List[Chunk]:
        """转换 chunks。

        将每个 chunk 中的 image_captions 追加到文本末尾。

        Args:
            chunks: 待转换的 chunks
            trace: 追踪上下文

        Returns:
            转换后的 chunks（文本包含融合后的描述）
        """
        if not chunks:
            return chunks

        # 检查是否启用
        if not self._enabled:
            logger.debug("TextEnricher is disabled in config")
            return chunks

        # Start stage if trace provided
        stage = None
        if trace:
            stage = trace.start_stage("text_enrich")

        # Statistics for trace
        total_captions = 0
        enriched_chunks = 0

        enriched_chunk_list = []
        for chunk in chunks:
            try:
                # 检查是否已有 image_captions
                captions: Dict[str, str] = chunk.metadata.get("image_captions", {})

                if not captions:
                    # 无描述，保持原样
                    enriched_chunk_list.append(chunk)
                    continue

                # 检查是否已融合过（幂等性）
                if chunk.metadata.get("caption_enriched"):
                    logger.debug(f"Chunk {chunk.id} already enriched, skipping")
                    enriched_chunk_list.append(chunk)
                    continue

                # 构建融合文本
                caption_texts = []
                for image_id, caption in captions.items():
                    # 使用 replace 而非 format，避免 caption 中 { } 字符导致的问题
                    formatted = self._caption_format.replace("{caption}", caption)
                    caption_texts.append(formatted)
                    total_captions += 1

                # 追加到正文末尾
                enriched_text = chunk.text + "\n" + "\n".join(caption_texts)

                # 创建增强后的 chunk
                enriched_chunk = Chunk(
                    id=chunk.id,
                    text=enriched_text,
                    metadata=chunk.metadata.copy(),
                    start_offset=chunk.start_offset,
                    end_offset=chunk.end_offset,
                    source_ref=chunk.source_ref
                )

                # 记录元数据
                enriched_chunk.metadata["caption_enriched"] = True
                enriched_chunk.metadata["original_text_length"] = len(chunk.text)

                enriched_chunk_list.append(enriched_chunk)
                enriched_chunks += 1

            except Exception as e:
                # 保留原始 chunk
                logger.error(f"Error enriching chunk {chunk.id}: {e}")
                enriched_chunk_list.append(chunk)

        # Finish stage
        if stage:
            trace.finish_stage("text_enrich", {
                "total_captions": total_captions,
                "enriched_chunks": enriched_chunks,
                "caption_format": self._caption_format,
            })

        logger.info(
            f"Text enrichment complete: {enriched_chunks} chunks enriched, "
            f"{total_captions} captions fused"
        )

        return enriched_chunk_list

    @property
    def enabled(self) -> bool:
        """返回是否启用。"""
        return self._enabled

    @property
    def caption_format(self) -> str:
        """返回描述格式模板。"""
        return self._caption_format