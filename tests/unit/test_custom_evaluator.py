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

    def test_empty_query_raises_error(self, mock_settings):
        """Test that empty query raises ValueError."""
        evaluator = CustomEvaluator(settings=mock_settings)

        with pytest.raises(ValueError) as exc_info:
            evaluator.evaluate("", ["chunk_1"], ["chunk_1"])

        assert "query must be a non-empty string" in str(exc_info.value)

    def test_non_string_query_raises_error(self, mock_settings):
        """Test that non-string query raises ValueError."""
        evaluator = CustomEvaluator(settings=mock_settings)

        with pytest.raises(ValueError) as exc_info:
            evaluator.evaluate(123, ["chunk_1"], ["chunk_1"])  # type: ignore[arg-type]

        assert "query must be a non-empty string" in str(exc_info.value)

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

    def test_trace_context_integration(self, mock_settings):
        """Test trace context metadata writing with current TraceContext."""
        from src.core.trace.trace_context import TraceContext

        evaluator = CustomEvaluator(settings=mock_settings)
        trace = TraceContext(trace_type="query")

        retrieved = ["chunk_1", "chunk_2", "chunk_3"]
        golden = ["chunk_2"]

        metrics = evaluator.evaluate("test query", retrieved, golden, trace=trace)

        # Verify metrics are returned normally
        assert metrics["hit_rate"] == 1.0
        assert metrics["mrr"] == 0.5

        # Verify trace context recorded metadata
        assert trace.metadata.get("evaluator_type") == "custom"
        assert trace.metadata.get("query") == "test query"
        assert "metrics" in trace.metadata


class TestCustomEvaluatorRecallNDCG:
    """新增 Recall@K 和 NDCG@K 指标的测试用例。"""

    def test_recall_perfect_overlap(self, mock_settings):
        """所有 golden IDs 都被召回时，recall == 1.0。"""
        evaluator = CustomEvaluator(settings=mock_settings)
        metrics = evaluator.evaluate("q", ["a", "b", "c"], ["a", "b"])
        assert metrics["recall"] == pytest.approx(1.0)

    def test_recall_partial_overlap(self, mock_settings):
        """一半 golden IDs 被召回时，recall == 0.5。"""
        evaluator = CustomEvaluator(settings=mock_settings)
        metrics = evaluator.evaluate("q", ["a", "x"], ["a", "b"])
        assert metrics["recall"] == pytest.approx(0.5)

    def test_recall_zero_when_no_overlap(self, mock_settings):
        """没有 golden IDs 被召回时，recall == 0.0。"""
        evaluator = CustomEvaluator(settings=mock_settings)
        metrics = evaluator.evaluate("q", ["x", "y"], ["a", "b"])
        assert metrics["recall"] == pytest.approx(0.0)

    def test_ndcg_perfect_rank(self, mock_settings):
        """唯一 golden doc 在第 1 位时，ndcg == 1.0。"""
        evaluator = CustomEvaluator(settings=mock_settings)
        metrics = evaluator.evaluate("q", ["gold", "x"], ["gold"])
        assert metrics["ndcg"] == pytest.approx(1.0)

    def test_ndcg_lower_rank_reduces_score(self, mock_settings):
        """golden doc 排名越靠后，ndcg 越低。"""
        evaluator = CustomEvaluator(settings=mock_settings)
        metrics_rank1 = evaluator.evaluate("q", ["gold", "x"], ["gold"])
        metrics_rank2 = evaluator.evaluate("q", ["x", "gold"], ["gold"])
        assert metrics_rank2["ndcg"] < metrics_rank1["ndcg"]

    def test_ndcg_zero_when_no_hit(self, mock_settings):
        """没有召回任何 golden doc 时，ndcg == 0.0。"""
        evaluator = CustomEvaluator(settings=mock_settings)
        metrics = evaluator.evaluate("q", ["x", "y"], ["gold"])
        assert metrics["ndcg"] == pytest.approx(0.0)

    def test_ndcg_multiple_relevant_docs(self, mock_settings):
        """多个相关文档时，ndcg 与手动计算结果一致。"""
        import math
        evaluator = CustomEvaluator(settings=mock_settings)
        # golden "a" 在第 1 位，"b" 在第 3 位；ideal 是第 1、2 位
        metrics = evaluator.evaluate("q", ["a", "x", "b"], ["a", "b"])
        dcg = 1.0 / math.log2(2) + 1.0 / math.log2(4)
        ideal_dcg = 1.0 / math.log2(2) + 1.0 / math.log2(3)
        assert metrics["ndcg"] == pytest.approx(dcg / ideal_dcg)

    def test_evaluate_returns_all_four_metric_keys(self, mock_settings):
        """evaluate() 必须同时返回 hit_rate、mrr、recall、ndcg 四个 key。"""
        evaluator = CustomEvaluator(settings=mock_settings)
        metrics = evaluator.evaluate("q", ["a"], ["a"])
        assert set(metrics.keys()) == {"hit_rate", "mrr", "recall", "ndcg"}

    def test_zero_metrics_returns_all_four_keys(self, mock_settings):
        """zero_metrics() 必须返回与 evaluate() 相同的四个 key，值均为 0.0。"""
        evaluator = CustomEvaluator(settings=mock_settings)
        zero = evaluator.zero_metrics()
        assert set(zero.keys()) == {"hit_rate", "mrr", "recall", "ndcg"}
        assert all(v == 0.0 for v in zero.values())

    def test_trace_records_recall_and_ndcg(self, mock_settings):
        """TraceContext.metadata['metrics'] 必须包含 recall 和 ndcg。"""
        from src.core.trace.trace_context import TraceContext
        evaluator = CustomEvaluator(settings=mock_settings)
        trace = TraceContext(trace_type="query")
        evaluator.evaluate("q", ["a", "b"], ["a"], trace=trace)
        assert "recall" in trace.metadata["metrics"]
        assert "ndcg" in trace.metadata["metrics"]
