"""多模态内容组装器 (Text + Image)。

该模块负责：
1. 从 RetrievalResult 中提取 image_refs
2. 从 ImageStorage 读取图片文件
3. 将图片编码为 base64 并构建 ImageContent
4. 返回混合内容（TextContent + ImageContent 列表）

设计原则：
1. 优雅降级：图片读取失败时不应影响文本内容返回
2. 性能优化：批量读取图片，减少 I/O 操作
3. MIME 类型检测：自动识别图片格式
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.types import TextContent, ImageContent

from src.core.types import RetrievalResult
from src.ingestion.storage.image_storage import BaseImageStorage, SQLiteImageStorage

from src.observability.logger import get_logger

logger = get_logger(__name__)


class MultimodalAssembler:
    """多模态内容组装器。

    职责：
        - 从检索结果中提取图片引用
        - 读取图片文件并编码为 base64
        - 构建符合 MCP 规范的 ImageContent
        - 返回混合内容（文本 + 图片）

    Design Principles Applied:
        - Graceful Degradation: 图片读取失败时记录日志并继续
        - Configurable: 支持依赖注入 ImageStorage
        - Type Safety: 返回 List[TextContent | ImageContent]

    Example:
        >>> assembler = MultimodalAssembler(image_storage)
        >>> contents = assembler.assemble(results)
        >>> for content in contents:
        ...     if isinstance(content, TextContent):
        ...         print(content.text)
        ...     elif isinstance(content, ImageContent):
        ...         print(f"Image: {content.mimeType}")
    """

    def __init__(self, image_storage: Optional[BaseImageStorage] = None) -> None:
        """初始化多模态组装器。

        Args:
            image_storage: 图片存储实例，默认使用 SQLiteImageStorage

        Raises:
            ValueError: 如果 image_storage 为 None（内部错误）
        """
        if image_storage is None:
            self._image_storage = SQLiteImageStorage()
        else:
            self._image_storage = image_storage

    def assemble(
        self,
        markdown: str,
        results: List[RetrievalResult],
        trace: Optional[Any] = None,
    ) -> List[TextContent | ImageContent | dict[str, Any]]:
        """组装多模态内容。

        从检索结果中提取图片引用，读取图片并构建混合内容。

        Args:
            markdown: Markdown 格式的响应文本（含 [IMAGE: {id}] 占位符）
            results: 检索结果列表（可能包含 image_refs）
            trace: 可选的 TraceContext 用于可观测性

        Returns:
            混合内容列表，顺序为：
            1. 文本内容（TextContent）
            2. 图片内容（ImageContent 列表，按在文本中出现顺序）
            3. 引用字典（dict，包含 images）

        说明：
            - 图片内容按 [IMAGE: {id}] 在 markdown 中出现顺序返回
            - 图片读取失败时记录警告并跳过该图片
            - 总是返回 TextContent（即使没有图片）
        """
        # 1. 收集所有图片引用
        image_refs: List[Dict[str, Any]] = self._extract_image_refs(results)

        if not image_refs:
            # 没有图片，只返回文本和引用
            return [
                TextContent(type="text", text=markdown),
                {"images": []}
            ]

        logger.info("Found %d image references in retrieval results", len(image_refs))

        # 2. 批量读取图片（保留 image_id 用于排序）
        image_contents: List[tuple[str, ImageContent]] = []
        for ref in image_refs:
            try:
                image_content = self._load_image(ref)
                if image_content:
                    image_contents.append((ref["id"], image_content))
            except Exception as e:
                logger.warning(
                    "Failed to load image %s: %s",
                    ref.get("id", "unknown"),
                    e,
                    exc_info=True,
                )
                # 优雅降级：跳过失败的图片，继续处理其他图片

        # 3. 按在文本中的出现顺序排序
        sorted_images = self._sort_by_text_offset(image_contents, markdown)

        # 4. 构建返回内容
        return [
            TextContent(type="text", text=markdown),
            *[img for _, img in sorted_images],
            {"images": [
                {
                    "id": image_id,
                    "mimeType": img.mimeType,
                }
                for image_id, img in sorted_images
            ]}
        ]

    def _extract_image_refs(
        self,
        results: List[RetrievalResult],
    ) -> List[Dict[str, Any]]:
        """从检索结果中提取图片引用。

        Args:
            results: 检索结果列表

        Returns:
            图片引用列表，去重后按文本偏移排序
        """
        image_refs: Dict[str, Dict[str, Any]] = {}

        for result in results:
            metadata = result.metadata
            images = metadata.get("images", [])

            for img_ref in images:
                if isinstance(img_ref, dict):
                    image_id = img_ref.get("id")
                elif hasattr(img_ref, "id"):
                    image_id = img_ref.id
                else:
                    continue

                if not image_id:
                    continue

                # 去重：保留首次出现的引用
                if image_id not in image_refs:
                    image_refs[image_id] = {
                        "id": image_id,
                        "path": img_ref.get("path") if isinstance(img_ref, dict) else getattr(img_ref, "path", None),
                        "text_offset": img_ref.get("text_offset") if isinstance(img_ref, dict) else getattr(img_ref, "text_offset", 0),
                        "text_length": img_ref.get("text_length") if isinstance(img_ref, dict) else getattr(img_ref, "text_length", 0),
                    }

        # 按文本偏移排序
        return sorted(
            image_refs.values(),
            key=lambda x: x.get("text_offset", 0)
        )

    def _load_image(self, ref: Dict[str, Any]) -> Optional[ImageContent]:
        """加载图片并构建 ImageContent。

        Args:
            ref: 图片引用字典

        Returns:
            ImageContent，如果加载失败返回 None

        Raises:
            FileNotFoundError: 如果图片文件不存在
        """
        image_id = ref.get("id")
        if not image_id:
            return None

        # 从 ImageStorage 获取图片路径
        image_path = self._image_storage.get_image_path(image_id)
        if not image_path:
            logger.warning("Image not found in storage: %s", image_id)
            return None

        # 读取图片文件
        path = Path(image_path)
        if not path.exists():
            logger.warning("Image file does not exist: %s", image_path)
            return None

        # 检测 MIME 类型
        mime_type, _ = mimetypes.guess_type(str(path))
        if not mime_type or not mime_type.startswith("image/"):
            # 默认使用 image/png
            mime_type = "image/png"
            logger.debug("Cannot detect MIME type for %s, using default: %s", path, mime_type)

        # 读取并编码图片
        try:
            with open(path, "rb") as f:
                image_data = f.read()
                base64_data = base64.b64encode(image_data).decode("utf-8")

            return ImageContent(
                type="image",
                data=base64_data,
                mimeType=mime_type,
            )
        except IOError as e:
            logger.error("Failed to read image file %s: %s", path, e)
            return None
        except Exception as e:
            logger.error("Unexpected error encoding image %s: %s", path, e)
            return None

    def _sort_by_text_offset(
        self,
        image_contents: List[tuple[str, ImageContent]],
        markdown: str,
    ) -> List[tuple[str, ImageContent]]:
        """按图片在文本中的出现顺序排序。

        Args:
            image_contents: 图片内容列表（包含 image_id 和 ImageContent）
            markdown: Markdown 文本（包含 [IMAGE: {id}] 占位符）

        Returns:
            按出现顺序排序的图片内容列表（保留 image_id）
        """
        # 提取所有 [IMAGE: {id}] 占位符位置和 ID
        image_positions: List[tuple[int, str]] = []
        start = 0
        while True:
            pos = markdown.find("[IMAGE:", start)
            if pos == -1:
                break
            end = markdown.find("]", pos)
            if end == -1:
                break

            # 提取 image_id
            image_id = markdown[pos + 7:end].strip()  # Skip "[IMAGE:" and strip whitespace
            image_positions.append((pos, image_id))
            start = end + 1

        # 如果没有找到占位符，返回原顺序
        if not image_positions:
            return image_contents

        # 创建 image_id -> (original_index, content) 的映射
        id_map: Dict[str, tuple[int, ImageContent]] = {}
        for idx, (image_id, content) in enumerate(image_contents):
            id_map[image_id] = (idx, content)

        # 按 markdown 中的出现顺序构建结果
        sorted_contents: List[tuple[str, ImageContent]] = []
        used_ids = set()

        for pos, markdown_id in image_positions:
            if markdown_id in id_map and markdown_id not in used_ids:
                _, content = id_map[markdown_id]
                sorted_contents.append((markdown_id, content))
                used_ids.add(markdown_id)

        # 添加未匹配的内容（在 markdown 中未显式引用的）
        for image_id, (original_idx, content) in id_map.items():
            if image_id not in used_ids:
                sorted_contents.append((image_id, content))

        return sorted_contents

    @staticmethod
    def detect_mime_type(image_path: str) -> str:
        """检测图片文件的 MIME 类型。

        Args:
            image_path: 图片文件路径

        Returns:
            MIME 类型字符串，默认为 "image/png"
        """
        mime_type, _ = mimetypes.guess_type(image_path)
        if mime_type and mime_type.startswith("image/"):
            return mime_type

        # 根据文件扩展名回退判断
        ext = Path(image_path).suffix.lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
            ".svg": "image/svg+xml",
        }
        return mime_map.get(ext, "image/png")
