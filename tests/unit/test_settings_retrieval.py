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
    VALID_FUSION_ROUTES,
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

    def test_extra_route_key_rejected(self) -> None:
        """多余的路径键**必须拒绝**。

        ⚠️ 这条 2026-08-25 从「接受」翻转为「拒绝」，推翻的是 feature-005 当时的
        决定（原文：「多余的路径键不拒绝 —— 可能是为未来路径预留的配置」）。
        理由：

        - 「为未来路径预留」**买不到任何东西** —— 代码不支持那条路之前，
          预留的键什么都不做。
        - 而它的代价是实打实的：**拼错的键与预留的键完全无法区分**。
          ``sparce: 0.75`` 会顺利通过校验，然后 ``Fusion.weight_for()``
          查不到 ``sparse`` 就回落 1.0 —— 校准出来的权重被悄悄作废、
          sparse 回到等权，系统照常运行、不报错、指标只是变差。
          本项目已因这一类静默失效栽过十余次。

        翻转的代价是「新增检索路径时要同步更新 ``VALID_FUSION_ROUTES``」——
        那是同一个 commit 里的一行，而且 ``test_future_multi_query_route_rejected_for_now``
        已把这件事变成**强制配套**（校验与 ``weight_for()`` 必须一起改）。

        ⚠️ 注意这**不影响**规格承诺的「缺失的键缺省 1.0」
        （``specs/005-weighted-fusion/data-model.md:27``）—— 那条由
        ``test_subset_of_routes_accepted`` 与 ``test_empty_mapping_accepted`` 守着。
        缺失与拼错是两件事：前者是刻意不配，后者是想配却配错了。
        """
        with pytest.raises(SettingsError, match="Unknown route name"):
            _validate_fusion_settings(
                RetrievalSettings(
                    fusion_weights={"dense": 1.0, "sparse": 1.0, "future": 0.5}
                )
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


class TestFusionRouteNameValidation:
    """``fusion_weights`` 的键名必须是已知路径 —— 拼错的键**静默不生效**。

    此前校验只看值(类型 / 非负 / 非全零),**完全不看键名**。于是
    ``sparce: 0.75`` 会顺利通过,而 ``Fusion.weight_for()`` 查不到 ``sparse``
    就回落 ``DEFAULT_ROUTE_WEIGHT``(1.0)—— 校准出来的权重被悄悄作废、
    sparse 回到等权,系统照常运行、不报错、指标只是变差。

    ⚠️ ``tests/unit/test_no_dead_settings.py`` 那个守卫**抓不到这一类** ——
    它守的是 dataclass 字段有没有读取点,而这里错的是**字典的键**。
    两个守卫覆盖的是不同的失效面。
    """

    def test_misspelled_route_rejected(self) -> None:
        with pytest.raises(SettingsError, match="Unknown route name"):
            _validate_fusion_settings(
                RetrievalSettings(fusion_weights={"dense": 1.0, "sparce": 0.75})
            )

    def test_trailing_underscore_rejected(self) -> None:
        """``sparse_`` 这种「看起来对」的拼错最危险 —— 肉眼极难发现。"""
        with pytest.raises(SettingsError, match="Unknown route name"):
            _validate_fusion_settings(
                RetrievalSettings(fusion_weights={"dense": 1.0, "sparse_": 0.75})
            )

    def test_future_multi_query_route_rejected_for_now(self) -> None:
        """``sparse_q0`` 目前也被拒 —— 这是**刻意**的。

        引入多路检索时这里要与 ``Fusion.weight_for()`` **同时**放宽成路径族判定。
        只改一处会重新打开静默失效的口子,所以现在先让它硬失败,
        逼下一个变更两处一起动。
        """
        with pytest.raises(SettingsError, match="Unknown route name"):
            _validate_fusion_settings(
                RetrievalSettings(fusion_weights={"dense": 1.0, "sparse_q0": 0.5})
            )

    def test_error_lists_valid_routes(self) -> None:
        with pytest.raises(SettingsError) as exc:
            _validate_fusion_settings(
                RetrievalSettings(fusion_weights={"bogus": 1.0})
            )
        for name in VALID_FUSION_ROUTES:
            assert name in str(exc.value)

    def test_known_routes_accepted(self) -> None:
        _validate_fusion_settings(
            RetrievalSettings(fusion_weights={"dense": 1.0, "sparse": 0.75})
        )

    def test_subset_of_routes_accepted(self) -> None:
        """只配一路是合法的 —— 缺失的路走缺省权重。"""
        _validate_fusion_settings(RetrievalSettings(fusion_weights={"dense": 1.0}))

    def test_constant_matches_types_module(self) -> None:
        """``VALID_FUSION_ROUTES`` 必须与 ``types.py`` 的路径名常量一致。

        settings.py 刻意不 import types(保持它无内部依赖),所以两处一致性
        只能靠这条用例守 —— 否则两份字面量可以各自漂移,而漂移是静默的。
        """
        from src.core.types import ROUTE_DENSE, ROUTE_SPARSE

        assert VALID_FUSION_ROUTES == frozenset({ROUTE_DENSE, ROUTE_SPARSE})


class TestRealConfigWiring:
    """settings.yaml 端到端装配。"""

    def test_real_config_wires_new_fields(self) -> None:
        """settings.yaml 里是**校准后的推荐值**，与 dataclass 默认值不同。

        这个区分是刻意的：

        - ``RetrievalSettings`` 的默认值是等权 ``1.0 / 1.0`` —— 配置缺该字段时
          行为与 feature-005 之前逐条一致（FR-003 的向后兼容）
        - ``settings.yaml`` 交付的是在英文金标上**校准出来的**值

        ⚠️ **本断言刻意不钉死具体数字。** 它原本写作
        ``== {"dense": 1.0, "sparse": 0.1}``，于是 2026-08-25 那次合法的重校准
        （0.1 → 0.75，依据是第一代金标已被推翻）让它变红了 —— 而它想守的从来
        不是「这个值是多少」，是「YAML 的值真的到达了 dataclass，没有静默回落
        成默认值」。钉死数字只会让每一次正当的重校准都要来改测试，
        久了就变成「改测试让它绿」的肌肉记忆。

        `fusion_weights` **本来就是为按语料重校准而存在的旋钮**，
        断言不该假设它不变。
        """
        r = load_settings(_REAL_CONFIG).retrieval
        assert r.rrf_k == 60
        # 键齐、值合法、且**不等于 dataclass 默认值** —— 这三条才是「接上了」的判据
        assert set(r.fusion_weights) == {"dense", "sparse"}
        assert all(v >= 0.0 for v in r.fusion_weights.values())
        assert any(v > 0.0 for v in r.fusion_weights.values())
        assert r.fusion_weights != RetrievalSettings().fusion_weights, (
            "settings.yaml 的权重与 dataclass 默认值相同 —— "
            "无法区分「配置真的被读了」与「静默回落成默认值」"
        )

    def test_dataclass_default_stays_equal_weight(self) -> None:
        """dataclass 默认值必须保持等权 —— 它守的是向后兼容而非推荐值。

        若把校准值写进 dataclass 默认，既有部署（配置里没这个字段）升级后
        行为会**静默改变**。
        """
        assert RetrievalSettings().fusion_weights == {"dense": 1.0, "sparse": 1.0}

    def test_real_config_passes_validation(self) -> None:
        validate_settings(load_settings(_REAL_CONFIG))

    def test_validate_settings_invokes_fusion_checks(self) -> None:
        """融合校验必须挂在 validate_settings 的调用链上,不能只是个孤立函数。"""
        settings = load_settings(_REAL_CONFIG)
        settings.retrieval.rrf_k = 0

        with pytest.raises(SettingsError, match="rrf_k"):
            validate_settings(settings)
