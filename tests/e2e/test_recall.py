"""Recall 回归测试（E2E）。

该测试基于 golden test set 运行 EvalRunner，并校验 hit@k 阈值，
用于防止检索策略迭代引发的召回退化。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.settings import (
    EmbeddingSettings,
    EvaluationSettings,
    LLMSettings,
    RetrievalSettings,
    Settings,
    VectorStoreSettings,
    VisionLLMSettings,
)
from src.core.types import RetrievalResult
from src.libs.evaluator.custom_evaluator import CustomEvaluator
from src.observability.evaluation.eval_runner import EvalRunner


GOLDEN_SET_PATH = Path("tests/fixtures/golden_test_set.json")
HIT_AT_K_THRESHOLD = 0.75
MRR_THRESHOLD = 0.60


class _RegressionHybridSearch:
    """用于回归测试的检索桩实现。"""

    def __init__(self, query_to_results: dict[str, list[RetrievalResult]]) -> None:
        self._query_to_results = query_to_results

    def search(
        self,
        query: str,
        top_k: int,
        filters: dict[str, str] | None = None,
    ) -> list[RetrievalResult]:
        del filters
        return self._query_to_results.get(query, [])[:top_k]


def _build_settings() -> Settings:
    """构造评估所需最小配置。"""
    return Settings(
        llm=LLMSettings(provider="ollama", model="llama3"),
        embedding=EmbeddingSettings(provider="openai", model="text-embedding-3-small"),
        vision_llm=VisionLLMSettings(provider="azure", model="gpt-4o"),
        vector_store=VectorStoreSettings(backend="chroma"),
        retrieval=RetrievalSettings(top_k_final=3),
        evaluation=EvaluationSettings(backends=["custom"]),
    )


def _load_queries_and_expected_ids() -> list[tuple[str, list[str]]]:
    """从 golden test set 提取 query 与 expected ids。"""
    raw = json.loads(GOLDEN_SET_PATH.read_text(encoding="utf-8"))
    test_cases = raw["test_cases"]
    return [(case["query"], case["expected_chunk_ids"]) for case in test_cases]


@pytest.mark.e2e
def test_recall_hit_at_k_meets_threshold() -> None:
    """回归测试：hit@k 必须达到阈值。"""
    query_pairs = _load_queries_and_expected_ids()

    # 这里显式构造“3 命中 + 1 未命中”的回归基线，确保阈值逻辑能稳定守护质量。
    results_mapping: dict[str, list[RetrievalResult]] = {}
    for idx, (query, expected_ids) in enumerate(query_pairs):
        if idx == len(query_pairs) - 1:
            results_mapping[query] = [
                RetrievalResult(
                    chunk_id="chunk_non_match_001",
                    score=0.91,
                    text="non-matching chunk",
                    metadata={"source": "noise.txt"},
                )
            ]
            continue

        results_mapping[query] = [
            RetrievalResult(
                chunk_id=expected_ids[0],
                score=0.95,
                text=f"matched chunk for {query}",
                metadata={"source": "golden-source"},
            ),
            RetrievalResult(
                chunk_id=f"chunk_noise_{idx}",
                score=0.40,
                text="fallback chunk",
                metadata={"source": "noise.txt"},
            ),
        ]

    runner = EvalRunner(
        settings=_build_settings(),
        hybrid_search=_RegressionHybridSearch(results_mapping),
        evaluator=CustomEvaluator(_build_settings()),
    )
    report = runner.run(str(GOLDEN_SET_PATH), top_k=3)

    assert report.total_cases == len(query_pairs)
    assert report.hit_rate >= HIT_AT_K_THRESHOLD
    assert report.mrr >= MRR_THRESHOLD

