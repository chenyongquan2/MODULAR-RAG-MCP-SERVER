"""Integration tests for ChromaStore roundtrip (upsert → query).

This module tests the complete lifecycle of storing and retrieving vectors
in ChromaDB, verifying deterministic behavior and correctness.
"""

import tempfile
from typing import Any, Dict, List

import pytest

from src.libs.vector_store.chroma_store import ChromaStore
from src.core.settings import Settings


@pytest.fixture
def temp_settings() -> Settings:
    """Create temporary settings for testing."""
    class MockVectorStore:
        backend = "chroma"
        collection_name = "test_collection"
        persist_path = tempfile.mkdtemp()

    class MockSettings:
        vector_store = MockVectorStore()

    return MockSettings()  # type: ignore


@pytest.fixture
def chroma_store_ephemeral(temp_settings: Settings) -> ChromaStore:
    """Create ephemeral ChromaStore for testing."""
    return ChromaStore(temp_settings, ephemeral=True)


def test_chroma_store_upsert_basic(chroma_store_ephemeral: ChromaStore) -> None:
    """Test basic upsert operation."""
    records = [
        {
            "id": "chunk_001",
            "vector": [0.1, 0.2, 0.3],
            "text": "Hello world",
            "metadata": {"source": "test.pdf"},
        },
        {
            "id": "chunk_002",
            "vector": [0.4, 0.5, 0.6],
            "text": "Goodbye world",
            "metadata": {"source": "test.pdf"},
        },
    ]

    # Should not raise
    chroma_store_ephemeral.upsert(records)


def test_chroma_store_query_basic(chroma_store_ephemeral: ChromaStore) -> None:
    """Test basic query operation after upsert."""
    # Insert test data
    records = [
        {
            "id": "chunk_001",
            "vector": [1.0, 0.0, 0.0],
            "text": "Document about cats",
            "metadata": {"topic": "animals"},
        },
        {
            "id": "chunk_002",
            "vector": [0.0, 1.0, 0.0],
            "text": "Document about dogs",
            "metadata": {"topic": "animals"},
        },
        {
            "id": "chunk_003",
            "vector": [0.0, 0.0, 1.0],
            "text": "Document about cars",
            "metadata": {"topic": "vehicles"},
        },
    ]
    chroma_store_ephemeral.upsert(records)

    # Query with vector similar to first record
    query_vector = [0.9, 0.1, 0.0]
    results = chroma_store_ephemeral.query(query_vector, top_k=2)

    # Verify results
    assert len(results) == 2
    assert results[0]["id"] == "chunk_001"  # Most similar
    assert "score" in results[0]
    assert "text" in results[0]
    assert results[0]["text"] == "Document about cats"


def test_chroma_store_query_top_k(chroma_store_ephemeral: ChromaStore) -> None:
    """Test top_k parameter."""
    # Insert 5 records
    records = [
        {
            "id": f"chunk_{i:03d}",
            "vector": [float(i), 0.0, 0.0],
            "text": f"Document {i}",
            "metadata": {},
        }
        for i in range(5)
    ]
    chroma_store_ephemeral.upsert(records)

    # Query with top_k=3
    results = chroma_store_ephemeral.query([2.5, 0.0, 0.0], top_k=3)

    assert len(results) == 3


def test_chroma_store_metadata_filters(chroma_store_ephemeral: ChromaStore) -> None:
    """Test metadata filtering."""
    # Insert records with different metadata
    records = [
        {
            "id": "chunk_001",
            "vector": [1.0, 0.0, 0.0],
            "text": "Animal doc 1",
            "metadata": {"category": "animals"},
        },
        {
            "id": "chunk_002",
            "vector": [1.0, 0.0, 0.0],
            "text": "Animal doc 2",
            "metadata": {"category": "animals"},
        },
        {
            "id": "chunk_003",
            "vector": [1.0, 0.0, 0.0],
            "text": "Vehicle doc",
            "metadata": {"category": "vehicles"},
        },
    ]
    chroma_store_ephemeral.upsert(records)

    # Query with metadata filter
    results = chroma_store_ephemeral.query(
        [1.0, 0.0, 0.0],
        top_k=10,
        filters={"category": "animals"},
    )

    # Should only return animal documents
    assert len(results) == 2
    assert all(r["metadata"]["category"] == "animals" for r in results)


def test_chroma_store_upsert_idempotent(chroma_store_ephemeral: ChromaStore) -> None:
    """Test that upsert is idempotent (updates existing records)."""
    # First upsert
    records_v1 = [
        {
            "id": "chunk_001",
            "vector": [1.0, 0.0, 0.0],
            "text": "Version 1",
            "metadata": {"version": "1"},
        }
    ]
    chroma_store_ephemeral.upsert(records_v1)

    # Second upsert with same ID but different content
    records_v2 = [
        {
            "id": "chunk_001",
            "vector": [0.0, 1.0, 0.0],
            "text": "Version 2",
            "metadata": {"version": "2"},
        }
    ]
    chroma_store_ephemeral.upsert(records_v2)

    # Query should return updated version
    results = chroma_store_ephemeral.query([0.0, 1.0, 0.0], top_k=1)

    assert len(results) == 1
    assert results[0]["id"] == "chunk_001"
    assert results[0]["text"] == "Version 2"
    assert results[0]["metadata"]["version"] == "2"


def test_chroma_store_delete(temp_settings: Settings) -> None:
    """Test delete operation."""
    # Create a fresh ephemeral store for this test
    store = ChromaStore(temp_settings, ephemeral=True, collection_name="delete_test")

    # Insert records
    records = [
        {
            "id": f"chunk_{i:03d}",
            "vector": [float(i), 0.0, 0.0],
            "text": f"Document {i}",
            "metadata": {"idx": i},
        }
        for i in range(3)
    ]
    store.upsert(records)

    # Delete one record
    store.delete(["chunk_001"])

    # Query should not return deleted record
    results = store.query([1.0, 0.0, 0.0], top_k=10)

    assert len(results) == 2
    assert all(r["id"] != "chunk_001" for r in results)


def test_chroma_store_get_backend_name(chroma_store_ephemeral: ChromaStore) -> None:
    """Test get_backend_name method."""
    assert chroma_store_ephemeral.get_backend_name() == "chromadb"


def test_chroma_store_get_collection_names(chroma_store_ephemeral: ChromaStore) -> None:
    """Test get_collection_names method."""
    names = chroma_store_ephemeral.get_collection_names()

    assert isinstance(names, list)
    assert "test_collection" in names


@pytest.mark.integration
def test_chroma_store_roundtrip_deterministic() -> None:
    """Test complete roundtrip with deterministic results.

    This test verifies that:
    1. Data can be inserted
    2. Data can be queried back
    3. Results are deterministic and correct
    4. Similarity scores make sense
    """
    # Create ephemeral store
    class MockVectorStore:
        backend = "chroma"
        collection_name = "roundtrip_test"
        persist_path = "/tmp/chroma_test"

    class MockSettings:
        vector_store = MockVectorStore()

    settings = MockSettings()  # type: ignore
    store = ChromaStore(settings, ephemeral=True)

    # Insert known test data
    test_records = [
        {
            "id": "doc_A",
            "vector": [1.0, 0.0, 0.0],  # Orthogonal vectors for clear similarity
            "text": "This is about topic A",
            "metadata": {"category": "A"},
        },
        {
            "id": "doc_B",
            "vector": [0.0, 1.0, 0.0],
            "text": "This is about topic B",
            "metadata": {"category": "B"},
        },
        {
            "id": "doc_C",
            "vector": [0.0, 0.0, 1.0],
            "text": "This is about topic C",
            "metadata": {"category": "C"},
        },
    ]
    store.upsert(test_records)

    # Query with vector identical to doc_A
    results = store.query([1.0, 0.0, 0.0], top_k=3)

    # Verify deterministic behavior
    assert len(results) == 3

    # First result should be exact match
    assert results[0]["id"] == "doc_A"
    assert results[0]["text"] == "This is about topic A"
    assert results[0]["metadata"]["category"] == "A"
    # Score should be very high (close to 1.0 for cosine similarity)
    assert results[0]["score"] > 0.99

    # Other results should have lower scores (orthogonal vectors have distance ~1.0)
    # For cosine similarity, orthogonal vectors score around 0.0
    assert results[1]["score"] <= results[0]["score"]
    assert results[2]["score"] <= results[0]["score"]
