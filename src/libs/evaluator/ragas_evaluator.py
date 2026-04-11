"""Compatibility import for RagasEvaluator.

Ragas evaluator implementation lives in ``src.observability.evaluation``.
This module keeps the historical import path stable.
"""

from src.observability.evaluation.ragas_evaluator import RagasEvaluator

__all__ = ["RagasEvaluator"]
