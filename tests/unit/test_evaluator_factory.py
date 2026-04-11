"""Unit tests for EvaluatorFactory."""

import pytest

from src.libs.evaluator.evaluator_factory import EvaluatorFactory
from src.libs.evaluator.base_evaluator import BaseEvaluator
from src.libs.evaluator.custom_evaluator import CustomEvaluator
from src.observability.evaluation.ragas_evaluator import RagasEvaluator
from src.core.settings import Settings, EvaluationSettings


@pytest.fixture
def mock_settings_custom():
    """Create Settings with custom evaluator backend."""
    settings = Settings(
        llm=None,
        embedding=None,
        vision_llm=None,
        vector_store=None,
        evaluation=EvaluationSettings(backends=["custom"]),
    )
    return settings


class TestEvaluatorFactory:
    """Test suite for EvaluatorFactory."""

    def test_create_custom_evaluator(self, mock_settings_custom):
        """Test creating custom evaluator via factory."""
        evaluator = EvaluatorFactory.create(mock_settings_custom)

        assert isinstance(evaluator, BaseEvaluator)
        assert isinstance(evaluator, CustomEvaluator)

    def test_unsupported_backend_raises_error(self):
        """Test that unsupported backend raises ValueError with clear message."""
        settings = Settings(
            llm=None,
            embedding=None,
            vision_llm=None,
            vector_store=None,
            evaluation=EvaluationSettings(backends=["unsupported_backend"]),
        )

        with pytest.raises(ValueError) as exc_info:
            EvaluatorFactory.create(settings)

        error_msg = str(exc_info.value)
        assert "Unsupported Evaluator provider" in error_msg
        assert "unsupported_backend" in error_msg
        assert "Available providers:" in error_msg

    def test_missing_backends_raises_error(self):
        """Test that missing backends field raises ValueError."""
        settings = Settings(
            llm=None,
            embedding=None,
            vision_llm=None,
            vector_store=None,
            evaluation=EvaluationSettings(backends=[]),  # Empty list
        )

        with pytest.raises(ValueError) as exc_info:
            EvaluatorFactory.create(settings)

        assert "backends list is empty" in str(exc_info.value)

    def test_factory_creates_working_evaluator(self, mock_settings_custom):
        """Test that factory-created evaluator works correctly."""
        evaluator = EvaluatorFactory.create(mock_settings_custom)

        retrieved = ["chunk_1", "chunk_2", "chunk_3"]
        golden = ["chunk_2"]

        metrics = evaluator.evaluate("test query", retrieved, golden)

        assert "hit_rate" in metrics
        assert "mrr" in metrics
        assert metrics["hit_rate"] == 1.0
        assert metrics["mrr"] == 0.5

    def test_list_providers(self):
        """Test that list_providers returns available providers."""
        providers = EvaluatorFactory.list_providers()

        assert isinstance(providers, list)
        assert "custom" in providers
        assert "ragas" in providers
        assert providers == sorted(providers)  # Should be sorted

    def test_create_ragas_evaluator(self):
        """Test creating ragas evaluator via factory."""
        settings = Settings(
            llm=None,
            embedding=None,
            vision_llm=None,
            vector_store=None,
            evaluation=EvaluationSettings(backends=["ragas"]),
        )

        evaluator = EvaluatorFactory.create(settings)

        assert isinstance(evaluator, BaseEvaluator)
        assert isinstance(evaluator, RagasEvaluator)

    def test_register_provider(self):
        """Test manual provider registration."""

        class MockEvaluator(BaseEvaluator):
            def __init__(self, settings, **kwargs):
                pass

            def evaluate(self, query, retrieved_ids, golden_ids, trace=None, **kwargs):
                return {"mock_metric": 0.5}

        # Register new provider
        EvaluatorFactory.register_provider("mock", MockEvaluator)

        # Verify it's in the registry
        assert "mock" in EvaluatorFactory.list_providers()

        # Create instance
        settings = Settings(
            llm=None,
            embedding=None,
            vision_llm=None,
            vector_store=None,
            evaluation=EvaluationSettings(backends=["mock"]),
        )
        evaluator = EvaluatorFactory.create(settings)

        assert isinstance(evaluator, MockEvaluator)

    def test_register_invalid_provider_raises_error(self):
        """Test that registering non-BaseEvaluator class raises error."""

        class NotAnEvaluator:
            pass

        with pytest.raises(ValueError) as exc_info:
            EvaluatorFactory.register_provider("invalid", NotAnEvaluator)

        assert "must inherit from BaseEvaluator" in str(exc_info.value)
