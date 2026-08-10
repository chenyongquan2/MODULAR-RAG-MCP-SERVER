"""Unit tests for Feature-005 `retrieval` 融合参数 (T001/T002/T004)。

测试范围:

1. ``rrf_k`` 与 ``fusion_weights`` 的默认值
2. ``_validate_fusion_settings`` 的 negative cases —— 这些校验刻意在启动期
   硬失败,因为**违反后不会有任何报错**,只是排序悄悄失去意义
3. **向后兼容回归**:``settings.yaml`` 不含新字段时必须仍能加载并通过校验
4. settings.yaml 端到端装配

背景:``rrf_k`` 此前硬编码在 ``Fusion.DEFAULT_K``,且 ``Fusion()`` 构造时不读
任何配置 —— 属宪法原则二禁止的硬编码可调参数。

不触发任何 LLM / 向量库调用。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.core.settings import (
    RetrievalSettings,
    SettingsError,
    _validate_fusion_settings,
    load_settings,
    validate_settings,
)

pytestmark = pytest.mark.unit


_REAL_CONFIG = "config/settings.yaml"


class TestDefaults:
    """新字段默认值必须保持本 feature 之前的行为。"""

    def test_rrf_k_default_matches_old_hardcoded_value(self) -> None:
        """默认 60 —— 与此前 Fusion.DEFAULT_K 一致,确保升级后行为不变。"""
        assert RetrievalSettings().rrf_k == 60

    def test_fusion_weights_default_is_equal_weight(self) -> None:
        """默认等权 —— 等权时新公式与旧公式排序等价(FR-003)。"""
        assert RetrievalSettings().fusion_weights == {"dense": 1.0, "sparse": 1.0}

    def test_existing_fields_unchanged(self) -> None:
        r = RetrievalSettings()
        assert r.sparse_backend == "bm25"
        assert r.fusion_algorithm == "rrf"
        assert (r.top_k_dense, r.top_k_sparse, r.top_k_final) == (20, 20, 10)

    def test_default_factory_not_shared_between_instances(self) -> None:
        """可变默认值必须走 default_factory,否则两个实例共享同一个 dict。"""
        a, b = RetrievalSettings(), RetrievalSettings()
        a.fusion_weights["dense"] = 99.0
        assert b.fusion_weights["dense"] == 1.0


class TestRrfKValidation:
    """``rrf_k`` 必须是正整数。"""

    @pytest.mark.parametrize("bad", [0, -1, -60])
    def test_non_positive_rejected(self, bad: int) -> None:
        with pytest.raises(SettingsError, match="rrf_k"):
            _validate_fusion_settings(RetrievalSettings(rrf_k=bad))

    @pytest.mark.parametrize("bad", ["60", 60.0, None, [60]])
    def test_non_integer_rejected(self, bad: object) -> None:
        with pytest.raises(SettingsError, match="rrf_k"):
            _validate_fusion_settings(RetrievalSettings(rrf_k=bad))  # type: ignore[arg-type]

    def test_bool_rejected(self) -> None:
        """``True`` 在 Python 里 isinstance(int) 为真,必须单独挡掉。

        否则 YAML 写成 ``rrf_k: true`` 会被静默当作 k=1,衰减过陡而无人察觉。
        """
        with pytest.raises(SettingsError, match="rrf_k"):
            _validate_fusion_settings(RetrievalSettings(rrf_k=True))  # type: ignore[arg-type]

    def test_positive_accepted(self) -> None:
        _validate_fusion_settings(RetrievalSettings(rrf_k=1))
        _validate_fusion_settings(RetrievalSettings(rrf_k=100))


class TestFusionWeightsValidation:
    """``fusion_weights`` 的校验。"""

    def test_negative_weight_rejected(self) -> None:
        with pytest.raises(SettingsError, match="fusion_weights"):
            _validate_fusion_settings(
                RetrievalSettings(fusion_weights={"dense": 1.0, "sparse": -0.5})
            )

    @pytest.mark.parametrize("bad", ["1.0", None, [1.0], {"x": 1}])
    def test_non_numeric_weight_rejected(self, bad: object) -> None:
        with pytest.raises(SettingsError, match="fusion_weights"):
            _validate_fusion_settings(
                RetrievalSettings(fusion_weights={"dense": bad})  # type: ignore[dict-item]
            )

    def test_bool_weight_rejected(self) -> None:
        with pytest.raises(SettingsError, match="fusion_weights"):
            _validate_fusion_settings(
                RetrievalSettings(fusion_weights={"dense": True})  # type: ignore[dict-item]
            )

    def test_all_zero_rejected(self) -> None:
        """全零权重必须拒绝 —— 这是本组最重要的一条。

        所有融合得分归零后,排序完全由字典遍历顺序决定,检索结果实际上变成
        随机的 —— **而这不会抛任何异常、不会有任何日志**。正是宪法原则三
        要防的那类静默失效。
        """
        with pytest.raises(SettingsError, match="all weights are zero"):
            _validate_fusion_settings(
                RetrievalSettings(fusion_weights={"dense": 0.0, "sparse": 0})
            )

    def test_single_zero_weight_is_legal(self) -> None:
        """单条路径为 0 合法 —— 等价于关闭该路,是 SC-005 的测试手段。"""
        _validate_fusion_settings(
            RetrievalSettings(fusion_weights={"dense": 1.0, "sparse": 0.0})
        )

    def test_non_mapping_rejected(self) -> None:
        with pytest.raises(SettingsError, match="fusion_weights"):
            _validate_fusion_settings(RetrievalSettings(fusion_weights=[1.0, 1.0]))  # type: ignore[arg-type]

    def test_extra_route_key_accepted(self) -> None:
        """多余的路径键不拒绝 —— 可能是为未来路径预留的配置。"""
        _validate_fusion_settings(
            RetrievalSettings(fusion_weights={"dense": 1.0, "sparse": 1.0, "future": 0.5})
        )

    def test_empty_mapping_accepted(self) -> None:
        """空映射合法 —— 所有路径按缺省 1.0 处理,等价于等权。"""
        _validate_fusion_settings(RetrievalSettings(fusion_weights={}))


class TestBackwardCompatibility:
    """既有配置(不含新字段)必须仍能加载 —— 回归保护。"""

    def test_yaml_without_new_fields_still_loads(self, tmp_path: Path) -> None:
        raw = yaml.safe_load(Path(_REAL_CONFIG).read_text(encoding="utf-8"))
        raw["retrieval"].pop("rrf_k", None)
        raw["retrieval"].pop("fusion_weights", None)

        cfg = tmp_path / "settings.yaml"
        cfg.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

        settings = load_settings(str(cfg))

        assert settings.retrieval.rrf_k == 60
        assert settings.retrieval.fusion_weights == {"dense": 1.0, "sparse": 1.0}
        validate_settings(settings)


class TestRealConfigWiring:
    """settings.yaml 端到端装配。"""

    def test_real_config_wires_new_fields(self) -> None:
        r = load_settings(_REAL_CONFIG).retrieval
        assert r.rrf_k == 60
        assert r.fusion_weights == {"dense": 1.0, "sparse": 1.0}

    def test_real_config_passes_validation(self) -> None:
        validate_settings(load_settings(_REAL_CONFIG))

    def test_validate_settings_invokes_fusion_checks(self) -> None:
        """融合校验必须挂在 validate_settings 的调用链上,不能只是个孤立函数。"""
        settings = load_settings(_REAL_CONFIG)
        settings.retrieval.rrf_k = 0

        with pytest.raises(SettingsError, match="rrf_k"):
            validate_settings(settings)
