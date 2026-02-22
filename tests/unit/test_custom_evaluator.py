"""Unit tests for CustomEvaluator."""

import pytest

from src.libs.evaluator.custom_evaluator import CustomEvaluator
from src.core.settings import Settings, EvaluationSettings


@pytest.fixture
def mock_settings():
    """Create a minimal Settings object for testing."""
    settings = Settings(
        llm=None,  # Not needed for evaluator tests
        embedding=None,
        vision_llm=None,
        vector_store=None,
        evaluation=EvaluationSettings(backends=["custom"]),
    )
    return settings


class TestCustomEvaluator:
    """Test suite for CustomEvaluator."""

    def test_hit_rate_perfect_match(self, mock_settings):
        """Test hit_rate when all golden IDs are in retrieved set."""
        evaluator = CustomEvaluator(settings=mock_settings)

        retrieved = ["chunk_1", "chunk_2", "chunk_3"]
        golden = ["chunk_2"]

        metrics = evaluator.evaluate("test query", retrieved, golden)

        assert "hit_rate" in metrics
        assert metrics["hit_rate"] == 1.0

    def test_hit_rate_no_match(self, mock_settings):
        """Test hit_rate when no golden IDs are in retrieved set."""
        evaluator = CustomEvaluator(settings=mock_settings)

        retrieved = ["chunk_1", "chunk_2", "chunk_3"]
        golden = ["chunk_10", "chunk_20"]

        metrics = evaluator.evaluate("test query", retrieved, golden)

        assert "hit_rate" in metrics
        assert metrics["hit_rate"] == 0.0

    def test_hit_rate_partial_match(self, mock_settings):
        """Test hit_rate when some golden IDs are in retrieved set."""
        evaluator = CustomEvaluator(settings=mock_settings)

        retrieved = ["chunk_1", "chunk_2", "chunk_3"]
        golden = ["chunk_2", "chunk_10"]  # Only chunk_2 is present

        metrics = evaluator.evaluate("test query", retrieved, golden)

        # Hit rate is binary: 1.0 if ANY match exists
        assert metrics["hit_rate"] == 1.0

    def test_mrr_first_position(self, mock_settings):
        """Test MRR when first retrieved item is golden."""
        evaluator = CustomEvaluator(settings=mock_settings)

        retrieved = ["chunk_gold", "chunk_2", "chunk_3"]
        golden = ["chunk_gold"]

        metrics = evaluator.evaluate("test query", retrieved, golden)

        assert "mrr" in metrics
        assert metrics["mrr"] == 1.0

    def test_mrr_second_position(self, mock_settings):
        """Test MRR when second retrieved item is golden."""
        evaluator = CustomEvaluator(settings=mock_settings)

        retrieved = ["chunk_1", "chunk_gold", "chunk_3"]
        golden = ["chunk_gold"]

        metrics = evaluator.evaluate("test query", retrieved, golden)

        assert metrics["mrr"] == 0.5

    def test_mrr_third_position(self, mock_settings):
        """Test MRR when third retrieved item is golden."""
        evaluator = CustomEvaluator(settings=mock_settings)

        retrieved = ["chunk_1", "chunk_2", "chunk_gold"]
        golden = ["chunk_gold"]

        metrics = evaluator.evaluate("test query", retrieved, golden)

        assert abs(metrics["mrr"] - 1.0 / 3) < 1e-6

    def test_mrr_no_hit(self, mock_settings):
        """Test MRR when no golden IDs are retrieved."""
        evaluator = CustomEvaluator(settings=mock_settings)

        retrieved = ["chunk_1", "chunk_2", "chunk_3"]
        golden = ["chunk_gold"]

        metrics = evaluator.evaluate("test query", retrieved, golden)

        assert metrics["mrr"] == 0.0

    def test_mrr_multiple_golden_first_hit_counts(self, mock_settings):
        """Test MRR with multiple golden IDs - first hit determines rank."""
        evaluator = CustomEvaluator(settings=mock_settings)

        retrieved = ["chunk_1", "chunk_2", "gold_2", "chunk_4", "gold_1"]
        golden = ["gold_1", "gold_2"]

        metrics = evaluator.evaluate("test query", retrieved, golden)

        # gold_2 appears first at position 3
        assert abs(metrics["mrr"] - 1.0 / 3) < 1e-6

    def test_empty_golden_ids_raises_error(self, mock_settings):
        """Test that empty golden_ids raises ValueError."""
        evaluator = CustomEvaluator(settings=mock_settings)

        retrieved = ["chunk_1", "chunk_2", "chunk_3"]
        golden = []

        with pytest.raises(ValueError) as exc_info:
            evaluator.evaluate("test query", retrieved, golden)

        assert "golden_ids cannot be empty" in str(exc_info.value)

    def test_empty_retrieved_ids_raises_error(self, mock_settings):
        """Test that empty retrieved_ids raises ValueError."""
        evaluator = CustomEvaluator(settings=mock_settings)

        retrieved = []
        golden = ["chunk_1"]

        with pytest.raises(ValueError) as exc_info:
            evaluator.evaluate("test query", retrieved, golden)

        assert "retrieved_ids cannot be empty" in str(exc_info.value)

    def test_duplicate_ids_handled_gracefully(self, mock_settings):
        """Test that duplicate IDs in inputs are handled correctly."""
        evaluator = CustomEvaluator(settings=mock_settings)

        # Duplicates in retrieved list
        retrieved = ["chunk_1", "chunk_2", "chunk_2", "chunk_3"]
        golden = ["chunk_2"]

        metrics = evaluator.evaluate("test query", retrieved, golden)

        # Should still calculate correctly (set deduplication)
        assert metrics["hit_rate"] == 1.0
        assert metrics["mrr"] == 0.5  # First occurrence at position 2

    def test_deterministic_output(self, mock_settings):
        """Test that same inputs always produce same outputs."""
        evaluator = CustomEvaluator(settings=mock_settings)

        retrieved = ["chunk_1", "chunk_2", "chunk_3"]
        golden = ["chunk_2"]

        metrics_1 = evaluator.evaluate("test", retrieved, golden)
        metrics_2 = evaluator.evaluate("test", retrieved, golden)

        assert metrics_1 == metrics_2

    @pytest.mark.skip(reason="TraceContext not yet implemented (Stage G)")
    def test_trace_context_integration(self, mock_settings):
        """Test trace context integration (reserved for Stage F)."""
        from src.core.trace.trace_context import TraceContext

        evaluator = CustomEvaluator(settings=mock_settings)
        trace = TraceContext(operation="test_evaluation")

        retrieved = ["chunk_1", "chunk_2", "chunk_3"]
        golden = ["chunk_2"]

        metrics = evaluator.evaluate("test query", retrieved, golden, trace=trace)

        # Verify metrics are returned normally
        assert metrics["hit_rate"] == 1.0
        assert metrics["mrr"] == 0.5

        # Verify trace context recorded metadata
        assert trace.metadata.get("evaluator_type") == "custom"
        assert "metrics" in trace.metadata
