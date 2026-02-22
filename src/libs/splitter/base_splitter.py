"""Abstract base class for Splitter providers.

This module defines the pluggable interface for text splitting strategies,
enabling seamless switching between different backends (Recursive, Semantic,
Fixed, etc.) through configuration-driven instantiation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List, Optional


class BaseSplitter(ABC):
    """Abstract base class for Splitter providers.

    All Splitter implementations must inherit from this class and implement
    the split_text() method. This ensures consistent interface across different
    strategies (Recursive, Semantic, Fixed, etc.).

    Design Principles Applied:
    - Pluggable: Subclasses can be swapped without changing upstream code.
    - Observable: Accepts optional TraceContext for observability integration.
    - Config-Driven: Instances are created via factory based on settings.
    """

    @abstractmethod
    def split_text(
        self,
        text: str,
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[str]:
        """Split a text string into a list of chunks.

        Args:
            text: The text string to split. Must be non-empty.
            trace: Optional TraceContext for observability (reserved for Stage F).
            **kwargs: Strategy-specific parameters.

        Returns:
            A list of text chunks. Each chunk is a non-empty string.

        Raises:
            ValueError: If text is empty or not a string.
            RuntimeError: If the splitting operation fails.

        Example:
            >>> chunks = splitter.split_text("Hello world. Foo bar baz.")
            >>> isinstance(chunks, list)
            True
            >>> all(isinstance(c, str) for c in chunks)
            True
        """
        pass

    def validate_text(self, text: str) -> None:
        """Validate input text.

        Args:
            text: The text string to validate.

        Raises:
            ValueError: If text is not a non-empty string.
        """
        if not isinstance(text, str):
            raise ValueError(
                f"Text must be a string (type: {type(text).__name__})"
            )
        if not text.strip():
            raise ValueError("Text cannot be empty or whitespace-only")

    def get_strategy_name(self) -> str:
        """Get the splitting strategy name used by this provider.

        Returns:
            The strategy identifier string.

        Raises:
            NotImplementedError: If the subclass doesn't override this method.

        Note:
            Subclasses should override this method to return their specific strategy.
            This is useful for logging and observability.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement get_strategy_name() method"
        )

    def get_chunk_size(self) -> int:
        """Get the configured chunk size.

        Returns:
            The maximum chunk size in characters.

        Raises:
            NotImplementedError: If the subclass doesn't override this method.

        Note:
            Subclasses should override this method to return the configured chunk size.
            This is useful for validation and observability.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement get_chunk_size() method"
        )

    def get_chunk_overlap(self) -> int:
        """Get the configured chunk overlap.

        Returns:
            The overlap size in characters between consecutive chunks.

        Raises:
            NotImplementedError: If the subclass doesn't override this method.

        Note:
            Subclasses should override this method to return the configured overlap.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement get_chunk_overlap() method"
        )
