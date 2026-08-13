"""Unit tests for `rerank` 段配置与启动期校验。

change: activate-cross-encoder-rerank (T-2.1)

测试范围:

1. 新字段 ``timeout_sec`` / ``batch_size`` 的默认值,以及既有字段不受影响
2. ``_validate_rerank_settings`` 的通过与拒绝两侧
3. **向后兼容回归**:``settings.yaml`` 不含新字段时必须仍能加载并通过校验
4. 校验必须挂在 ``validate_settings`` 调用链上,不能只是个孤立函数

背景:重排此前有三处「看起来可配、实际不起作用」的缺陷 —— ``model`` 有隐式
兜底默认值(纯英文模型,对中文语料无效且不报错)、``top_m`` 从未被消费、
超时机制完全不存在。这些校验守的是同一件事:**配置错误必须在启动期报错,
而不是让用户拿到一次不报错的普通检索**。

不触发任何模型加载 / LLM 调用。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.core.settings import (
    VALID_RERANK_BACKENDS,
    RerankSettings,
    SettingsError,
    _validate_rerank_settings,
    load_settings,
    validate_settings,
)

pytestmark = pytest.mark.unit


_REAL_CONFIG = "config/settings.yaml"


class TestDefaults:
    """默认值必须保持本变更之前的行为(默认不重排)。"""

    def test_backend_default_is_none(self) -> None:
        """默认关闭 —— 重排依赖是 optional extra,默认配置不得触碰它。"""
        assert RerankSettings().backend == "none"

    def test_model_default_is_empty(self) -> None:
        """刻意留空,不设隐式默认模型。

        此前 ``CrossEncoderReranker`` 用 ``getattr(..., "cross-encoder/
        ms-marco-MiniLM-L-6-v2")`` 兜底 —— 那是个纯英文 MS MARCO 模型,对本
        项目一半语料(中文 MT5 文档)完全无效,而且不报错。现在改为
        ``backend != none`` 时强制显式配置。
        """
        assert RerankSettings().model == ""

    def test_new_fields_defaults(self) -> None:
        r = RerankSettings()
        assert r.timeout_sec == 30.0
        assert r.batch_size == 8

    def test_existing_fields_unchanged(self) -> None:
        """``top_m`` 的默认值不动 —— 改它会静默改变既有部署的行为。"""
        assert RerankSettings().top_m == 30


class TestBackendValidation:
    """``backend`` 必须在白名单内。"""

    @pytest.mark.parametrize("good", sorted(VALID_RERANK_BACKENDS))
    def test_whitelisted_backends_accepted(self, good: str) -> None:
        # backend != none 时 model 必填,所以合法后端要带上 model
        model = "" if good == "none" else "BAAI/bge-reranker-base"
        _validate_rerank_settings(RerankSettings(backend=good, model=model))

    @pytest.mark.parametrize("bad", ["cohere", "jina", "None", "CROSS_ENCODER", ""])
    def test_unknown_backend_rejected(self, bad: str) -> None:
        """拼错的后端名必须启动期报错,不能静默退化为不重排。"""
        with pytest.raises(SettingsError, match="rerank.backend"):
            _validate_rerank_settings(RerankSettings(backend=bad))

    def test_error_message_lists_valid_options(self) -> None:
        with pytest.raises(SettingsError, match="cross_encoder"):
            _validate_rerank_settings(RerankSettings(backend="cohere"))


class TestModelRequiredWhenEnabled:
    """``backend != none`` 时 ``model`` 必填 —— 本组是本变更的核心校验之一。"""

    @pytest.mark.parametrize("backend", ["cross_encoder", "llm"])
    def test_empty_model_rejected_when_enabled(self, backend: str) -> None:
        with pytest.raises(SettingsError, match="rerank.model is required"):
            _validate_rerank_settings(RerankSettings(backend=backend, model=""))

    @pytest.mark.parametrize("blank", ["   ", "\t", "\n"])
    def test_whitespace_only_model_rejected(self, blank: str) -> None:
        """纯空白等同于空 —— 否则 YAML 里一个空格就能绕过校验。"""
        with pytest.raises(SettingsError, match="rerank.model is required"):
            _validate_rerank_settings(
                RerankSettings(backend="cross_encoder", model=blank)
            )

    def test_empty_model_accepted_when_disabled(self) -> None:
        """``backend: none`` 时 model 留空合法 —— 这是默认配置的形态。"""
        _validate_rerank_settings(RerankSettings(backend="none", model=""))

    def test_error_message_names_a_recommended_model(self) -> None:
        """错误消息要能直接照抄 —— 用户是学习者,不该让他去猜模型名。"""
        with pytest.raises(SettingsError, match="bge-reranker-base"):
            _validate_rerank_settings(RerankSettings(backend="cross_encoder"))


class TestTopMValidation:
    """``top_m`` 必须是正整数。"""

    @pytest.mark.parametrize("bad", [0, -1, -50])
    def test_non_positive_rejected(self, bad: int) -> None:
        with pytest.raises(SettingsError, match="rerank.top_m"):
            _validate_rerank_settings(RerankSettings(top_m=bad))

    @pytest.mark.parametrize("bad", ["50", 50.5, None, [50]])
    def test_non_integer_rejected(self, bad: object) -> None:
        with pytest.raises(SettingsError, match="rerank.top_m"):
            _validate_rerank_settings(RerankSettings(top_m=bad))  # type: ignore[arg-type]

    def test_bool_rejected(self) -> None:
        """``top_m: true`` 会被当作 1 —— 只重排第一条,等于没重排。"""
        with pytest.raises(SettingsError, match="rerank.top_m"):
            _validate_rerank_settings(RerankSettings(top_m=True))  # type: ignore[arg-type]

    def test_positive_accepted(self) -> None:
        _validate_rerank_settings(RerankSettings(top_m=1))
        _validate_rerank_settings(RerankSettings(top_m=1000))


class TestBatchSizeValidation:
    """``batch_size`` 必须是正整数(它同时决定超时检查的粒度)。"""

    @pytest.mark.parametrize("bad", [0, -1])
    def test_non_positive_rejected(self, bad: int) -> None:
        with pytest.raises(SettingsError, match="rerank.batch_size"):
            _validate_rerank_settings(RerankSettings(batch_size=bad))

    @pytest.mark.parametrize("bad", ["8", 8.0, None])
    def test_non_integer_rejected(self, bad: object) -> None:
        with pytest.raises(SettingsError, match="rerank.batch_size"):
            _validate_rerank_settings(RerankSettings(batch_size=bad))  # type: ignore[arg-type]

    def test_bool_rejected(self) -> None:
        with pytest.raises(SettingsError, match="rerank.batch_size"):
            _validate_rerank_settings(RerankSettings(batch_size=True))  # type: ignore[arg-type]

    def test_positive_accepted(self) -> None:
        _validate_rerank_settings(RerankSettings(batch_size=1))
        _validate_rerank_settings(RerankSettings(batch_size=32))


class TestTimeoutValidation:
    """``timeout_sec`` 必须是正数(允许小数)。"""

    @pytest.mark.parametrize("bad", [0, 0.0, -1, -0.5])
    def test_non_positive_rejected(self, bad: float) -> None:
        """非正超时会让每次重排立刻「超时」并退化为原序 —— 静默失效。"""
        with pytest.raises(SettingsError, match="rerank.timeout_sec"):
            _validate_rerank_settings(RerankSettings(timeout_sec=bad))

    @pytest.mark.parametrize("bad", ["30", None, [30]])
    def test_non_numeric_rejected(self, bad: object) -> None:
        with pytest.raises(SettingsError, match="rerank.timeout_sec"):
            _validate_rerank_settings(RerankSettings(timeout_sec=bad))  # type: ignore[arg-type]

    def test_bool_rejected(self) -> None:
        with pytest.raises(SettingsError, match="rerank.timeout_sec"):
            _validate_rerank_settings(RerankSettings(timeout_sec=True))  # type: ignore[arg-type]

    def test_fractional_accepted(self) -> None:
        """允许小数 —— 亚秒级超时对交互式查询是合理需求。"""
        _validate_rerank_settings(RerankSettings(timeout_sec=0.5))

    def test_int_accepted(self) -> None:
        """整数也合法 —— YAML 写 ``timeout_sec: 30`` 不该被拒。"""
        _validate_rerank_settings(RerankSettings(timeout_sec=30))


class TestBackwardCompatibility:
    """既有配置(不含新字段)必须仍能加载 —— 回归保护。"""

    def test_yaml_without_new_fields_still_loads(self, tmp_path: Path) -> None:
        raw = yaml.safe_load(Path(_REAL_CONFIG).read_text(encoding="utf-8"))
        raw.setdefault("rerank", {})
        raw["rerank"].pop("timeout_sec", None)
        raw["rerank"].pop("batch_size", None)

        cfg = tmp_path / "settings.yaml"
        cfg.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

        settings = load_settings(str(cfg))

        assert settings.rerank.timeout_sec == 30.0
        assert settings.rerank.batch_size == 8
        validate_settings(settings)

    def test_yaml_without_rerank_section_still_loads(self, tmp_path: Path) -> None:
        """整段缺失也要能起来 —— 默认即 backend: none,不重排。"""
        raw = yaml.safe_load(Path(_REAL_CONFIG).read_text(encoding="utf-8"))
        raw.pop("rerank", None)

        cfg = tmp_path / "settings.yaml"
        cfg.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

        settings = load_settings(str(cfg))

        assert settings.rerank.backend == "none"
        validate_settings(settings)


class TestRealConfigWiring:
    """settings.yaml 端到端装配。"""

    def test_real_config_keeps_rerank_disabled(self) -> None:
        """交付的默认配置必须保持不重排。

        本变更只让 cross_encoder 这条路径「能真实跑通」,不改变默认行为 ——
        既有中英金标基线全部是无重排产出的,改默认会让后续 delta 无法与历史
        对比。A/B 数据出来后再单独一行配置切换。
        """
        assert load_settings(_REAL_CONFIG).rerank.backend == "none"

    def test_real_config_passes_validation(self) -> None:
        validate_settings(load_settings(_REAL_CONFIG))

    def test_validate_settings_invokes_rerank_checks(self) -> None:
        """重排校验必须挂在 validate_settings 调用链上,不能只是个孤立函数。"""
        settings = load_settings(_REAL_CONFIG)
        settings.rerank.top_m = 0

        with pytest.raises(SettingsError, match="rerank.top_m"):
            validate_settings(settings)
