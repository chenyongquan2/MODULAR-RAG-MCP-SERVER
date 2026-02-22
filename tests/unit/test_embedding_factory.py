"""Unit tests for Embedding Factory and Base Embedding.

Test Coverage:
- Factory pattern: provider registration, creation, and routing
- Configuration-driven instantiation
- Error handling for unknown/missing providers
- Validation logic in BaseEmbedding
"""

from typing import Any, List, Optional
from unittest.mock import MagicMock

import pytest

from src.libs.embedding.base_embedding import BaseEmbedding
from src.libs.embedding.embedding_factory import EmbeddingFactory


class FakeEmbedding(BaseEmbedding):
    """Fake Embedding provider for testing.

    Returns deterministic fake vectors for reproducible testing.
    """

    # 默认向量维度
    DIMENSION = 3

    def __init__(
        self,
        settings: Any = None,
        model_name: str = "fake-embedding",
        dimension: int = DIMENSION,
        **kwargs: Any,
    ):
        """Initialize fake Embedding provider.

        Args:
            settings: Optional settings (unused in fake).
            model_name: Model name to report.
            dimension: Embedding vector dimension.
            **kwargs: Additional parameters (unused).
        """
        self.settings = settings
        self._model_name = model_name
        self._dimension = dimension
        self.call_count = 0
        self.last_texts: List[str] = []

    def embed(
        self,
        texts: List[str],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[List[float]]:
        """Generate fake embedding vectors.

        每个向量是基于文本长度生成的确定性向量。
        """
        self.validate_texts(texts)
        self.call_count += 1
        self.last_texts = texts

        # 返回确定性 fake 向量：基于文本长度生成稳定值
        vectors = []
        for text in texts:
            seed = float(len(text))
            vectors.append([seed / 100.0] * self._dimension)
        return vectors

    def get_model_name(self) -> str:
        """Return configured model name."""
        return self._model_name

    def get_dimension(self) -> int:
        """Return configured dimension."""
        return self._dimension


class TestBaseEmbedding:
    """Tests for BaseEmbedding abstract class."""

    def test_validate_texts_success(self):
        """Valid text list should pass validation."""
        embedding = FakeEmbedding()
        # Should not raise
        embedding.validate_texts(["hello", "world"])

    def test_validate_texts_single(self):
        """Single text should pass validation."""
        embedding = FakeEmbedding()
        embedding.validate_texts(["hello"])

    def test_validate_texts_empty_list(self):
        """Empty list should raise ValueError."""
        embedding = FakeEmbedding()
        with pytest.raises(ValueError, match="cannot be empty"):
            embedding.validate_texts([])

    def test_validate_texts_non_string(self):
        """Non-string entries should raise ValueError."""
        embedding = FakeEmbedding()
        with pytest.raises(ValueError, match="not a string"):
            embedding.validate_texts([123])  # type: ignore

    def test_validate_texts_mixed_types(self):
        """Mixed valid/invalid entries should raise on first invalid."""
        embedding = FakeEmbedding()
        with pytest.raises(ValueError, match="index 1"):
            embedding.validate_texts(["valid", 42])  # type: ignore

    def test_get_model_name_implemented(self):
        """FakeEmbedding should return configured model name."""
        embedding = FakeEmbedding(model_name="text-embedding-3-small")
        assert embedding.get_model_name() == "text-embedding-3-small"

    def test_get_model_name_not_implemented(self):
        """BaseEmbedding without override should raise NotImplementedError."""

        class IncompleteEmbedding(BaseEmbedding):
            def embed(
                self,
                texts: List[str],
                trace: Optional[Any] = None,
                **kwargs: Any,
            ) -> List[List[float]]:
                return [[0.0]]

        incomplete = IncompleteEmbedding()
        with pytest.raises(
            NotImplementedError, match="must implement get_model_name"
        ):
            incomplete.get_model_name()

    def test_get_dimension_implemented(self):
        """FakeEmbedding should return configured dimension."""
        embedding = FakeEmbedding(dimension=768)
        assert embedding.get_dimension() == 768

    def test_get_dimension_not_implemented(self):
        """BaseEmbedding without override should raise NotImplementedError."""

        class IncompleteEmbedding(BaseEmbedding):
            def embed(
                self,
                texts: List[str],
                trace: Optional[Any] = None,
                **kwargs: Any,
            ) -> List[List[float]]:
                return [[0.0]]

        incomplete = IncompleteEmbedding()
        with pytest.raises(
            NotImplementedError, match="must implement get_dimension"
        ):
            incomplete.get_dimension()


class TestFakeEmbedding:
    """Tests for FakeEmbedding provider implementation."""

    def test_embed_single_text(self):
        """Embedding single text should return one vector."""
        embedding = FakeEmbedding()
        result = embedding.embed(["hello"])

        assert len(result) == 1
        assert isinstance(result[0], list)
        assert len(result[0]) == FakeEmbedding.DIMENSION

    def test_embed_multiple_texts(self):
        """Embedding multiple texts should return matching count."""
        embedding = FakeEmbedding()
        texts = ["hello", "world", "foo"]
        result = embedding.embed(texts)

        assert len(result) == 3
        assert all(len(v) == FakeEmbedding.DIMENSION for v in result)

    def test_embed_deterministic(self):
        """Same input should produce same output."""
        embedding = FakeEmbedding()
        texts = ["deterministic test"]

        result1 = embedding.embed(texts)
        result2 = embedding.embed(texts)

        assert result1 == result2

    def test_embed_different_texts_different_vectors(self):
        """Different texts should produce different vectors."""
        embedding = FakeEmbedding()
        result = embedding.embed(["short", "a much longer text for testing"])

        assert result[0] != result[1]

    def test_embed_increments_call_count(self):
        """Each embed call should increment the counter."""
        embedding = FakeEmbedding()
        assert embedding.call_count == 0

        embedding.embed(["test1"])
        assert embedding.call_count == 1

        embedding.embed(["test2"])
        assert embedding.call_count == 2

    def test_embed_records_last_texts(self):
        """embed() should record the texts for inspection."""
        embedding = FakeEmbedding()
        texts = ["remember", "these"]
        embedding.embed(texts)

        assert embedding.last_texts == texts

    def test_embed_validates_input(self):
        """embed() should call validate_texts and raise on invalid input."""
        embedding = FakeEmbedding()

        with pytest.raises(ValueError, match="cannot be empty"):
            embedding.embed([])

        with pytest.raises(ValueError, match="not a string"):
            embedding.embed([42])  # type: ignore

    def test_embed_custom_dimension(self):
        """Custom dimension should affect vector length."""
        embedding = FakeEmbedding(dimension=768)
        result = embedding.embed(["test"])

        assert len(result[0]) == 768

    def test_embed_consistent_dimension(self):
        """All vectors in a batch should have the same dimension."""
        embedding = FakeEmbedding(dimension=128)
        result = embedding.embed(["a", "bb", "ccc", "dddd"])

        dimensions = {len(v) for v in result}
        assert len(dimensions) == 1
        assert dimensions.pop() == 128


class TestEmbeddingFactory:
    """Tests for EmbeddingFactory."""

    def setup_method(self):
        """Reset factory registry before each test."""
        EmbeddingFactory._PROVIDERS.clear()

    def test_register_provider_success(self):
        """Registering valid provider should succeed."""
        EmbeddingFactory.register_provider("fake", FakeEmbedding)
        assert "fake" in EmbeddingFactory._PROVIDERS
        assert EmbeddingFactory._PROVIDERS["fake"] == FakeEmbedding

    def test_register_provider_case_insensitive(self):
        """Provider names should be normalized to lowercase."""
        EmbeddingFactory.register_provider("OpenAI", FakeEmbedding)
        assert "openai" in EmbeddingFactory._PROVIDERS

    def test_register_provider_invalid_class(self):
        """Registering non-BaseEmbedding class should raise ValueError."""

        class NotAnEmbedding:
            pass

        with pytest.raises(ValueError, match="must inherit from BaseEmbedding"):
            EmbeddingFactory.register_provider(
                "invalid", NotAnEmbedding,  # type: ignore
            )

    def test_list_providers_empty(self):
        """list_providers should return empty list when no providers registered."""
        assert EmbeddingFactory.list_providers() == []

    def test_list_providers_sorted(self):
        """list_providers should return sorted provider names."""
        EmbeddingFactory.register_provider("zebra", FakeEmbedding)
        EmbeddingFactory.register_provider("alpha", FakeEmbedding)
        EmbeddingFactory.register_provider("beta", FakeEmbedding)

        providers = EmbeddingFactory.list_providers()
        assert providers == ["alpha", "beta", "zebra"]

    def test_create_success(self):
        """Creating registered provider should succeed."""
        EmbeddingFactory.register_provider("fake", FakeEmbedding)

        settings = MagicMock()
        settings.embedding.provider = "fake"

        embedding = EmbeddingFactory.create(settings)

        assert isinstance(embedding, FakeEmbedding)
        assert embedding.settings == settings

    def test_create_case_insensitive(self):
        """Provider lookup should be case-insensitive."""
        EmbeddingFactory.register_provider("fake", FakeEmbedding)

        settings = MagicMock()
        settings.embedding.provider = "FAKE"

        embedding = EmbeddingFactory.create(settings)
        assert isinstance(embedding, FakeEmbedding)

    def test_create_with_overrides(self):
        """Factory should pass override kwargs to provider constructor."""
        EmbeddingFactory.register_provider("fake", FakeEmbedding)

        settings = MagicMock()
        settings.embedding.provider = "fake"

        embedding = EmbeddingFactory.create(
            settings, model_name="custom-model",
        )
        assert embedding.get_model_name() == "custom-model"

    def test_create_unknown_provider(self):
        """Creating unregistered provider should raise clear error."""
        EmbeddingFactory.register_provider("fake", FakeEmbedding)

        settings = MagicMock()
        settings.embedding.provider = "unknown"

        with pytest.raises(ValueError) as exc_info:
            EmbeddingFactory.create(settings)

        error_message = str(exc_info.value)
        assert "Unsupported Embedding provider: 'unknown'" in error_message
        assert "Available providers:" in error_message

    def test_create_missing_provider_config(self):
        """Missing provider in settings should raise clear error."""
        settings = MagicMock()
        del settings.embedding  # Simulate missing config

        with pytest.raises(ValueError) as exc_info:
            EmbeddingFactory.create(settings)

        error_message = str(exc_info.value)
        assert "Missing required configuration" in error_message
        assert "settings.embedding.provider" in error_message
        assert "settings.yaml" in error_message

    def test_create_provider_instantiation_failure(self):
        """Provider constructor errors should be wrapped in RuntimeError."""

        class BrokenEmbedding(BaseEmbedding):
            def __init__(self, settings: Any, **kwargs: Any):
                raise ValueError("Intentional init error")

            def embed(
                self,
                texts: List[str],
                trace: Optional[Any] = None,
                **kwargs: Any,
            ) -> List[List[float]]:
                return [[0.0]]

        EmbeddingFactory.register_provider("broken", BrokenEmbedding)

        settings = MagicMock()
        settings.embedding.provider = "broken"

        with pytest.raises(RuntimeError) as exc_info:
            EmbeddingFactory.create(settings)

        error_message = str(exc_info.value)
        assert "Failed to instantiate Embedding provider 'broken'" in error_message
        assert "Intentional init error" in error_message

    def test_create_no_providers_registered(self):
        """Creating provider when registry is empty should show helpful message."""
        settings = MagicMock()
        settings.embedding.provider = "openai"

        with pytest.raises(ValueError) as exc_info:
            EmbeddingFactory.create(settings)

        error_message = str(exc_info.value)
        assert "Unsupported Embedding provider: 'openai'" in error_message
        assert "Available providers: none" in error_message

    def test_create_and_embed_roundtrip(self):
        """Factory-created embedding should produce valid vectors."""
        EmbeddingFactory.register_provider("fake", FakeEmbedding)

        settings = MagicMock()
        settings.embedding.provider = "fake"

        embedding = EmbeddingFactory.create(settings)
        vectors = embedding.embed(["hello world", "test"])

        assert len(vectors) == 2
        assert all(isinstance(v, list) for v in vectors)
        assert all(isinstance(x, float) for v in vectors for x in v)
