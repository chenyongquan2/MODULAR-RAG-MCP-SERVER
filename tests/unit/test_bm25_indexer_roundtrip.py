"""BM25 Indexer Roundtrip Tests."""

import json
import tempfile
from pathlib import Path

import pytest

from src.core.types import ChunkRecord
from src.ingestion.storage.bm25_indexer import BM25Indexer


@pytest.fixture
def temp_index_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def sample_records():
    return [
        ChunkRecord(
            id="chunk_1",
            text="hello world hello",
            metadata={},
            sparse_vector={"hello": 2.0, "world": 1.0},
        ),
        ChunkRecord(
            id="chunk_2",
            text="hello machine learning",
            metadata={},
            sparse_vector={"hello": 1.0, "machine": 1.0, "learning": 1.0},
        ),
        ChunkRecord(
            id="chunk_3",
            text="world wide web",
            metadata={},
            sparse_vector={"world": 1.0, "wide": 1.0, "web": 1.0},
        ),
    ]


class TestBM25IndexerBuild:
    def test_build_basic(self, temp_index_dir, sample_records):
        indexer = BM25Indexer(index_dir=temp_index_dir)
        indexer.build(sample_records)

        stats = indexer.stats
        assert stats["total_documents"] == 3
        assert stats["total_terms"] > 0

    def test_build_empty_records(self, temp_index_dir):
        indexer = BM25Indexer(index_dir=temp_index_dir)
        indexer.build([])

        stats = indexer.stats
        assert stats["total_documents"] == 0

    def test_build_ignores_null_sparse_vector(self, temp_index_dir):
        records = [
            ChunkRecord(id="1", text="hello world", metadata={}, sparse_vector=None),
            ChunkRecord(id="2", text="test text", metadata={}, sparse_vector={"test": 1.0}),
        ]
        indexer = BM25Indexer(index_dir=temp_index_dir)
        indexer.build(records)

        assert indexer.stats["total_documents"] == 1


class TestBM25IndexerQuery:
    def test_query_single_keyword(self, temp_index_dir, sample_records):
        indexer = BM25Indexer(index_dir=temp_index_dir)
        indexer.build(sample_records)

        results = indexer.query(["hello"], top_k=10)

        assert len(results) > 0
        assert all("chunk_id" in r and "score" in r for r in results)
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_query_multiple_keywords(self, temp_index_dir, sample_records):
        indexer = BM25Indexer(index_dir=temp_index_dir)
        indexer.build(sample_records)

        results = indexer.query(["hello", "world"], top_k=10)

        assert len(results) > 0
        assert results[0]["chunk_id"] in ["chunk_1", "chunk_2", "chunk_3"]

    def test_query_empty_keywords(self, temp_index_dir, sample_records):
        indexer = BM25Indexer(index_dir=temp_index_dir)
        indexer.build(sample_records)

        results = indexer.query([], top_k=10)
        assert results == []

    def test_query_top_k_limit(self, temp_index_dir, sample_records):
        indexer = BM25Indexer(index_dir=temp_index_dir)
        indexer.build(sample_records)

        results = indexer.query(["hello"], top_k=1)
        assert len(results) <= 1

    def test_query_no_matching_terms(self, temp_index_dir, sample_records):
        indexer = BM25Indexer(index_dir=temp_index_dir)
        indexer.build(sample_records)

        results = indexer.query(["xyz123"], top_k=10)
        assert results == []


class TestBM25IndexerPersistence:
    def test_save_and_load(self, temp_index_dir, sample_records):
        indexer = BM25Indexer(index_dir=temp_index_dir)
        indexer.build(sample_records)
        indexer.save(collection="test")

        new_indexer = BM25Indexer(index_dir=temp_index_dir)
        loaded = new_indexer.load(collection="test")

        assert loaded is True
        assert new_indexer.stats["total_documents"] == 3

    def test_save_creates_directory(self, temp_index_dir, sample_records):
        indexer = BM25Indexer(index_dir=temp_index_dir)
        indexer.build(sample_records)

        index_file = indexer.save(collection="test")

        assert index_file.exists()

    def test_load_returns_false_for_missing_file(self, temp_index_dir):
        indexer = BM25Indexer(index_dir=temp_index_dir)
        loaded = indexer.load(collection="nonexistent")

        assert loaded is False


class TestBM25IndexerCRUD:
    def test_add_documents_incremental(self, temp_index_dir, sample_records):
        indexer = BM25Indexer(index_dir=temp_index_dir)
        indexer.build(sample_records[:2])

        initial_stats = indexer.stats
        assert initial_stats["total_documents"] == 2

        indexer.add_documents(sample_records[2:])

        final_stats = indexer.stats
        assert final_stats["total_documents"] == 3

    def test_remove_documents(self, temp_index_dir, sample_records):
        indexer = BM25Indexer(index_dir=temp_index_dir)
        indexer.build(sample_records)

        indexer.remove_documents({"chunk_1"})

        stats = indexer.stats
        assert stats["total_documents"] == 2

        results = indexer.query(["hello"], top_k=10)
        assert all(r["chunk_id"] != "chunk_1" for r in results)


class TestBM25IDFCalculation:
    def test_idf_calculation_known_corpus(self, temp_index_dir):
        records = [
            ChunkRecord(id="1", text="cat", metadata={}, sparse_vector={"cat": 1.0}),
            ChunkRecord(id="2", text="dog", metadata={}, sparse_vector={"dog": 1.0}),
            ChunkRecord(id="3", text="mouse", metadata={}, sparse_vector={"mouse": 1.0}),
        ]
        indexer = BM25Indexer(index_dir=temp_index_dir)
        indexer.build(records)

        idf_cat = indexer._calculate_idf(1)
        assert idf_cat > 0

    def test_idf_with_higher_df(self, temp_index_dir):
        records = [
            ChunkRecord(id="1", text="the cat", metadata={}, sparse_vector={"the": 1.0, "cat": 1.0}),
            ChunkRecord(id="2", text="the dog", metadata={}, sparse_vector={"the": 1.0, "dog": 1.0}),
            ChunkRecord(id="3", text="the bird", metadata={}, sparse_vector={"the": 1.0, "bird": 1.0}),
        ]
        indexer = BM25Indexer(index_dir=temp_index_dir)
        indexer.build(records)

        idf_the = indexer._calculate_idf(3)
        idf_cat = indexer._calculate_idf(1)

        assert idf_the == 0.0
        assert idf_cat > 0


class TestBM25QueryRoundtrip:
    def test_query_returns_stable_results(self, temp_index_dir, sample_records):
        indexer = BM25Indexer(index_dir=temp_index_dir)
        indexer.build(sample_records)

        results1 = indexer.query(["hello"], top_k=10)
        results2 = indexer.query(["hello"], top_k=10)

        assert results1 == results2

    def test_full_pipeline_build_save_query(self, temp_index_dir):
        records = [
            ChunkRecord(id=f"doc_{i}", text=f"text content {i}", metadata={}, sparse_vector={"text": 1.0, f"content_{i}": 1.0})
            for i in range(5)
        ]

        indexer = BM25Indexer(index_dir=temp_index_dir)
        indexer.build(records)
        index_path = indexer.save(collection="pipeline_test")

        new_indexer = BM25Indexer(index_dir=temp_index_dir)
        new_indexer.load(collection="pipeline_test")

        results = new_indexer.query(["text"], top_k=5)
        assert len(results) > 0
