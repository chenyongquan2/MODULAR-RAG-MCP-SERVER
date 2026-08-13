"""配置读取服务。

提供 Dashboard 所需的配置读取和格式化功能，包括：
- 读取系统配置（Settings）
- 获取组件配置摘要
- 获取数据存储统计信息

Design Principles Applied:
- Config-Driven: 所有配置从 settings.yaml 读取
- Observable: 提供结构化配置信息用于展示
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.core.settings import Settings


@dataclass
class ComponentConfig:
    """组件配置摘要。

    Attributes:
        name: 组件名称（如 "LLM", "Embedding"）
        provider: 提供商名称（如 "openai", "chroma"）
        model: 模型名称（如 "gpt-4", "text-embedding-3-small"）
        details: 其他配置详情（如 endpoint, api_key 状态等）
    """

    name: str
    provider: str
    model: str
    details: Dict[str, Any]


class ConfigService:
    """配置读取服务。

    封装配置读取逻辑，为 Dashboard 提供结构化的配置信息。
    """

    def __init__(self, settings: Settings) -> None:
        """初始化配置服务。

        Args:
            settings: 应用配置对象。
        """
        self._settings = settings

    def get_all_components(self) -> List[ComponentConfig]:
        """获取所有组件的配置摘要。

        Returns:
            组件配置列表，包含 LLM、Embedding、Splitter、Reranker、VectorStore 等。
        """
        components = []

        # LLM 配置
        llm_config = ComponentConfig(
            name="LLM",
            provider=self._settings.llm.provider,
            model=self._settings.llm.model,
            details={
                "azure_endpoint": self._settings.llm.azure_endpoint,
                "has_api_key": bool(self._settings.llm.api_key),
                "base_url": self._settings.llm.base_url,
            },
        )
        components.append(llm_config)

        # Embedding 配置
        embedding_config = ComponentConfig(
            name="Embedding",
            provider=self._settings.embedding.provider,
            model=self._settings.embedding.model,
            details={
                "has_api_key": bool(self._settings.embedding.api_key),
                "base_url": self._settings.embedding.base_url,
            },
        )
        components.append(embedding_config)

        # Vision LLM 配置
        vision_config = ComponentConfig(
            name="Vision LLM",
            provider=self._settings.vision_llm.provider,
            model=self._settings.vision_llm.model,
            details={},
        )
        components.append(vision_config)

        # Vector Store 配置
        vector_config = ComponentConfig(
            name="Vector Store",
            provider=self._settings.vector_store.backend,
            model="N/A",  # Vector store 没有 model 概念
            details={
                "persist_path": self._settings.vector_store.persist_path,
                "collection_name": self._settings.vector_store.collection_name,
            },
        )
        components.append(vector_config)

        # Splitter 配置
        splitter_config = ComponentConfig(
            name="Splitter",
            provider=self._settings.splitter.strategy,
            model="N/A",
            details={
                "chunk_size": self._settings.splitter.chunk_size,
                "chunk_overlap": self._settings.splitter.chunk_overlap,
            },
        )
        components.append(splitter_config)

        # Reranker 配置
        # top_m / timeout_sec / batch_size 三项都影响重排的实际行为与延迟，
        # dashboard 上要能一眼看全 —— 此前只暴露 top_m，而那时它还是个死配置。
        reranker_config = ComponentConfig(
            name="Reranker",
            provider=self._settings.rerank.backend,
            model=self._settings.rerank.model or "N/A",
            details={
                "top_m": self._settings.rerank.top_m,
                "timeout_sec": self._settings.rerank.timeout_sec,
                "batch_size": self._settings.rerank.batch_size,
            },
        )
        components.append(reranker_config)

        # Retrieval 配置
        retrieval_config = ComponentConfig(
            name="Retrieval",
            provider=f"{self._settings.retrieval.sparse_backend}+{self._settings.retrieval.fusion_algorithm}",
            model="N/A",
            details={
                "top_k_dense": self._settings.retrieval.top_k_dense,
                "top_k_sparse": self._settings.retrieval.top_k_sparse,
                "top_k_final": self._settings.retrieval.top_k_final,
            },
        )
        components.append(retrieval_config)

        return components

    def get_vector_store_path(self) -> str:
        """获取向量存储路径。

        Returns:
            向量存储的持久化路径。
        """
        return self._settings.vector_store.persist_path

    def get_log_file_path(self) -> str:
        """获取日志文件路径。

        Returns:
            日志文件路径。
        """
        return self._settings.observability.log_file

    def is_observability_enabled(self) -> bool:
        """检查可观测性是否启用。

        Returns:
            可观测性是否启用。
        """
        return self._settings.observability.enabled

    def get_settings(self) -> Settings:
        """获取原始 Settings 对象。

        Returns:
            完整的 Settings 对象。
        """
        return self._settings