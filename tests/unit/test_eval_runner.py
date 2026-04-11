"""Unit tests for EvalRunner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.settings import (
    EmbeddingSettings,
    EvaluationSettings,
    LLMSettings,
    Settings,
    VectorStoreSettings,
    VisionLLMSettings,
)
from src.core.types import RetrievalResult
from src.libs.evaluator.base_evaluator import BaseEvaluator
from src.observability.evaluation.eval_runner import EvalRunner


class _StubHybridSearch:
    """Stub hybrid search with deterministic query->results mapping."""

    def __init__(self, mapping: dict[str, list[RetrievalResult]]) -> None:
        self._mapping = mapping
        self.calls: list[dict[str, object]] = []

    def search(self, query: str, top_k: int, filters=None) -> list[RetrievalResult]:
        self.calls.append({"query": query, "top_k": top_k, "filters": filters})
        return self._mapping.get(query, [])


class _StubEvaluator(BaseEvaluator):
    """Stub evaluator returning a deterministic custom score."""

    def evaluate(
        self,
        query: str,
        retrieved_ids: list[str],
        golden_ids: list[str],
        trace=None,
        **kwargs,
    ) -> dict[str, float]:
        overlap = len(set(retrieved_ids) & set(golden_ids))
        return {
            "custom_overlap": float(overlap),
            "hit_rate": 1.0 if overlap else 0.0,
            "mrr": 1.0 if overlap else 0.0,
        }


def _build_settings() -> Settings:
    """Build minimal valid Settings for EvalRunner tests."""
    return Settings(
        llm=LLMSettings(provider="ollama", model="llama3"),
        embedding=EmbeddingSettings(provider="openai", model="text-embedding-3-small"),
        vision_llm=VisionLLMSettings(provider="azure", model="gpt-4o"),
        vector_store=VectorStoreSettings(backend="chroma"),
        evaluation=EvaluationSettings(backends=["custom"]),
    )


def test_run_returns_expected_report(tmp_path: Path) -> None:
    """EvalRunner should compute hit_rate, mrr and aggregate metrics."""
    test_set = tmp_path / "golden.json"
    test_set.write_text(
        json.dumps(
            {
                "test_cases": [
                    {
                        "query": "q1",
                        "expected_chunk_ids": ["c1"],
                        "expected_sources": ["doc1.pdf"],
                    },
                    {
                        "query": "q2",
                        "expected_chunk_ids": ["c2"],
                        "expected_sources": ["doc2.pdf"],
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    hybrid = _StubHybridSearch(
        mapping={
            "q1": [
                RetrievalResult(
                    chunk_id="c1",
                    score=0.9,
                    text="text1",
                    metadata={"source": "doc1.pdf"},
                )
            ],
            "q2": [
                RetrievalResult(
                    chunk_id="x1",
                    score=0.8,
                    text="text2",
                    metadata={"source": "other.pdf"},
                ),
                RetrievalResult(
                    chunk_id="c2",
                    score=0.7,
                    text="text3",
                    metadata={"source": "doc2.pdf"},
                ),
            ],
        }
    )
    runner = EvalRunner(_build_settings(), hybrid, _StubEvaluator())

    report = runner.run(str(test_set), top_k=5, filters={"collection": "default"})

    assert report.total_cases == 2
    assert report.hit_rate == 1.0
    assert report.mrr == pytest.approx((1.0 + 0.5) / 2)
    assert report.source_hit_rate == 1.0
    assert report.aggregate_metrics["custom_overlap"] == 1.0
    assert len(report.case_results) == 2
    assert hybrid.calls[0]["top_k"] == 5
    assert hybrid.calls[0]["filters"] == {"collection": "default"}


def test_run_handles_empty_retrieval_results(tmp_path: Path) -> None:
    """EvalRunner should not crash when retrieval returns empty list."""
    test_set = tmp_path / "golden.json"
    test_set.write_text(
        json.dumps(
            {"test_cases": [{"query": "q-empty", "expected_chunk_ids": ["c1"]}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    runner = EvalRunner(_build_settings(), _StubHybridSearch(mapping={}), _StubEvaluator())

    report = runner.run(str(test_set))

    assert report.total_cases == 1
    assert report.hit_rate == 0.0
    assert report.mrr == 0.0
    assert report.case_results[0].metrics["hit_rate"] == 0.0
    assert report.case_results[0].metrics["mrr"] == 0.0


def test_run_raises_error_when_test_set_missing() -> None:
    """Missing test set path should raise ValueError."""
    runner = EvalRunner(_build_settings(), _StubHybridSearch(mapping={}), _StubEvaluator())

    with pytest.raises(ValueError, match="file not found"):
        runner.run("tests/fixtures/not_exists.json")


def test_run_raises_error_for_invalid_test_set_format(tmp_path: Path) -> None:
    """Invalid golden test set format should raise ValueError."""
    test_set = tmp_path / "golden_invalid.json"
    test_set.write_text('{"test_cases": "oops"}', encoding="utf-8")
    runner = EvalRunner(_build_settings(), _StubHybridSearch(mapping={}), _StubEvaluator())

    with pytest.raises(ValueError, match="test_cases"):
        runner.run(str(test_set))
