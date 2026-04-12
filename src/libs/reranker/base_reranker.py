"""Abstract base class for Reranker providers.

This module defines the pluggable interface for reranking backends,
enabling seamless switching between different strategies (LLM-based,
Cross-Encoder, None/passthrough) through configuration-driven instantiation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseReranker(ABC):
    """Abstract base class for Reranker providers.

    All Reranker implementations must inherit from this class and implement
    the rerank() method. This ensures consistent interface across different
    backends (LLM, Cross-Encoder, None, etc.).

    Design Principles Applied:
    - Pluggable: Subclasses can be swapped without changing upstream code.
    - Observable: Accepts optional TraceContext for observability integration.
    - Config-Driven: Instances are created via factory based on settings.
    """

    @abstractmethod
    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Rerank a list of candidates based on relevance to the query.

        Each candidate is a dict containing at minimum:
        - 'id': str — unique identifier
        - 'text': str — the text content to evaluate
        - 'score': float — the original retrieval score

        The returned list preserves the same dict structure but reorders
        and may update the 'score' field.

        Args:
            query: The original query text.
            candidates: List of candidate dicts to rerank.
            trace: Optional TraceContext for observability (reserved for Stage F).
            **kwargs: Backend-specific parameters.

        Returns:
            A list of candidate dicts, reranked by relevance (most relevant first).
            Each dict retains its original fields but may have updated scores.

        Raises:
            ValueError: If query is empty or candidates list is invalid.
            RuntimeError: If the reranking operation fails.

        Example:
            >>> ranked = reranker.rerank("What is RAG?", [
            ...     {"id": "1", "text": "RAG is...", "score": 0.8},
            ...     {"id": "2", "text": "Unrelated", "score": 0.9},
            ... ])
            >>> ranked[0]["id"]
            '1'
        """
        pass

    def validate_inputs(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
    ) -> None:
        """Validate reranking inputs.

        Args:
            query: The query string to validate.
            candidates: The candidates list to validate.

        Raises:
            ValueError: If query is empty or candidates are invalid.
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query must be a non-empty string")
        if not candidates:
            raise ValueError("Candidates list cannot be empty")
        required_fields = {"id", "text", "score"}
        for i, candidate in enumerate(candidates):
            if not isinstance(candidate, dict):
                raise ValueError(
                    f"Candidate at index {i} is not a dict "
                    f"(type: {type(candidate).__name__})"
                )
            missing_fields = required_fields - set(candidate.keys())
            if missing_fields:
                raise ValueError(
                    f"Candidate at index {i} is missing required fields: "
                    f"{sorted(missing_fields)}"
                )

    def get_backend_name(self) -> str:
        """Get the backend name used by this provider.

        Returns:
            The backend identifier string.

        Raises:
            NotImplementedError: If the subclass doesn't override this method.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement get_backend_name() method"
        )


class NoneReranker(BaseReranker):
    """Passthrough reranker that preserves the original candidate order.

    Used as a default fallback when no reranking is configured or when
    the reranking backend is unavailable.
    """

    def __init__(self, settings: Any = None, **kwargs: Any):
        """Initialize NoneReranker.

        Args:
            settings: Optional settings (unused).
            **kwargs: Additional parameters (unused).
        """
        self.settings = settings

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Return candidates in their original order without modification."""
        self.validate_inputs(query, candidates)
        return list(candidates)

    def get_backend_name(self) -> str:
        """Return 'none' as the backend name."""
        return "none"
