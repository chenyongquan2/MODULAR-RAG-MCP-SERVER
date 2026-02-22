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
