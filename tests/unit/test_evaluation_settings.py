"""Unit tests for Feature-001 evaluation settings (T007).

测试范围:
1. ``EvaluationSettings`` / ``JudgeLLMSettings`` / ``EvaluationEmbeddingSettings`` /
   ``AcceptanceThresholds`` 默认值正确性
2. ``_validate_evaluation_settings`` 16 条校验规则的 negative cases
3. settings.yaml 端到端加载(顶层 _schema_version → schema_version 字段映射)

覆盖 spec § FR-013 / FR-016 / FR-017 + research § Decision 7 +
contracts/settings.evaluation.schema.md § Field Validation Rules。

不依赖 ragas / langchain (本测试聚焦 dataclass + 校验逻辑,不触发任何 LLM 调用)。
"""

from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from src.core.settings import (
    AcceptanceThresholds,
    EvaluationEmbeddingSettings,
    EvaluationSettings,
    JudgeLLMSettings,
    Settings,
    SettingsError,
    _validate_evaluation_settings,
    load_settings,
)


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 默认值与 dataclass 行为
# ---------------------------------------------------------------------------


class TestDefaults:
    """默认值正确性 (FR-013 业界参考阈值 + 其他默认行为)。"""

    def test_acceptance_thresholds_industry_reference_defaults(self) -> None:
        """FR-013 默认 8 项阈值即业界参考值(2026-04-25 clarify 决议)。"""
        thresholds = AcceptanceThresholds()
        assert thresholds.ragas__context_recall == 0.70
        assert thresholds.ragas__context_precision == 0.65
        assert thresholds.ragas__faithfulness == 0.85
        assert thresholds.ragas__answer_relevancy == 0.75
        assert thresholds.custom__hit_rate == 0.60
        assert thresholds.custom__mrr == 0.55
        assert thresholds.custom__recall == 0.70
        assert thresholds.custom__ndcg == 0.55

    def test_acceptance_thresholds_to_dict_8_keys(self) -> None:
        """to_dict() 必须返回完整 8 个 metric key,顺序无关。"""
        snap = AcceptanceThresholds().to_dict()
        expected_keys = {
            "ragas__context_recall",
            "ragas__context_precision",
            "ragas__faithfulness",
            "ragas__answer_relevancy",
            "custom__hit_rate",
            "custom__mrr",
            "custom__recall",
            "custom__ndcg",
        }
        assert set(snap.keys()) == expected_keys

    def test_judge_llm_default_glm_4(self) -> None:
        """默认 Judge = GLM-4(spec § Assumptions § Judge LLM 选型)。"""
        judge = JudgeLLMSettings()
        assert judge.provider == "glm"
        assert judge.model == "glm-4"
        assert judge.temperature == 0.0  # 推荐 0.0 提高判分稳定性
        assert judge.request_timeout_sec == 60

    def test_evaluation_embedding_defaults_empty_means_inherit(self) -> None:
        """默认 evaluation.embedding 全空,语义为"复用顶层 embedding"。"""
        emb = EvaluationEmbeddingSettings()
        assert emb.provider == ""
        assert emb.model == ""

    def test_evaluation_settings_defaults(self) -> None:
        """EvaluationSettings 默认 chunk_id_validation=True、only custom backend、tag_slice_min_samples=5。"""
        es = EvaluationSettings()
        assert es.schema_version == 1
        assert es.backends == ["custom"]
        assert es.chunk_id_validation is True
        assert es.tag_slice_min_samples == 5
        assert es.by_tag_dimensions == ["content_type", "difficulty"]


# ---------------------------------------------------------------------------
# 帮助函数:构造一个最小有效 Settings(沿用 settings.yaml 默认值)
# ---------------------------------------------------------------------------


def _make_valid_settings(tmp_path: Path) -> Settings:
    """构造一个最小有效 Settings,临时目录用于可写性校验。"""
    from src.core.settings import (
        EmbeddingSettings,
        LLMSettings,
        VectorStoreSettings,
        VisionLLMSettings,
    )

    return Settings(
        llm=LLMSettings(provider="glm", model="glm-4"),
        embedding=EmbeddingSettings(provider="openai", model="text-embedding-3-small"),
        vision_llm=VisionLLMSettings(provider="azure", model="gpt-4o"),
        vector_store=VectorStoreSettings(backend="chroma"),
        evaluation=EvaluationSettings(
            report_archive_dir=str(tmp_path / "reports"),
            baseline_store_path=str(tmp_path / "baselines.json"),
        ),
    )


# ---------------------------------------------------------------------------
# 16 条 _validate_evaluation_settings 校验规则
# ---------------------------------------------------------------------------


class TestValidationNegativeCases:
    """每条非法配置必须触发 SettingsError(快速失败,宪法 § III)。"""

    def test_schema_version_below_1_rejected(self, tmp_path: Path) -> None:
        s = _make_valid_settings(tmp_path)
        s.evaluation.schema_version = 0
        with pytest.raises(SettingsError, match="_schema_version=0"):
            _validate_evaluation_settings(s)

    def test_unknown_backend_rejected(self, tmp_path: Path) -> None:
        s = _make_valid_settings(tmp_path)
        s.evaluation.backends = ["custom", "deepeval"]
        with pytest.raises(SettingsError, match="unknown backend"):
            _validate_evaluation_settings(s)

    def test_ragas_enabled_but_judge_provider_empty_rejected(self, tmp_path: Path) -> None:
        s = _make_valid_settings(tmp_path)
        s.evaluation.backends = ["custom", "ragas"]
        s.evaluation.judge_llm.provider = ""
        with pytest.raises(SettingsError, match="judge_llm.provider is empty"):
            _validate_evaluation_settings(s)

    def test_judge_llm_provider_not_in_factory_registry_rejected(self, tmp_path: Path) -> None:
        s = _make_valid_settings(tmp_path)
        s.evaluation.judge_llm.provider = "claude"  # 不在 LLMFactory 5 个 provider 列表
        with pytest.raises(SettingsError, match="not in LLMFactory registry"):
            _validate_evaluation_settings(s)

    def test_judge_llm_temperature_out_of_range_rejected(self, tmp_path: Path) -> None:
        s = _make_valid_settings(tmp_path)
        s.evaluation.judge_llm.temperature = 3.0
        with pytest.raises(SettingsError, match="temperature=3.0 out of range"):
            _validate_evaluation_settings(s)

    def test_judge_llm_request_timeout_zero_rejected(self, tmp_path: Path) -> None:
        s = _make_valid_settings(tmp_path)
        s.evaluation.judge_llm.request_timeout_sec = 0
        with pytest.raises(SettingsError, match="request_timeout_sec"):
            _validate_evaluation_settings(s)

    def test_eval_embedding_provider_unknown_rejected(self, tmp_path: Path) -> None:
        s = _make_valid_settings(tmp_path)
        s.evaluation.embedding.provider = "cohere"
        with pytest.raises(SettingsError, match="EmbeddingFactory registry"):
            _validate_evaluation_settings(s)

    def test_acceptance_thresholds_above_one_rejected(self, tmp_path: Path) -> None:
        s = _make_valid_settings(tmp_path)
        s.evaluation.acceptance_thresholds.ragas__faithfulness = 1.5
        with pytest.raises(SettingsError, match="acceptance_thresholds.ragas__faithfulness=1.5"):
            _validate_evaluation_settings(s)

    def test_acceptance_thresholds_negative_rejected(self, tmp_path: Path) -> None:
        s = _make_valid_settings(tmp_path)
        s.evaluation.acceptance_thresholds.custom__hit_rate = -0.1
        with pytest.raises(SettingsError, match="out of range"):
            _validate_evaluation_settings(s)

    def test_by_tag_dimensions_unknown_rejected(self, tmp_path: Path) -> None:
        s = _make_valid_settings(tmp_path)
        s.evaluation.by_tag_dimensions = ["language", "content_type"]
        with pytest.raises(SettingsError, match="unknown dimension"):
            _validate_evaluation_settings(s)

    def test_tag_slice_min_samples_zero_rejected(self, tmp_path: Path) -> None:
        s = _make_valid_settings(tmp_path)
        s.evaluation.tag_slice_min_samples = 0
        with pytest.raises(SettingsError, match="tag_slice_min_samples"):
            _validate_evaluation_settings(s)

    def test_archive_dir_parent_unwritable_rejected(self, tmp_path: Path) -> None:
        """父目录无写权限时拒绝(模拟方式:用一个不存在且无法创建的路径)。"""
        s = _make_valid_settings(tmp_path)
        # 用 NUL 路径之类的非法路径(在 Windows 上 NUL 是设备文件,无法作为目录)
        # 跨平台兼容做法:用一个文件路径作为 parent(文件存在 → 不能作为目录)
        nonfile = tmp_path / "i_am_a_file.txt"
        nonfile.write_text("blocker")
        s.evaluation.report_archive_dir = str(nonfile / "child" / "x.json")
        with pytest.raises(SettingsError, match="report_archive_dir parent not writable"):
            _validate_evaluation_settings(s)


class TestValidationPositiveCases:
    """合法配置不应触发任何错误。"""

    def test_default_evaluation_settings_pass(self, tmp_path: Path) -> None:
        s = _make_valid_settings(tmp_path)
        _validate_evaluation_settings(s)  # 不抛错

    def test_ragas_with_valid_judge_pass(self, tmp_path: Path) -> None:
        s = _make_valid_settings(tmp_path)
        s.evaluation.backends = ["custom", "ragas"]
        # judge_llm 默认值即合法(provider=glm, model=glm-4)
        _validate_evaluation_settings(s)

    def test_user_overrides_thresholds_within_range_pass(self, tmp_path: Path) -> None:
        s = _make_valid_settings(tmp_path)
        s.evaluation.acceptance_thresholds.ragas__faithfulness = 0.95
        s.evaluation.acceptance_thresholds.custom__hit_rate = 0.50
        _validate_evaluation_settings(s)


# ---------------------------------------------------------------------------
# 端到端 load_settings 加载 (验证 _schema_version YAML key → schema_version
# 字段映射 + 嵌套 dataclass 构造)
# ---------------------------------------------------------------------------


class TestLoadSettingsEndToEnd:
    """直接读项目 config/settings.yaml,验证 evaluation 段加载正确。"""

    def test_load_real_yaml_loads_evaluation_section(self) -> None:
        """实际加载 config/settings.yaml,evaluation 段嵌套 dataclass 字段都正确填充。"""
        s = load_settings()
        # 顶层
        assert s.evaluation.schema_version == 1
        assert "custom" in s.evaluation.backends
        # 嵌套 judge_llm
        assert s.evaluation.judge_llm.provider == "glm"
        assert s.evaluation.judge_llm.model == "glm-4"
        # 嵌套 embedding(默认空)
        assert s.evaluation.embedding.provider == ""
        # 嵌套 acceptance_thresholds(默认 8 项业界参考值)
        snap = s.evaluation.acceptance_thresholds.to_dict()
        assert snap["ragas__faithfulness"] == 0.85
        assert snap["custom__mrr"] == 0.55
        assert len(snap) == 8


# ---------------------------------------------------------------------------
# AcceptanceThresholds.to_dict 行为
# ---------------------------------------------------------------------------


class TestAcceptanceThresholdsSnapshot:
    """to_dict() 用于 EvaluationReport.acceptance_thresholds_snapshot 字段。"""

    def test_to_dict_reflects_user_overrides(self) -> None:
        thresholds = AcceptanceThresholds(
            ragas__faithfulness=0.95,
            custom__hit_rate=0.50,
        )
        snap = thresholds.to_dict()
        assert snap["ragas__faithfulness"] == 0.95
        assert snap["custom__hit_rate"] == 0.50
        # 未覆盖的字段保持默认
        assert snap["ragas__context_recall"] == 0.70
