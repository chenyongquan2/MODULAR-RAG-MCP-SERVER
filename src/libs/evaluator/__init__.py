"""Evaluator library module.

This module provides evaluator abstractions and factory for retrieval quality
assessment. Supports multiple evaluation backends: custom metrics, Ragas, DeepEval.
"""

from src.libs.evaluator.base_evaluator import BaseEvaluator
from src.libs.evaluator.custom_evaluator import CustomEvaluator
from src.libs.evaluator.evaluator_factory import EvaluatorFactory

__all__ = [
    "BaseEvaluator",
    "CustomEvaluator",
    "EvaluatorFactory",
]
