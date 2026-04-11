"""ChromaDB vector store implementation.

This module provides a ChromaDB-based implementation of the BaseVectorStore
interface, supporting both persistent and ephemeral storage modes for
efficient vector similarity search.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Dict, List, Optional

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

    # ChromaDB max batch size limit (typically ~5461), use safe threshold
    MAX_BATCH_SIZE = 5000

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
            # 延迟导入：避免仅导入模块时触发 chromadb/protobuf 依赖错误
            import chromadb
            from chromadb.config import Settings as ChromaSettings

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
            error_msg = f"Failed to initialize ChromaDB: {e}"
            if "Descriptors cannot be created directly" in str(e):
                error_msg += (
                    " (Detected protobuf/chromadb compatibility issue. "
                    "Please install dependencies with pyproject constraints, "
                    "or run: pip install 'protobuf>=3.20.0,<4')"
                )
            raise RuntimeError(error_msg) from e

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
            # ChromaDB 只接受基本类型的 metadata 值：str, int, float, bool, None
            # 需要过滤掉列表等非基本类型的值
            metadata = record.get("metadata", {})
            if not metadata:
                metadata = {"__placeholder": "empty"}
            else:
                # 过滤非基本类型的 metadata 值
                filtered_metadata = {}
                for key, value in metadata.items():
                    # 只保留基本类型的值：str, int, float, bool, None
                    if value is None or isinstance(value, (str, int, float, bool)):
                        filtered_metadata[key] = value
                    else:
                        # 对于列表等非基本类型，转换为 JSON 字符串
                        import json
                        try:
                            filtered_metadata[key] = json.dumps(value, ensure_ascii=False)
                        except (TypeError, ValueError):
                            # 如果转换失败，跳过该字段
                            pass
                metadata = filtered_metadata if filtered_metadata else {"__placeholder": "empty"}
            metadatas.append(metadata)

        try:
            # ChromaDB has a max batch size limit (typically ~5461)
            # Split large batches into smaller chunks to avoid ValueError
            total_records = len(ids)
            for i in range(0, total_records, self.MAX_BATCH_SIZE):
                batch_start = i
                batch_end = min(i + self.MAX_BATCH_SIZE, total_records)

                # 分批插入 ChromaDB
                self._collection.upsert(
                    ids=ids[batch_start:batch_end],
                    embeddings=embeddings[batch_start:batch_end],
                    documents=documents[batch_start:batch_end],
                    metadatas=metadatas[batch_start:batch_end],
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

    def get_collection_stats(self, collection_name: str | None = None) -> Dict[str, Any]:
        """Get statistics for a specific collection or all collections.

        Args:
            collection_name: Name of collection to get stats for.
                If None, returns aggregated stats for all collections.

        Returns:
            Dict with collection statistics:
            - 'count': Number of vectors in collection
            - 'name': Collection name
            - If collection_name is None, returns list of all collection stats

        Raises:
            RuntimeError: If operation fails.
        """
        try:
            if collection_name:
                # Get stats for specific collection
                collection = self._client.get_or_create_collection(
                    name=collection_name,
                    metadata={"hnsw:space": "cosine"},
                )
                count = collection.count()
                return {
                    "name": collection_name,
                    "count": count,
                }
            else:
                # Get stats for all collections
                collections = self._client.list_collections()
                stats = []
                for col in collections:
                    stats.append({
                        "name": col.name,
                        "count": col.count(),
                    })
                return {
                    "collections": stats,
                    "total_collections": len(stats),
                    "total_vectors": sum(s["count"] for s in stats),
                }
        except Exception as e:
            raise RuntimeError(f"Failed to get collection stats: {e}") from e

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

    def get_by_ids(
        self,
        ids: List[str],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Retrieve records by their IDs.

        Args:
            ids: List of chunk IDs to retrieve.
            trace: Optional TraceContext for observability (reserved for Stage F).
            **kwargs: Backend-specific parameters.

        Returns:
            List of result dicts with 'id', 'text', 'metadata'.
            Records are returned in the same order as the input IDs.
            Missing IDs are omitted from the results.

        Raises:
            ValueError: If ids list is empty.
            RuntimeError: If retrieval operation fails.
        """
        if not ids:
            raise ValueError("ids list cannot be empty")

        try:
            results = self._collection.get(ids=ids)

            output: List[Dict[str, Any]] = []

            if not results["ids"]:
                return []

            for i, chunk_id in enumerate(results["ids"]):
                result_dict = {
                    "id": chunk_id,
                    "text": results["documents"][i] if results["documents"] else "",
                    "metadata": results["metadatas"][i] if results["metadatas"] else {},
                }
                output.append(result_dict)

            return output

        except Exception as e:
            raise RuntimeError(f"ChromaDB get_by_ids failed: {e}") from e

    def delete_by_metadata(
        self,
        metadata_filters: Dict[str, Any],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> int:
        """Delete records by matching metadata.

        This method queries records that match the given metadata filters
        and deletes them all. Useful for batch deletion of all chunks
        belonging to a specific document.

        Args:
            metadata_filters: Metadata filters (ChromaDB where clause format).
                Example: {"doc_id": "abc123"} or {"source_path": "path/to/file.pdf"}
            trace: Optional TraceContext for observability.
            **kwargs: Backend-specific parameters.

        Returns:
            Number of records deleted.

        Raises:
            ValueError: If filters are empty.
            RuntimeError: If operation fails.
        """
        if not metadata_filters:
            raise ValueError("metadata_filters cannot be empty")

        try:
            # Query records that match the metadata filter
            # Use a large limit to get all matching records
            results = self._collection.get(
                where=metadata_filters,
                limit=10000,  # ChromaDB default max
            )

            if not results["ids"]:
                return 0

            # Delete the matching IDs
            self._collection.delete(ids=results["ids"])
            deleted_count = len(results["ids"])

            return deleted_count

        except Exception as e:
            raise RuntimeError(f"ChromaDB delete_by_metadata failed: {e}") from e

    def get_ids_by_metadata(
        self,
        metadata_filters: Dict[str, Any],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[str]:
        """Get record IDs by matching metadata.

        Args:
            metadata_filters: Metadata filters (ChromaDB where clause format).
            trace: Optional TraceContext for observability.
            **kwargs: Backend-specific parameters.

        Returns:
            List of chunk IDs that match the filters.

        Raises:
            ValueError: If filters are empty.
            RuntimeError: If operation fails.
        """
        if not metadata_filters:
            raise ValueError("metadata_filters cannot be empty")

        try:
            results = self._collection.get(
                where=metadata_filters,
                limit=10000,
            )

            return results["ids"] or []

        except Exception as e:
            raise RuntimeError(f"ChromaDB get_ids_by_metadata failed: {e}") from e
