"""Factory for creating Splitter provider instances.

This module implements the Factory Pattern to instantiate the appropriate
Splitter strategy based on configuration, enabling configuration-driven
selection of different backends without code changes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.libs.splitter.base_splitter import BaseSplitter

if TYPE_CHECKING:
    from src.core.settings import Settings


class SplitterFactory:
    """Factory for creating Splitter provider instances.

    This factory reads the strategy configuration from settings and instantiates
    the corresponding Splitter implementation. Supported strategies: recursive,
    semantic, fixed, and more to be added in subsequent tasks.

    Design Principles Applied:
    - Factory Pattern: Centralizes object creation logic.
    - Config-Driven: Strategy selection based on settings.yaml.
    - Fail-Fast: Raises clear errors for unknown strategies.
    """

    # Registry of supported strategies
    _PROVIDERS: dict[str, type[BaseSplitter]] = {}

    @classmethod
    def register_provider(
        cls,
        name: str,
        provider_class: type[BaseSplitter],
    ) -> None:
        """Register a new Splitter strategy implementation.

        This method allows strategy implementations to register themselves
        with the factory, supporting extensibility.

        Args:
            name: The strategy identifier (e.g., 'recursive', 'semantic', 'fixed').
            provider_class: The BaseSplitter subclass implementing the strategy.

        Raises:
            ValueError: If provider_class doesn't inherit from BaseSplitter.
        """
        if not issubclass(provider_class, BaseSplitter):
            raise ValueError(
                f"Provider class {provider_class.__name__} "
                f"must inherit from BaseSplitter"
            )
        cls._PROVIDERS[name.lower()] = provider_class

    @classmethod
    def create(cls, settings: Settings, **override_kwargs: Any) -> BaseSplitter:
        """Create a Splitter instance based on configuration.

        Args:
            settings: The application settings containing Splitter configuration.
            **override_kwargs: Optional parameters to override config values.

        Returns:
            An instance of the configured Splitter strategy.

        Raises:
            ValueError: If the configured strategy is not supported.
            AttributeError: If required configuration fields are missing.

        Example:
            >>> settings = Settings.load('config/settings.yaml')
            >>> splitter = SplitterFactory.create(settings)
            >>> chunks = splitter.split_text("Hello world.")
        """
        # Extract strategy name from settings
        try:
            strategy_name = settings.splitter.strategy.lower()
        except AttributeError as e:
            raise ValueError(
                "Missing required configuration: settings.splitter.strategy. "
                "Please ensure 'splitter.strategy' is specified in settings.yaml"
            ) from e

        # Look up strategy class in registry
        provider_class = cls._PROVIDERS.get(strategy_name)

        if provider_class is None:
            available = (
                ", ".join(sorted(cls._PROVIDERS.keys()))
                if cls._PROVIDERS
                else "none"
            )
            raise ValueError(
                f"Unsupported Splitter strategy: '{strategy_name}'. "
                f"Available strategies: {available}"
            )

        # Instantiate the strategy
        try:
            return provider_class(settings=settings, **override_kwargs)
        except Exception as e:
            raise RuntimeError(
                f"Failed to instantiate Splitter strategy "
                f"'{strategy_name}': {e}"
            ) from e

    @classmethod
    def list_providers(cls) -> list[str]:
        """List all registered strategy names.

        Returns:
            Sorted list of available strategy identifiers.
        """
        return sorted(cls._PROVIDERS.keys())


# Auto-register providers on module import
def _register_builtin_providers() -> None:
    """Register built-in Splitter strategies with the factory."""
    try:
        from src.libs.splitter.recursive_splitter import RecursiveSplitter

        SplitterFactory.register_provider("recursive", RecursiveSplitter)
    except ImportError:
        pass  # Recursive splitter not available yet


# Register providers when module is imported
_register_builtin_providers()
