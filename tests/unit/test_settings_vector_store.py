"""Unit tests for Feature-004 `vector_store` 新增字段 (T001)。

测试范围:

1. ``VectorStoreSettings`` 的两个新字段默认值
2. ``validate_settings`` 对 ``bm25_index_format_version`` 的 negative cases
3. **向后兼容回归**:settings.yaml 中不含这两个字段的既有配置必须仍能加载
4. settings.yaml 端到端加载(字段正确装配)

覆盖 spec § FR-014 的配置载体与宪法原则二(配置驱动)/ 原则三(快速失败校验)。

背景:``bm25_index_path`` 此前被 ``sparse_retriever.py`` 用
``getattr(settings.vector_store, "bm25_index_path", "data/db/bm25")`` 读取,
而该字段并不存在于 dataclass —— 属于宪法原则三禁止的"静默回退默认值"。
本 feature 补为正式字段,这些测试守住它。

不触发任何 LLM / 向量库调用。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.core.settings import (
    SettingsError,
    VectorStoreSettings,
    load_settings,
    validate_settings,
)

pytestmark = pytest.mark.unit


_REAL_CONFIG = "config/settings.yaml"


class TestVectorStoreDefaults:
    """新字段的默认值。"""

    def test_new_fields_have_defaults(self) -> None:
        vs = VectorStoreSettings(backend="chroma")
        assert vs.bm25_index_path == "./data/db/bm25"
        assert vs.bm25_index_format_version == 2

    def test_existing_fields_unchanged(self) -> None:
        """新增字段不得改变既有字段的默认值。"""
        vs = VectorStoreSettings(backend="chroma")
        assert vs.persist_path == "./data/db/chroma"
        assert vs.collection_name == "default"


class TestFormatVersionValidation:
    """``bm25_index_format_version`` 的启动期校验(宪法原则三)。"""

    @pytest.mark.parametrize("bad_value", [0, -1, -99])
    def test_non_positive_rejected(self, bad_value: int) -> None:
        settings = load_settings(_REAL_CONFIG)
        settings.vector_store.bm25_index_format_version = bad_value

        with pytest.raises(SettingsError, match="bm25_index_format_version"):
            validate_settings(settings)

    @pytest.mark.parametrize("bad_value", ["2", 2.0, None, [2]])
    def test_non_integer_rejected(self, bad_value: object) -> None:
        """字符串 "2" / 浮点 2.0 都不算合法 —— 版本号必须是 int。"""
        settings = load_settings(_REAL_CONFIG)
        settings.vector_store.bm25_index_format_version = bad_value  # type: ignore[assignment]

        with pytest.raises(SettingsError, match="bm25_index_format_version"):
            validate_settings(settings)

    def test_bool_rejected(self) -> None:
        """``True`` 在 Python 里 isinstance(int) 为真,必须被单独挡掉。

        否则 ``bm25_index_format_version: true`` 这种 YAML 笔误会静默通过
        并被当作版本 1。
        """
        settings = load_settings(_REAL_CONFIG)
        settings.vector_store.bm25_index_format_version = True  # type: ignore[assignment]

        with pytest.raises(SettingsError, match="bm25_index_format_version"):
            validate_settings(settings)

    def test_positive_integer_accepted(self) -> None:
        settings = load_settings(_REAL_CONFIG)
        settings.vector_store.bm25_index_format_version = 3
        validate_settings(settings)  # 不抛异常即通过


class TestBackwardCompatibility:
    """既有配置(不含新字段)必须仍能加载 —— 回归保护。"""

    def test_yaml_without_new_fields_still_loads(self, tmp_path: Path) -> None:
        raw = yaml.safe_load(Path(_REAL_CONFIG).read_text(encoding="utf-8"))
        raw["vector_store"].pop("bm25_index_path", None)
        raw["vector_store"].pop("bm25_index_format_version", None)

        cfg = tmp_path / "settings.yaml"
        cfg.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

        settings = load_settings(str(cfg))

        # 缺失时回落到 dataclass 默认值,且校验通过
        assert settings.vector_store.bm25_index_path == "./data/db/bm25"
        assert settings.vector_store.bm25_index_format_version == 2


class TestRealConfigWiring:
    """settings.yaml 端到端装配。"""

    def test_real_config_wires_new_fields(self) -> None:
        settings = load_settings(_REAL_CONFIG)
        assert settings.vector_store.bm25_index_path == "./data/db/bm25"
        assert settings.vector_store.bm25_index_format_version == 2

    def test_real_config_passes_validation(self) -> None:
        validate_settings(load_settings(_REAL_CONFIG))
