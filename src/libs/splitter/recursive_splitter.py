"""Recursive Splitter provider implementation.

This module provides a text splitting strategy using LangChain's
RecursiveCharacterTextSplitter, optimized for Markdown structure preservation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.libs.splitter.base_splitter import BaseSplitter
from src.observability.logger import get_logger

if TYPE_CHECKING:
    from src.core.settings import Settings

logger = get_logger(__name__)


class RecursiveSplitter(BaseSplitter):
    """Recursive text splitter implementation.

    Wraps LangChain's RecursiveCharacterTextSplitter with Markdown-aware
    separators to preserve document structure (headers, code blocks, lists, etc.).

    Design Principles Applied:
    - Pluggable: Implements BaseSplitter interface for seamless swapping.
    - Config-Driven: chunk_size and chunk_overlap from settings.
    - Fail-Fast: Validates input text using base class validate_text().
    - Observable: Logs splitting operations and accepts TraceContext.
    """

    # Markdown-aware separators (ordered by priority)
    DEFAULT_SEPARATORS = [
        "\n## ",      # Secondary headers
        "\n### ",     # Tertiary headers
        "\n\n",       # Paragraphs
        "\n",         # Lines
        ". ",         # Sentences
        " ",          # Words
        "",           # Characters
    ]

    def __init__(self, settings: Settings, **kwargs: Any):
        """Initialize Recursive Splitter.

        Args:
            settings: Application settings containing Splitter configuration.
            **kwargs: Optional overrides (chunk_size, chunk_overlap, separators).

        Raises:
            ValueError: If chunk_size or chunk_overlap is invalid.
        """
        # Load configuration from settings
        self._chunk_size = kwargs.get("chunk_size", settings.splitter.chunk_size)
        self._chunk_overlap = kwargs.get(
            "chunk_overlap", settings.splitter.chunk_overlap
        )
        self._separators = kwargs.get("separators", self.DEFAULT_SEPARATORS)

        # Validate configuration
        if self._chunk_size <= 0:
            raise ValueError(
                f"chunk_size must be positive (got: {self._chunk_size})"
            )
        if self._chunk_overlap < 0:
            raise ValueError(
                f"chunk_overlap cannot be negative (got: {self._chunk_overlap})"
            )
        if self._chunk_overlap >= self._chunk_size:
            raise ValueError(
                f"chunk_overlap ({self._chunk_overlap}) must be less than "
                f"chunk_size ({self._chunk_size})"
            )

        # Initialize LangChain splitter
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=self._chunk_size,
            chunk_overlap=self._chunk_overlap,
            separators=self._separators,
            length_function=len,
            is_separator_regex=False,
        )

        logger.info(
            f"RecursiveSplitter initialized: chunk_size={self._chunk_size}, "
            f"chunk_overlap={self._chunk_overlap}, "
            f"separators={len(self._separators)} configured"
        )

    def split_text(
        self,
        text: str,
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[str]:
        """Split text into chunks using recursive strategy.

        Args:
            text: The text string to split. Must be non-empty.
            trace: Optional TraceContext for observability (reserved for Stage F).
            **kwargs: Runtime parameter overrides (chunk_size, chunk_overlap, separators).

        Returns:
            A list of text chunks. Each chunk is a non-empty string.

        Raises:
            ValueError: If text is empty or not a string.
            RuntimeError: If the splitting operation fails.

        Example:
            >>> splitter = RecursiveSplitter(settings)
            >>> chunks = splitter.split_text("# Title\\n\\nContent here.")
            >>> len(chunks) >= 1
            True
        """
        # Validate input text
        self.validate_text(text)

        # Handle runtime parameter overrides
        if kwargs:
            # Create temporary splitter with overridden parameters
            chunk_size = kwargs.get("chunk_size", self._chunk_size)
            chunk_overlap = kwargs.get("chunk_overlap", self._chunk_overlap)
            separators = kwargs.get("separators", self._separators)

            temp_splitter = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separators=separators,
                length_function=len,
                is_separator_regex=False,
            )
            splitter_to_use = temp_splitter
            logger.debug(
                f"Using runtime overrides: chunk_size={chunk_size}, "
                f"chunk_overlap={chunk_overlap}"
            )
        else:
            splitter_to_use = self._splitter

        try:
            # Perform splitting
            chunks = splitter_to_use.split_text(text)

            # Log splitting results
            chunk_count = len(chunks)
            avg_length = sum(len(c) for c in chunks) // chunk_count if chunk_count else 0
            logger.debug(
                f"Split text into {chunk_count} chunks "
                f"(avg length: {avg_length} chars, input: {len(text)} chars)"
            )

            # Record trace if provided (reserved for Phase F)
            if trace:
                trace.record_stage(
                    "split",
                    method="recursive",
                    provider="langchain",
                    chunk_count=chunk_count,
                    avg_chunk_length=avg_length,
                    input_length=len(text),
                )

            return chunks

        except Exception as e:
            error_msg = (
                f"Failed to split text using RecursiveSplitter: {str(e)} "
                f"(input length: {len(text)}, chunk_size: {self._chunk_size})"
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    def get_strategy_name(self) -> str:
        """Get the splitting strategy name.

        Returns:
            The strategy identifier string "recursive".
        """
        return "recursive"

    def get_chunk_size(self) -> int:
        """Get the configured chunk size.

        Returns:
            The maximum chunk size in characters.
        """
        return self._chunk_size

    def get_chunk_overlap(self) -> int:
        """Get the configured chunk overlap.

        Returns:
            The overlap size in characters between consecutive chunks.
        """
        return self._chunk_overlap
