"""Dense vector retrieval.

This module implements the DenseRetriever class that performs semantic search
using dense embeddings. It combines an embedding client with a vector store
to retrieve relevant chunks based on query similarity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.core.types import RetrievalResult
from src.libs.embedding.base_embedding import BaseEmbedding
from src.libs.vector_store.base_vector_store import BaseVectorStore

if TYPE_CHECKING:
    from src.core.settings import Settings


class DenseRetriever:
    """Dense vector retriever.

    Combines an embedding client with a vector store to perform semantic search.
    The retriever converts the query into a dense vector using the embedding
    client, then queries the vector store for similar vectors.

    Design Principles Applied:
    - Dependency Injection: Accepts embedding_client and vector_store for testability.
    - Pluggable: Works with any implementation of BaseEmbedding and BaseVectorStore.
    - Fail-Fast: Validates inputs and provides clear error messages.

    Attributes:
        _embedding_client: The embedding client for query vectorization.
        _vector_store: The vector store for similarity search.
        _top_k: Default number of results to retrieve.
        _embedding_model: Model name for observability.

    Example:
        >>> retriever = DenseRetriever(settings, embedding_client, vector_store)
        >>> results = retriever.retrieve("How to configure LLM?", top_k=5)
        >>> len(results) <= 5
        True
    """

    def __init__(
        self,
        settings: Settings,
        embedding_client: Optional[BaseEmbedding] = None,
        vector_store: Optional[BaseVectorStore] = None,
        top_k: Optional[int] = None,
    ) -> None:
        """Initialize DenseRetriever.

        Args:
            settings: Application settings containing retrieval configuration.
            embedding_client: Optional embedding client (created from factory if not provided).
            vector_store: Optional vector store (created from factory if not provided).
            top_k: Optional override for default top_k (defaults to retrieval.top_k_dense).

        Raises:
            ValueError: If settings is None.
        """
        if settings is None:
            raise ValueError("Settings cannot be None")

        self._settings = settings

        # Use dependency injection or create from factory
        if embedding_client is not None:
            self._embedding_client = embedding_client
        else:
            from src.libs.embedding.embedding_factory import EmbeddingFactory

            self._embedding_client = EmbeddingFactory.create(settings)

        if vector_store is not None:
            self._vector_store = vector_store
        else:
            from src.libs.vector_store.vector_store_factory import VectorStoreFactory

            self._vector_store = VectorStoreFactory.create(settings)

        # Get top_k from settings or use override
        default_top_k = getattr(settings.retrieval, "top_k_dense", 20)
        self._top_k = top_k if top_k is not None else default_top_k

        # Get embedding model name for observability
        try:
            self._embedding_model = self._embedding_client.get_model_name()
        except Exception:
            self._embedding_model = "unknown"

    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
        trace: Optional[Any] = None,
    ) -> List[RetrievalResult]:
        """Retrieve relevant chunks using dense vector similarity.

        Args:
            query: The search query text.
            top_k: Optional override for number of results (defaults to instance top_k).
            filters: Optional metadata filters for the vector store.
            trace: Optional TraceContext for observability (reserved for Stage F).

        Returns:
            List of RetrievalResult sorted by similarity score (descending).

        Raises:
            ValueError: If query is empty or top_k is invalid.
            RuntimeError: If embedding or vector store operation fails.
        """
        # Validate inputs
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")

        effective_top_k = top_k if top_k is not None else self._top_k

        if effective_top_k <= 0:
            raise ValueError("top_k must be a positive integer")

        try:
            # Step 1: Convert query to embedding vector
            vectors = self._embedding_client.embed([query.strip()], trace=trace)

            if not vectors or len(vectors) == 0:
                raise RuntimeError("Embedding client returned empty result")

            query_vector = vectors[0]

            # Step 2: Query vector store for similar vectors
            raw_results = self._vector_store.query(
                vector=query_vector,
                top_k=effective_top_k,
                filters=filters,
                trace=trace,
            )

            # Step 3: Transform raw results to RetrievalResult
            results: List[RetrievalResult] = []

            for raw in raw_results:
                # ChromaStore.query returns: id, score, text, metadata
                result = RetrievalResult(
                    chunk_id=raw.get("id", ""),
                    score=raw.get("score", 0.0),
                    text=raw.get("text", ""),
                    metadata=raw.get("metadata", {}),
                )
                results.append(result)

            return results

        except ValueError:
            # Re-raise validation errors as-is
            raise
        except Exception as e:
            raise RuntimeError(
                f"Dense retrieval failed: {e}"
            ) from e

    def get_backend_name(self) -> str:
        """Get the vector store backend name.

        Returns:
            The backend name (e.g., 'chromadb').
        """
        try:
            return self._vector_store.get_backend_name()
        except Exception:
            return "unknown"

    def get_embedding_model(self) -> str:
        """Get the embedding model name.

        Returns:
            The embedding model name.
        """
        return self._embedding_model
