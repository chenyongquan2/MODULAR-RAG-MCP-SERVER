"""Contract tests for VectorStore abstract interface and factory.

Test Coverage:
- Contract tests: validate input/output shape for upsert and query
- Factory pattern: backend registration, creation, and routing
- Configuration-driven instantiation
- Error handling for unknown/missing backends
- Validation logic in BaseVectorStore
"""

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from src.libs.vector_store.base_vector_store import BaseVectorStore
from src.libs.vector_store.vector_store_factory import VectorStoreFactory


class FakeVectorStore(BaseVectorStore):
    """Fake VectorStore for testing.

    In-memory vector store that supports basic upsert and query operations
    with deterministic behavior for reproducible testing.
    """

    def __init__(
        self,
        settings: Any = None,
        backend_name: str = "fake",
        **kwargs: Any,
    ):
        """Initialize fake VectorStore.

        Args:
            settings: Optional settings (unused in fake).
            backend_name: Backend name to report.
            **kwargs: Additional parameters (unused).
        """
        self.settings = settings
        self._backend_name = backend_name
        self._store: Dict[str, Dict[str, Any]] = {}
        self.upsert_call_count = 0
        self.query_call_count = 0

    def upsert(
        self,
        records: List[Dict[str, Any]],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        """Upsert records into in-memory store."""
        self.validate_records(records)
        self.upsert_call_count += 1

        for record in records:
            self._store[record["id"]] = {
                "id": record["id"],
                "vector": record["vector"],
                "text": record.get("text", ""),
                "metadata": record.get("metadata", {}),
            }

    def query(
        self,
        vector: List[float],
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Query in-memory store using simple dot-product similarity."""
        self.validate_query_params(vector, top_k)
        self.query_call_count += 1

        results = []
        for record_id, record in self._store.items():
            # Apply metadata filters if provided
            if filters:
                match = all(
                    record.get("metadata", {}).get(k) == v
                    for k, v in filters.items()
                )
                if not match:
                    continue

            # Simple dot-product similarity
            stored_vec = record["vector"]
            min_len = min(len(vector), len(stored_vec))
            score = sum(
                a * b for a, b in zip(vector[:min_len], stored_vec[:min_len])
            )

            results.append({
                "id": record["id"],
                "score": score,
                "text": record.get("text", ""),
                "metadata": record.get("metadata", {}),
            })

        # Sort by score descending
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def get_backend_name(self) -> str:
        """Return configured backend name."""
        return self._backend_name

    def get_by_ids(
        self,
        ids: List[str],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Retrieve records by their IDs."""
        results = []
        for record_id in ids:
            if record_id in self._store:
                record = self._store[record_id]
                results.append({
                    "id": record["id"],
                    "text": record.get("text", ""),
                    "metadata": record.get("metadata", {}),
                })
        return results

    def delete_by_metadata(
        self,
        metadata_filters: Dict[str, Any],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> int:
        """Delete records by metadata filters and return deleted count."""
        if not metadata_filters:
            raise ValueError("metadata_filters cannot be empty")

        to_delete = [
            record_id
            for record_id, record in self._store.items()
            if all(record.get("metadata", {}).get(k) == v for k, v in metadata_filters.items())
        ]
        for record_id in to_delete:
            del self._store[record_id]
        return len(to_delete)

    def get_ids_by_metadata(
        self,
        metadata_filters: Dict[str, Any],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[str]:
        """Get record IDs by metadata filters."""
        if not metadata_filters:
            raise ValueError("metadata_filters cannot be empty")

        return [
            record_id
            for record_id, record in self._store.items()
            if all(record.get("metadata", {}).get(k) == v for k, v in metadata_filters.items())
        ]

    def delete_by_metadata(
        self,
        metadata_filters: Dict[str, Any],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> int:
        """Delete records that match metadata filters and return deleted count."""
        if not metadata_filters:
            raise ValueError("metadata_filters cannot be empty")

        ids_to_delete = self.get_ids_by_metadata(metadata_filters, trace=trace)
        for record_id in ids_to_delete:
            self._store.pop(record_id, None)
        return len(ids_to_delete)

    def get_ids_by_metadata(
        self,
        metadata_filters: Dict[str, Any],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[str]:
        """Return IDs of records matching metadata filters."""
        if not metadata_filters:
            raise ValueError("metadata_filters cannot be empty")

        matched_ids: List[str] = []
        for record_id, record in self._store.items():
            metadata = record.get("metadata", {})
            is_match = all(metadata.get(k) == v for k, v in metadata_filters.items())
            if is_match:
                matched_ids.append(record_id)
        return matched_ids


# ===========================================================================
# Contract Tests: Validate input/output shape
# ===========================================================================


class TestVectorStoreContract:
    """Contract tests ensuring consistent upsert/query behavior."""

    def test_upsert_single_record(self):
        """Single record upsert should store the record."""
        store = FakeVectorStore()
        store.upsert([{
            "id": "chunk_001",
            "vector": [0.1, 0.2, 0.3],
            "text": "Hello world",
            "metadata": {"source": "test.pdf"},
        }])
        assert len(store._store) == 1

    def test_upsert_multiple_records(self):
        """Multiple records should all be stored."""
        store = FakeVectorStore()
        records = [
            {"id": f"chunk_{i:03d}", "vector": [float(i)] * 3,
             "text": f"Text {i}", "metadata": {"idx": i}}
            for i in range(5)
        ]
        store.upsert(records)
        assert len(store._store) == 5

    def test_upsert_idempotent(self):
        """Upserting same record twice should not create duplicates."""
        store = FakeVectorStore()
        record = [{
            "id": "chunk_001",
            "vector": [0.1, 0.2, 0.3],
            "text": "Hello",
            "metadata": {},
        }]
        store.upsert(record)
        store.upsert(record)
        assert len(store._store) == 1

    def test_upsert_updates_existing(self):
        """Upserting existing ID should update the record."""
        store = FakeVectorStore()
        store.upsert([{
            "id": "chunk_001",
            "vector": [0.1, 0.2, 0.3],
            "text": "Original",
            "metadata": {},
        }])
        store.upsert([{
            "id": "chunk_001",
            "vector": [0.4, 0.5, 0.6],
            "text": "Updated",
            "metadata": {},
        }])
        assert store._store["chunk_001"]["text"] == "Updated"
        assert store._store["chunk_001"]["vector"] == [0.4, 0.5, 0.6]

    def test_query_returns_list(self):
        """Query should return a list of dicts."""
        store = FakeVectorStore()
        store.upsert([{
            "id": "chunk_001",
            "vector": [1.0, 0.0, 0.0],
            "text": "Hello",
            "metadata": {},
        }])
        results = store.query([1.0, 0.0, 0.0], top_k=5)

        assert isinstance(results, list)
        assert len(results) >= 1

    def test_query_result_shape(self):
        """Each result should contain id, score, text, metadata."""
        store = FakeVectorStore()
        store.upsert([{
            "id": "chunk_001",
            "vector": [1.0, 0.0, 0.0],
            "text": "Hello world",
            "metadata": {"source": "test.pdf"},
        }])
        results = store.query([1.0, 0.0, 0.0], top_k=1)

        assert len(results) == 1
        result = results[0]
        assert "id" in result
        assert "score" in result
        assert "text" in result
        assert "metadata" in result
        assert isinstance(result["id"], str)
        assert isinstance(result["score"], (int, float))
        assert isinstance(result["text"], str)
        assert isinstance(result["metadata"], dict)

    def test_query_respects_top_k(self):
        """Query should return at most top_k results."""
        store = FakeVectorStore()
        for i in range(10):
            store.upsert([{
                "id": f"chunk_{i:03d}",
                "vector": [float(i)] * 3,
                "text": f"Text {i}",
                "metadata": {},
            }])
        results = store.query([5.0, 5.0, 5.0], top_k=3)
        assert len(results) <= 3

    def test_query_sorted_by_score_descending(self):
        """Results should be sorted by score in descending order."""
        store = FakeVectorStore()
        store.upsert([
            {"id": "low", "vector": [0.1, 0.0, 0.0], "text": "low", "metadata": {}},
            {"id": "high", "vector": [1.0, 0.0, 0.0], "text": "high", "metadata": {}},
            {"id": "mid", "vector": [0.5, 0.0, 0.0], "text": "mid", "metadata": {}},
        ])
        results = store.query([1.0, 0.0, 0.0], top_k=10)

        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_query_with_filters(self):
        """Filters should narrow down results by metadata."""
        store = FakeVectorStore()
        store.upsert([
            {"id": "a", "vector": [1.0], "text": "A", "metadata": {"source": "doc1.pdf"}},
            {"id": "b", "vector": [1.0], "text": "B", "metadata": {"source": "doc2.pdf"}},
            {"id": "c", "vector": [1.0], "text": "C", "metadata": {"source": "doc1.pdf"}},
        ])
        results = store.query(
            [1.0], top_k=10, filters={"source": "doc1.pdf"},
        )
        assert len(results) == 2
        assert all(r["metadata"]["source"] == "doc1.pdf" for r in results)

    def test_query_empty_store(self):
        """Querying empty store should return empty list."""
        store = FakeVectorStore()
        results = store.query([1.0, 0.0, 0.0], top_k=5)
        assert results == []

    def test_query_no_filter_match(self):
        """Query with non-matching filters should return empty list."""
        store = FakeVectorStore()
        store.upsert([{
            "id": "a", "vector": [1.0], "text": "A",
            "metadata": {"source": "doc1.pdf"},
        }])
        results = store.query(
            [1.0], top_k=10, filters={"source": "nonexistent.pdf"},
        )
        assert results == []

    def test_delete_by_metadata_success(self):
        """delete_by_metadata should remove matched records and return count."""
        store = FakeVectorStore()
        store.upsert([
            {"id": "a", "vector": [1.0], "text": "A", "metadata": {"source": "doc1.pdf"}},
            {"id": "b", "vector": [1.0], "text": "B", "metadata": {"source": "doc1.pdf"}},
            {"id": "c", "vector": [1.0], "text": "C", "metadata": {"source": "doc2.pdf"}},
        ])

        deleted = store.delete_by_metadata({"source": "doc1.pdf"})

        assert deleted == 2
        assert sorted(store._store.keys()) == ["c"]

    def test_delete_by_metadata_no_match(self):
        """delete_by_metadata should return 0 when no records match."""
        store = FakeVectorStore()
        store.upsert([
            {"id": "a", "vector": [1.0], "text": "A", "metadata": {"source": "doc1.pdf"}},
        ])

        deleted = store.delete_by_metadata({"source": "missing.pdf"})

        assert deleted == 0
        assert sorted(store._store.keys()) == ["a"]

    def test_delete_by_metadata_empty_filters(self):
        """delete_by_metadata with empty filters should raise ValueError."""
        store = FakeVectorStore()
        with pytest.raises(ValueError, match="metadata_filters cannot be empty"):
            store.delete_by_metadata({})

    def test_delete_by_metadata_deletes_matching_records(self):
        """delete_by_metadata should remove only matched records."""
        store = FakeVectorStore()
        store.upsert([
            {"id": "a", "vector": [1.0], "text": "A", "metadata": {"source": "doc1.pdf"}},
            {"id": "b", "vector": [1.0], "text": "B", "metadata": {"source": "doc2.pdf"}},
            {"id": "c", "vector": [1.0], "text": "C", "metadata": {"source": "doc1.pdf"}},
        ])

        deleted_count = store.delete_by_metadata({"source": "doc1.pdf"})

        assert deleted_count == 2
        assert set(store._store.keys()) == {"b"}

    def test_delete_by_metadata_no_match_returns_zero(self):
        """delete_by_metadata should return 0 when no record matches."""
        store = FakeVectorStore()
        store.upsert([
            {"id": "a", "vector": [1.0], "text": "A", "metadata": {"source": "doc1.pdf"}},
        ])

        deleted_count = store.delete_by_metadata({"source": "doc2.pdf"})

        assert deleted_count == 0
        assert set(store._store.keys()) == {"a"}

    def test_delete_by_metadata_empty_filters_raises_error(self):
        """delete_by_metadata should reject empty filter dict."""
        store = FakeVectorStore()
        with pytest.raises(ValueError, match="metadata_filters cannot be empty"):
            store.delete_by_metadata({})


# ===========================================================================
# Validation Tests
# ===========================================================================


class TestBaseVectorStoreValidation:
    """Tests for BaseVectorStore validation methods."""

    def test_validate_records_success(self):
        """Valid records should pass validation."""
        store = FakeVectorStore()
        store.validate_records([
            {"id": "1", "vector": [0.1, 0.2]},
        ])

    def test_validate_records_empty(self):
        """Empty records list should raise ValueError."""
        store = FakeVectorStore()
        with pytest.raises(ValueError, match="cannot be empty"):
            store.validate_records([])

    def test_validate_records_non_dict(self):
        """Non-dict record should raise ValueError."""
        store = FakeVectorStore()
        with pytest.raises(ValueError, match="not a dict"):
            store.validate_records(["not_a_dict"])  # type: ignore

    def test_validate_records_missing_id(self):
        """Record without id should raise ValueError."""
        store = FakeVectorStore()
        with pytest.raises(ValueError, match="missing required fields"):
            store.validate_records([{"vector": [0.1]}])

    def test_validate_records_missing_vector(self):
        """Record without vector should raise ValueError."""
        store = FakeVectorStore()
        with pytest.raises(ValueError, match="missing required fields"):
            store.validate_records([{"id": "1"}])

    def test_validate_query_params_success(self):
        """Valid query params should pass validation."""
        store = FakeVectorStore()
        store.validate_query_params([0.1, 0.2], 5)

    def test_validate_query_params_empty_vector(self):
        """Empty query vector should raise ValueError."""
        store = FakeVectorStore()
        with pytest.raises(ValueError, match="cannot be empty"):
            store.validate_query_params([], 5)

    def test_validate_query_params_top_k_zero(self):
        """top_k=0 should raise ValueError."""
        store = FakeVectorStore()
        with pytest.raises(ValueError, match="must be at least 1"):
            store.validate_query_params([0.1], 0)

    def test_validate_query_params_top_k_negative(self):
        """Negative top_k should raise ValueError."""
        store = FakeVectorStore()
        with pytest.raises(ValueError, match="must be at least 1"):
            store.validate_query_params([0.1], -1)

    def test_get_backend_name_implemented(self):
        """FakeVectorStore should return configured backend name."""
        store = FakeVectorStore(backend_name="chroma")
        assert store.get_backend_name() == "chroma"

    def test_get_backend_name_not_implemented(self):
        """BaseVectorStore without override should raise NotImplementedError."""

        class IncompleteStore(BaseVectorStore):
            def get_by_ids(self, ids, trace=None, **kwargs):
                return []

            def upsert(self, records, trace=None, **kwargs):
                pass

            def query(self, vector, top_k=10, filters=None, trace=None, **kwargs):
                return []

        incomplete = IncompleteStore()
        with pytest.raises(
            NotImplementedError, match="must implement get_backend_name"
        ):
            incomplete.get_backend_name()

    def test_delete_by_metadata_not_implemented(self):
        """BaseVectorStore default delete_by_metadata should raise NotImplementedError."""

        class IncompleteStore(BaseVectorStore):
            def get_by_ids(self, ids, trace=None, **kwargs):
                return []

            def upsert(self, records, trace=None, **kwargs):
                pass

            def query(self, vector, top_k=10, filters=None, trace=None, **kwargs):
                return []

        incomplete = IncompleteStore()
        with pytest.raises(
            NotImplementedError, match="must implement delete_by_metadata"
        ):
            incomplete.delete_by_metadata({"source": "test.pdf"})


# ===========================================================================
# Factory Tests
# ===========================================================================


class TestVectorStoreFactory:
    """Tests for VectorStoreFactory."""

    def setup_method(self):
        """Reset factory registry before each test."""
        VectorStoreFactory._PROVIDERS.clear()

    def test_register_provider_success(self):
        """Registering valid provider should succeed."""
        VectorStoreFactory.register_provider("fake", FakeVectorStore)
        assert "fake" in VectorStoreFactory._PROVIDERS

    def test_register_provider_case_insensitive(self):
        """Backend names should be normalized to lowercase."""
        VectorStoreFactory.register_provider("Chroma", FakeVectorStore)
        assert "chroma" in VectorStoreFactory._PROVIDERS

    def test_register_provider_invalid_class(self):
        """Registering non-BaseVectorStore class should raise ValueError."""

        class NotAStore:
            pass

        with pytest.raises(ValueError, match="must inherit from BaseVectorStore"):
            VectorStoreFactory.register_provider(
                "invalid", NotAStore,  # type: ignore
            )

    def test_list_providers_empty(self):
        """list_providers should return empty list when no providers registered."""
        assert VectorStoreFactory.list_providers() == []

    def test_list_providers_sorted(self):
        """list_providers should return sorted provider names."""
        VectorStoreFactory.register_provider("chroma", FakeVectorStore)
        VectorStoreFactory.register_provider("qdrant", FakeVectorStore)
        VectorStoreFactory.register_provider("milvus", FakeVectorStore)

        providers = VectorStoreFactory.list_providers()
        assert providers == ["chroma", "milvus", "qdrant"]

    def test_create_success(self):
        """Creating registered backend should succeed."""
        VectorStoreFactory.register_provider("fake", FakeVectorStore)

        settings = MagicMock()
        settings.vector_store.backend = "fake"

        store = VectorStoreFactory.create(settings)

        assert isinstance(store, FakeVectorStore)
        assert store.settings == settings

    def test_create_case_insensitive(self):
        """Backend lookup should be case-insensitive."""
        VectorStoreFactory.register_provider("fake", FakeVectorStore)

        settings = MagicMock()
        settings.vector_store.backend = "FAKE"

        store = VectorStoreFactory.create(settings)
        assert isinstance(store, FakeVectorStore)

    def test_create_unknown_backend(self):
        """Creating unregistered backend should raise clear error."""
        VectorStoreFactory.register_provider("fake", FakeVectorStore)

        settings = MagicMock()
        settings.vector_store.backend = "unknown"

        with pytest.raises(ValueError) as exc_info:
            VectorStoreFactory.create(settings)

        error_message = str(exc_info.value)
        assert "Unsupported VectorStore backend: 'unknown'" in error_message
        assert "Available backends:" in error_message

    def test_create_missing_backend_config(self):
        """Missing backend in settings should raise clear error."""
        settings = MagicMock()
        del settings.vector_store

        with pytest.raises(ValueError) as exc_info:
            VectorStoreFactory.create(settings)

        error_message = str(exc_info.value)
        assert "Missing required configuration" in error_message
        assert "settings.vector_store.backend" in error_message

    def test_create_provider_instantiation_failure(self):
        """Provider constructor errors should be wrapped in RuntimeError."""

        class BrokenStore(BaseVectorStore):
            def __init__(self, settings: Any, **kwargs: Any):
                raise ValueError("Intentional init error")

            def get_by_ids(self, ids, trace=None, **kwargs):
                return []

            def upsert(self, records, trace=None, **kwargs):
                pass

            def query(self, vector, top_k=10, filters=None, trace=None, **kwargs):
                return []

        VectorStoreFactory.register_provider("broken", BrokenStore)

        settings = MagicMock()
        settings.vector_store.backend = "broken"

        with pytest.raises(RuntimeError) as exc_info:
            VectorStoreFactory.create(settings)

        error_message = str(exc_info.value)
        assert "Failed to instantiate VectorStore backend 'broken'" in error_message

    def test_create_no_providers_registered(self):
        """Creating backend when registry is empty should show helpful message."""
        settings = MagicMock()
        settings.vector_store.backend = "chroma"

        with pytest.raises(ValueError) as exc_info:
            VectorStoreFactory.create(settings)

        error_message = str(exc_info.value)
        assert "Available backends: none" in error_message

    def test_create_and_roundtrip(self):
        """Factory-created store should support full upsert-query roundtrip."""
        VectorStoreFactory.register_provider("fake", FakeVectorStore)

        settings = MagicMock()
        settings.vector_store.backend = "fake"

        store = VectorStoreFactory.create(settings)
        store.upsert([{
            "id": "chunk_001",
            "vector": [1.0, 0.0, 0.0],
            "text": "Hello world",
            "metadata": {"source": "test.pdf"},
        }])
        results = store.query([1.0, 0.0, 0.0], top_k=1)

        assert len(results) == 1
        assert results[0]["id"] == "chunk_001"
        assert results[0]["text"] == "Hello world"
