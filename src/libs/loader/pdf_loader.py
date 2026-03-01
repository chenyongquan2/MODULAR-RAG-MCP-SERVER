"""PDF Loader (MarkItDown)。"""

import hashlib
from pathlib import Path

from markitdown import MarkItDown

from core.types import Document
from .base_loader import BaseLoader


class PdfLoader(BaseLoader):
    """PDF 文档加载器。

    使用 MarkItDown 库将 PDF 转换为 Markdown 格式，
    保留文档结构（标题、列表、代码块等）。

    Attributes:
        collection: 文档所属集合名称
    """

    def __init__(self, collection: str = "default"):
        """初始化 PDF 加载器。

        Args:
            collection: 文档所属集合名称
        """
        super().__init__(collection)
        self._converter = MarkItDown()

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

        result = self._converter.convert(str(path))
        text = result.text_content

        doc_hash = hashlib.sha256(path.read_bytes()).hexdigest()[:16]

        return Document(
            id=f"doc_{doc_hash}",
            text=text,
            metadata={
                "source_path": str(path),
                "collection": self.collection,
                "doc_type": "pdf",
            }
        )
