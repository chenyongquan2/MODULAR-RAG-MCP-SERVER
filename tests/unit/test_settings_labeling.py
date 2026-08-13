"""Unit tests for `evaluation.labeling` / `evaluation.labeling_llm` 配置与校验。

change: retriever-agnostic-golden-labels (T-1.1)

测试范围:

1. 新字段默认值,以及既有 evaluation 字段不受影响
2. ``_validate_labeling_settings`` 的通过与拒绝两侧
3. **至少两路池化**这条最关键的校验(单路池化会静默退化成第一代做法)
4. ``LabelingLLMSettings`` 的 is_enabled 语义与密钥不入 repr
5. 向后兼容:``settings.yaml`` 不含新段时仍能加载并通过校验
6. 校验挂在 ``validate_settings`` 调用链上

背景:第一代金标的 ``expected_chunk_ids`` 由纯 dense top-5 回填,标准答案就是
「embedding 认为最像答案的那几条」,导致所有召回类指标锚定 dense 一路。
2026-08-13 重排 A/B 实测 MRR 0.4914 → 0.3668,而集成测试里同一模型每次都能把
故意放末位的相关段落提到首位 —— 模型在做正确的事,指标却在跌。

不触发任何 LLM 调用。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.core.settings import (
    LabelingLLMSettings,
    LabelingSettings,
    SettingsError,
    _validate_labeling_settings,
    load_settings,
    validate_settings,
)

pytestmark = pytest.mark.unit


_REAL_CONFIG = "config/settings.yaml"


class TestDefaults:
    """默认值。"""

    def test_pool_defaults_enable_dense_and_sparse(self) -> None:
        """默认启用 dense + sparse 两路,满足「至少两路」。"""
        s = LabelingSettings()
        assert s.pool_top_n_dense == 20
        assert s.pool_top_n_sparse == 20

    def test_rerank_route_disabled_by_default(self) -> None:
        """重排路默认关闭 —— 重排依赖是 optional extra,核心安装即可标注。"""
        assert LabelingSettings().pool_top_n_rerank == 0

    def test_threshold_and_limits(self) -> None:
        s = LabelingSettings()
        assert s.relevance_threshold == 2  # 「部分支撑」及以上纳入
        assert s.max_judgements == 2000
        assert s.judge_failure_warn_ratio == 0.10
        assert s.dense_overlap_warn == 0.90
        assert s.human_agreement_warn == 0.80

    def test_default_config_passes_validation(self) -> None:
        _validate_labeling_settings(LabelingSettings())


class TestAtLeastTwoRoutes:
    """**本文件最重要的一组** —— 单路池化必须被拒绝。

    若只有一路 > 0,候选池完全由那一路决定,那条路径永远「全对」,其他路径找到
    的正确结果连进入标准答案的机会都没有。这正是第一代纯 dense top-5 回填造成
    的偏差,本变更的全部意义就在于消除它。**只配一路等于把新方法退化成旧方法,
    而且不会有任何报错** —— 属宪法原则三要防的静默失效。
    """

    @pytest.mark.parametrize(
        "dense,sparse,rerank",
        [
            (20, 0, 0),   # 只有 dense —— 等价于第一代
            (0, 20, 0),   # 只有 sparse
            (0, 0, 20),   # 只有 rerank
        ],
    )
    def test_single_route_rejected(self, dense: int, sparse: int, rerank: int) -> None:
        with pytest.raises(SettingsError, match="at least TWO retrieval routes"):
            _validate_labeling_settings(
                LabelingSettings(
                    pool_top_n_dense=dense,
                    pool_top_n_sparse=sparse,
                    pool_top_n_rerank=rerank,
                )
            )

    def test_zero_routes_rejected(self) -> None:
        with pytest.raises(SettingsError, match="at least TWO retrieval routes"):
            _validate_labeling_settings(
                LabelingSettings(
                    pool_top_n_dense=0, pool_top_n_sparse=0, pool_top_n_rerank=0
                )
            )

    @pytest.mark.parametrize(
        "dense,sparse,rerank",
        [
            (20, 20, 0),   # dense + sparse（默认）
            (20, 0, 20),   # dense + rerank
            (0, 20, 20),   # sparse + rerank
            (20, 20, 20),  # 三路全开
            (1, 1, 0),     # 极小值也合法
        ],
    )
    def test_two_or_more_routes_accepted(
        self, dense: int, sparse: int, rerank: int
    ) -> None:
        _validate_labeling_settings(
            LabelingSettings(
                pool_top_n_dense=dense,
                pool_top_n_sparse=sparse,
                pool_top_n_rerank=rerank,
            )
        )

    def test_error_explains_why_not_just_what(self) -> None:
        """错误消息要说明**为什么**,不只是说违规了。

        使用者很可能觉得「我就想只用 dense 快速跑一遍」—— 消息必须让他明白
        那样做等于退回到有偏的旧方法。
        """
        with pytest.raises(SettingsError, match="monopolise"):
            _validate_labeling_settings(
                LabelingSettings(pool_top_n_sparse=0, pool_top_n_rerank=0)
            )


class TestPoolSizeValidation:
    """``pool_top_n_*`` 必须是非负整数。"""

    @pytest.mark.parametrize("bad", [-1, -20])
    def test_negative_rejected(self, bad: int) -> None:
        with pytest.raises(SettingsError, match="pool_top_n_dense"):
            _validate_labeling_settings(LabelingSettings(pool_top_n_dense=bad))

    @pytest.mark.parametrize("bad", ["20", 20.5, None, [20]])
    def test_non_integer_rejected(self, bad: object) -> None:
        with pytest.raises(SettingsError, match="pool_top_n_dense"):
            _validate_labeling_settings(
                LabelingSettings(pool_top_n_dense=bad)  # type: ignore[arg-type]
            )

    def test_bool_rejected(self) -> None:
        """``pool_top_n_dense: true`` 会被当作 1 —— 池子只有 1 条候选。"""
        with pytest.raises(SettingsError, match="pool_top_n_dense"):
            _validate_labeling_settings(
                LabelingSettings(pool_top_n_dense=True)  # type: ignore[arg-type]
            )

    def test_zero_is_legal_as_route_disable(self) -> None:
        """0 合法 —— 它是「关闭该路」的表达方式(前提是仍有两路开着)。"""
        _validate_labeling_settings(
            LabelingSettings(
                pool_top_n_dense=20, pool_top_n_sparse=20, pool_top_n_rerank=0
            )
        )


class TestRelevanceThreshold:
    """``relevance_threshold`` 必须是 1/2/3。"""

    @pytest.mark.parametrize("good", [1, 2, 3])
    def test_valid_grades_accepted(self, good: int) -> None:
        _validate_labeling_settings(LabelingSettings(relevance_threshold=good))

    def test_zero_rejected(self) -> None:
        """0 会让池子里每个候选都成为标准答案 —— 标注彻底失去意义。"""
        with pytest.raises(SettingsError, match="relevance_threshold"):
            _validate_labeling_settings(LabelingSettings(relevance_threshold=0))

    @pytest.mark.parametrize("bad", [4, -1, 2.5, "2", None, True])
    def test_out_of_range_rejected(self, bad: object) -> None:
        with pytest.raises(SettingsError, match="relevance_threshold"):
            _validate_labeling_settings(
                LabelingSettings(relevance_threshold=bad)  # type: ignore[arg-type]
            )

    def test_error_explains_the_grade_scale(self) -> None:
        with pytest.raises(SettingsError, match="directly answers"):
            _validate_labeling_settings(LabelingSettings(relevance_threshold=9))


class TestMaxJudgements:
    """``max_judgements`` 必须是正整数(成本闸门)。"""

    @pytest.mark.parametrize("bad", [0, -1])
    def test_non_positive_rejected(self, bad: int) -> None:
        with pytest.raises(SettingsError, match="max_judgements"):
            _validate_labeling_settings(LabelingSettings(max_judgements=bad))

    @pytest.mark.parametrize("bad", ["2000", 2000.5, None, True])
    def test_non_integer_rejected(self, bad: object) -> None:
        with pytest.raises(SettingsError, match="max_judgements"):
            _validate_labeling_settings(
                LabelingSettings(max_judgements=bad)  # type: ignore[arg-type]
            )

    def test_positive_accepted(self) -> None:
        _validate_labeling_settings(LabelingSettings(max_judgements=1))
        _validate_labeling_settings(LabelingSettings(max_judgements=100000))


class TestRatioFields:
    """三个告警比例必须在 [0, 1]。"""

    @pytest.mark.parametrize(
        "field",
        ["judge_failure_warn_ratio", "dense_overlap_warn", "human_agreement_warn"],
    )
    @pytest.mark.parametrize("bad", [-0.1, 1.1, 2.0])
    def test_out_of_range_rejected(self, field: str, bad: float) -> None:
        with pytest.raises(SettingsError, match=field):
            _validate_labeling_settings(LabelingSettings(**{field: bad}))

    @pytest.mark.parametrize(
        "field",
        ["judge_failure_warn_ratio", "dense_overlap_warn", "human_agreement_warn"],
    )
    @pytest.mark.parametrize("bad", ["0.5", None, True, [0.5]])
    def test_non_numeric_rejected(self, field: str, bad: object) -> None:
        with pytest.raises(SettingsError, match=field):
            _validate_labeling_settings(LabelingSettings(**{field: bad}))

    @pytest.mark.parametrize(
        "field",
        ["judge_failure_warn_ratio", "dense_overlap_warn", "human_agreement_warn"],
    )
    @pytest.mark.parametrize("good", [0.0, 0.5, 1.0, 1])
    def test_boundaries_accepted(self, field: str, good: float) -> None:
        _validate_labeling_settings(LabelingSettings(**{field: good}))


class TestLabelingLLMSettings:
    """判定 LLM 配置。"""

    def test_disabled_by_default(self) -> None:
        """默认空 = 未启用。不做标注的既有用法不该因此启动失败。"""
        assert LabelingLLMSettings().is_enabled() is False

    @pytest.mark.parametrize(
        "provider,model",
        [("", "some-model"), ("glm", ""), ("", ""), ("  ", "  ")],
    )
    def test_partial_config_is_not_enabled(self, provider: str, model: str) -> None:
        assert LabelingLLMSettings(provider=provider, model=model).is_enabled() is False

    def test_both_set_is_enabled(self) -> None:
        assert LabelingLLMSettings(provider="glm", model="glm-4.6").is_enabled() is True

    def test_api_key_not_in_repr(self) -> None:
        """密钥不得进 repr —— dataclass 默认 repr 会把它打进 traceback /
        日志 / pytest 断言输出。本项目实测过一次断言失败泄露完整密钥。
        """
        s = LabelingLLMSettings(provider="glm", model="m", api_key="sk-SECRET-VALUE")
        assert "sk-SECRET-VALUE" not in repr(s)

    def test_has_retry_config(self) -> None:
        """标注要发上千次调用,网关实测常态性超时 —— 必须有重试。"""
        s = LabelingLLMSettings()
        assert s.max_retries == 3
        assert s.request_timeout_sec == 60

    def test_temperature_defaults_to_deterministic(self) -> None:
        """判定应尽量确定,便于复现。"""
        assert LabelingLLMSettings().temperature == 0.0

    def test_max_tokens_is_generous_enough_for_real_chunks(self) -> None:
        """**这条守的是一个实测踩过的坑**(2026-08-13, T-6.1)。

        判定回复的 max_tokens 此前**硬编码 200**,在真实语料上几乎全军覆没:

        | chunk 长度 | max_tokens=200 | max_tokens=800 |
        |---|---|---|
        | 301 字符 | 截断在 JSON 中间 | 完整,解析成功 |
        | 367 字符 | **空响应** | 完整,解析成功 |
        | 430 字符 | **空响应** | 完整,解析成功 |

        预算不足时输出被截断成半个 JSON 或干脆为空,于是每条都标 judge_failed
        —— 表现得像「模型不会遵从 JSON 格式」,真实原因是**没给它写完的余量**。
        本项目真实 chunk 中位约 428 字符,所以 200 是绝对不够的。

        这也是「硬编码可调参数」(违反宪法原则二)的又一个实例 —— 与本变更
        正在修的 dense 锚定、以及重排变更修掉的 batch_size 硬编码同类。
        """
        assert LabelingLLMSettings().max_tokens >= 800

    def test_max_tokens_is_configurable_not_hardcoded(self) -> None:
        """必须能从配置改 —— 换判定模型后余量需求可能不同。"""
        assert LabelingLLMSettings(max_tokens=1500).max_tokens == 1500


class TestSeparateFromScreeningLLM:
    """刻意不复用 ``screening_llm`` —— 两者阈值标度不同,共用会互相干扰。"""

    def test_labeling_llm_is_a_distinct_field(self) -> None:
        e = load_settings(_REAL_CONFIG).evaluation
        assert hasattr(e, "labeling_llm")
        assert hasattr(e, "screening_llm")
        assert e.labeling_llm is not e.screening_llm

    def test_labeling_has_no_keep_drop_thresholds(self) -> None:
        """预筛的 keep/drop 阈值不该出现在标注配置里 —— 那是不同的问题。"""
        s = LabelingSettings()
        assert not hasattr(s, "keep_threshold")
        assert not hasattr(s, "drop_threshold")


class TestBackwardCompatibility:
    """既有配置(不含新段)必须仍能加载 —— 回归保护。"""

    def test_yaml_without_labeling_sections_still_loads(self, tmp_path: Path) -> None:
        raw = yaml.safe_load(Path(_REAL_CONFIG).read_text(encoding="utf-8"))
        raw.setdefault("evaluation", {})
        raw["evaluation"].pop("labeling", None)
        raw["evaluation"].pop("labeling_llm", None)

        cfg = tmp_path / "settings.yaml"
        cfg.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

        settings = load_settings(str(cfg))

        assert settings.evaluation.labeling.pool_top_n_dense == 20
        assert settings.evaluation.labeling_llm.is_enabled() is False
        validate_settings(settings)


class TestRealConfigWiring:
    """settings.yaml 端到端装配。"""

    def test_real_config_passes_validation(self) -> None:
        validate_settings(load_settings(_REAL_CONFIG))

    def test_validate_settings_invokes_labeling_checks(self) -> None:
        """标注校验必须挂在 validate_settings 调用链上,不能只是个孤立函数。"""
        settings = load_settings(_REAL_CONFIG)
        settings.evaluation.labeling.relevance_threshold = 0

        with pytest.raises(SettingsError, match="relevance_threshold"):
            validate_settings(settings)

    def test_validate_settings_catches_single_route(self) -> None:
        settings = load_settings(_REAL_CONFIG)
        settings.evaluation.labeling.pool_top_n_sparse = 0
        settings.evaluation.labeling.pool_top_n_rerank = 0

        with pytest.raises(SettingsError, match="at least TWO retrieval routes"):
            validate_settings(settings)
