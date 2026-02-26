"""Factory for creating VectorStore provider instances.

This module implements the Factory Pattern to instantiate the appropriate
VectorStore backend based on configuration, enabling configuration-driven
selection of different providers without code changes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.libs.vector_store.base_vector_store import BaseVectorStore

if TYPE_CHECKING:
    from src.core.settings import Settings


class VectorStoreFactory:
    """Factory for creating VectorStore provider instances.

    This factory reads the backend configuration from settings and instantiates
    the corresponding VectorStore implementation. Supported backends: chroma,
    and more to be added in subsequent tasks.

    Design Principles Applied:
    - Factory Pattern: Centralizes object creation logic.
    - Config-Driven: Backend selection based on settings.yaml.
    - Fail-Fast: Raises clear errors for unknown backends.
    """

    # Registry of supported backends
    _PROVIDERS: dict[str, type[BaseVectorStore]] = {}

    @classmethod
    def register_provider(
        cls,
        name: str,
        provider_class: type[BaseVectorStore],
    ) -> None:
        """Register a new VectorStore backend implementation.

        Args:
            name: The backend identifier (e.g., 'chroma').
            provider_class: The BaseVectorStore subclass implementing the backend.

        Raises:
            ValueError: If provider_class doesn't inherit from BaseVectorStore.
        """
        if not issubclass(provider_class, BaseVectorStore):
            raise ValueError(
                f"Provider class {provider_class.__name__} "
                f"must inherit from BaseVectorStore"
            )
        cls._PROVIDERS[name.lower()] = provider_class

    @classmethod
    def create(cls, settings: Settings, **override_kwargs: Any) -> BaseVectorStore:
        """Create a VectorStore instance based on configuration.

        Args:
            settings: The application settings containing VectorStore configuration.
            **override_kwargs: Optional parameters to override config values.

        Returns:
            An instance of the configured VectorStore backend.

        Raises:
            ValueError: If the configured backend is not supported.
            AttributeError: If required configuration fields are missing.

        Example:
            >>> settings = Settings.load('config/settings.yaml')
            >>> store = VectorStoreFactory.create(settings)
            >>> store.upsert([{"id": "1", "vector": [0.1], "text": "hi", "metadata": {}}])
        """
        # Extract backend name from settings
        try:
            backend_name = settings.vector_store.backend.lower()
        except AttributeError as e:
            raise ValueError(
                "Missing required configuration: settings.vector_store.backend. "
                "Please ensure 'vector_store.backend' is specified in settings.yaml"
            ) from e

        # Look up backend class in registry
        provider_class = cls._PROVIDERS.get(backend_name)

        if provider_class is None:
            available = (
                ", ".join(sorted(cls._PROVIDERS.keys()))
                if cls._PROVIDERS
                else "none"
            )
            raise ValueError(
                f"Unsupported VectorStore backend: '{backend_name}'. "
                f"Available backends: {available}"
            )

        # Instantiate the backend
        try:
            return provider_class(settings=settings, **override_kwargs)
        except Exception as e:
            raise RuntimeError(
                f"Failed to instantiate VectorStore backend "
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
    """Register built-in VectorStore backends with the factory."""
    from src.libs.vector_store.chroma_store import ChromaStore

    VectorStoreFactory.register_provider("chroma", ChromaStore)


# Register providers when module is imported
_register_builtin_providers()
