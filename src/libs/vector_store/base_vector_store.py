"""Abstract base class for VectorStore providers.

This module defines the pluggable interface for vector storage backends,
enabling seamless switching between different providers (Chroma, etc.)
through configuration-driven instantiation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseVectorStore(ABC):
    """Abstract base class for VectorStore providers.

    All VectorStore implementations must inherit from this class and implement
    the upsert() and query() methods. This ensures consistent interface across
    different backends (Chroma, etc.).

    Design Principles Applied:
    - Pluggable: Subclasses can be swapped without changing upstream code.
    - Observable: Accepts optional TraceContext for observability integration.
    - Config-Driven: Instances are created via factory based on settings.
    """

    @abstractmethod
    def upsert(
        self,
        records: List[Dict[str, Any]],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        """Upsert records into the vector store.

        Each record is a dict containing at minimum:
        - 'id': str — unique record identifier
        - 'vector': List[float] — the embedding vector
        - 'text': str — the original text content
        - 'metadata': Dict[str, Any] — additional metadata

        Args:
            records: List of record dicts to upsert.
            trace: Optional TraceContext for observability (reserved for Stage F).
            **kwargs: Backend-specific parameters.

        Raises:
            ValueError: If records list is empty or contains invalid entries.
            RuntimeError: If the upsert operation fails.

        Example:
            >>> store.upsert([{
            ...     "id": "chunk_001",
            ...     "vector": [0.1, 0.2, 0.3],
            ...     "text": "Hello world",
            ...     "metadata": {"source": "test.pdf"}
            ... }])
        """
        pass

    @abstractmethod
    def query(
        self,
        vector: List[float],
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Query the vector store for similar vectors.

        Args:
            vector: The query embedding vector.
            top_k: Maximum number of results to return.
            filters: Optional metadata filters to apply.
            trace: Optional TraceContext for observability (reserved for Stage F).
            **kwargs: Backend-specific parameters.

        Returns:
            A list of result dicts, each containing:
            - 'id': str — record identifier
            - 'score': float — similarity score
            - 'text': str — the stored text content
            - 'metadata': Dict[str, Any] — stored metadata

            Results are sorted by score in descending order (most similar first).

        Raises:
            ValueError: If vector is empty or top_k < 1.
            RuntimeError: If the query operation fails.

        Example:
            >>> results = store.query([0.1, 0.2, 0.3], top_k=5)
            >>> results[0]["id"]
            'chunk_001'
            >>> results[0]["score"]
            0.95
        """
        pass

    def validate_records(self, records: List[Dict[str, Any]]) -> None:
        """Validate input records for upsert.

        Args:
            records: List of record dicts to validate.

        Raises:
            ValueError: If records list is empty or records are missing required fields.
        """
        if not records:
            raise ValueError("Records list cannot be empty")

        required_fields = {"id", "vector"}
        for i, record in enumerate(records):
            if not isinstance(record, dict):
                raise ValueError(
                    f"Record at index {i} is not a dict "
                    f"(type: {type(record).__name__})"
                )
            missing = required_fields - set(record.keys())
            if missing:
                raise ValueError(
                    f"Record at index {i} is missing required fields: "
                    f"{sorted(missing)}"
                )

    def validate_query_params(
        self,
        vector: List[float],
        top_k: int,
    ) -> None:
        """Validate query parameters.

        Args:
            vector: The query vector to validate.
            top_k: The top_k value to validate.

        Raises:
            ValueError: If vector is empty or top_k < 1.
        """
        if not vector:
            raise ValueError("Query vector cannot be empty")
        if top_k < 1:
            raise ValueError(
                f"top_k must be at least 1 (got: {top_k})"
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

    @abstractmethod
    def get_by_ids(
        self,
        ids: List[str],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Retrieve records by their IDs.

        This method is required for sparse retrieval (BM25) to fetch
        text and metadata for chunks identified by BM25 query results.

        Args:
            ids: List of chunk IDs to retrieve.
            trace: Optional TraceContext for observability (reserved for Stage F).
            **kwargs: Backend-specific parameters.

        Returns:
            A list of result dicts, each containing:
            - 'id': str — record identifier
            - 'text': str — the stored text content
            - 'metadata': Dict[str, Any] — stored metadata

            Records are returned in the same order as the input IDs.
            Missing IDs are omitted from the results.

        Raises:
            ValueError: If ids list is empty.
            RuntimeError: If the retrieval operation fails.

        Example:
            >>> results = store.get_by_ids(["chunk_001", "chunk_002"])
            >>> results[0]["id"]
            'chunk_001'
            >>> results[0]["text"]
            'Hello world'
        """
        pass

    def get_collection_stats(
        self, collection_name: str | None = None
    ) -> dict[str, Any]:
        """Get statistics for a specific collection or all collections.

        Args:
            collection_name: Name of collection to get stats for.
                If None, returns aggregated stats for all collections.

        Returns:
            Dict with collection statistics:
            - If collection_name is provided: {'name': str, 'count': int}
            - If collection_name is None: {'collections': list, 'total_collections': int, 'total_vectors': int}

        Raises:
            RuntimeError: If operation fails.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement get_collection_stats() method"
        )

    def get_collection_names(self) -> list[str]:
        """Get all collection names in the vector store.

        Returns:
            List of collection names.

        Raises:
            RuntimeError: If operation fails.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement get_collection_names() method"
        )

    def delete(
        self,
        doc_ids: list[str],
        trace: Any | None = None,
        **kwargs: Any,
    ) -> None:
        """Delete records by document IDs.

        Args:
            doc_ids: List of document IDs to delete.
            trace: Optional TraceContext for observability.
            **kwargs: Backend-specific parameters.

        Raises:
            ValueError: If doc_ids is empty.
            RuntimeError: If delete operation fails.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement delete() method"
        )

    def clear_collection(self, collection_name: str) -> None:
        """Clear all records from a collection.

        Args:
            collection_name: Name of the collection to clear.

        Raises:
            RuntimeError: If clear operation fails.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement clear_collection() method"
        )
