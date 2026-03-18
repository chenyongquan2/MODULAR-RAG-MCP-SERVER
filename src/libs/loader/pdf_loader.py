"""PDF Loader (pdfplumber)。

支持从 PDF 中提取文本和嵌入图片：
1. 使用 pdfplumber 提取文本内容
2. 提取嵌入图片并保存到临时目录
3. 生成 ImageReference 并添加到 metadata["images"]
4. 在文本中插入 [IMAGE: {image_id}] 占位符
"""

import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional

import pdfplumber

from src.core.types import Document, ImageReference
from src.observability.logger import get_logger
from .base_loader import BaseLoader

logger = get_logger(__name__)


class PdfLoader(BaseLoader):
    """PDF 文档加载器。

    使用 pdfplumber 库提取 PDF 文本内容和嵌入图片，
    对中文支持更好。

    Attributes:
        collection: 文档所属集合名称
    """

    def __init__(self, collection: str = "default"):
        """初始化 PDF 加载器。

        Args:
            collection: 文档所属集合名称
        """
        super().__init__(collection)
        self._temp_dirs: List[str] = []  # 跟踪创建的临时目录，用于清理

    def load(self, path: str | Path) -> Document:
        """加载 PDF 文档。

        Args:
            path: PDF 文件路径

        Returns:
            Document: 加载后的文档对象

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文件格式不支持
        """
        path = self._validate_path(path)

        if path.suffix.lower() != ".pdf":
            raise ValueError(f"Unsupported file format: {path.suffix}. Expected .pdf")

        # 计算文档哈希（用于生成图片 ID）
        doc_hash = hashlib.sha256(path.read_bytes()).hexdigest()[:16]

        # 提取图片到临时目录
        extracted_images = self._extract_images(path, doc_hash)

        # 提取文本内容
        text_parts = []
        image_placeholders: Dict[int, str] = {}  # page -> placeholder text

        with pdfplumber.open(path) as pdf:
            for page_num, page in enumerate(pdf.pages):
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)

                # 为该页的图片添加占位符
                page_images = [img for img in extracted_images if img["page"] == page_num]
                for img in page_images:
                    placeholder = f"\n[IMAGE: {img['image_id']}]\n"
                    image_placeholders[page_num] = image_placeholders.get(page_num, "") + placeholder

            # 在每页文本后添加图片占位符
            final_text_parts = []
            for page_num, page in enumerate(pdf.pages):
                page_text = page.extract_text() or ""
                if page_num in image_placeholders:
                    page_text += image_placeholders[page_num]
                if page_text.strip():
                    final_text_parts.append(page_text)

        text = "\n\n".join(final_text_parts)

        if not text.strip():
            raise ValueError(f"Failed to extract text from PDF: {path}")

        # 构建 ImageReference 列表
        image_refs = []
        for img in extracted_images:
            img_ref = ImageReference(
                id=img["image_id"],
                path=img["temp_path"],
                text_offset=0,  # 将在后续处理中更新
                text_length=len(f"[IMAGE: {img['image_id']}]"),
                page=img["page"],
                position=img.get("position"),
            )
            image_refs.append(img_ref)

        return Document(
            id=f"doc_{doc_hash}",
            text=text,
            metadata={
                "source_path": str(path),
                "collection": self.collection,
                "doc_type": "pdf",
                "page_count": len(text_parts),
                "images": image_refs,
            }
        )

    def _extract_images(self, path: Path, doc_hash: str) -> List[Dict[str, Any]]:
        """从 PDF 中提取嵌入图片。

        Args:
            path: PDF 文件路径
            doc_hash: 文档哈希值

        Returns:
            List[Dict]: 提取的图片信息列表，每个元素包含：
                - image_id: 图片唯一标识符
                - temp_path: 临时存储路径
                - page: 页码
                - position: 位置信息
        """
        extracted = []
        temp_dir = tempfile.mkdtemp(prefix="pdf_images_")
        self._temp_dirs.append(temp_dir)  # 跟踪临时目录

        with pdfplumber.open(path) as pdf:
            for page_num, page in enumerate(pdf.pages):
                # 获取页面中的图片对象
                images = page.images

                for seq, img in enumerate(images):
                    try:
                        # 提取图片数据
                        image_data = self._get_image_data(page, img)
                        if image_data is None:
                            logger.debug(f"No image data extracted for page {page_num}, image {seq}")
                            continue

                        # 生成图片 ID
                        image_id = self._generate_image_id(doc_hash, page_num, seq)

                        # 保存图片到临时目录
                        temp_path = self._save_temp_image(
                            image_data=image_data,
                            image_id=image_id,
                            temp_dir=temp_dir,
                        )

                        if temp_path:
                            extracted.append({
                                "image_id": image_id,
                                "temp_path": temp_path,
                                "page": page_num,
                                "position": {
                                    "x0": float(img.get("x0", 0)),
                                    "y0": float(img.get("y0", 0)),
                                    "x1": float(img.get("x1", 0)),
                                    "y1": float(img.get("y1", 0)),
                                    "width": float(img.get("width", 0)),
                                    "height": float(img.get("height", 0)),
                                },
                            })
                    except Exception as e:
                        # 单个图片提取失败不影响整体处理
                        logger.debug(f"Failed to extract image at page {page_num}, seq {seq}: {e}")
                        continue

        return extracted

    def _get_image_data(self, page, img_obj: Dict) -> Optional[bytes]:
        """从页面对象中获取图片数据。

        Args:
            page: pdfplumber 页面对象
            img_obj: 图片对象信息

        Returns:
            bytes: 图片二进制数据，如果无法提取则返回 None
        """
        # pdfplumber 的 images 属性返回的是图片位置信息
        # 需要通过底层 pdfminer 获取实际图片数据
        try:
            # 尝试从页面的 resources 中获取图片
            xobject = page.page.get("resources", {}).get("XObject", {})
            if xobject:
                for name, obj in xobject.items():
                    if obj.get("Subtype") == "Image":
                        # 获取图片流数据
                        stream = obj.get("stream")
                        if stream:
                            return stream.get_data()
                        # 尝试直接获取原始数据
                        if hasattr(obj, "get_data"):
                            return obj.get_data()
        except Exception as e:
            logger.debug(f"Failed to extract image via XObject: {e}")

        # 备选方案：使用 PIL 从页面裁剪区域提取
        try:
            from PIL import Image
            import io

            # 将页面转换为图片
            im = page.to_image(resolution=150)

            # 裁剪图片区域
            x0 = float(img_obj.get("x0", 0))
            y0 = float(img_obj.get("y0", 0))
            x1 = float(img_obj.get("x1", 0))
            y1 = float(img_obj.get("y1", 0))

            # pdfplumber 的坐标系与 PIL 不同，需要转换
            page_height = page.height
            y0_pil = page_height - y1
            y1_pil = page_height - y0

            # 裁剪
            cropped = im.original.crop((x0, y0_pil, x1, y1_pil))

            # 转换为字节
            buffer = io.BytesIO()
            cropped.save(buffer, format="PNG")
            return buffer.getvalue()
        except Exception as e:
            logger.debug(f"Failed to extract image via PIL fallback: {e}")

        return None

    def _generate_image_id(self, doc_hash: str, page: int, seq: int) -> str:
        """生成图片唯一标识符。

        格式: img_{doc_hash}_{page}_{seq}

        Args:
            doc_hash: 文档哈希值
            page: 页码
            seq: 序号

        Returns:
            str: 图片唯一标识符
        """
        return f"img_{doc_hash}_{page}_{seq}"

    def _save_temp_image(
        self,
        image_data: bytes,
        image_id: str,
        temp_dir: str,
    ) -> Optional[str]:
        """保存图片到临时目录。

        Args:
            image_data: 图片二进制数据
            image_id: 图片唯一标识符
            temp_dir: 临时目录路径

        Returns:
            str: 保存后的文件路径，失败返回 None
        """
        try:
            # 根据图片头判断格式
            ext = self._detect_image_extension(image_data)

            # 保存文件
            file_path = Path(temp_dir) / f"{image_id}{ext}"
            file_path.write_bytes(image_data)

            return str(file_path)
        except Exception as e:
            logger.debug(f"Failed to save temp image {image_id}: {e}")
            return None

    def _detect_image_extension(self, data: bytes) -> str:
        """根据图片头检测图片格式。

        Args:
            data: 图片二进制数据

        Returns:
            str: 文件扩展名（包含点）
        """
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            return ".png"
        elif data[:2] == b'\xff\xd8':
            return ".jpg"
        elif data[:6] in (b'GIF87a', b'GIF89a'):
            return ".gif"
        elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            return ".webp"
        else:
            # 默认使用 PNG
            return ".png"

    def cleanup_temp_dirs(self) -> None:
        """清理创建的临时目录。

        在图片被持久化存储后调用，释放临时文件空间。
        """
        for temp_dir in self._temp_dirs:
            try:
                if Path(temp_dir).exists():
                    shutil.rmtree(temp_dir)
                    logger.debug(f"Cleaned up temp directory: {temp_dir}")
            except Exception as e:
                logger.warning(f"Failed to cleanup temp directory {temp_dir}: {e}")
        self._temp_dirs.clear()
