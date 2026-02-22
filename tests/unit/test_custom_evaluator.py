"""CustomEvaluator 单元测试。"""

import pytest

from src.libs.evaluator.custom_evaluator import CustomEvaluator


class TestCustomEvaluator:
    """CustomEvaluator 测试套件。"""

    def test_hit_rate_at_5_with_hit(self):
        """测试 Hit Rate@5 - 命中情况。"""
        evaluator = CustomEvaluator(k_values=[5])
        
        retrieved = ["chunk1", "chunk2", "chunk3", "chunk4", "chunk5"]
        golden = ["chunk3", "chunk10"]
        
        metrics = evaluator.evaluate("test query", retrieved, golden)
        
        assert "hit_rate@5" in metrics
        assert metrics["hit_rate@5"] == 1.0

    def test_hit_rate_at_5_no_hit(self):
        """测试 Hit Rate@5 - 未命中情况。"""
        evaluator = CustomEvaluator(k_values=[5])
        
        retrieved = ["chunk1", "chunk2", "chunk3", "chunk4", "chunk5"]
        golden = ["chunk10", "chunk20"]
        
        metrics = evaluator.evaluate("test query", retrieved, golden)
        
        assert "hit_rate@5" in metrics
        assert metrics["hit_rate@5"] == 0.0

    def test_hit_rate_at_10_with_hit_beyond_5(self):
        """测试 Hit Rate@10 - 在第 6-10 位命中。"""
        evaluator = CustomEvaluator(k_values=[5, 10])
        
        retrieved = ["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8", "c9", "c10"]
        golden = ["c7"]
        
        metrics = evaluator.evaluate("test query", retrieved, golden)
        
        # 前5个没命中
        assert metrics["hit_rate@5"] == 0.0
        # 前10个命中了
        assert metrics["hit_rate@10"] == 1.0

    def test_mrr_first_position(self):
        """测试 MRR - 第一个位置命中。"""
        evaluator = CustomEvaluator()
        
        retrieved = ["chunk_gold", "chunk2", "chunk3"]
        golden = ["chunk_gold"]
        
        metrics = evaluator.evaluate("test query", retrieved, golden)
        
        assert "mrr" in metrics
        assert metrics["mrr"] == 1.0

    def test_mrr_second_position(self):
        """测试 MRR - 第二个位置命中。"""
        evaluator = CustomEvaluator()
        
        retrieved = ["chunk1", "chunk_gold", "chunk3"]
        golden = ["chunk_gold"]
        
        metrics = evaluator.evaluate("test query", retrieved, golden)
        
        assert metrics["mrr"] == 0.5

    def test_mrr_third_position(self):
        """测试 MRR - 第三个位置命中。"""
        evaluator = CustomEvaluator()
        
        retrieved = ["chunk1", "chunk2", "chunk_gold"]
        golden = ["chunk_gold"]
        
        metrics = evaluator.evaluate("test query", retrieved, golden)
        
        assert abs(metrics["mrr"] - 1.0/3) < 1e-6

    def test_mrr_no_hit(self):
        """测试 MRR - 完全未命中。"""
        evaluator = CustomEvaluator()
        
        retrieved = ["chunk1", "chunk2", "chunk3"]
        golden = ["chunk_gold"]
        
        metrics = evaluator.evaluate("test query", retrieved, golden)
        
        assert metrics["mrr"] == 0.0

    def test_multiple_golden_chunks_first_hit_counts(self):
        """测试多个黄金标准，MRR 取第一个命中的位置。"""
        evaluator = CustomEvaluator()
        
        retrieved = ["chunk1", "chunk2", "gold2", "chunk4", "gold1"]
        golden = ["gold1", "gold2"]
        
        metrics = evaluator.evaluate("test query", retrieved, golden)
        
        # gold2 在第3位最先命中
        assert abs(metrics["mrr"] - 1.0/3) < 1e-6

    def test_empty_golden_chunks(self):
        """测试空的黄金标准列表。"""
        evaluator = CustomEvaluator(k_values=[5])
        
        retrieved = ["chunk1", "chunk2", "chunk3"]
        golden = []
        
        metrics = evaluator.evaluate("test query", retrieved, golden)
        
        assert metrics["hit_rate@5"] == 0.0
        assert metrics["mrr"] == 0.0

    def test_empty_retrieved_chunks(self):
        """测试空的检索结果列表。"""
        evaluator = CustomEvaluator(k_values=[5])
        
        retrieved = []
        golden = ["chunk1"]
        
        metrics = evaluator.evaluate("test query", retrieved, golden)
        
        assert metrics["hit_rate@5"] == 0.0
        assert metrics["mrr"] == 0.0

    def test_custom_k_values(self):
        """测试自定义 K 值列表。"""
        evaluator = CustomEvaluator(k_values=[3, 7, 15])
        
        retrieved = ["c1", "c2", "c3", "c4", "gold", "c6", "c7"]
        golden = ["gold"]
        
        metrics = evaluator.evaluate("test query", retrieved, golden)
        
        # 检查所有自定义的 K 值
        assert "hit_rate@3" in metrics
        assert "hit_rate@7" in metrics
        assert "hit_rate@15" in metrics
        
        # gold 在第5位
        assert metrics["hit_rate@3"] == 0.0  # 前3个没有
        assert metrics["hit_rate@7"] == 1.0  # 前7个有
        assert metrics["hit_rate@15"] == 1.0  # 前15个有（实际只有7个）

    def test_default_k_values(self):
        """测试默认 K 值为 [5, 10]。"""
        evaluator = CustomEvaluator()
        
        retrieved = ["c1", "c2", "c3", "c4", "c5"]
        golden = ["c3"]
        
        metrics = evaluator.evaluate("test query", retrieved, golden)
        
        assert "hit_rate@5" in metrics
        assert "hit_rate@10" in metrics
        assert metrics["hit_rate@5"] == 1.0
        assert metrics["hit_rate@10"] == 1.0

    @pytest.mark.skip(reason="TraceContext not yet implemented (Stage G)")
    def test_trace_context_integration(self):
        """测试追踪上下文集成（可选）。"""
        from src.core.trace.trace_context import TraceContext
        
        evaluator = CustomEvaluator(k_values=[5])
        trace = TraceContext(operation="test_evaluation")
        
        retrieved = ["chunk1", "chunk2", "chunk3"]
        golden = ["chunk2"]
        
        metrics = evaluator.evaluate("test query", retrieved, golden, trace=trace)
        
        # 验证指标正常返回
        assert metrics["hit_rate@5"] == 1.0
        assert metrics["mrr"] == 0.5
        
        # 验证追踪上下文记录了元数据
        assert trace.metadata.get("evaluator_type") == "custom"
        assert trace.metadata.get("k_values") == [5]
        assert "metrics" in trace.metadata
