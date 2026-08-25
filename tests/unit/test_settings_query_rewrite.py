"""Unit tests for query_rewrite 配置的启动期校验 (T-2.1)。

change: per-route-metrics-and-synonym-rewrite

**为什么这些校验必须在启动期硬失败**：本项目的招牌病是「看起来生效、实际没生效、
而且不报错」。这里两条都是那个病的典型形态：

1. **未知策略静默回落 ``none``** —— 会让「配置写错了」与「刻意关闭」表现完全相同，
   而两者的处置完全相反。
2. **词表缺失时用隐式默认值** —— 重排那次就是这么栽的：兜底成纯英文 ms-marco 模型，
   对中文语料完全无效**且不报错**。

判据一如既往：**「它没生效的时候，我怎么会知道？」**

纯配置校验，不联网、不调用任何模型。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from src.core.settings import (
    VALID_QUERY_REWRITE_STRATEGIES,
    QueryRewriteSettings,
    SettingsError,
    _validate_query_rewrite_settings,
)

pytestmark = pytest.mark.unit


def _write_dict(tmp_path, content, name: str = "synonyms.yaml") -> str:
    path = tmp_path / name
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_text(yaml.safe_dump(content, allow_unicode=True), encoding="utf-8")
    return str(path)


class TestDefaults:
    def test_default_is_disabled(self) -> None:
        """默认必须是关闭 —— 一个默认不启用的能力不该向所有调用方收税。"""
        assert QueryRewriteSettings().strategy == "none"

    def test_default_passes_validation(self) -> None:
        _validate_query_rewrite_settings(QueryRewriteSettings())

    def test_none_does_not_validate_dict(self) -> None:
        """未启用时不校验策略专属资源 —— 词表路径写错也不该影响启动。"""
        cfg = QueryRewriteSettings(strategy="none", synonym_dict="/nope/missing.yaml")

        _validate_query_rewrite_settings(cfg)  # 不抛


class TestStrategyValidation:
    def test_unknown_strategy_rejected(self) -> None:
        """不认识的策略必须报错，**不能静默回落 none**。

        回落会让 typo 与「刻意关闭」长得一模一样。
        """
        cfg = QueryRewriteSettings(strategy="synonyms")  # 多了个 s

        with pytest.raises(SettingsError, match="Invalid query_rewrite.strategy"):
            _validate_query_rewrite_settings(cfg)

    def test_error_lists_supported_strategies(self) -> None:
        cfg = QueryRewriteSettings(strategy="bogus")

        with pytest.raises(SettingsError) as exc:
            _validate_query_rewrite_settings(cfg)

        for name in VALID_QUERY_REWRITE_STRATEGIES:
            assert name in str(exc.value)

    def test_hyde_is_not_a_strategy(self) -> None:
        """``hyde`` 刻意不在枚举里。

        它与 synonym 不在同一层：synonym 改的是查询本身，改完 dense 与 sparse
        仍共享同一个 ``ProcessedQuery``；而 HyDE 要让 dense 拿假想文档、sparse
        拿原始查询，**两路输入不同** —— 那是接口变更，不是加一个枚举值。
        """
        assert "hyde" not in VALID_QUERY_REWRITE_STRATEGIES


class TestSynonymDictValidation:
    def test_empty_path_rejected(self) -> None:
        """启用 synonym 但没给词表 → 报错，且刻意不设隐式默认值。"""
        cfg = QueryRewriteSettings(strategy="synonym", synonym_dict="   ")

        with pytest.raises(SettingsError, match="synonym_dict is required"):
            _validate_query_rewrite_settings(cfg)

    def test_missing_file_rejected(self, tmp_path) -> None:
        cfg = QueryRewriteSettings(
            strategy="synonym", synonym_dict=str(tmp_path / "nope.yaml")
        )

        with pytest.raises(SettingsError, match="not found"):
            _validate_query_rewrite_settings(cfg)

    def test_unparseable_file_rejected(self, tmp_path) -> None:
        """内容坏了与路径错了必须**可区分** —— 两者的处置不同。"""
        path = _write_dict(tmp_path, "止损: [SL,\n  unclosed: [")
        cfg = QueryRewriteSettings(strategy="synonym", synonym_dict=path)

        with pytest.raises(SettingsError, match="not parseable YAML"):
            _validate_query_rewrite_settings(cfg)

    def test_missing_and_unparseable_have_different_messages(self, tmp_path) -> None:
        missing = QueryRewriteSettings(
            strategy="synonym", synonym_dict=str(tmp_path / "nope.yaml")
        )
        broken = QueryRewriteSettings(
            strategy="synonym", synonym_dict=_write_dict(tmp_path, "a: [b,\nc: [")
        )

        with pytest.raises(SettingsError) as missing_exc:
            _validate_query_rewrite_settings(missing)
        with pytest.raises(SettingsError) as broken_exc:
            _validate_query_rewrite_settings(broken)

        assert "not found" in str(missing_exc.value)
        assert "not parseable" in str(broken_exc.value)

    def test_non_mapping_rejected(self, tmp_path) -> None:
        path = _write_dict(tmp_path, ["止损", "点差"])
        cfg = QueryRewriteSettings(strategy="synonym", synonym_dict=path)

        with pytest.raises(SettingsError, match="must contain a mapping"):
            _validate_query_rewrite_settings(cfg)

    def test_non_list_value_rejected(self, tmp_path) -> None:
        """值必须是列表 —— ``止损: SL`` 这种写法要当场拦住。"""
        path = _write_dict(tmp_path, {"止损": "SL"})
        cfg = QueryRewriteSettings(strategy="synonym", synonym_dict=path)

        with pytest.raises(SettingsError, match="must map to a\n?\\s*list of synonyms"):
            _validate_query_rewrite_settings(cfg)

    def test_valid_dict_accepted(self, tmp_path) -> None:
        path = _write_dict(
            tmp_path, {"止损": ["SL", "stop loss"], "点差": ["spread"]}
        )
        cfg = QueryRewriteSettings(strategy="synonym", synonym_dict=path)

        _validate_query_rewrite_settings(cfg)  # 不抛

    def test_empty_yaml_is_accepted(self, tmp_path) -> None:
        """空词表是合法的 —— 它表示「暂时没有条目」，不是配置错误。

        真正的错误是「说要用词表却没给路径」，那条由 test_empty_path_rejected 守。
        """
        path = _write_dict(tmp_path, "")
        cfg = QueryRewriteSettings(strategy="synonym", synonym_dict=path)

        _validate_query_rewrite_settings(cfg)  # 不抛


class TestRaisesSettingsErrorNotValueError:
    """``src/core/settings.py`` 的校验一律抛 ``SettingsError``。

    这是本模块既有的统一约定（``_validate_fusion_settings`` /
    ``_validate_rerank_settings`` 皆然）。写 design 时最容易想当然写成
    ``ValueError``。
    """

    def test_error_type(self) -> None:
        cfg = QueryRewriteSettings(strategy="bogus")

        with pytest.raises(SettingsError):
            _validate_query_rewrite_settings(cfg)

    def test_settings_error_is_not_value_error_subclass_by_accident(self) -> None:
        cfg = replace(QueryRewriteSettings(), strategy="bogus")
        try:
            _validate_query_rewrite_settings(cfg)
        except SettingsError as exc:
            assert isinstance(exc, SettingsError)
        else:  # pragma: no cover - 上面必抛
            pytest.fail("expected SettingsError")


class TestWiredIntoLoadSettings:
    """校验必须真的挂在 ``load_settings()`` 上。

    这条守的是本项目的招牌病：**写了校验函数但没接上**。
    ``question_language_mismatch_warn`` 就是这么成为死配置的 —— 有实现、有单测、
    进了 settings 并被校验取值范围，然后没有任何生产路径调用它。
    """

    def test_load_settings_calls_the_validator(self) -> None:
        import inspect

        from src.core import settings as settings_module

        source = inspect.getsource(settings_module.validate_settings)
        assert "_validate_query_rewrite_settings" in source, (
            "校验函数没有挂进 validate_settings —— 写了但没接上，等于没写"
        )

    def test_yaml_section_is_actually_read(self, tmp_path) -> None:
        """YAML 里的 ``query_rewrite:`` 段必须真的被读进 dataclass。

        **这条是补一个真实事故**（2026-08-25，本变更实施途中）：dataclass 加了、
        校验加了、``settings.yaml`` 也写了 —— 但 ``load_settings()`` 里
        **忘了把这一段接进 ``Settings(...)``**，于是无论 YAML 写什么，
        运行时拿到的都是 dataclass 默认值 ``strategy='none'``。

        更值得记的是：**当时本文件其余 17 条用例全绿**。因为它们都直接构造
        ``QueryRewriteSettings(...)``，**绕过了 YAML 加载这一段**。
        这正是 ``_labeling_method`` 那次的翻版 —— 测了端点，没测那条线。
        """
        import yaml as _yaml

        from src.core.settings import load_settings as _load

        base = _yaml.safe_load(
            (Path("config/settings.yaml")).read_text(encoding="utf-8")
        )
        syn = tmp_path / "syn.yaml"
        syn.write_text("grp: [group]", encoding="utf-8")
        base["query_rewrite"] = {
            "strategy": "synonym",
            "synonym_dict": str(syn),
        }
        cfg = tmp_path / "settings.yaml"
        cfg.write_text(_yaml.safe_dump(base, allow_unicode=True), encoding="utf-8")

        settings = _load(str(cfg))

        assert settings.query_rewrite.strategy == "synonym", (
            "YAML 写的是 synonym 但读出来是默认值 —— "
            "query_rewrite 段没有接进 load_settings()"
        )
        assert settings.query_rewrite.synonym_dict == str(syn)

    def test_missing_section_falls_back_to_defaults(self, tmp_path) -> None:
        """YAML 里没有这一段时用默认值（关闭），且不报错 —— 向后兼容。"""
        import yaml as _yaml

        from src.core.settings import load_settings as _load

        base = _yaml.safe_load(
            (Path("config/settings.yaml")).read_text(encoding="utf-8")
        )
        base.pop("query_rewrite", None)
        cfg = tmp_path / "settings.yaml"
        cfg.write_text(_yaml.safe_dump(base, allow_unicode=True), encoding="utf-8")

        settings = _load(str(cfg))

        assert settings.query_rewrite.strategy == "none"

    def test_real_config_loads(self) -> None:
        """仓库里的 config/settings.yaml 必须能通过校验。"""
        from src.core.settings import load_settings

        settings = load_settings()

        assert settings.query_rewrite.strategy in VALID_QUERY_REWRITE_STRATEGIES
