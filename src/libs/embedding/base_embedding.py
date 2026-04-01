"""Abstract base class for Embedding providers.

This module defines the pluggable interface for Embedding service providers,
enabling seamless switching between different backends (OpenAI, Azure OpenAI,
Ollama, etc.) through configuration-driven instantiation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List, Optional


class BaseEmbedding(ABC):
    """Abstract base class for Embedding providers.

    All Embedding implementations must inherit from this class and implement
    the embed() method. This ensures consistent interface across different
    providers (OpenAI, Azure OpenAI, Ollama, etc.).

    Design Principles Applied:
    - Pluggable: Subclasses can be swapped without changing upstream code.
    - Observable: Accepts optional TraceContext for observability integration.
    - Config-Driven: Instances are created via factory based on settings.
    """

    @abstractmethod
    def embed(
        self,
        texts: List[str],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[List[float]]:
        """Embed a list of texts into dense vectors.

        Args:
            texts: List of text strings to embed. Must be non-empty.
            trace: Optional TraceContext for observability (reserved for Stage F).
            **kwargs: Provider-specific parameters.

        Returns:
            A list of embedding vectors. Each vector is a list of floats.
            The length of the returned list matches len(texts).
            All vectors have the same dimensionality.

        Raises:
            ValueError: If texts list is empty or contains invalid entries.
            RuntimeError: If the embedding provider call fails.

        Example:
            >>> vectors = embedding.embed(["Hello world", "Foo bar"])
            >>> len(vectors) == 2
            True
            >>> all(isinstance(v, list) for v in vectors)
            True
        """
        pass

    def validate_texts(self, texts: List[str]) -> None:
        """Validate input text list.

        Args:
            texts: List of text strings to validate.

        Raises:
            ValueError: If texts list is empty or contains non-string entries.
        """
        if not texts:
            raise ValueError("Texts list cannot be empty")

        for i, text in enumerate(texts):
            if not isinstance(text, str):
                raise ValueError(
                    f"Text at index {i} is not a string "
                    f"(type: {type(text).__name__})"
                )

    def get_model_name(self) -> str:
        """Get the model name used by this provider.

        Returns:
            The model identifier string.

        Raises:
            NotImplementedError: If the subclass doesn't override this method.

        Note:
            Subclasses should override this method to return their specific model.
            This is useful for logging and observability.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement get_model_name() method"
        )

    def get_dimension(self) -> int:
        """Get the embedding vector dimension.

        Returns:
            The number of dimensions in the embedding vectors.

        Raises:
            NotImplementedError: If the subclass doesn't override this method.

        Note:
            Subclasses should override this method to return the vector dimension.
            This is useful for vector store configuration and validation.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement get_dimension() method"
        )

    def get_max_batch_size(self) -> int:
        """Get the maximum batch size supported by this provider.

        Returns:
            The maximum number of texts that can be embedded in a single API call.
            Default is 100 if not overridden.

        Note:
            Subclasses should override this method to return their specific limit.
            This is useful for BatchProcessor to optimize batch sizing.
        """
        return 100
