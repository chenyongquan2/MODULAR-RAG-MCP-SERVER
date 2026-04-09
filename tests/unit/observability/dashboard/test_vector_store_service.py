"""VectorStoreService 单元测试。

测试向量存储服务的功能，包括：
- 获取向量存储摘要
- 获取集合名称列表
- 获取后端名称

Design Principles Applied:
- Testability: 使用 mock BaseVectorStore 进行单元测试
- Fast: 不依赖外部服务（如 ChromaDB）
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from src.observability.dashboard.services.vector_store_service import (
    VectorStoreService,
    VectorStoreSummary,
    CollectionStats,
)


class MockVectorStore:
    """Mock VectorStore 实现。"""

    def __init__(self) -> None:
        """初始化 Mock VectorStore。"""
        self._collections = {
            "collection1": 100,
            "collection2": 200,
        }

    def get_backend_name(self) -> str:
        """获取后端名称。"""
        return "test_backend"

    def get_collection_names(self) -> List[str]:
        """获取集合名称列表。"""
        return list(self._collections.keys())

    def get_collection_stats(
        self, collection_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """获取集合统计信息。"""
        if collection_name:
            return {
                "name": collection_name,
                "count": self._collections.get(collection_name, 0),
            }
        else:
            collections = [
                {"name": name, "count": count}
                for name, count in self._collections.items()
            ]
            return {
                "collections": collections,
                "total_collections": len(collections),
                "total_vectors": sum(c["count"] for c in collections),
            }


class MockVectorStoreFactory:
    """Mock VectorStoreFactory 实现。"""

    @staticmethod
    def create(settings: Any) -> MockVectorStore:
        """创建 Mock VectorStore。"""
        return MockVectorStore()


class TestVectorStoreService:
    """VectorStoreService 测试类。"""

    def test_get_summary_with_default_settings(self, fake_settings, monkeypatch) -> None:
        """测试 get_summary 返回正确的摘要信息。"""
        # Arrange
        import src.observability.dashboard.services.vector_store_service as vs_module

        # Patch VectorStoreFactory to return mock
        def mock_create(settings):
            return MockVectorStore()

        monkeypatch.setattr(vs_module, "VectorStoreFactory", MockVectorStoreFactory)

        settings = fake_settings()
        service = VectorStoreService(settings)

        # Act
        summary = service.get_summary()

        # Assert
        assert summary.backend_name == "test_backend"
        assert summary.total_collections == 2
        assert summary.total_vectors == 300
        assert len(summary.collections) == 2
        assert summary.collections[0].name == "collection1"
        assert summary.collections[0].count == 100
        assert summary.collections[1].name == "collection2"
        assert summary.collections[1].count == 200

    def test_get_summary_with_no_collections(self, fake_settings, monkeypatch) -> None:
        """测试 get_summary 在没有集合时返回空摘要。"""
        # Arrange
        import src.observability.dashboard.services.vector_store_service as vs_module

        class EmptyVectorStore:
            def get_backend_name(self) -> str:
                return "empty_backend"

            def get_collection_names(self) -> List[str]:
                return []

            def get_collection_stats(
                self, collection_name: Optional[str] = None
            ) -> Dict[str, Any]:
                return {"collections": [], "total_collections": 0, "total_vectors": 0}

        class EmptyFactory:
            @staticmethod
            def create(settings: Any) -> EmptyVectorStore:
                return EmptyVectorStore()

        monkeypatch.setattr(vs_module, "VectorStoreFactory", EmptyFactory)

        settings = fake_settings()
        service = VectorStoreService(settings)

        # Act
        summary = service.get_summary()

        # Assert
        assert summary.backend_name == "empty_backend"
        assert summary.total_collections == 0
        assert summary.total_vectors == 0
        assert len(summary.collections) == 0

    def test_get_summary_on_vector_store_error(self, fake_settings, monkeypatch) -> None:
        """测试 get_summary 在向量存储错误时返回空摘要。"""
        # Arrange
        import src.observability.dashboard.services.vector_store_service as vs_module

        class RaisingFactory:
            @staticmethod
            def create(settings: Any):
                raise RuntimeError("Cannot connect to vector store")

        monkeypatch.setattr(vs_module, "VectorStoreFactory", RaisingFactory)

        settings = fake_settings()
        service = VectorStoreService(settings)

        # Act
        summary = service.get_summary()

        # Assert: 应该返回空摘要而不是抛出异常
        assert summary.backend_name == "unknown"
        assert summary.total_collections == 0
        assert summary.total_vectors == 0
        assert len(summary.collections) == 0

    def test_get_collection_names(self, fake_settings, monkeypatch) -> None:
        """测试获取集合名称列表。"""
        # Arrange
        import src.observability.dashboard.services.vector_store_service as vs_module

        monkeypatch.setattr(vs_module, "VectorStoreFactory", MockVectorStoreFactory)

        settings = fake_settings()
        service = VectorStoreService(settings)

        # Act
        names = service.get_collection_names()

        # Assert
        assert names == ["collection1", "collection2"]

    def test_get_collection_names_on_error(self, fake_settings, monkeypatch) -> None:
        """测试在错误时获取集合名称返回空列表。"""
        # Arrange
        import src.observability.dashboard.services.vector_store_service as vs_module

        class RaisingFactory:
            @staticmethod
            def create(settings: Any):
                raise RuntimeError("Error")

        monkeypatch.setattr(vs_module, "VectorStoreFactory", RaisingFactory)

        settings = fake_settings()
        service = VectorStoreService(settings)

        # Act
        names = service.get_collection_names()

        # Assert
        assert names == []

    def test_get_backend_name(self, fake_settings, monkeypatch) -> None:
        """测试获取后端名称。"""
        # Arrange
        import src.observability.dashboard.services.vector_store_service as vs_module

        monkeypatch.setattr(vs_module, "VectorStoreFactory", MockVectorStoreFactory)

        settings = fake_settings()
        service = VectorStoreService(settings)

        # Act
        backend = service.get_backend_name()

        # Assert
        assert backend == "test_backend"

    def test_get_backend_name_on_error(self, fake_settings, monkeypatch) -> None:
        """测试在错误时获取后端名称返回 'unknown'。"""
        # Arrange
        import src.observability.dashboard.services.vector_store_service as vs_module

        class RaisingFactory:
            @staticmethod
            def create(settings: Any):
                raise RuntimeError("Error")

        monkeypatch.setattr(vs_module, "VectorStoreFactory", RaisingFactory)

        settings = fake_settings()
        service = VectorStoreService(settings)

        # Act
        backend = service.get_backend_name()

        # Assert
        assert backend == "unknown"

    def test_lazy_initialization(self, fake_settings, monkeypatch) -> None:
        """测试向量存储实例是延迟初始化的。"""
        # Arrange
        import src.observability.dashboard.services.vector_store_service as vs_module

        create_calls = []

        class TrackedFactory:
            @staticmethod
            def create(settings: Any):
                create_calls.append(1)
                return MockVectorStore()

        monkeypatch.setattr(vs_module, "VectorStoreFactory", TrackedFactory)

        settings = fake_settings()
        service = VectorStoreService(settings)

        # Assert: create 不应该被调用（延迟初始化）
        assert len(create_calls) == 0

        # Act: 调用需要用到的函数
        service.get_summary()

        # Assert: create 应该被调用一次
        assert len(create_calls) == 1

        # Act: 再次调用
        service.get_summary()

        # Assert: create 不应该再次被调用（缓存）
        assert len(create_calls) == 1


class TestCollectionStats:
    """CollectionStats 测试类。"""

    def test_collection_stats_creation(self) -> None:
        """测试 CollectionStats 创建。"""
        # Act
        stats = CollectionStats(name="test_collection", count=123)

        # Assert
        assert stats.name == "test_collection"
        assert stats.count == 123


class TestVectorStoreSummary:
    """VectorStoreSummary 测试类。"""

    def test_vector_store_summary_creation(self) -> None:
        """测试 VectorStoreSummary 创建。"""
        # Arrange
        collections = [CollectionStats("col1", 100), CollectionStats("col2", 200)]

        # Act
        summary = VectorStoreSummary(
            backend_name="chromadb",
            total_collections=2,
            total_vectors=300,
            collections=collections,
        )

        # Assert
        assert summary.backend_name == "chromadb"
        assert summary.total_collections == 2
        assert summary.total_vectors == 300
        assert len(summary.collections) == 2
        assert summary.collections[0].name == "col1"
        assert summary.collections[0].count == 100


# ===================== Fixtures =====================


@pytest.fixture
def fake_settings():
    """创建假的 Settings 用于测试。"""
    from dataclasses import dataclass, field
    from typing import Any

    @dataclass
    class FakeVectorStoreSettings:
        backend: str = "test"
        persist_path: str = "./test/path"
        collection_name: str = "test_collection"

    @dataclass
    class FakeSettings:
        vector_store: FakeVectorStoreSettings = field(
            default_factory=FakeVectorStoreSettings
        )

    return FakeSettings