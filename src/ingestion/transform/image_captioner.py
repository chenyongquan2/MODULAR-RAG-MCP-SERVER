"""图片描述生成器 (ImageCaptioner)。

该模块使用 Vision LLM 为 chunk 中的图片生成文本描述,支持两种模式:
1. 启用模式: 检测到图片引用时,调用 Vision LLM 生成 caption,写入 metadata
2. 降级模式: Vision LLM 不可用时,标记 has_unprocessed_images,不阻塞 pipeline

设计原则:
- 配置驱动: 通过 settings.ingestion.image_captioner.enabled 开关控制
- 优雅降级: Vision LLM 不可用或单个图片失败时不阻塞整体处理
- 单个图片处理异常不影响其他图片
- Caption 存储在 chunk.metadata["image_captions"] 字典中
"""

import os
from typing import List, Optional, Dict
from pathlib import Path

from src.core.types import Chunk, ImageReference
from src.core.trace.trace_context import TraceContext
from src.ingestion.transform.base_transform import BaseTransform
from src.core.settings import Settings
from src.libs.llm.base_vision_llm import BaseVisionLLM
from src.observability.logger import get_logger

logger = get_logger(__name__)


DEFAULT_PROMPT = """You are an image captioning assistant. Provide a detailed and accurate description of this image.

Describe the image in detail, including:
- Main subjects and objects
- Actions or activities
- Colors, textures, and visual elements
- Spatial relationships
- Any text visible in the image

Be concise but comprehensive."""


class ImageCaptioner(BaseTransform):
    """图片描述生成器。

    为 chunk 中的图片生成文本描述,将多模态内容转换为可检索的文本。

    Attributes:
        settings: 配置对象
        vision_llm: Vision LLM 实例 (可选)
        prompt_template: Vision LLM prompt 模板
        enabled: 是否启用图片描述生成
    """

    def __init__(
        self,
        settings: Settings,
        vision_llm: Optional[BaseVisionLLM] = None,
        prompt_path: Optional[str] = None
    ):
        """初始化 ImageCaptioner。

        Args:
            settings: 配置对象
            vision_llm: Vision LLM 实例 (可选)
            prompt_path: prompt 模板文件路径 (可选)
        """
        self.settings = settings
        self.vision_llm = vision_llm

        # Check if image_captioner config exists and enabled is set
        self.enabled = False
        if hasattr(settings.ingestion, 'image_captioner'):
            self.enabled = settings.ingestion.image_captioner.enabled

        self.prompt_template = self._load_prompt(prompt_path)

    def _load_prompt(self, prompt_path: Optional[str] = None) -> str:
        """加载 prompt 模板。

        Args:
            prompt_path: prompt 文件路径

        Returns:
            prompt 模板字符串
        """
        if prompt_path and Path(prompt_path).exists():
            with open(prompt_path, 'r', encoding='utf-8') as f:
                return f.read()

        # Try default location
        default_path = Path("config/prompts/image_captioning.txt")
        if default_path.exists():
            with open(default_path, 'r', encoding='utf-8') as f:
                return f.read()

        return DEFAULT_PROMPT

    def transform(
        self,
        chunks: List[Chunk],
        trace: Optional[TraceContext] = None
    ) -> List[Chunk]:
        """转换 chunks。

        检测并处理 chunk 中的图片引用,生成 caption 并存入 metadata。

        Args:
            chunks: 待转换的 chunks
            trace: 追踪上下文

        Returns:
            转换后的 chunks
        """
        if not chunks:
            return chunks

        # Check if image captioning is disabled
        if not self.enabled:
            logger.debug("Image captioning is disabled in config")
            return chunks

        # Check if Vision LLM is available
        if self.vision_llm is None:
            logger.warning(
                "Vision LLM not available, marking images as unprocessed"
            )
            return self._mark_unprocessed_images(chunks)

        # Start stage if trace provided
        stage = None
        if trace:
            stage = trace.start_stage("image_caption")

        # Statistics for trace
        total_images = 0
        captioned_images = 0
        failed_images = 0

        captioned_chunks = []
        for chunk in chunks:
            try:
                # Check if chunk has image references
                images = chunk.metadata.get("images", [])

                if not images:
                    # No images, keep chunk as-is
                    captioned_chunks.append(chunk)
                    continue

                # Process images
                captions: Dict[str, str] = {}
                errors: Dict[str, str] = {}

                for image_ref in images:
                    # Handle both ImageReference objects and dicts
                    if isinstance(image_ref, dict):
                        image_id = image_ref.get("id", "")
                        image_path = image_ref.get("path", "")
                    elif isinstance(image_ref, ImageReference):
                        image_id = image_ref.id
                        image_path = image_ref.path
                    else:
                        logger.warning(
                            f"Unknown image reference type in chunk {chunk.id}: {type(image_ref)}"
                        )
                        continue

                    total_images += 1

                    # Check if image file exists
                    if not os.path.exists(image_path):
                        logger.warning(
                            f"Image file not found for chunk {chunk.id}: {image_path}"
                        )
                        errors[image_id] = f"File not found: {image_path}"
                        failed_images += 1
                        continue

                    # Generate caption
                    try:
                        caption = self._generate_caption(image_path, trace)
                        if caption:
                            captions[image_id] = caption
                            captioned_images += 1
                            logger.debug(
                                f"Generated caption for image {image_id}: {caption[:100]}..."
                            )
                        else:
                            errors[image_id] = "Empty caption returned"
                            failed_images += 1

                    except Exception as e:
                        logger.warning(
                            f"Failed to caption image {image_id} in chunk {chunk.id}: {e}"
                        )
                        errors[image_id] = str(e)
                        failed_images += 1

                # Create enriched chunk with captions
                enriched_chunk = Chunk(
                    id=chunk.id,
                    text=chunk.text,
                    metadata=chunk.metadata.copy(),
                    start_offset=chunk.start_offset,
                    end_offset=chunk.end_offset,
                    source_ref=chunk.source_ref
                )

                # Store captions and errors in metadata
                if captions:
                    enriched_chunk.metadata["image_captions"] = captions
                if errors:
                    enriched_chunk.metadata["caption_errors"] = errors

                captioned_chunks.append(enriched_chunk)

            except Exception as e:
                # Preserve original chunk on critical failure
                logger.error(
                    f"Critical error processing chunk {chunk.id}: {e}"
                )
                chunk.metadata["caption_error"] = str(e)
                captioned_chunks.append(chunk)

        # Finish stage
        if stage:
            trace.finish_stage("image_caption", {
                "total_images": total_images,
                "captioned": captioned_images,
                "failed": failed_images,
                "vision_model": self.vision_llm.get_model_name() if self.vision_llm else "none"
            })

        logger.info(
            f"Image captioning complete: {captioned_images}/{total_images} succeeded, "
            f"{failed_images} failed"
        )

        return captioned_chunks

    def _generate_caption(
        self,
        image_path: str,
        trace: Optional[TraceContext] = None
    ) -> str:
        """为单个图片生成 caption。

        Args:
            image_path: 图片文件路径
            trace: 追踪上下文

        Returns:
            生成的 caption 文本

        Raises:
            Exception: Vision LLM 调用失败时抛出
        """
        if not self.vision_llm:
            raise RuntimeError("Vision LLM not available")

        # Use prompt template
        prompt = self.prompt_template

        # Call Vision LLM (let exceptions propagate)
        caption = self.vision_llm.chat_with_image(
            text=prompt,
            image=image_path,
            trace=trace
        )

        return caption.strip() if caption else ""

    def _mark_unprocessed_images(self, chunks: List[Chunk]) -> List[Chunk]:
        """标记包含未处理图片的 chunks。

        当 Vision LLM 不可用时调用,标记 has_unprocessed_images 但不阻塞。

        Args:
            chunks: 待标记的 chunks

        Returns:
            标记后的 chunks
        """
        marked_chunks = []
        for chunk in chunks:
            images = chunk.metadata.get("images", [])
            if images:
                # Create a copy with marker
                marked_chunk = Chunk(
                    id=chunk.id,
                    text=chunk.text,
                    metadata=chunk.metadata.copy(),
                    start_offset=chunk.start_offset,
                    end_offset=chunk.end_offset,
                    source_ref=chunk.source_ref
                )
                marked_chunk.metadata["has_unprocessed_images"] = True
                marked_chunks.append(marked_chunk)
            else:
                # No images, keep as-is
                marked_chunks.append(chunk)

        return marked_chunks
