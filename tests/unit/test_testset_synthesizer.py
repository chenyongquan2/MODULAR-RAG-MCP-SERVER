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


class TestSourceFilter:
    """``source_filter`` substring 过滤(用于混合语种 collection 按文件名分流)。"""

    def test_source_filter_keeps_only_matching_chunks(self) -> None:
        """source_filter='Chinese.chm' 只保留含该子串的 chunks。"""
        synth = TestsetSynthesizer(settings=_make_settings())
        # 模拟混合 source 的 raw chromadb output
        all_chunks = [
            {"id": "zh-1", "text": "中文内容 1", "metadata": {"source": "MetaTrader5SDK_Chinese.chm"}},
            {"id": "en-1", "text": "English content 1", "metadata": {"source": "MetaTrader5SDK_English.chm"}},
            {"id": "zh-2", "text": "中文内容 2", "metadata": {"source": "MetaTrader5SDK_Chinese.chm"}},
            {"id": "noise-1", "text": "其他", "metadata": {"source": "company_policy.md"}},
        ]
        # 直接通过 mock chromadb 的 col.get() 来测试 _fetch_chunks 的过滤逻辑
        from unittest.mock import patch
        mock_col = MagicMock()
        mock_col.count.return_value = len(all_chunks)
        mock_col.get.return_value = {
            "ids": [c["id"] for c in all_chunks],
            "documents": [c["text"] for c in all_chunks],
            "metadatas": [c["metadata"] for c in all_chunks],
        }
        mock_client = MagicMock()
        mock_client.get_collection.return_value = mock_col
        with patch("chromadb.PersistentClient", return_value=mock_client):
            result = synth._fetch_chunks(
                collection="default", limit=100, source_filter="Chinese.chm"
            )
        # 只剩 2 条中文
        assert len(result) == 2
        assert all("Chinese.chm" in c["metadata"]["source"] for c in result)
        assert {c["id"] for c in result} == {"zh-1", "zh-2"}

    def test_source_filter_empty_returns_all(self) -> None:
        """source_filter=None 时不过滤,所有非空 chunks 返回。"""
        synth = TestsetSynthesizer(settings=_make_settings())
        all_chunks = [
            {"id": "a", "text": "x", "metadata": {"source": "a.md"}},
            {"id": "b", "text": "y", "metadata": {"source": "b.md"}},
        ]
        from unittest.mock import patch
        mock_col = MagicMock()
        mock_col.count.return_value = 2
        mock_col.get.return_value = {
            "ids": ["a", "b"],
            "documents": ["x", "y"],
            "metadatas": [{"source": "a.md"}, {"source": "b.md"}],
        }
        mock_client = MagicMock()
        mock_client.get_collection.return_value = mock_col
        with patch("chromadb.PersistentClient", return_value=mock_client):
            result = synth._fetch_chunks(collection="default", limit=10)
        assert len(result) == 2

    def test_source_filter_no_matches_yields_value_error(self) -> None:
        """source_filter 过滤后 0 chunks → synthesize 抛 ValueError。"""
        synth = TestsetSynthesizer(settings=_make_settings())
        synth._fetch_chunks = MagicMock(return_value=[])  # type: ignore[method-assign]
        with pytest.raises(ValueError, match="source_filter"):
            synth.synthesize(
                collection="default", lang="zh",
                target_count=10, source_filter="nonexistent",
            )


class TestRagasVersionTracking:
    def test_ragas_version_recorded_in_metadata(self) -> None:
        """verify _synthesis_metadata.ragas_version 反映装版本。"""
        synth = TestsetSynthesizer(settings=_make_settings())
        v = synth._ragas_version()
        # 装版本 0.1.21 → 应不是 'unavailable' 也不是 'unknown'
        assert v not in ("unavailable",)


# ---------------------------------------------------------------------------
# adapt(language) + retry + cache (Feature-001 closeout, 2026-04-28)
# ---------------------------------------------------------------------------


class TestRagasAdapt:
    """RAGAS adapt(language=chinese) 翻译内部 prompt + 2 次 retry + cache_dir。

    背景:RAGAS 0.1.x 默认 evolution prompt 是英文,中文 corpus 必须先 adapt
    才能让 Judge 据此产中文 question。adapt 内部调 LLM 翻译,要求返 valid JSON;
    部分 model(如 minimax)输出非 JSON 解释文本 → 失败。需要重试 + cache 容错。
    """

    def _setup_synth_with_mocked_pipeline(
        self,
        adapt_side_effects: list,
    ) -> TestsetSynthesizer:
        """配好 synth + 跳过 chromadb / generator,只留 adapt 这一段真跑。

        Args:
            adapt_side_effects: 给 _generator.adapt 的 side_effect 列表。
                None 元素 = 成功(无返回);Exception 子类 = 抛错。
        """
        synth = TestsetSynthesizer(settings=_make_settings())

        # 跳过 chromadb 拉 chunks
        synth._fetch_chunks = MagicMock(  # type: ignore[method-assign]
            return_value=[
                {"id": "c1", "text": "中文内容", "metadata": {"source": "doc.md"}},
            ]
        )

        # mock generator + adapt + generate
        synth._ensure_generator = MagicMock()  # type: ignore[method-assign]
        gen = MagicMock()
        gen.adapt = MagicMock(side_effect=adapt_side_effects)

        # generate 返回 1 条空 case 让 synthesize 走完
        fake_testset = MagicMock()
        fake_testset.test_data = [
            MagicMock(
                question="问题?",
                ground_truth="答案",
                contexts=["上下文"],
                evolution_type="simple",
            ),
        ]
        del fake_testset.to_pandas
        gen.generate_with_langchain_docs.return_value = fake_testset
        synth._generator = gen
        return synth

    def test_adapt_called_for_zh_lang(self, tmp_path) -> None:
        """lang='zh' → adapt(language='chinese', cache_dir=...) 必须被调用。"""
        synth = self._setup_synth_with_mocked_pipeline(adapt_side_effects=[None])
        with patch(
            "src.observability.evaluation._ragas_wrappers.get_judge_identifier",
            return_value="glm:test",
        ), patch(
            "src.observability.evaluation._ragas_wrappers.get_embedding_identifier",
            return_value="openai:test",
        ):
            synth.synthesize(collection="x", lang="zh", target_count=1)

        assert synth._generator.adapt.call_count == 1
        kwargs = synth._generator.adapt.call_args.kwargs
        assert kwargs["language"] == "chinese"
        # cache_dir 必须传(防止后续无 cache 反复调 LLM)
        assert "cache_dir" in kwargs and kwargs["cache_dir"]

    def test_adapt_skipped_for_en_lang(self) -> None:
        """lang='en' → 不调 adapt(英文是 RAGAS 默认 prompt 语言)。"""
        synth = self._setup_synth_with_mocked_pipeline(adapt_side_effects=[None])
        with patch(
            "src.observability.evaluation._ragas_wrappers.get_judge_identifier",
            return_value="glm:test",
        ), patch(
            "src.observability.evaluation._ragas_wrappers.get_embedding_identifier",
            return_value="openai:test",
        ):
            synth.synthesize(collection="x", lang="en", target_count=1)

        assert synth._generator.adapt.call_count == 0

    def test_adapt_retries_once_on_first_failure(self) -> None:
        """第 1 次 adapt 失败 → retry → 第 2 次成功 → 整体不抛错。"""
        synth = self._setup_synth_with_mocked_pipeline(
            adapt_side_effects=[ValueError("invalid JSON"), None],
        )
        with patch(
            "src.observability.evaluation._ragas_wrappers.get_judge_identifier",
            return_value="glm:test",
        ), patch(
            "src.observability.evaluation._ragas_wrappers.get_embedding_identifier",
            return_value="openai:test",
        ):
            # 不应抛错
            synth.synthesize(collection="x", lang="zh", target_count=1)

        assert synth._generator.adapt.call_count == 2

    def test_adapt_two_failures_raise_runtime_error(self) -> None:
        """2 次 adapt 都失败 → 抛 RuntimeError(不静默 fallback 到英文)。

        关键:之前曾有静默 fallback 设计,导致跑 1-2h 后才发现产出全英文。
        现在必须显式 fail-fast,把控制权给 user。
        """
        synth = self._setup_synth_with_mocked_pipeline(
            adapt_side_effects=[
                ValueError("attempt 1 fail"),
                ValueError("attempt 2 fail"),
            ],
        )
        with patch(
            "src.observability.evaluation._ragas_wrappers.get_judge_identifier",
            return_value="glm:test",
        ), patch(
            "src.observability.evaluation._ragas_wrappers.get_embedding_identifier",
            return_value="openai:test",
        ):
            with pytest.raises(RuntimeError, match="adapt.*failed after 2 attempts"):
                synth.synthesize(collection="x", lang="zh", target_count=1)

        # 验证抛错前确实尝试了 2 次
        assert synth._generator.adapt.call_count == 2

    def test_adapt_unknown_lang_skipped(self) -> None:
        """非 zh/en 的 lang(假设未来扩展)默认跳过 adapt 直到映射添加。"""
        synth = self._setup_synth_with_mocked_pipeline(adapt_side_effects=[None])
        with patch(
            "src.observability.evaluation._ragas_wrappers.get_judge_identifier",
            return_value="glm:test",
        ), patch(
            "src.observability.evaluation._ragas_wrappers.get_embedding_identifier",
            return_value="openai:test",
        ):
            # lang='ja' 当前没在 lang_to_ragas 映射,不 adapt 也不抛
            synth.synthesize(collection="x", lang="ja", target_count=1)

        assert synth._generator.adapt.call_count == 0
