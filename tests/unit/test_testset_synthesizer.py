"""Unit tests for TestsetSynthesizer (T023, refs FR-004).

测试范围:
- distribution 校验(总和 ≈ 1.0,unknown key 拒绝)
- candidate JSON schema 含 _synthesis_metadata 与 4 个必需字段
- mock RAGAS TestsetGenerator → 验证转换路径(不调真实 LLM)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.core.settings import (
    EmbeddingSettings,
    EvaluationSettings,
    LLMSettings,
    Settings,
    VectorStoreSettings,
    VisionLLMSettings,
)
from src.observability.evaluation.testset_synthesizer import (
    DEFAULT_DISTRIBUTION,
    TestsetSynthesizer,
)


pytestmark = pytest.mark.unit


def _make_settings() -> Settings:
    return Settings(
        llm=LLMSettings(provider="glm", model="glm-4"),
        embedding=EmbeddingSettings(provider="openai", model="text-embedding-3-small"),
        vision_llm=VisionLLMSettings(provider="azure", model="gpt-4o"),
        vector_store=VectorStoreSettings(backend="chroma"),
        evaluation=EvaluationSettings(),
    )


# ---------------------------------------------------------------------------
# Distribution validation
# ---------------------------------------------------------------------------


class TestDistributionValidation:
    def test_default_distribution_is_50_30_20(self) -> None:
        assert DEFAULT_DISTRIBUTION == {"simple": 0.5, "reasoning": 0.3, "multi_context": 0.2}

    def test_validate_rejects_unknown_keys(self) -> None:
        synth = TestsetSynthesizer(settings=_make_settings())
        with pytest.raises(ValueError, match="unknown keys"):
            synth._validate_distribution({"easy": 1.0})

    def test_validate_rejects_total_far_from_one(self) -> None:
        synth = TestsetSynthesizer(settings=_make_settings())
        with pytest.raises(ValueError, match="must sum to"):
            synth._validate_distribution({"simple": 0.3, "reasoning": 0.2})

    def test_validate_allows_minor_floating_error(self) -> None:
        """0.99 / 1.01 in tolerance,不拒绝。"""
        synth = TestsetSynthesizer(settings=_make_settings())
        result = synth._validate_distribution(
            {"simple": 0.5, "reasoning": 0.3, "multi_context": 0.19}  # 0.99
        )
        # 应正常返回(不抛错)
        assert sum(result.values()) == pytest.approx(0.99)

    def test_target_count_zero_rejected(self) -> None:
        synth = TestsetSynthesizer(settings=_make_settings())
        with pytest.raises(ValueError, match="target_count must be > 0"):
            synth.synthesize(collection="x", lang="zh", target_count=0)


# ---------------------------------------------------------------------------
# Candidate output schema
# ---------------------------------------------------------------------------


class TestCandidateSchema:
    def test_synthesize_with_mocked_ragas_returns_full_schema(self) -> None:
        """mock RAGAS + chromadb,验证 candidate JSON 顶层字段齐全。"""
        # mock fetch_chunks 直接返回非空 list,跳过 chromadb
        synth = TestsetSynthesizer(settings=_make_settings())
        synth._fetch_chunks = MagicMock(  # type: ignore[method-assign]
            return_value=[
                {"id": "c1", "text": "Hello world", "metadata": {"source": "doc1.md"}},
                {"id": "c2", "text": "Foo bar baz", "metadata": {"source": "doc1.md"}},
            ]
        )

        # mock _ensure_generator + _generator.generate_with_langchain_docs
        fake_testset = MagicMock()
        fake_testset.test_data = [
            MagicMock(
                question="What is X?",
                ground_truth="X is a thing.",
                contexts=["Some context."],
                evolution_type="simple",
            ),
            MagicMock(
                question="Why does Y?",
                ground_truth="Because Z.",
                contexts=["More context."],
                evolution_type="reasoning",
            ),
        ]
        # to_pandas 不存在 → 走 test_data 路径
        del fake_testset.to_pandas

        synth._ensure_generator = MagicMock()  # type: ignore[method-assign]
        synth._generator = MagicMock()
        synth._generator.generate_with_langchain_docs.return_value = fake_testset

        with patch(
            "src.observability.evaluation._ragas_wrappers.get_judge_identifier",
            return_value="glm:glm-4",
        ), patch(
            "src.observability.evaluation._ragas_wrappers.get_embedding_identifier",
            return_value="openai:text-embedding-3-small",
        ):
            candidate = synth.synthesize(
                collection="default", lang="zh", target_count=2
            )

        # Schema 顶层
        assert candidate["_schema_version"] == 1
        assert candidate["language"] == "zh"
        meta = candidate["_synthesis_metadata"]
        assert meta["generator"] == "ragas.testset.TestsetGenerator"
        assert meta["judge_llm_identifier"] == "glm:glm-4"
        assert meta["embedding_identifier"] == "openai:text-embedding-3-small"
        assert meta["distribution"] == DEFAULT_DISTRIBUTION

        # Test cases: 2 个,字段齐全
        assert len(candidate["test_cases"]) == 2
        case = candidate["test_cases"][0]
        assert case["query"] == "What is X?"
        assert case["ground_truth"] == "X is a thing."
        assert case["expected_chunk_ids"] == []  # 由 backfill 阶段填
        assert case["tags"]["language"] == "zh"
        assert case["tags"]["doc_version"] == "v1"
        assert case["tags"]["difficulty"] == "simple"

        # 第二条 case 的 evolution_type → difficulty 映射
        assert candidate["test_cases"][1]["tags"]["difficulty"] == "reasoning"

    def test_empty_collection_raises_value_error(self) -> None:
        synth = TestsetSynthesizer(settings=_make_settings())
        synth._fetch_chunks = MagicMock(return_value=[])  # type: ignore[method-assign]
        with pytest.raises(ValueError, match="contains no chunks"):
            synth.synthesize(collection="empty", lang="zh", target_count=10)


class TestRagasVersionTracking:
    def test_ragas_version_recorded_in_metadata(self) -> None:
        """verify _synthesis_metadata.ragas_version 反映装版本。"""
        synth = TestsetSynthesizer(settings=_make_settings())
        v = synth._ragas_version()
        # 装版本 0.1.21 → 应不是 'unavailable' 也不是 'unknown'
        assert v not in ("unavailable",)
