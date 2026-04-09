"""ConfigService 单元测试。

测试配置服务的功能，包括：
- 组件配置读取
- 向量存储路径获取
- 日志文件路径获取
- 可观测性状态检查

Design Principles Applied:
- Testability: 使用 mock Settings 对象进行单元测试
- Fast: 不依赖外部服务
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from src.core.settings import (
    LLMSettings,
    EmbeddingSettings,
    VisionLLMSettings,
    VectorStoreSettings,
    SplitterSettings,
    RerankSettings,
    RetrievalSettings,
    IngestionSettings,
    ChunkRefinerSettings,
    MetadataEnricherSettings,
    ImageCaptionerSettings,
    TextEnricherSettings,
    ObservabilitySettings,
)
from src.observability.dashboard.services.config_service import (
    ConfigService,
    ComponentConfig,
)


class TestConfigService:
    """ConfigService 测试类。"""

    def test_get_all_components_returns_all_components(self, fake_settings: type) -> None:
        """测试 get_all_components 返回所有组件。"""
        # Arrange
        settings = fake_settings()
        config_service = ConfigService(settings)

        # Act
        components = config_service.get_all_components()

        # Assert
        assert len(components) == 7  # LLM, Embedding, Vision, VectorStore, Splitter, Reranker, Retrieval
        component_names = {c.name for c in components}
        expected_names = {
            "LLM",
            "Embedding",
            "Vision LLM",
            "Vector Store",
            "Splitter",
            "Reranker",
            "Retrieval",
        }
        assert component_names == expected_names

    def test_get_all_components_llm_config(self, fake_settings: type) -> None:
        """测试 LLM 组件配置正确。"""
        # Arrange
        settings = fake_settings()
        config_service = ConfigService(settings)

        # Act
        components = config_service.get_all_components()
        llm_component = next((c for c in components if c.name == "LLM"), None)

        # Assert
        assert llm_component is not None
        assert llm_component.provider == "test_llm"
        assert llm_component.model == "test-model"
        assert llm_component.details["has_api_key"] is True
        assert llm_component.details["azure_endpoint"] == "http://test"

    def test_get_all_components_embedding_config(self, fake_settings: type) -> None:
        """测试 Embedding 组件配置正确。"""
        # Arrange
        settings = fake_settings()
        config_service = ConfigService(settings)

        # Act
        components = config_service.get_all_components()
        embedding_component = next(
            (c for c in components if c.name == "Embedding"), None
        )

        # Assert
        assert embedding_component is not None
        assert embedding_component.provider == "test_embedding"
        assert embedding_component.model == "test-embedding-model"
        assert embedding_component.details["has_api_key"] is True

    def test_get_all_components_vector_store_config(self, fake_settings: type) -> None:
        """测试 Vector Store 组件配置正确。"""
        # Arrange
        settings = fake_settings()
        config_service = ConfigService(settings)

        # Act
        components = config_service.get_all_components()
        vs_component = next(
            (c for c in components if c.name == "Vector Store"), None
        )

        # Assert
        assert vs_component is not None
        assert vs_component.provider == "chroma"
        assert vs_component.model == "N/A"
        assert vs_component.details["persist_path"] == "./test/db"
        assert vs_component.details["collection_name"] == "test_collection"

    def test_get_all_components_splitter_config(self, fake_settings: type) -> None:
        """测试 Splitter 组件配置正确。"""
        # Arrange
        settings = fake_settings()
        config_service = ConfigService(settings)

        # Act
        components = config_service.get_all_components()
        splitter_component = next(
            (c for c in components if c.name == "Splitter"), None
        )

        # Assert
        assert splitter_component is not None
        assert splitter_component.provider == "recursive"
        assert splitter_component.model == "N/A"
        assert splitter_component.details["chunk_size"] == 1000
        assert splitter_component.details["chunk_overlap"] == 200

    def test_get_vector_store_path(self, fake_settings: type) -> None:
        """测试获取向量存储路径。"""
        # Arrange
        settings = fake_settings()
        config_service = ConfigService(settings)

        # Act
        path = config_service.get_vector_store_path()

        # Assert
        assert path == "./test/db"

    def test_get_log_file_path(self, fake_settings: type) -> None:
        """测试获取日志文件路径。"""
        # Arrange
        settings = fake_settings()
        config_service = ConfigService(settings)

        # Act
        path = config_service.get_log_file_path()

        # Assert
        assert path == "./test/traces.jsonl"

    def test_is_observability_enabled_true(self, fake_settings: type) -> None:
        """测试可观测性启用状态（启用）。"""
        # Arrange
        settings = fake_settings()

        # Act
        config_service = ConfigService(settings)
        enabled = config_service.is_observability_enabled()

        # Assert
        assert enabled is True

    def test_get_settings_returns_original_settings(self, fake_settings: type) -> None:
        """测试 get_settings 返回原始 Settings 对象。"""
        # Arrange
        settings = fake_settings()
        config_service = ConfigService(settings)

        # Act
        returned_settings = config_service.get_settings()

        # Assert
        assert returned_settings is settings


class TestComponentConfig:
    """ComponentConfig 测试类。"""

    def test_component_config_creation(self) -> None:
        """测试 ComponentConfig 创建。"""
        # Act
        config = ComponentConfig(
            name="Test Component",
            provider="test_provider",
            model="test_model",
            details={"key": "value"},
        )

        # Assert
        assert config.name == "Test Component"
        assert config.provider == "test_provider"
        assert config.model == "test_model"
        assert config.details == {"key": "value"}


# ===================== Fixtures =====================


@pytest.fixture
def fake_settings() -> type:
    """创建假的 Settings 用于测试。"""
    @dataclass
    class FakeObservabilitySettings:
        """假的 ObservabilitySettings 用于测试。"""
        enabled: bool = True
        log_file: str = "./test/traces.jsonl"

    @dataclass
    class FakeSettings:
        """假的 Settings 用于测试。"""
        llm: LLMSettings = field(
            default_factory=lambda: LLMSettings(
                provider="test_llm",
                model="test-model",
                azure_endpoint="http://test",
                api_key="test-key",
            )
        )
        embedding: EmbeddingSettings = field(
            default_factory=lambda: EmbeddingSettings(
                provider="test_embedding",
                model="test-embedding-model",
                api_key="test-embedding-key",
            )
        )
        vision_llm: VisionLLMSettings = field(
            default_factory=lambda: VisionLLMSettings(
                provider="azure",
                model="gpt-4-vision",
            )
        )
        vector_store: VectorStoreSettings = field(
            default_factory=lambda: VectorStoreSettings(
                backend="chroma",
                persist_path="./test/db",
                collection_name="test_collection",
            )
        )
        splitter: SplitterSettings = field(
            default_factory=lambda: SplitterSettings(
                strategy="recursive",
                chunk_size=1000,
                chunk_overlap=200,
            )
        )
        rerank: Any = field(
            default_factory=lambda: RerankSettings(
                backend="cross_encoder",
                model="test-reranker",
                top_m=30,
            )
        )
        retrieval: Any = field(
            default_factory=lambda: RetrievalSettings(
                sparse_backend="bm25",
                fusion_algorithm="rrf",
                top_k_dense=20,
                top_k_sparse=20,
                top_k_final=10,
            )
        )
        ingestion: IngestionSettings = field(
            default_factory=lambda: IngestionSettings(
                chunk_refiner=ChunkRefinerSettings(use_llm=False),
                metadata_enricher=MetadataEnricherSettings(use_llm=False),
                image_captioner=ImageCaptionerSettings(enabled=False),
                text_enricher=TextEnricherSettings(enabled=True),
            )
        )
        observability: FakeObservabilitySettings = field(
            default_factory=FakeObservabilitySettings
        )

    return FakeSettings