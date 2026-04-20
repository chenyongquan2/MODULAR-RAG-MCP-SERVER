"""PDF 文档加载器 - 基于 Docling 引擎，输出结构化 Markdown。

相比旧版 pdfplumber 方案，Docling 的核心优势：
- 输出带 # 标题层级的 Markdown，保留文档语义结构（对 RAG chunk 切分质量至关重要）
- 自动识别并转换复杂表格为 Markdown 表格语法（| col1 | col2 |）
- 支持扫描版 PDF 的 OCR 识别（可选，速度约慢 5x）
- 图片提取直接集成到 DoclingDocument，无需手动解析 XObject
- 多栏布局自动处理，文本顺序不再乱序

RAG 影响：标题层级保留使得 chunk 内含有语义锚点，检索时向量相似度更准确。
"""

import hashlib
import shutil
import tempfile
from pathlib import Path
from typing import List

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

from src.core.types import Document, ImageReference
from src.observability.logger import get_logger
from .base_loader import BaseLoader

logger = get_logger(__name__)


class PdfLoader(BaseLoader):
    """基于 Docling 的 PDF 文档加载器。

    将 PDF 转换为结构化 Markdown，保留标题层级、表格和图片引用，
    显著提升后续 chunk 切分和向量检索的质量。

    Attributes:
        collection: 文档所属集合名称
        enable_ocr: 是否启用 OCR（扫描版 PDF 需开启，速度约慢 5x）
        enable_table_structure: 是否启用表格结构识别
        extract_images: 是否提取 PDF 中的图片
    """

    def __init__(
        self,
        collection: str = "default",
        enable_ocr: bool = False,
        enable_table_structure: bool = True,
        extract_images: bool = True,
    ):
        """初始化 PDF 加载器。

        Args:
            collection: 文档所属集合名称
            enable_ocr: 是否启用 OCR（扫描版 PDF 开启，速度约慢 5x）
            enable_table_structure: 是否识别表格结构并输出 Markdown 表格
            extract_images: 是否提取 PDF 中的嵌入图片
        """
        super().__init__(collection)
        self.enable_ocr = enable_ocr
        self.enable_table_structure = enable_table_structure
        self.extract_images = extract_images
        self._temp_dirs: List[str] = []  # 跟踪创建的临时目录，用于清理

        # 构建 Docling PDF Pipeline 配置
        # generate_picture_images=True 会让 Docling 提取图片的 PIL 对象，供后续保存
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = enable_ocr
        pipeline_options.do_table_structure = enable_table_structure
        pipeline_options.generate_picture_images = extract_images

        # 初始化 DocumentConverter（仅构造一次，避免重复加载 ML 模型）
        self._converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
        logger.debug(
            f"PdfLoader 初始化完成 (ocr={enable_ocr}, table={enable_table_structure}, "
            f"images={extract_images})"
        )

    def load(self, path: str | Path) -> Document:
        """加载 PDF 文档，返回结构化 Document。

        Args:
            path: PDF 文件路径

        Returns:
            Document: text 为 Markdown 格式（含 # 标题层级），
                      metadata["images"] 为 ImageReference 列表

        Raises:
            ValueError: 文件不存在或格式不支持
            RuntimeError: Docling 解析过程中发生错误
        """
        path = self._validate_path(path)

        if path.suffix.lower() != ".pdf":
            raise ValueError(f"不支持的文件格式: {path.suffix}，期望 .pdf")

        # 计算文件 SHA256 哈希前 16 位，用于生成稳定的文档 ID 和图片 ID
        doc_hash = self._compute_hash(path)
        doc_id = f"doc_{doc_hash}"

        logger.info(f"使用 Docling 加载 PDF: {path.name} (hash={doc_hash})")

        try:
            result = self._converter.convert(str(path))
        except Exception as e:
            raise RuntimeError(f"Docling 解析 PDF 失败: {path} — {e}") from e

        # export_to_markdown() 输出带 # 标题层级、表格、代码块的标准 Markdown
        # 这是与 pdfplumber 最核心的区别：结构化文本 vs 纯文本
        md_text = result.document.export_to_markdown()

        if not md_text.strip():
            raise ValueError(f"PDF 内容为空，无法提取文本: {path}")

        # 提取图片并在 Markdown 中插入 [IMAGE: id] 占位符
        images: List[ImageReference] = []
        if self.extract_images:
            md_text, images = self._extract_and_embed_images(result, md_text, doc_hash)

        # 获取页数（Docling 的 pages 是字典，键为页码整数）
        page_count = len(result.document.pages) if result.document.pages else 0

        return Document(
            id=doc_id,
            text=md_text,
            metadata={
                "source_path": str(path),
                "collection": self.collection,
                "doc_type": "pdf",
                "title": path.stem,
                "page_count": page_count,
                "images": images,
                "parser": "docling",  # 记录解析器，便于 dashboard 展示和调试
            },
        )

    def _extract_and_embed_images(
        self,
        result,
        md_text: str,
        doc_hash: str,
    ) -> tuple[str, List[ImageReference]]:
        """提取 Docling 识别到的图片，保存到临时目录，并在 Markdown 中补充占位符。

        Docling 通过 result.document.pictures 提供图片对象：
        - picture.get_image(doc) 返回 PIL.Image 对象
        - picture.prov 包含位置信息（页码、边界框）

        Markdown 占位符格式与旧版保持一致：[IMAGE: img_{hash}_{page}_{seq}]
        确保下游 ImageCaptioner 等组件无需改动。

        Args:
            result: Docling ConversionResult 对象
            md_text: 已生成的 Markdown 文本
            doc_hash: 文档哈希（用于生成图片 ID）

        Returns:
            tuple: (更新后的 md_text, ImageReference 列表)
        """
        temp_dir = tempfile.mkdtemp(prefix="rag_pdf_images_")
        self._temp_dirs.append(temp_dir)

        images: List[ImageReference] = []

        for seq, picture in enumerate(result.document.pictures):
            try:
                pil_image = picture.get_image(result.document)
                if pil_image is None:
                    continue

                # 获取页码（Docling 页码从 1 开始）
                page_no = picture.prov[0].page_no if picture.prov else 0

                image_id = f"img_{doc_hash}_{page_no}_{seq}"
                image_path = Path(temp_dir) / f"{image_id}.png"
                pil_image.save(str(image_path), format="PNG")

                placeholder = f"[IMAGE: {image_id}]"

                # Docling 在 Markdown 中会以 <!-- image --> 等注释标记图片位置
                # 如果已有占位符则查找其偏移，否则追加到文末
                offset = md_text.find(placeholder)
                if offset == -1:
                    md_text += f"\n{placeholder}\n"
                    offset = md_text.rfind(placeholder)

                # 提取边界框（如有）
                bbox = None
                if picture.prov and picture.prov[0].bbox:
                    b = picture.prov[0].bbox
                    bbox = {"l": b.l, "t": b.t, "r": b.r, "b": b.b}

                images.append(
                    ImageReference(
                        id=image_id,
                        path=str(image_path),
                        text_offset=offset,
                        text_length=len(placeholder),
                        page=page_no,
                        position={"bbox": bbox} if bbox else None,
                    )
                )
                logger.debug(f"提取图片: {image_id} (page={page_no})")

            except Exception as e:
                # 单张图片失败不阻断整体处理
                logger.warning(f"图片提取失败 (seq={seq}): {e}")

        return md_text, images

    def _compute_hash(self, path: Path) -> str:
        """计算文件 SHA256 哈希前 16 位，用于生成稳定的文档/图片 ID。

        流式读取，避免大文件一次性加载到内存。
        """
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()[:16]

    def cleanup_temp_dirs(self) -> None:
        """清理图片临时目录。

        在图片被持久化存储（ImageCaptioner 处理完毕）后调用，释放临时空间。
        """
        for temp_dir in self._temp_dirs:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.debug(f"已清理临时目录: {temp_dir}")
            except Exception as e:
                logger.warning(f"清理临时目录失败: {temp_dir} — {e}")
        self._temp_dirs.clear()
