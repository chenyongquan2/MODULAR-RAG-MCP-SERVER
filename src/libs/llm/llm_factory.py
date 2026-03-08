"""Factory for creating LLM provider instances.

This module implements the Factory Pattern to instantiate the appropriate
LLM provider based on configuration, enabling configuration-driven selection
of different backends without code changes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.libs.llm.base_llm import BaseLLM
from src.libs.llm.base_vision_llm import BaseVisionLLM

if TYPE_CHECKING:
    from src.core.settings import Settings


class LLMFactory:
    """Factory for creating LLM provider instances.

    This factory reads the provider configuration from settings and instantiates
    the corresponding LLM implementation. Supported providers: Azure OpenAI,
    OpenAI, Ollama, DeepSeek, and more to be added in subsequent tasks.

    Design Principles Applied:
    - Factory Pattern: Centralizes object creation logic.
    - Config-Driven: Provider selection based on settings.yaml.
    - Fail-Fast: Raises clear errors for unknown providers.
    """

    # Registry of supported providers
    _PROVIDERS: dict[str, type[BaseLLM]] = {}

    # Registry of supported Vision LLM providers
    _VISION_PROVIDERS: dict[str, type[BaseVisionLLM]] = {}

    @classmethod
    def register_provider(cls, name: str, provider_class: type[BaseLLM]) -> None:
        """Register a new LLM provider implementation.

        This method allows provider implementations to register themselves
        with the factory, supporting extensibility.

        Args:
            name: The provider identifier (e.g., 'openai', 'azure', 'ollama').
            provider_class: The BaseLLM subclass implementing the provider.

        Raises:
            ValueError: If provider_class doesn't inherit from BaseLLM.
        """
        if not issubclass(provider_class, BaseLLM):
            raise ValueError(
                f"Provider class {provider_class.__name__} must inherit from BaseLLM"
            )
        cls._PROVIDERS[name.lower()] = provider_class

    @classmethod
    def register_vision_provider(
        cls, name: str, provider_class: type[BaseVisionLLM]
    ) -> None:
        """Register a new Vision LLM provider implementation.

        This method allows Vision LLM provider implementations to register themselves
        with the factory, supporting extensibility.

        Args:
            name: The provider identifier (e.g., 'azure', 'openai').
            provider_class: The BaseVisionLLM subclass implementing the provider.

        Raises:
            ValueError: If provider_class doesn't inherit from BaseVisionLLM.
        """
        if not issubclass(provider_class, BaseVisionLLM):
            raise ValueError(
                f"Provider class {provider_class.__name__} must inherit from BaseVisionLLM"
            )
        cls._VISION_PROVIDERS[name.lower()] = provider_class

    @classmethod
    def create(cls, settings: Settings, **override_kwargs: Any) -> BaseLLM:
        """Create an LLM instance based on configuration.

        Args:
            settings: The application settings containing LLM configuration.
            **override_kwargs: Optional parameters to override config values.

        Returns:
            An instance of the configured LLM provider.

        Raises:
            ValueError: If the configured provider is not supported.
            AttributeError: If required configuration fields are missing.

        Example:
            >>> settings = Settings.load('config/settings.yaml')
            >>> llm = LLMFactory.create(settings)
            >>> response = llm.chat([{"role": "user", "content": "Hello"}])
        """
        # Extract provider name from settings
        try:
            provider_name = settings.llm.provider.lower()
        except AttributeError as e:
            raise ValueError(
                "Missing required configuration: settings.llm.provider. "
                "Please ensure 'llm.provider' is specified in settings.yaml"
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
                f"Unsupported LLM provider: '{provider_name}'. "
                f"Available providers: {available}"
            )

        # Instantiate the provider
        try:
            return provider_class(settings=settings, **override_kwargs)
        except Exception as e:
            raise RuntimeError(
                f"Failed to instantiate LLM provider '{provider_name}': {e}"
            ) from e

    @classmethod
    def list_providers(cls) -> list[str]:
        """List all registered provider names.

        Returns:
            Sorted list of available provider identifiers.
        """
        return sorted(cls._PROVIDERS.keys())

    @classmethod
    def create_vision_llm(
        cls, settings: Settings, **override_kwargs: Any
    ) -> BaseVisionLLM:
        """Create a Vision LLM instance based on configuration.

        Args:
            settings: The application settings containing Vision LLM configuration.
            **override_kwargs: Optional parameters to override config values.

        Returns:
            An instance of the configured Vision LLM provider.

        Raises:
            ValueError: If the configured provider is not supported.
            AttributeError: If required configuration fields are missing.

        Example:
            >>> settings = Settings.load('config/settings.yaml')
            >>> vision_llm = LLMFactory.create_vision_llm(settings)
            >>> caption = vision_llm.chat_with_image(
            ...     text="Describe this image",
            ...     image="data/images/chart.png"
            ... )
        """
        # Extract provider name from settings (same as regular LLM for now)
        try:
            provider_name = settings.llm.provider.lower()
        except AttributeError as e:
            raise ValueError(
                "Missing required configuration: settings.llm.provider. "
                "Please ensure 'llm.provider' is specified in settings.yaml"
            ) from e

        # Look up provider class in Vision registry
        provider_class = cls._VISION_PROVIDERS.get(provider_name)

        if provider_class is None:
            available = (
                ", ".join(sorted(cls._VISION_PROVIDERS.keys()))
                if cls._VISION_PROVIDERS
                else "none"
            )
            raise ValueError(
                f"Unsupported Vision LLM provider: '{provider_name}'. "
                f"Available Vision providers: {available}"
            )

        # Instantiate the provider
        try:
            return provider_class(settings=settings, **override_kwargs)
        except Exception as e:
            raise RuntimeError(
                f"Failed to instantiate Vision LLM provider '{provider_name}': {e}"
            ) from e

    @classmethod
    def list_vision_providers(cls) -> list[str]:
        """List all registered Vision LLM provider names.

        Returns:
            Sorted list of available Vision provider identifiers.
        """
        return sorted(cls._VISION_PROVIDERS.keys())


# Auto-register providers on module import
def _register_builtin_providers() -> None:
    """Register built-in LLM providers with the factory."""
    try:
        from src.libs.llm.openai_llm import OpenAILLM

        LLMFactory.register_provider("openai", OpenAILLM)
    except ImportError:
        pass  # OpenAI provider not available

    try:
        from src.libs.llm.azure_llm import AzureLLM

        LLMFactory.register_provider("azure", AzureLLM)
    except ImportError:
        pass  # Azure provider not available

    try:
        from src.libs.llm.ollama_llm import OllamaLLM

        LLMFactory.register_provider("ollama", OllamaLLM)
    except ImportError:
        pass  # Ollama provider not available

    try:
        from src.libs.llm.deepseek_llm import DeepSeekLLM

        LLMFactory.register_provider("deepseek", DeepSeekLLM)
    except ImportError:
        pass  # DeepSeek provider not available

    try:
        from src.libs.llm.glm_llm import GLMLLM

        LLMFactory.register_provider("glm", GLMLLM)
    except ImportError:
        pass  # GLM provider not available


def _register_builtin_vision_providers() -> None:
    """Register built-in Vision LLM providers with the factory."""
    try:
        from src.libs.llm.azure_vision_llm import AzureVisionLLM

        LLMFactory.register_vision_provider("azure", AzureVisionLLM)
    except ImportError:
        pass  # Azure Vision provider not available


# Register providers when module is imported
_register_builtin_providers()
_register_builtin_vision_providers()
