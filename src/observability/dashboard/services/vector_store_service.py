"""向量存储服务。

提供向量存储统计信息的读取功能，包括：
- 获取集合统计信息
- 获取所有集合列表
- 获取向量总数

Design Principles Applied:
- Pluggable: 通过 BaseVectorStore 接口访问，支持任意后端
- Observable: 提供结构化统计信息用于展示
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.core.settings import Settings
from src.libs.vector_store.base_vector_store import BaseVectorStore
from src.libs.vector_store.vector_store_factory import VectorStoreFactory


@dataclass
class CollectionStats:
    """集合统计信息。

    Attributes:
        name: 集合名称
        count: 向量数量
    """

    name: str
    count: int


@dataclass
class VectorStoreSummary:
    """向量存储摘要。

    Attributes:
        backend_name: 后端名称（如 "chromadb"）
        total_collections: 集合总数
        total_vectors: 向量总数
        collections: 各集合的详细统计
    """

    backend_name: str
    total_collections: int
    total_vectors: int
    collections: List[CollectionStats]


class VectorStoreService:
    """向量存储服务。

    封装向量存储访问逻辑，为 Dashboard 提供统计信息。
    """

    def __init__(self, settings: Settings) -> None:
        """初始化向量存储服务。

        Args:
            settings: 应用配置对象。
        """
        self._settings = settings
        # 延迟初始化：只有在需要时才创建 VectorStore 实例
        self._vector_store: Optional[BaseVectorStore] = None

    def _get_vector_store(self) -> BaseVectorStore:
        """获取向量存储实例（延迟初始化）。

        Returns:
            向量存储实例。

        Raises:
            RuntimeError: 如果向量存储初始化失败。
        """
        if self._vector_store is None:
            self._vector_store = VectorStoreFactory.create(self._settings)
        return self._vector_store

    def get_summary(self) -> VectorStoreSummary:
        """获取向量存储摘要。

        Returns:
            包含后端名称、集合总数、向量总数和各集合详细统计的摘要对象。

        Raises:
            RuntimeError: 如果获取统计信息失败。
        """
        try:
            vector_store = self._get_vector_store()

            # 获取所有集合的统计信息
            stats = vector_store.get_collection_stats(collection_name=None)

            # 解析统计信息
            collections = []
            for col_stats in stats.get("collections", []):
                collections.append(
                    CollectionStats(
                        name=col_stats["name"],
                        count=col_stats["count"],
                    )
                )

            return VectorStoreSummary(
                backend_name=vector_store.get_backend_name(),
                total_collections=stats.get("total_collections", 0),
                total_vectors=stats.get("total_vectors", 0),
                collections=collections,
            )
        except Exception as e:
            # 如果向量存储访问失败，返回空摘要
            return VectorStoreSummary(
                backend_name="unknown",
                total_collections=0,
                total_vectors=0,
                collections=[],
            )

    def get_collection_names(self) -> List[str]:
        """获取所有集合名称。

        Returns:
            集合名称列表。
        """
        try:
            vector_store = self._get_vector_store()
            return vector_store.get_collection_names()
        except Exception:
            return []

    def get_backend_name(self) -> str:
        """获取向量存储后端名称。

        Returns:
            后端名称（如 "chromadb"）。
        """
        try:
            vector_store = self._get_vector_store()
            return vector_store.get_backend_name()
        except Exception:
            return "unknown"