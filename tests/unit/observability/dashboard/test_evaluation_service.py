"""EvaluationService 单元测试。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
from src.observability.dashboard.services.evaluation_service import EvaluationService
from src.observability.evaluation.eval_runner import EvalCaseResult, EvalReport


@dataclass
class _StubRunner:
    """用于测试 run_evaluation 的 EvalRunner stub。"""

    report: EvalReport

    def run(
        self,
        test_set_path: str,
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> EvalReport:
        self.last_args = {
            "test_set_path": test_set_path,
            "top_k": top_k,
            "filters": filters,
        }
        return self.report


def _build_settings() -> Settings:
    """构建最小可用的 Settings。"""
    return Settings(
        llm=LLMSettings(provider="ollama", model="llama3"),
        embedding=EmbeddingSettings(provider="openai", model="text-embedding-3-small"),
        vision_llm=VisionLLMSettings(provider="azure", model="gpt-4o"),
        vector_store=VectorStoreSettings(backend="chroma"),
        retrieval=RetrievalSettings(top_k_final=9),
        evaluation=EvaluationSettings(backends=["custom", "ragas"]),
    )


def _build_report() -> EvalReport:
    """构建固定评估报告。"""
    return EvalReport(
        total_cases=1,
        hit_rate=1.0,
        mrr=1.0,
        source_hit_rate=1.0,
        aggregate_metrics={"hit_rate": 1.0, "mrr": 1.0},
        case_results=[
            EvalCaseResult(
                query="q1",
                expected_chunk_ids=["c1"],
                expected_sources=["doc.pdf"],
                retrieved_chunk_ids=["c1"],
                retrieved_sources=["doc.pdf"],
                hit=True,
                reciprocal_rank=1.0,
                source_hit=True,
                metrics={"hit_rate": 1.0, "mrr": 1.0},
            )
        ],
    )


def test_resolve_backends_supports_all_modes() -> None:
    """应根据模式返回正确后端列表。"""
    service = EvaluationService()

    assert service.resolve_backends("custom", ["custom", "ragas"]) == ["custom"]
    assert service.resolve_backends("ragas", ["custom", "ragas"]) == ["ragas"]
    assert service.resolve_backends("all", ["custom", "ragas"]) == ["custom", "ragas"]
    assert service.resolve_backends("all", []) == ["custom"]


def test_discover_test_sets_filters_golden_files(tmp_path: Path) -> None:
    """应仅发现 golden 相关 JSON 文件。"""
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir(parents=True)
    (fixtures / "golden_test_set.json").write_text("{}", encoding="utf-8")
    (fixtures / "other.json").write_text("{}", encoding="utf-8")
    default_file = fixtures / "default_golden.json"
    default_file.write_text("{}", encoding="utf-8")

    service = EvaluationService()
    paths = service.discover_test_sets(
        default_path=str(default_file),
        fixtures_dir=fixtures,
    )

    assert str(default_file) in paths
    assert str(fixtures / "golden_test_set.json") in paths
    assert str(fixtures / "other.json") not in paths


def test_append_and_load_history_roundtrip(tmp_path: Path) -> None:
    """应正确写入并读取评估历史。"""
    history_file = tmp_path / "logs" / "evals.jsonl"
    service = EvaluationService(history_file=history_file)

    service.append_history({"timestamp": "2026-04-12T10:00:00", "hit_rate": 0.8})
    service.append_history({"timestamp": "2026-04-12T11:00:00", "hit_rate": 0.9})

    records = service.load_history(limit=10)

    assert len(records) == 2
    assert records[0]["hit_rate"] == 0.9
    assert records[1]["hit_rate"] == 0.8


def test_run_evaluation_passes_collection_filter_and_mode() -> None:
    """run_evaluation 应传递过滤条件并按模式覆写后端。"""
    service = EvaluationService()
    settings = _build_settings()
    report = _build_report()
    stub_runner = _StubRunner(report=report)

    def _stub_hybrid_builder(effective_settings: Settings) -> object:
        assert effective_settings.evaluation.backends == ["custom"]
        return object()

    def _stub_evaluator_builder(effective_settings: Settings) -> object:
        assert effective_settings.evaluation.backends == ["custom"]
        return object()

    def _stub_runner_builder(
        _effective_settings: Settings,
        _hybrid_search: object,
        _evaluator: object,
    ) -> _StubRunner:
        return stub_runner

    result = service.run_evaluation(
        settings=settings,
        mode="custom",
        test_set_path="tests/fixtures/golden_test_set.json",
        top_k=5,
        collection=" default ",
        hybrid_search_builder=_stub_hybrid_builder,
        evaluator_builder=_stub_evaluator_builder,
        runner_builder=_stub_runner_builder,
    )

    assert result is report
    assert stub_runner.last_args == {
        "test_set_path": "tests/fixtures/golden_test_set.json",
        "top_k": 5,
        "filters": {"collection": "default"},
    }
    # 原 settings 不应被污染
    assert settings.evaluation.backends == ["custom", "ragas"]


def test_run_evaluation_rejects_invalid_top_k() -> None:
    """top_k 非正数时应抛出 ValueError。"""
    service = EvaluationService()
    settings = _build_settings()

    with pytest.raises(ValueError, match="top_k"):
        service.run_evaluation(
            settings=settings,
            mode="all",
            test_set_path="tests/fixtures/golden_test_set.json",
            top_k=0,
            collection="",
            hybrid_search_builder=lambda _: object(),
            evaluator_builder=lambda _: object(),  # type: ignore[return-value]
            runner_builder=lambda *_: _StubRunner(report=_build_report()),  # type: ignore[return-value]
        )
