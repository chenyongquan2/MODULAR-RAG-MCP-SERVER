"""PDF Loader (pdfplumber)。"""

import hashlib
from pathlib import Path

import pdfplumber

from src.core.types import Document
from .base_loader import BaseLoader


class PdfLoader(BaseLoader):
    """PDF 文档加载器。

    使用 pdfplumber 库提取 PDF 文本内容，
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

        text_parts = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)

        text = "\n\n".join(text_parts)

        if not text.strip():
            raise ValueError(f"Failed to extract text from PDF: {path}")

        doc_hash = hashlib.sha256(path.read_bytes()).hexdigest()[:16]

        return Document(
            id=f"doc_{doc_hash}",
            text=text,
            metadata={
                "source_path": str(path),
                "collection": self.collection,
                "doc_type": "pdf",
                "page_count": len(text_parts),
            }
        )
