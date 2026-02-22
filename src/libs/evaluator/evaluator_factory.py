"""Factory for creating Evaluator provider instances.

This module implements the Factory Pattern to instantiate the appropriate
Evaluator provider based on configuration, enabling configuration-driven
selection of different backends without code changes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.libs.evaluator.base_evaluator import BaseEvaluator

if TYPE_CHECKING:
    from src.core.settings import Settings


class EvaluatorFactory:
    """Factory for creating Evaluator provider instances.

    This factory reads the provider configuration from settings and instantiates
    the corresponding Evaluator implementation. Supported providers: custom,
    Ragas, DeepEval, and more to be added in subsequent tasks.

    Design Principles Applied:
    - Factory Pattern: Centralizes object creation logic.
    - Config-Driven: Provider selection based on settings.yaml.
    - Fail-Fast: Raises clear errors for unknown providers.
    """

    # Registry of supported providers
    _PROVIDERS: dict[str, type[BaseEvaluator]] = {}

    @classmethod
    def register_provider(
        cls,
        name: str,
        provider_class: type[BaseEvaluator],
    ) -> None:
        """Register a new Evaluator provider implementation.

        This method allows provider implementations to register themselves
        with the factory, supporting extensibility.

        Args:
            name: The provider identifier (e.g., 'custom', 'ragas', 'deepeval').
            provider_class: The BaseEvaluator subclass implementing the provider.

        Raises:
            ValueError: If provider_class doesn't inherit from BaseEvaluator.
        """
        if not issubclass(provider_class, BaseEvaluator):
            raise ValueError(
                f"Provider class {provider_class.__name__} "
                f"must inherit from BaseEvaluator"
            )
        cls._PROVIDERS[name.lower()] = provider_class

    @classmethod
    def create(cls, settings: Settings, **override_kwargs: Any) -> BaseEvaluator:
        """Create an Evaluator instance based on configuration.

        Args:
            settings: The application settings containing Evaluator configuration.
            **override_kwargs: Optional parameters to override config values.

        Returns:
            An instance of the configured Evaluator provider.

        Raises:
            ValueError: If the configured provider is not supported.
            AttributeError: If required configuration fields are missing.

        Example:
            >>> settings = Settings.load('config/settings.yaml')
            >>> evaluator = EvaluatorFactory.create(settings)
            >>> metrics = evaluator.evaluate(
            ...     query="test",
            ...     retrieved_ids=["chunk_1"],
            ...     golden_ids=["chunk_1"]
            ... )
        """
        # Extract provider name from settings
        try:
            # Get first backend from list (support for multiple backends in future)
            backends = settings.evaluation.backends
            if not backends:
                raise ValueError(
                    "Missing required configuration: settings.evaluation.backends "
                    "list is empty. Please specify at least one backend."
                )
            provider_name = backends[0].lower()
        except AttributeError as e:
            raise ValueError(
                "Missing required configuration: settings.evaluation.backends. "
                "Please ensure 'evaluation.backends' is specified in settings.yaml"
            ) from e

        # Look up provider class in registry
        provider_class = cls._PROVIDERS.get(provider_name)

        if provider_class is None:
            available = (
                ", ".join(sorted(cls._PROVIDERS.keys()))
                if cls._PROVIDERS
                else "none"
            )
            raise ValueError(
                f"Unsupported Evaluator provider: '{provider_name}'. "
                f"Available providers: {available}"
            )

        # Instantiate the provider
        try:
            return provider_class(settings=settings, **override_kwargs)
        except Exception as e:
            raise RuntimeError(
                f"Failed to instantiate Evaluator provider "
                f"'{provider_name}': {e}"
            ) from e

    @classmethod
    def list_providers(cls) -> list[str]:
        """List all registered provider names.

        Returns:
            Sorted list of available provider identifiers.
        """
        return sorted(cls._PROVIDERS.keys())


# Auto-register providers on module import
def _register_builtin_providers() -> None:
    """Register built-in Evaluator providers with the factory."""
    try:
        from src.libs.evaluator.custom_evaluator import CustomEvaluator

        EvaluatorFactory.register_provider("custom", CustomEvaluator)
    except ImportError:
        pass  # Custom provider not available


# Register providers when module is imported
_register_builtin_providers()
