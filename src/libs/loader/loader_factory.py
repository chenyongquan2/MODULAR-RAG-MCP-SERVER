"""LoaderFactory - 根据文件扩展名自动选择并实例化对应的 Loader。

设计与 LLMFactory / EmbeddingFactory 保持一致：
- 注册表模式（_REGISTRY）：扩展名 → Loader 类的映射
- 内置 Loader 在模块首次导入时自动注册（_register_builtin_loaders）
- 支持外部通过 register() 扩展新格式，无需修改此文件

典型用法：
    from libs.loader.loader_factory import LoaderFactory
    loader = LoaderFactory.create("doc.pdf", settings.loader, collection="my_docs")
    document = loader.load("doc.pdf")
"""

from pathlib import Path
from typing import Dict, Type

from src.core.settings import LoaderSettings
from src.observability.logger import get_logger
from .base_loader import BaseLoader

logger = get_logger(__name__)


class LoaderFactory:
    """文档加载器工厂。

    根据文件扩展名自动选择 Loader，与项目其他工厂模式（LLMFactory 等）保持一致。
    """

    # 扩展名 → Loader 类的注册表，键统一小写（如 ".pdf"）
    _REGISTRY: Dict[str, Type[BaseLoader]] = {}

    @classmethod
    def register(cls, extensions: list[str], loader_cls: Type[BaseLoader]) -> None:
        """注册文件扩展名到 Loader 类的映射。

        Args:
            extensions: 文件扩展名列表（含点，如 [".pdf", ".PDF"]）
            loader_cls: 对应的 Loader 实现类
        """
        for ext in extensions:
            cls._REGISTRY[ext.lower()] = loader_cls
            logger.debug(f"注册 Loader: {ext.lower()} → {loader_cls.__name__}")

    @classmethod
    def create(
        cls,
        file_path: str | Path,
        settings: LoaderSettings,
        collection: str = "default",
    ) -> BaseLoader:
        """根据文件扩展名创建对应的 Loader 实例。

        Args:
            file_path: 目标文件路径（仅用于推断扩展名，不需要文件存在）
            settings: LoaderSettings 配置对象
            collection: 文档所属集合名称

        Returns:
            BaseLoader: 已配置的 Loader 实例

        Raises:
            ValueError: 文件扩展名未注册（格式不支持）
        """
        ext = Path(file_path).suffix.lower()
        loader_cls = cls._REGISTRY.get(ext)

        if loader_cls is None:
            supported = ", ".join(sorted(cls._REGISTRY.keys()))
            raise ValueError(
                f"不支持的文件格式: '{ext}'，已支持格式: {supported}"
            )

        # PDFLoader 支持额外的 settings 参数（OCR、表格识别等）
        # 其他 Loader 只需要 collection
        if ext == ".pdf":
            return loader_cls(
                collection=collection,
                enable_ocr=settings.enable_ocr,
                enable_table_structure=settings.enable_table_structure,
                extract_images=settings.extract_images,
            )

        return loader_cls(collection=collection)

    @classmethod
    def list_supported(cls) -> list[str]:
        """列出所有已注册的文件扩展名。

        Returns:
            list[str]: 已支持的扩展名列表（已排序）
        """
        return sorted(cls._REGISTRY.keys())


def _register_builtin_loaders() -> None:
    """注册项目内置的 Loader，在模块首次导入时自动执行。

    添加新格式时：在此处增加 register() 调用，无需修改 LoaderFactory 本身。
    """
    from .pdf_loader import PdfLoader
    from .markdown_loader import MarkdownLoader
    from .chm_loader import ChmLoader

    LoaderFactory.register([".pdf"], PdfLoader)
    LoaderFactory.register([".md", ".markdown"], MarkdownLoader)
    LoaderFactory.register([".chm"], ChmLoader)

    logger.debug(f"内置 Loader 注册完成，已支持格式: {LoaderFactory.list_supported()}")


# 模块导入时立即注册内置 Loader
_register_builtin_loaders()
