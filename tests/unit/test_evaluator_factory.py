"""EvaluatorFactory 单元测试。"""

import pytest

from src.libs.evaluator import create_evaluator, BaseEvaluator, CustomEvaluator


class TestEvaluatorFactory:
    """EvaluatorFactory 测试套件。"""

    def test_create_custom_evaluator(self):
        """测试创建 custom 评估器。"""
        evaluator = create_evaluator("custom")
        
        assert isinstance(evaluator, BaseEvaluator)
        assert isinstance(evaluator, CustomEvaluator)

    def test_create_custom_evaluator_with_k_values(self):
        """测试创建 custom 评估器并指定 K 值。"""
        evaluator = create_evaluator("custom", k_values=[3, 7, 15])
        
        assert isinstance(evaluator, CustomEvaluator)
        assert evaluator.k_values == [3, 7, 15]

    def test_create_custom_evaluator_default_k_values(self):
        """测试创建 custom 评估器使用默认 K 值。"""
        evaluator = create_evaluator("custom")
        
        assert isinstance(evaluator, CustomEvaluator)
        assert evaluator.k_values == [5, 10]

    def test_unsupported_backend_raises_error(self):
        """测试不支持的后端类型抛出异常。"""
        with pytest.raises(ValueError) as exc_info:
            create_evaluator("unsupported_backend")
        
        assert "Unsupported evaluator backend" in str(exc_info.value)
        assert "unsupported_backend" in str(exc_info.value)

    def test_default_backend_is_custom(self):
        """测试默认后端为 custom。"""
        evaluator = create_evaluator()
        
        assert isinstance(evaluator, CustomEvaluator)

    def test_factory_creates_working_evaluator(self):
        """测试工厂创建的评估器能正常工作。"""
        evaluator = create_evaluator("custom", k_values=[5])
        
        retrieved = ["chunk1", "chunk2", "chunk3"]
        golden = ["chunk2"]
        
        metrics = evaluator.evaluate("test query", retrieved, golden)
        
        assert "hit_rate@5" in metrics
        assert "mrr" in metrics
        assert metrics["hit_rate@5"] == 1.0
        assert metrics["mrr"] == 0.5
