"""Sparse retrieval (BM25).

This module implements the SparseRetriever class that performs keyword-based
search using BM25 algorithm. It combines a BM25 indexer with a vector store
to retrieve relevant chunks based on keyword matching.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.core.types import RetrievalResult

if TYPE_CHECKING:
    from src.core.settings import Settings
    from src.ingestion.storage.bm25_indexer import BM25Indexer
    from src.libs.vector_store.base_vector_store import BaseVectorStore


class SparseRetriever:
    """Sparse retrieval retriever using BM25 algorithm.

    Performs keyword-based search using BM25 (Best Matching 25) ranking function.
    Combines a BM25 indexer with a vector store to retrieve relevant chunks
    based on keyword matching.

    Design Principles Applied:
    - Dependency Injection: Accepts bm25_indexer and vector_store for testability.
    - Pluggable: Works with any implementation of BaseVectorStore.
    - Fail-Fast: Validates inputs and provides clear error messages.

    Attributes:
        _bm25_indexer: The BM25 indexer for keyword search.
        _vector_store: The vector store for fetching full records.
        _top_k: Default number of results to retrieve.
        _collection: Collection name for index loading.

    Example:
        >>> retriever = SparseRetriever(settings, bm25_indexer, vector_store)
        >>> results = retriever.retrieve(["LLM", "config"], top_k=5)
        >>> len(results) <= 5
        True
    """

    def __init__(
        self,
        settings: Settings,
        bm25_indexer: Optional[BM25Indexer] = None,
        vector_store: Optional[BaseVectorStore] = None,
        top_k: Optional[int] = None,
    ) -> None:
        """Initialize SparseRetriever.

        Args:
            settings: Application settings containing retrieval configuration.
            bm25_indexer: Optional BM25 indexer (created if not provided).
            vector_store: Optional vector store (created from factory if not provided).
            top_k: Optional override for default top_k (defaults to retrieval.top_k_sparse).

        Raises:
            ValueError: If settings is None.
        """
        if settings is None:
            raise ValueError("Settings cannot be None")

        self._settings = settings
        # 两路检索共用 collection_name 这一个真源（见 VectorStoreSettings docstring）。
        # 该字段在 dataclass 上有默认值且经 load_settings 校验，无需 getattr 兜底 ——
        # 静默回退默认值正是宪法原则三禁止的（feature-004 T001）。
        self._collection = settings.vector_store.collection_name

        # Use dependency injection or create BM25 indexer
        if bm25_indexer is not None:
            self._bm25_indexer = bm25_indexer
        else:
            from src.ingestion.storage.bm25_indexer import BM25Indexer

            index_dir = settings.vector_store.bm25_index_path
            self._bm25_indexer = BM25Indexer(index_dir=index_dir)
            self._bm25_indexer.load(collection=self._collection)

        if vector_store is not None:
            self._vector_store = vector_store
        else:
            from src.libs.vector_store.vector_store_factory import VectorStoreFactory

            self._vector_store = VectorStoreFactory.create(settings)

        # Get top_k from settings or use override
        default_top_k = getattr(settings.retrieval, "top_k_sparse", 20)
        self._top_k = top_k if top_k is not None else default_top_k

    def retrieve(
        self,
        keywords: List[str],
        top_k: Optional[int] = None,
        trace: Optional[Any] = None,
    ) -> List[RetrievalResult]:
        """Retrieve relevant chunks using BM25 keyword search.

        Args:
            keywords: List of keywords to search for.
            top_k: Optional override for number of results (defaults to instance top_k).
            trace: Optional TraceContext for observability (reserved for Stage F).

        Returns:
            List of RetrievalResult sorted by BM25 score (descending).

        Raises:
            ValueError: If keywords list is empty or top_k is invalid.
            RuntimeError: If BM25 query or vector store operation fails.
        """
        # Validate inputs
        if not keywords:
            raise ValueError("Keywords list cannot be empty")

        effective_top_k = top_k if top_k is not None else self._top_k

        if effective_top_k <= 0:
            raise ValueError("top_k must be a positive integer")

        try:
            # Step 1: Query BM25 index for matching chunk IDs with scores
            bm25_results = self._bm25_indexer.query(
                keywords=keywords,
                top_k=effective_top_k,
            )

            if not bm25_results:
                return []

            # Extract chunk IDs in order
            chunk_ids = [result["chunk_id"] for result in bm25_results]
            chunk_id_to_score = {result["chunk_id"]: result["score"] for result in bm25_results}

            # Step 2: Fetch full records from vector store
            raw_results = self._vector_store.get_by_ids(
                ids=chunk_ids,
                trace=trace,
            )

            # Step 3: Transform raw results to RetrievalResult with BM25 scores
            results: List[RetrievalResult] = []

            # Create a mapping for quick lookup
            id_to_result = {raw["id"]: raw for raw in raw_results}

            # Maintain order from BM25 results
            for chunk_id in chunk_ids:
                if chunk_id in id_to_result:
                    raw = id_to_result[chunk_id]
                    result = RetrievalResult(
                        chunk_id=chunk_id,
                        score=chunk_id_to_score.get(chunk_id, 0.0),
                        text=raw.get("text", ""),
                        metadata=raw.get("metadata", {}),
                    )
                    results.append(result)

            return results

        except ValueError:
            raise
        except Exception as e:
            raise RuntimeError(f"Sparse retrieval failed: {e}") from e

    def get_backend_name(self) -> str:
        """Get the vector store backend name.

        Returns:
            The backend name (e.g., 'chromadb').
        """
        try:
            return self._vector_store.get_backend_name()
        except Exception:
            return "unknown"

    def get_index_stats(self) -> Dict[str, Any]:
        """Get BM25 index statistics.

        Returns:
            Dictionary containing index statistics.
        """
        try:
            return self._bm25_indexer.stats
        except Exception:
            return {"error": "Failed to get index stats"}
