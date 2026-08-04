"""Unit tests for Feature-003 `evaluation.screening_llm` settings (T006).

测试范围:
1. ``ScreeningLLMSettings`` 默认值与 ``is_enabled()`` / ``thresholds_snapshot()`` 行为
2. ``_validate_evaluation_settings`` 中 screening_llm 相关校验的 negative cases
3. **FR-004 关键回归**:未配置 ``screening_llm`` 节的既有配置必须仍能正常加载
4. settings.yaml 端到端加载(本节存在时字段正确装配)

覆盖 spec § FR-009(配置驱动)+ contracts/settings.screening.schema.md § 2-3。

不触发任何 LLM 调用。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.core.settings import (
    EmbeddingSettings,
    EvaluationSettings,
    LLMSettings,
    ScreeningLLMSettings,
    Settings,
    SettingsError,
    VectorStoreSettings,
    VisionLLMSettings,
    _validate_evaluation_settings,
    load_settings,
)

pytestmark = pytest.mark.unit


_REAL_CONFIG = "config/settings.yaml"

# 5 个比例/阈值字段,校验区间同为 (0.0, 1.0]
_RATIO_FIELDS = (
    "keep_threshold",
    "drop_threshold",
    "borderline_ratio_warn",
    "sample_ratio",
    "compliance_gate",
)


def _make_valid_settings(tmp_path: Path) -> Settings:
    """构造一个最小有效 Settings,临时目录用于可写性校验。"""
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
# 默认值与 dataclass 行为
# ---------------------------------------------------------------------------


class TestDefaults:
    """默认值必须是「未启用 + 初始阈值」。"""

    def test_provider_and_model_default_empty(self) -> None:
        """默认空 = 未启用。这是 FR-004 的基础:默认交互模式不需要预筛模型。"""
        s = ScreeningLLMSettings()
        assert s.provider == ""
        assert s.model == ""

    def test_threshold_defaults(self) -> None:
        s = ScreeningLLMSettings()
        assert s.keep_threshold == 0.80
        assert s.drop_threshold == 0.80
        assert s.borderline_ratio_warn == 0.40
        assert s.sample_ratio == 0.10
        assert s.compliance_gate == 0.90

    def test_temperature_defaults_to_zero(self) -> None:
        """判定应尽量确定,与 Judge 同取 0.0。"""
        assert ScreeningLLMSettings().temperature == 0.0


class TestIsEnabled:
    """is_enabled() 决定 --auto-mode 能否启动。"""

    def test_disabled_by_default(self) -> None:
        assert ScreeningLLMSettings().is_enabled() is False

    def test_enabled_when_both_set(self) -> None:
        assert ScreeningLLMSettings(provider="glm", model="glm-4.6").is_enabled() is True

    @pytest.mark.parametrize(
        ("provider", "model"),
        [("glm", ""), ("", "glm-4.6")],
        ids=["model-missing", "provider-missing"],
    )
    def test_disabled_when_either_missing(self, provider: str, model: str) -> None:
        assert ScreeningLLMSettings(provider=provider, model=model).is_enabled() is False

    def test_whitespace_only_treated_as_empty(self) -> None:
        """纯空白等同未配置,避免 YAML 里写了空格就被当成已启用。"""
        assert ScreeningLLMSettings(provider="  ", model="  ").is_enabled() is False


class TestThresholdsSnapshot:
    """FR-005:阈值须随金标落盘,使历史金标可追溯当时判定条件。"""

    def test_snapshot_contains_all_five_thresholds(self) -> None:
        snap = ScreeningLLMSettings().thresholds_snapshot()
        assert set(snap) == set(_RATIO_FIELDS)

    def test_snapshot_reflects_overrides(self) -> None:
        s = ScreeningLLMSettings(keep_threshold=0.95, sample_ratio=0.2)
        snap = s.thresholds_snapshot()
        assert snap["keep_threshold"] == 0.95
        assert snap["sample_ratio"] == 0.2


# ---------------------------------------------------------------------------
# 校验 negative cases(宪法 § III 快速失败)
# ---------------------------------------------------------------------------


class TestValidationNegativeCases:
    def test_unknown_provider_rejected(self, tmp_path: Path) -> None:
        s = _make_valid_settings(tmp_path)
        s.evaluation.screening_llm.provider = "not-a-provider"
        with pytest.raises(SettingsError, match="screening_llm.provider"):
            _validate_evaluation_settings(s)

    def test_empty_provider_accepted(self, tmp_path: Path) -> None:
        """空 provider 不报错——未启用是合法状态(FR-004)。"""
        s = _make_valid_settings(tmp_path)
        s.evaluation.screening_llm.provider = ""
        _validate_evaluation_settings(s)  # 不抛异常即通过

    @pytest.mark.parametrize("bad", [-0.1, 2.1])
    def test_temperature_out_of_range_rejected(self, tmp_path: Path, bad: float) -> None:
        s = _make_valid_settings(tmp_path)
        s.evaluation.screening_llm.temperature = bad
        with pytest.raises(SettingsError, match="screening_llm.temperature"):
            _validate_evaluation_settings(s)

    @pytest.mark.parametrize("bad", [0, -1])
    def test_non_positive_timeout_rejected(self, tmp_path: Path, bad: int) -> None:
        s = _make_valid_settings(tmp_path)
        s.evaluation.screening_llm.request_timeout_sec = bad
        with pytest.raises(SettingsError, match="screening_llm.request_timeout_sec"):
            _validate_evaluation_settings(s)

    @pytest.mark.parametrize("field_name", _RATIO_FIELDS)
    @pytest.mark.parametrize("bad", [0.0, -0.1, 1.1])
    def test_ratio_out_of_range_rejected(
        self, tmp_path: Path, field_name: str, bad: float
    ) -> None:
        """5 个比例字段均须落在 (0.0, 1.0];0.0 也非法(阈值为 0 无意义)。"""
        s = _make_valid_settings(tmp_path)
        setattr(s.evaluation.screening_llm, field_name, bad)
        with pytest.raises(SettingsError, match=f"screening_llm.{field_name}"):
            _validate_evaluation_settings(s)

    @pytest.mark.parametrize("field_name", _RATIO_FIELDS)
    def test_ratio_upper_bound_inclusive(self, tmp_path: Path, field_name: str) -> None:
        """1.0 合法(如 sample_ratio=1.0 表示全量自检)。"""
        s = _make_valid_settings(tmp_path)
        setattr(s.evaluation.screening_llm, field_name, 1.0)
        _validate_evaluation_settings(s)


# ---------------------------------------------------------------------------
# 端到端加载
# ---------------------------------------------------------------------------


class TestEndToEndLoad:
    def test_real_config_exposes_screening_section(self) -> None:
        """真实 config/settings.yaml 装配出 ScreeningLLMSettings。"""
        s = load_settings()
        sc = s.evaluation.screening_llm
        assert isinstance(sc, ScreeningLLMSettings)
        # 仓库内默认留空 = 未启用,不会给既有用法带来任何 LLM 调用
        assert sc.is_enabled() is False
        assert sc.thresholds_snapshot()["compliance_gate"] == 0.90

    def test_config_without_screening_section_still_loads(self, tmp_path: Path) -> None:
        """**FR-004 关键回归**:删掉 screening_llm 节的旧配置必须照常加载。

        本 feature 新增了 YAML 字段,若装配逻辑把缺失的节当错误处理,所有
        尚未升级配置的环境都会启动失败。
        """
        raw = yaml.safe_load(Path(_REAL_CONFIG).read_text(encoding="utf-8"))
        raw["evaluation"].pop("screening_llm", None)
        assert "screening_llm" not in raw["evaluation"]

        stripped = tmp_path / "settings_no_screening.yaml"
        stripped.write_text(
            yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

        s = load_settings(str(stripped))
        # 缺失时回落到 dataclass 默认值,而非报错
        assert s.evaluation.screening_llm.is_enabled() is False
        assert s.evaluation.screening_llm.keep_threshold == 0.80

    def test_configured_section_is_assembled(self, tmp_path: Path) -> None:
        """本节填了值时,各字段如实装配(含阈值覆盖)。"""
        raw = yaml.safe_load(Path(_REAL_CONFIG).read_text(encoding="utf-8"))
        raw["evaluation"]["screening_llm"] = {
            "provider": "glm",
            "model": "glm-4.6",
            "api_key": "sk-test",
            "base_url": "https://example.invalid/v1",
            "temperature": 0.0,
            "request_timeout_sec": 30,
            "keep_threshold": 0.9,
            "drop_threshold": 0.85,
            "borderline_ratio_warn": 0.3,
            "sample_ratio": 0.2,
            "compliance_gate": 0.95,
        }
        configured = tmp_path / "settings_with_screening.yaml"
        configured.write_text(
            yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

        sc = load_settings(str(configured)).evaluation.screening_llm
        assert sc.is_enabled() is True
        assert sc.provider == "glm"
        assert sc.model == "glm-4.6"
        assert sc.request_timeout_sec == 30
        assert sc.thresholds_snapshot() == {
            "keep_threshold": 0.9,
            "drop_threshold": 0.85,
            "borderline_ratio_warn": 0.3,
            "sample_ratio": 0.2,
            "compliance_gate": 0.95,
        }
