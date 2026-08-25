"""查询改写器工厂 —— 按配置选择策略，调用方不感知具体实现。

与 ``LLMFactory`` / ``RerankerFactory`` 同构：注册表 + ``create()``。
业务代码（``src/core/``）只经这里拿改写器，不 import 任何具体实现，
也不出现 ``if strategy == "synonym"`` 这类分支（宪法原则一）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.libs.query_rewriter.base_query_rewriter import (
    BaseQueryRewriter,
    NoneQueryRewriter,
)

if TYPE_CHECKING:
    from src.core.settings import Settings


class QueryRewriterFactory:
    """按 ``settings.query_rewrite.strategy`` 创建改写器。"""

    _PROVIDERS: dict[str, type[BaseQueryRewriter]] = {}

    @classmethod
    def register_provider(
        cls, name: str, provider_class: type[BaseQueryRewriter]
    ) -> None:
        """注册一个改写策略实现。

        Args:
            name: 策略标识（对应 ``query_rewrite.strategy`` 的取值）。
            provider_class: ``BaseQueryRewriter`` 的子类。

        Raises:
            ValueError: provider_class 不是 BaseQueryRewriter 的子类。
        """
        if not issubclass(provider_class, BaseQueryRewriter):
            raise ValueError(
                f"Provider class {provider_class.__name__} "
                "must inherit from BaseQueryRewriter"
            )
        cls._PROVIDERS[name.lower()] = provider_class

    @classmethod
    def create(cls, settings: "Settings", **override_kwargs: Any) -> BaseQueryRewriter:
        """按配置创建改写器。

        Args:
            settings: 应用配置。
            **override_kwargs: 透传给实现（供测试覆盖词表路径等）。

        Returns:
            对应策略的改写器实例。``strategy: none`` 时返回
            :class:`NoneQueryRewriter` —— **不返回 None**，这样调用点不必写
            ``if rewriter is not None``，关闭与启用走同一条代码路径。

        Raises:
            ValueError: 策略未注册。正常情况下 ``load_settings()`` 已在启动期
                挡住未知策略；这里是防止绕过配置直接调用的情形。
        """
        strategy = str(settings.query_rewrite.strategy).lower()
        provider_class = cls._PROVIDERS.get(strategy)
        if provider_class is None:
            available = ", ".join(sorted(cls._PROVIDERS)) or "none registered"
            raise ValueError(
                f"Unsupported query rewrite strategy: {strategy!r}. "
                f"Available strategies: {available}"
            )
        return provider_class(settings=settings, **override_kwargs)

    @classmethod
    def list_providers(cls) -> list[str]:
        """已注册的策略名（排序后）。"""
        return sorted(cls._PROVIDERS)


def _register_builtin_providers() -> None:
    """注册内置策略。

    import 放在函数内是既有约定：让「某个实现的依赖装不上」只影响该实现，
    不至于连工厂本身都 import 不进来。
    """
    QueryRewriterFactory.register_provider("none", NoneQueryRewriter)

    from src.libs.query_rewriter.synonym_query_rewriter import SynonymQueryRewriter

    QueryRewriterFactory.register_provider("synonym", SynonymQueryRewriter)


_register_builtin_providers()
