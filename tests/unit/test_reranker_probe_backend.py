"""Unit tests for `RerankerFactory.probe_backend` 与启动期依赖探测。

change: activate-cross-encoder-rerank (T-2.2)

测试范围:

1. ``probe_backend`` 对未注册后端、不需额外依赖的后端、依赖缺失的后端的行为
2. 错误消息必须能**区分**「依赖缺失」与「权重获取失败」两种原因
3. ``load_settings`` / ``validate_settings`` 调用链上真的挂了探测
4. ``backend: none`` 时不做探测(默认配置不该为此加载 factory 及其重依赖链)
5. 宪法原则一回归:``src/core/`` 不得出现具体库名

为什么需要这一层:重排依赖是 optional extra,用户很可能配了
``backend: cross_encoder`` 却没装依赖。此前的行为是运行期捕获 ``ImportError``
后返回原序并标记降级 —— 用户以为重排在跑,实际拿到一次不报错的普通检索。

不触发任何模型加载。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

from src.core.settings import (
    RerankSettings,
    SettingsError,
    _probe_rerank_backend,
    load_settings,
    validate_settings,
)
from src.libs.reranker.reranker_factory import RerankerFactory

pytestmark = pytest.mark.unit


_REAL_CONFIG = "config/settings.yaml"
_SETTINGS_SOURCE = Path("src/core/settings.py")


class TestProbeUnknownBackend:
    """未注册的后端必须被拒绝。"""

    @pytest.mark.parametrize("bad", ["cohere", "jina", "voyage"])
    def test_unknown_backend_rejected(self, bad: str) -> None:
        with pytest.raises(ValueError, match="Unsupported Reranker backend"):
            RerankerFactory.probe_backend(bad)

    def test_error_lists_available_backends(self) -> None:
        with pytest.raises(ValueError, match="cross_encoder"):
            RerankerFactory.probe_backend("cohere")


class TestProbeBackendsWithoutExtraDeps:
    """``none`` 与 ``llm`` 走核心依赖,探测必须直接通过。"""

    @pytest.mark.parametrize("backend", ["none", "llm"])
    def test_core_dependency_backends_pass(self, backend: str) -> None:
        RerankerFactory.probe_backend(backend)

    def test_case_insensitive(self) -> None:
        """后端名大小写不敏感 —— 与 factory.create 的行为保持一致。"""
        RerankerFactory.probe_backend("NONE")
        RerankerFactory.probe_backend("Cross_Encoder")


class TestProbeMissingDependency:
    """依赖缺失时必须抛错并给出可执行的安装命令。"""

    def _simulate_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """让 find_spec 对 sentence_transformers 返回 None,模拟未安装。"""
        real_find_spec = importlib.util.find_spec

        def fake_find_spec(name: str, package: object = None) -> object:
            if name == "sentence_transformers":
                return None
            return real_find_spec(name, package)  # type: ignore[arg-type]

        monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

    def test_missing_dependency_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._simulate_missing(monkeypatch)
        with pytest.raises(ValueError, match="sentence_transformers"):
            RerankerFactory.probe_backend("cross_encoder")

    def test_error_carries_install_command(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """消息里要有能直接照抄的命令 —— 用户是学习者,不该让他去猜 extra 名。"""
        self._simulate_missing(monkeypatch)
        with pytest.raises(ValueError, match=r'pip install -e "\.\[rerank\]"'):
            RerankerFactory.probe_backend("cross_encoder")

    def test_error_distinguishes_from_weight_fetch_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """必须明说这是「依赖缺失」而非「权重下载失败」。

        两者的修法完全不同(装包 vs 配镜像),消息混在一起会让排查走弯路。
        对应的另一侧在 ``CrossEncoderReranker.model`` 的 RuntimeError 分支。
        """
        self._simulate_missing(monkeypatch)
        with pytest.raises(ValueError, match="MISSING DEPENDENCY"):
            RerankerFactory.probe_backend("cross_encoder")

    def test_llm_backend_unaffected_by_missing_sentence_transformers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``llm`` 后端不依赖 sentence-transformers,不能被连带误伤。"""
        self._simulate_missing(monkeypatch)
        RerankerFactory.probe_backend("llm")


class TestWeightFetchFailureMessage:
    """「权重获取失败」这一侧的消息(与依赖缺失区分开)。"""

    def test_model_load_failure_mentions_mirror(self) -> None:
        from unittest.mock import Mock, patch

        from src.core.settings import Settings
        from src.libs.reranker.cross_encoder_reranker import CrossEncoderReranker

        settings = Mock(spec=Settings)
        settings.rerank = Mock()
        settings.rerank.model = "BAAI/bge-reranker-base"

        reranker = CrossEncoderReranker(settings=settings)

        fake_module = Mock()
        fake_module.CrossEncoder = Mock(side_effect=OSError("connection refused"))

        with patch.dict("sys.modules", {"sentence_transformers": fake_module}):
            with pytest.raises(RuntimeError, match="HF_ENDPOINT"):
                _ = reranker.model

    def test_model_load_failure_says_it_is_not_a_missing_dependency(self) -> None:
        from unittest.mock import Mock, patch

        from src.core.settings import Settings
        from src.libs.reranker.cross_encoder_reranker import CrossEncoderReranker

        settings = Mock(spec=Settings)
        settings.rerank = Mock()
        settings.rerank.model = "BAAI/bge-reranker-base"

        reranker = CrossEncoderReranker(settings=settings)

        fake_module = Mock()
        fake_module.CrossEncoder = Mock(side_effect=OSError("connection refused"))

        with patch.dict("sys.modules", {"sentence_transformers": fake_module}):
            with pytest.raises(RuntimeError, match="not a missing"):
                _ = reranker.model


class TestSettingsIntegration:
    """探测必须真的挂在配置校验链上。"""

    def test_none_backend_skips_probe(self) -> None:
        """``backend: none`` 不探测 —— 默认配置不该为此加载重依赖链。"""
        _probe_rerank_backend(RerankSettings(backend="none"))

    def test_probe_failure_becomes_settings_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """factory 抛 ValueError,settings 层统一转成 SettingsError。

        调用方(main.py / scripts/)只需处理一种配置异常类型。
        """
        def boom(backend: str) -> None:
            raise ValueError("simulated probe failure")

        monkeypatch.setattr(RerankerFactory, "probe_backend", boom)

        with pytest.raises(SettingsError, match="simulated probe failure"):
            _probe_rerank_backend(
                RerankSettings(backend="cross_encoder", model="BAAI/bge-reranker-base")
            )

    def test_original_cause_preserved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``from e`` 保留原因链 —— 这不是「吞掉异常」。"""
        def boom(backend: str) -> None:
            raise ValueError("root cause here")

        monkeypatch.setattr(RerankerFactory, "probe_backend", boom)

        with pytest.raises(SettingsError) as excinfo:
            _probe_rerank_backend(
                RerankSettings(backend="cross_encoder", model="BAAI/bge-reranker-base")
            )
        assert isinstance(excinfo.value.__cause__, ValueError)

    def test_validate_settings_invokes_probe(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """校验链上真的调了探测,不是个孤立函数。"""
        calls: list[str] = []

        def spy(backend: str) -> None:
            calls.append(backend)

        monkeypatch.setattr(RerankerFactory, "probe_backend", spy)

        settings = load_settings(_REAL_CONFIG)
        settings.rerank.backend = "cross_encoder"
        settings.rerank.model = "BAAI/bge-reranker-base"
        validate_settings(settings)

        assert calls == ["cross_encoder"]

    def test_real_config_still_validates(self) -> None:
        """交付的默认配置(backend: none)必须仍能通过校验。"""
        validate_settings(load_settings(_REAL_CONFIG))

    def test_missing_dependency_blocks_startup_end_to_end(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """本变更的核心场景:配了重排却没装依赖 → 启动期直接失败。

        对照此前的行为:服务正常起来,查询正常返回,只是重排静默没生效。
        """
        real_find_spec = importlib.util.find_spec

        def fake_find_spec(name: str, package: object = None) -> object:
            if name == "sentence_transformers":
                return None
            return real_find_spec(name, package)  # type: ignore[arg-type]

        monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

        raw = yaml.safe_load(Path(_REAL_CONFIG).read_text(encoding="utf-8"))
        raw.setdefault("rerank", {})
        raw["rerank"]["backend"] = "cross_encoder"
        raw["rerank"]["model"] = "BAAI/bge-reranker-base"

        cfg = tmp_path / "settings.yaml"
        cfg.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

        with pytest.raises(SettingsError, match="rerank.backend"):
            validate_settings(load_settings(str(cfg)))


class TestProviderAgnosticism:
    """宪法原则一回归:具体库名不得出现在 ``src/core/``。"""

    def test_settings_module_does_not_depend_on_the_library(self) -> None:
        """``src/core/settings.py`` 不得对 sentence_transformers 产生代码依赖。

        这是把探测放进 factory 而非 settings 的**唯一理由**。若有人图省事在
        settings 里直接 ``find_spec("sentence_transformers")``,本测试会挡住
        —— 那等于把 provider 名硬编码进业务层,项目的核心价值(换 provider
        只改配置)就破了。

        守的是**代码依赖**而非字面出现:注释与 docstring 里提到库名是允许的
        (对学习者是有用信息),用 AST 把注释和字符串排除后再检查。
        """
        import ast

        tree = ast.parse(_SETTINGS_SOURCE.read_text(encoding="utf-8"))

        # 1) 不得有任何形式的 import
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("sentence_transformers"), (
                        f"src/core/settings.py 直接 import 了 {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("sentence_transformers"), (
                    f"src/core/settings.py 直接 from-import 了 {node.module}"
                )

        # 2) 不得把库名作为字符串字面量传给函数(挡住 find_spec / importlib)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        assert "sentence_transformers" not in arg.value, (
                            "src/core/settings.py 把 sentence_transformers 作为"
                            "参数传给了某个调用 —— 依赖探测应委托给 "
                            "RerankerFactory.probe_backend"
                        )

    def test_requirements_table_lives_in_factory(self) -> None:
        """依赖映射表归 factory —— 新增后端时只改这一处。"""
        assert "cross_encoder" in RerankerFactory._BACKEND_REQUIREMENTS
        module_name, extra_name = RerankerFactory._BACKEND_REQUIREMENTS["cross_encoder"]
        assert module_name == "sentence_transformers"
        assert extra_name == "rerank"
