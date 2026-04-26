"""Unit tests for RagasEvaluator Judge/embedding factory injection (T013).

测试范围 (refs spec FR-016 / FR-017):
- ``_ensure_wrappers()`` 通过 ``_ragas_wrappers.build_ragas_judge`` /
  ``build_ragas_embedding`` 取 Judge / embedding(不直接 import 任何
  具体 provider 模块)
- ``get_judge_identifier()`` 返回 ``"<provider>:<model>"`` 格式
- ``get_embedding_identifier()`` 默认 fallback 到顶层 production embedding
  (FR-017 train-eval skew 避免)
- 单元测试可通过 ``llm`` / ``embeddings`` kwargs 旁路 factory(测试隔离通道)

不测试 RAGAS 真实评估流程(那需要真实 LLM API);本测试只覆盖**注入路径**。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.core.settings import (
    EmbeddingSettings,
    EvaluationEmbeddingSettings,
    EvaluationSettings,
    JudgeLLMSettings,
    LLMSettings,
    Settings,
    VectorStoreSettings,
    VisionLLMSettings,
)
from src.observability.evaluation.ragas_evaluator import RagasEvaluator
from src.observability.evaluation._ragas_wrappers import (
    get_embedding_identifier,
    get_judge_identifier,
)


pytestmark = pytest.mark.unit


def _build_settings_with_judge() -> Settings:
    """构造一个含 ragas backend 与 GLM judge 的最小 Settings。"""
    return Settings(
        llm=LLMSettings(provider="glm", model="glm-4-production"),
        embedding=EmbeddingSettings(provider="openai", model="text-embedding-3-small"),
        vision_llm=VisionLLMSettings(provider="azure", model="gpt-4o"),
        vector_store=VectorStoreSettings(backend="chroma"),
        evaluation=EvaluationSettings(
            backends=["custom", "ragas"],
            judge_llm=JudgeLLMSettings(provider="glm", model="glm-4"),
            embedding=EvaluationEmbeddingSettings(),  # 默认空 = 复用顶层
            chunk_id_validation=False,
        ),
    )


# ---------------------------------------------------------------------------
# Identifier 助手 (provider-agnostic 验证)
# ---------------------------------------------------------------------------


class TestIdentifierHelpers:
    """``get_judge_identifier`` / ``get_embedding_identifier`` (FR-016/017 报告字段)。"""

    def test_judge_identifier_uses_evaluation_judge_llm_section(self) -> None:
        settings = _build_settings_with_judge()
        assert get_judge_identifier(settings) == "glm:glm-4"

    def test_embedding_identifier_falls_back_to_top_level_when_empty(self) -> None:
        """FR-017 默认行为:evaluation.embedding 全空时复用顶层 settings.embedding。"""
        settings = _build_settings_with_judge()
        # eval embedding 全空 → 复用 production
        assert (
            get_embedding_identifier(settings)
            == "openai:text-embedding-3-small"
        )

    def test_embedding_identifier_uses_eval_override_when_provided(self) -> None:
        """用户在 evaluation.embedding 覆盖时,使用 evaluation 段的值。"""
        settings = _build_settings_with_judge()
        settings.evaluation.embedding = EvaluationEmbeddingSettings(
            provider="bge", model="bge-m3"
        )
        assert get_embedding_identifier(settings) == "bge:bge-m3"

    def test_judge_identifier_after_provider_switch(self) -> None:
        """切换 provider 后,identifier 跟着改(FR-016 跨 Judge 可追溯)。"""
        settings = _build_settings_with_judge()
        settings.evaluation.judge_llm = JudgeLLMSettings(
            provider="azure", model="gpt-4o"
        )
        assert get_judge_identifier(settings) == "azure:gpt-4o"


# ---------------------------------------------------------------------------
# RagasEvaluator factory injection 集成
# ---------------------------------------------------------------------------


class TestRagasEvaluatorFactoryInjection:
    """RagasEvaluator 是否真的通过 _ragas_wrappers 取 Judge/embedding。"""

    def test_get_judge_identifier_delegates_to_settings(self) -> None:
        """RagasEvaluator.get_judge_identifier 应反映 settings 配置。"""
        settings = _build_settings_with_judge()
        evaluator = RagasEvaluator(settings=settings)
        assert evaluator.get_judge_identifier() == "glm:glm-4"

    def test_get_embedding_identifier_default_inherits_top_level(self) -> None:
        settings = _build_settings_with_judge()
        evaluator = RagasEvaluator(settings=settings)
        # eval embedding 默认空 → 复用顶层 openai
        assert evaluator.get_embedding_identifier() == "openai:text-embedding-3-small"

    def test_init_does_not_eagerly_build_wrappers(self) -> None:
        """RagasEvaluator() 实例化时不应触发 LLM 客户端创建(延迟到 evaluate)。"""
        with patch(
            "src.observability.evaluation._ragas_wrappers.build_ragas_judge"
        ) as mock_build_judge, patch(
            "src.observability.evaluation._ragas_wrappers.build_ragas_embedding"
        ) as mock_build_embedding:
            settings = _build_settings_with_judge()
            evaluator = RagasEvaluator(settings=settings)
            # 仅实例化不应触发 build
            assert mock_build_judge.call_count == 0
            assert mock_build_embedding.call_count == 0
            assert evaluator._wrappers_built is False

    def test_ensure_wrappers_calls_factory_helpers_once(self) -> None:
        """首次 _ensure_wrappers 触发 build;重复调用不再 build。"""
        with patch(
            "src.observability.evaluation._ragas_wrappers.build_ragas_judge",
            return_value=MagicMock(name="judge_wrapper"),
        ) as mock_build_judge, patch(
            "src.observability.evaluation._ragas_wrappers.build_ragas_embedding",
            return_value=MagicMock(name="embedding_wrapper"),
        ) as mock_build_embedding:
            settings = _build_settings_with_judge()
            evaluator = RagasEvaluator(settings=settings)

            # 第一次触发
            evaluator._ensure_wrappers()
            assert mock_build_judge.call_count == 1
            assert mock_build_embedding.call_count == 1
            assert evaluator._wrappers_built is True

            # 第二次不再 build
            evaluator._ensure_wrappers()
            assert mock_build_judge.call_count == 1
            assert mock_build_embedding.call_count == 1


class TestKwargsOverrideChannel:
    """单元测试可通过 kwargs.llm / .embeddings 旁路 factory(测试隔离通道)。

    实际评估流程不应使用 kwargs 注入,应让 RagasEvaluator 自己经 factory 构建。
    本测试验证 mock_metrics 路径不会触发 factory(避免无意 LLM 调用)。
    """

    def test_mock_metrics_short_circuits_factory(self) -> None:
        """mock_metrics 模式应在 factory 注入前直接返回(测试用)。"""
        with patch(
            "src.observability.evaluation._ragas_wrappers.build_ragas_judge"
        ) as mock_build_judge, patch(
            "src.observability.evaluation._ragas_wrappers.build_ragas_embedding"
        ) as mock_build_embedding:
            settings = _build_settings_with_judge()
            evaluator = RagasEvaluator(settings=settings)

            metrics = evaluator.evaluate(
                query="test",
                retrieved_ids=["c1"],
                golden_ids=["c1"],
                mock_metrics={"faithfulness": 0.9, "answer_relevancy": 0.8,
                              "context_precision": 0.85, "context_recall": 0.75},
            )

            # mock_metrics 路径不应触发 factory (零 LLM 客户端创建)
            assert mock_build_judge.call_count == 0
            assert mock_build_embedding.call_count == 0
            assert metrics["faithfulness"] == 0.9
