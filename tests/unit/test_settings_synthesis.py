"""Unit tests for `evaluation.synthesis` 配置与校验。

change: expand-chinese-golden-set (T-1.2)

这两个阈值守的是本变更的核心机制:**让「适配静默不生效」无法发生**。
取值非法会让语言校验自己失效 —— 那就等于什么都没做。

不触发任何 LLM 调用。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.core.settings import (
    SettingsError,
    SynthesisSettings,
    _validate_synthesis_settings,
    load_settings,
    validate_settings,
)

pytestmark = pytest.mark.unit

_REAL_CONFIG = "config/settings.yaml"
_FIELDS = ("adapt_language_ratio_min", "question_language_mismatch_warn")


class TestDefaults:
    def test_adapt_threshold_default(self) -> None:
        """0.05 —— 远低于「纯中文」,因为译文里仍有大量 JSON schema 与英文字段名。

        实测未翻译时恒为 0.0%,所以两端差距很大,阈值不必精调。
        """
        assert SynthesisSettings().adapt_language_ratio_min == 0.05

    def test_mismatch_warn_default(self) -> None:
        """0.20 —— 第一代实测是 70%(33/47),那是适配未生效的典型信号。"""
        assert SynthesisSettings().question_language_mismatch_warn == 0.20

    def test_defaults_pass_validation(self) -> None:
        _validate_synthesis_settings(SynthesisSettings())


class TestValidation:
    @pytest.mark.parametrize("field", _FIELDS)
    @pytest.mark.parametrize("bad", [-0.1, 1.1, 2.0, -1])
    def test_out_of_range_rejected(self, field: str, bad: float) -> None:
        with pytest.raises(SettingsError, match=field):
            _validate_synthesis_settings(SynthesisSettings(**{field: bad}))

    @pytest.mark.parametrize("field", _FIELDS)
    @pytest.mark.parametrize("bad", ["0.05", None, [0.05], {}])
    def test_non_numeric_rejected(self, field: str, bad: object) -> None:
        with pytest.raises(SettingsError, match=field):
            _validate_synthesis_settings(SynthesisSettings(**{field: bad}))

    @pytest.mark.parametrize("field", _FIELDS)
    def test_bool_rejected(self, field: str) -> None:
        """``True`` 在 Python 里 == 1,不挡会被当成「要求 100% 目标语言」。"""
        with pytest.raises(SettingsError, match=field):
            _validate_synthesis_settings(SynthesisSettings(**{field: True}))

    @pytest.mark.parametrize("field", _FIELDS)
    @pytest.mark.parametrize("good", [0.0, 0.5, 1.0, 1, 0])
    def test_boundaries_accepted(self, field: str, good: float) -> None:
        _validate_synthesis_settings(SynthesisSettings(**{field: good}))


class TestBackwardCompatibility:
    def test_yaml_without_synthesis_section_still_loads(self, tmp_path: Path) -> None:
        raw = yaml.safe_load(Path(_REAL_CONFIG).read_text(encoding="utf-8"))
        raw.setdefault("evaluation", {}).pop("synthesis", None)

        cfg = tmp_path / "settings.yaml"
        cfg.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

        settings = load_settings(str(cfg))

        assert settings.evaluation.synthesis.adapt_language_ratio_min == 0.05
        validate_settings(settings)


class TestRealConfigWiring:
    def test_real_config_passes(self) -> None:
        validate_settings(load_settings(_REAL_CONFIG))

    def test_real_config_has_synthesis(self) -> None:
        s = load_settings(_REAL_CONFIG).evaluation.synthesis
        assert 0.0 <= s.adapt_language_ratio_min <= 1.0

    def test_validate_settings_invokes_synthesis_checks(self) -> None:
        """校验必须挂在 validate_settings 调用链上,不能只是个孤立函数。"""
        settings = load_settings(_REAL_CONFIG)
        settings.evaluation.synthesis.adapt_language_ratio_min = 2.0

        with pytest.raises(SettingsError, match="adapt_language_ratio_min"):
            validate_settings(settings)
