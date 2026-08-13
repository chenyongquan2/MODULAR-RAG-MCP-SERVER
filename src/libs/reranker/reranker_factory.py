"""Factory for creating Reranker provider instances.

This module implements the Factory Pattern to instantiate the appropriate
Reranker backend based on configuration, enabling configuration-driven
selection of different strategies without code changes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.libs.reranker.base_reranker import BaseReranker, NoneReranker

if TYPE_CHECKING:
    from src.core.settings import Settings


class RerankerFactory:
    """Factory for creating Reranker provider instances.

    This factory reads the backend configuration from settings and instantiates
    the corresponding Reranker implementation. Supported backends: none, llm,
    cross_encoder, and more to be added in subsequent tasks.

    Design Principles Applied:
    - Factory Pattern: Centralizes object creation logic.
    - Config-Driven: Backend selection based on settings.yaml.
    - Fail-Fast: Raises clear errors for unknown backends.
    """

    # Registry of supported backends
    _PROVIDERS: dict[str, type[BaseReranker]] = {}

    @classmethod
    def register_provider(
        cls,
        name: str,
        provider_class: type[BaseReranker],
    ) -> None:
        """Register a new Reranker backend implementation.

        Args:
            name: The backend identifier (e.g., 'none', 'llm', 'cross_encoder').
            provider_class: The BaseReranker subclass implementing the backend.

        Raises:
            ValueError: If provider_class doesn't inherit from BaseReranker.
        """
        if not issubclass(provider_class, BaseReranker):
            raise ValueError(
                f"Provider class {provider_class.__name__} "
                f"must inherit from BaseReranker"
            )
        cls._PROVIDERS[name.lower()] = provider_class

    @classmethod
    def create(cls, settings: Settings, **override_kwargs: Any) -> BaseReranker:
        """Create a Reranker instance based on configuration.

        Args:
            settings: The application settings containing Reranker configuration.
            **override_kwargs: Optional parameters to override config values.

        Returns:
            An instance of the configured Reranker backend.

        Raises:
            ValueError: If the configured backend is not supported.
            AttributeError: If required configuration fields are missing.

        Example:
            >>> settings = Settings.load('config/settings.yaml')
            >>> reranker = RerankerFactory.create(settings)
            >>> ranked = reranker.rerank("query", candidates)
        """
        # Extract backend name from settings
        try:
            backend_name = settings.rerank.backend.lower()
        except AttributeError as e:
            raise ValueError(
                "Missing required configuration: settings.rerank.backend. "
                "Please ensure 'rerank.backend' is specified in settings.yaml"
            ) from e

        # Look up backend class in registry
        provider_class = cls._PROVIDERS.get(backend_name)

        if provider_class is None:
            available = (
                ", ".join(sorted(cls._PROVIDERS.keys()))
                if cls._PROVIDERS
                else "none registered"
            )
            raise ValueError(
                f"Unsupported Reranker backend: '{backend_name}'. "
                f"Available backends: {available}"
            )

        # Instantiate the backend
        try:
            return provider_class(settings=settings, **override_kwargs)
        except Exception as e:
            raise RuntimeError(
                f"Failed to instantiate Reranker backend "
                f"'{backend_name}': {e}"
            ) from e

    @classmethod
    def list_providers(cls) -> list[str]:
        """List all registered backend names.

        Returns:
            Sorted list of available backend identifiers.
        """
        return sorted(cls._PROVIDERS.keys())

    # 各后端的运行依赖：后端名 -> (import 名, 安装 extra 名)
    # 只有需要额外依赖的后端才登记；'none' 与 'llm' 用的是核心依赖。
    _BACKEND_REQUIREMENTS: dict[str, tuple[str, str]] = {
        "cross_encoder": ("sentence_transformers", "rerank"),
    }

    @classmethod
    def probe_backend(cls, backend: str) -> None:
        """探测某个重排后端在当前环境下是否真的可用（启动期快速失败）。

        为什么需要这个函数（change activate-cross-encoder-rerank T-2.2）：

        重排依赖是 optional extra，用户很可能配了 ``backend: cross_encoder``
        却没跑 ``pip install -e ".[rerank]"``。此前的行为是
        ``CrossEncoderReranker.rerank()`` 捕获 ``ImportError`` 后**返回原序并
        标记降级** —— 用户明确要求了重排，得到的却是一次不报错的普通检索。
        这是最难发现的一类失败：分数变化可以归因于任何环节，排查从这里就
        走错了方向。所以依赖缺失必须在启动期硬失败。

        为什么放在 factory 而不是 ``src/core/settings.py``：
        宪法原则一（provider 无关性）禁止业务代码 import 具体 provider 实现。
        ``importlib.util.find_spec("sentence_transformers")`` 写在 settings 里
        就是把库名硬编码进 ``src/core/``。factory 是唯一允许知道 provider
        细节的地方，所以由它对外提供这个探测能力。

        本函数只检查**依赖是否可导入**，不加载模型权重 —— 权重可能上 GB，
        启动期下载会让服务卡死数分钟。权重获取失败在首次重排时报错，错误
        消息与本函数的区分开（见 ``CrossEncoderReranker.model``）。

        Args:
            backend: 待探测的后端名，如 ``"cross_encoder"``。大小写不敏感。

        Raises:
            ValueError: 后端未注册，或其运行依赖不可导入。调用方
                （``load_settings``）会把它转成 ``SettingsError``。
        """
        name = backend.lower()

        if name not in cls._PROVIDERS:
            available = (
                ", ".join(sorted(cls._PROVIDERS.keys()))
                if cls._PROVIDERS
                else "none registered"
            )
            raise ValueError(
                f"Unsupported Reranker backend: '{name}'. "
                f"Available backends: {available}"
            )

        requirement = cls._BACKEND_REQUIREMENTS.get(name)
        if requirement is None:
            # 该后端不需要额外依赖（none / llm 走核心依赖）
            return

        module_name, extra_name = requirement

        import importlib.util

        if importlib.util.find_spec(module_name) is None:
            raise ValueError(
                f"Reranker backend '{name}' is configured but its runtime "
                f"dependency '{module_name}' is not installed. "
                f'Install it with: pip install -e ".[{extra_name}]"  '
                f"(this is a MISSING DEPENDENCY, not a model download "
                f"failure — model weights are fetched lazily on first rerank)"
            )


# Auto-register providers on module import
def _register_builtin_providers() -> None:
    """Register built-in Reranker backends with the factory."""
    # NoneReranker is always available as the default fallback
    RerankerFactory.register_provider("none", NoneReranker)

    try:
        from src.libs.reranker.llm_reranker import LLMReranker

        RerankerFactory.register_provider("llm", LLMReranker)
    except ImportError:
        pass  # LLM reranker not available yet

    try:
        from src.libs.reranker.cross_encoder_reranker import CrossEncoderReranker

        RerankerFactory.register_provider("cross_encoder", CrossEncoderReranker)
    except ImportError:
        pass  # Cross-encoder reranker not available yet


# Register providers when module is imported
_register_builtin_providers()
