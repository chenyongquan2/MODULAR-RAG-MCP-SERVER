"""Loader 抽象基类。"""

from abc import ABC, abstractmethod
from pathlib import Path

from core.types import Document


class BaseLoader(ABC):
    """文档加载器抽象基类。

    所有文档加载器必须继承此类并实现 load 方法。
    支持从不同格式（PDF、Markdown、HTML 等）加载文档。

    Attributes:
        collection: 文档所属集合名称
    """

    def __init__(self, collection: str = "default"):
        """初始化加载器。

        Args:
            collection: 文档所属集合名称
        """
        self.collection = collection

    @abstractmethod
    def load(self, path: str | Path) -> Document:
        """加载文档。

        Args:
            path: 文档路径

        Returns:
            Document: 加载后的文档对象

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文件格式不支持
        """
        pass

    def _validate_path(self, path: str | Path) -> Path:
        """验证文件路径。

        Args:
            path: 文件路径

        Returns:
            Path: 规范化后的路径

        Raises:
            FileNotFoundError: 文件不存在
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if not path.is_file():
            raise ValueError(f"Not a file: {path}")
        return path
