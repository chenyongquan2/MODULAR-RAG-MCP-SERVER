"""Markdown Loader."""

import hashlib
from pathlib import Path

from src.core.types import Document
from .base_loader import BaseLoader


class MarkdownLoader(BaseLoader):
    """Markdown 文档加载器。

    Attributes:
        collection: 文档所属集合名称
    """

    def __init__(self, collection: str = "default"):
        """初始化 Markdown 加载器。

        Args:
            collection: 文档所属集合名称
        """
        super().__init__(collection)

    def load(self, path: str | Path) -> Document:
        """加载 Markdown 文档。

        Args:
            path: Markdown 文件路径

        Returns:
            Document: 加载后的文档对象

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文件格式不支持
        """
        path = self._validate_path(path)

        if path.suffix.lower() not in [".md", ".markdown"]:
            raise ValueError(f"Unsupported file format: {path.suffix}. Expected .md or .markdown")

        text = path.read_text(encoding="utf-8")

        doc_hash = hashlib.sha256(path.read_bytes()).hexdigest()[:16]

        return Document(
            id=f"doc_{doc_hash}",
            text=text,
            metadata={
                "source_path": str(path),
                "collection": self.collection,
                "title": path.stem,
                "doc_type": "markdown",
            },
        )
