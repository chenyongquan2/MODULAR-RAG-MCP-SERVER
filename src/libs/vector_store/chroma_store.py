"""ChromaDB vector store implementation.

This module provides a ChromaDB-based implementation of the BaseVectorStore
interface, supporting both persistent and ephemeral storage modes for
efficient vector similarity search.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from src.libs.vector_store.base_vector_store import BaseVectorStore

if TYPE_CHECKING:
    from src.core.settings import Settings


class ChromaStore(BaseVectorStore):
    """ChromaDB-based vector store implementation.

    This implementation uses ChromaDB as the backend for storing and querying
    dense vectors. It supports both persistent storage (disk-based) and
    ephemeral storage (in-memory) modes.

    Design Principles Applied:
    - Pluggable: Implements BaseVectorStore interface for seamless backend swapping.
    - Config-Driven: All parameters read from settings.yaml.
    - Observable: Accepts optional trace parameter for tracing integration.
    - Fail-Fast: Validates inputs and provides clear error messages.

    Attributes:
        _client: The ChromaDB client instance.
        _collection: The ChromaDB collection for this store.
        _collection_name: Name of the collection.
    """

    def __init__(self, settings: Settings, **kwargs: Any) -> None:
        """Initialize ChromaDB vector store.

        Args:
            settings: Application settings containing vector_store configuration.
            **kwargs: Optional overrides for testing (e.g., ephemeral=True, collection_name="test").

        Raises:
            RuntimeError: If ChromaDB initialization fails.
        """
        self._collection_name = kwargs.get(
            "collection_name",
            getattr(settings.vector_store, "collection_name", "knowledge_base"),
        )

        # Support ephemeral mode for testing
        ephemeral = kwargs.get("ephemeral", False)

        try:
            if ephemeral:
                # In-memory mode for testing
                self._client = chromadb.Client(
                    ChromaSettings(
                        allow_reset=True,
                        is_persistent=False,
                    )
                )
            else:
                # Persistent mode for production
                persist_path = settings.vector_store.persist_path
                os.makedirs(persist_path, exist_ok=True)
                self._client = chromadb.PersistentClient(path=persist_path)

            # Get or create collection
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},  # Use cosine similarity
            )
        except Exception as e:
            raise RuntimeError(f"Failed to initialize ChromaDB: {e}") from e

    def upsert(
        self,
        records: List[Dict[str, Any]],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        """Upsert records into ChromaDB.

        Args:
            records: List of record dicts containing 'id', 'vector', 'text', 'metadata'.
            trace: Optional TraceContext for observability (reserved for Stage F).
            **kwargs: Backend-specific parameters.

        Raises:
            ValueError: If records list is empty or invalid.
            RuntimeError: If upsert operation fails.
        """
        # Validate input
        self.validate_records(records)

        # Prepare data for ChromaDB
        ids: List[str] = []
        embeddings: List[List[float]] = []
        documents: List[str] = []
        metadatas: List[Dict[str, Any]] = []

        for record in records:
            ids.append(record["id"])
            embeddings.append(record["vector"])
            # ChromaDB requires a document text for each embedding
            documents.append(record.get("text", ""))
            # Ensure metadata is a non-empty dict (ChromaDB requirement)
            # If metadata is empty, add a placeholder
            metadata = record.get("metadata", {})
            if not metadata:
                metadata = {"__placeholder": "empty"}
            metadatas.append(metadata)

        try:
            # ChromaDB's upsert is idempotent - updates if ID exists, inserts otherwise
            self._collection.upsert(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas,
            )
        except Exception as e:
            raise RuntimeError(f"ChromaDB upsert failed: {e}") from e

    def query(
        self,
        vector: List[float],
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Query ChromaDB for similar vectors.

        Args:
            vector: The query embedding vector.
            top_k: Maximum number of results to return.
            filters: Optional metadata filters (ChromaDB where clause format).
            trace: Optional TraceContext for observability (reserved for Stage F).
            **kwargs: Backend-specific parameters.

        Returns:
            List of result dicts with 'id', 'score', 'text', 'metadata'.
            Results sorted by similarity score (descending).

        Raises:
            ValueError: If query parameters are invalid.
            RuntimeError: If query operation fails.
        """
        # Validate input
        self.validate_query_params(vector, top_k)

        try:
            # Query ChromaDB
            results = self._collection.query(
                query_embeddings=[vector],
                n_results=top_k,
                where=filters,  # ChromaDB metadata filter
            )

            # Transform ChromaDB results to standard format
            output: List[Dict[str, Any]] = []

            # ChromaDB returns results as lists of lists (batch support)
            # We only queried with one vector, so take first element
            if not results["ids"] or not results["ids"][0]:
                return []

            for i in range(len(results["ids"][0])):
                result_dict = {
                    "id": results["ids"][0][i],
                    "score": 1.0 - results["distances"][0][i],  # Convert distance to similarity
                    "text": results["documents"][0][i] if results["documents"] else "",
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                }
                output.append(result_dict)

            return output

        except Exception as e:
            raise RuntimeError(f"ChromaDB query failed: {e}") from e

    def delete(
        self,
        doc_ids: List[str],
        trace: Optional[Any] = None,
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
        if not doc_ids:
            raise ValueError("doc_ids list cannot be empty")

        try:
            self._collection.delete(ids=doc_ids)
        except Exception as e:
            raise RuntimeError(f"ChromaDB delete failed: {e}") from e

    def clear_collection(self, collection_name: str) -> None:
        """Clear all records from a collection.

        Args:
            collection_name: Name of the collection to clear.

        Raises:
            RuntimeError: If clear operation fails.
        """
        try:
            self._client.delete_collection(name=collection_name)
            # Recreate the collection
            self._collection = self._client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as e:
            raise RuntimeError(
                f"Failed to clear collection '{collection_name}': {e}"
            ) from e

    def get_backend_name(self) -> str:
        """Get the backend name.

        Returns:
            The string 'chromadb'.
        """
        return "chromadb"

    def get_collection_names(self) -> List[str]:
        """Get all collection names in the ChromaDB instance.

        Returns:
            List of collection names.

        Raises:
            RuntimeError: If operation fails.
        """
        try:
            collections = self._client.list_collections()
            return [col.name for col in collections]
        except Exception as e:
            raise RuntimeError(f"Failed to list collections: {e}") from e
