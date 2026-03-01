"""Transform 抽象基类。

定义数据转换接口，用于 ingestion pipeline 中的 chunk 转换处理。
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from src.core.types import Chunk
from src.core.trace.trace_context import TraceContext


class BaseTransform(ABC):
    """数据转换抽象基类。

    所有转换器（如 ChunkRefiner、MetadataEnricher）都应继承此类。
    """

    @abstractmethod
    def transform(
        self,
        chunks: List[Chunk],
        trace: Optional[TraceContext] = None
    ) -> List[Chunk]:
        """转换 chunks。

        Args:
            chunks: 待转换的 chunks 列表
            trace: 追踪上下文（可选）

        Returns:
            转换后的 chunks 列表
        """
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"
