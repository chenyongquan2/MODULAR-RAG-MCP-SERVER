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


# ===========================================================================
# Feature-004 T015/T016/T017: v2 磁盘格式
# ===========================================================================


class TestIndexFormatV2:
    """v2 磁盘格式契约。

    见 specs/004-retrieval-infra-fix/contracts/bm25_index.schema.md。

    v2 存在的理由:新 chunk_id 是路径式、平均 91 字符(旧的 38),叠加中文
    bigram 带来的约 6 倍倒排项增长,沿用 v1 格式索引会从 38 MB 涨到 156 MB。
    标识字典化后回落到约 17 MB。
    """

    def _built(self, temp_index_dir, sample_records):
        indexer = BM25Indexer(index_dir=temp_index_dir)
        indexer.build(sample_records, collection="c")
        indexer.save(collection="c")
        return indexer

    def _raw(self, temp_index_dir):
        return json.loads((Path(temp_index_dir) / "c.json").read_text(encoding="utf-8"))

    def test_writes_format_version(self, temp_index_dir, sample_records):
        self._built(temp_index_dir, sample_records)
        assert self._raw(temp_index_dir)["_format_version"] == 2

    def test_chunk_ids_table_present_and_unique(self, temp_index_dir, sample_records):
        self._built(temp_index_dir, sample_records)
        raw = self._raw(temp_index_dir)
        assert isinstance(raw["chunk_ids"], list)
        assert len(raw["chunk_ids"]) == len(set(raw["chunk_ids"]))

    def test_postings_are_integer_index_pairs(self, temp_index_dir, sample_records):
        """倒排项必须是 [下标, tf],不再内嵌完整标识字符串。"""
        self._built(temp_index_dir, sample_records)
        raw = self._raw(temp_index_dir)

        n = len(raw["chunk_ids"])
        for term, entry in raw["index"].items():
            for posting in entry["postings"]:
                assert isinstance(posting, list) and len(posting) == 2, term
                chunk_index, tf = posting
                assert isinstance(chunk_index, int)
                assert 0 <= chunk_index < n
                assert isinstance(tf, int)

    def test_doc_length_not_duplicated_in_postings(self, temp_index_dir, sample_records):
        """顶层 doc_lengths 已有完整映射,倒排项内不得再存一份。"""
        self._built(temp_index_dir, sample_records)
        raw = self._raw(temp_index_dir)

        serialized = json.dumps(raw["index"])
        assert "doc_length" not in serialized

    def test_doc_lengths_aligned_with_chunk_ids(self, temp_index_dir, sample_records):
        self._built(temp_index_dir, sample_records)
        raw = self._raw(temp_index_dir)
        assert len(raw["doc_lengths"]) == len(raw["chunk_ids"])
        assert len(raw["chunk_ids"]) == raw["total_documents"]

    def test_no_indentation(self, temp_index_dir, sample_records):
        """缩进约占体积一半 —— 磁盘上遗留的 v1 文件带 indent=4。"""
        self._built(temp_index_dir, sample_records)
        text = (Path(temp_index_dir) / "c.json").read_text(encoding="utf-8")
        assert "\n    " not in text

    def test_roundtrip_preserves_query_results(self, temp_index_dir, sample_records):
        """压缩编码不得改变检索行为。"""
        original = self._built(temp_index_dir, sample_records)
        before = original.query(["hello"], top_k=10)

        reloaded = BM25Indexer(index_dir=temp_index_dir)
        assert reloaded.load(collection="c") is True
        after = reloaded.query(["hello"], top_k=10)

        assert before == after

    def test_roundtrip_restores_doc_length_in_memory(self, temp_index_dir, sample_records):
        """doc_length 不落盘,但加载后内存结构里必须被还原。"""
        self._built(temp_index_dir, sample_records)

        reloaded = BM25Indexer(index_dir=temp_index_dir)
        reloaded.load(collection="c")

        for entry in reloaded._index.values():
            for posting in entry["postings"]:
                assert posting["doc_length"] == reloaded._doc_lengths[posting["chunk_id"]]


class TestIndexFormatVersionGate:
    """版本校验必须**硬失败**,不允许静默降级(宪法原则三)。

    Feature-004 修的三个缺陷全是「静默失效」—— 不报错,只是结果悄悄变空。
    若这里留静默降级路径,等于在刚修好的地方重新埋雷。
    """

    def _write_raw(self, temp_index_dir, payload):
        path = Path(temp_index_dir) / "c.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_v1_file_raises_value_error(self, temp_index_dir):
        """v1 文件(无 _format_version)必须抛错并提示重建。"""
        self._write_raw(
            temp_index_dir,
            {
                "index": {"hello": {"idf": 1.0, "postings": [
                    {"chunk_id": "c1", "tf": 2.0, "doc_length": 5}
                ]}},
                "doc_lengths": {"c1": 5},
                "total_documents": 1,
                "avg_doc_length": 5.0,
                "k1": 1.5,
                "b": 0.75,
            },
        )

        indexer = BM25Indexer(index_dir=temp_index_dir)
        with pytest.raises(ValueError, match="rebuild_bm25_index"):
            indexer.load(collection="c")

    def test_future_version_raises_value_error(self, temp_index_dir):
        self._write_raw(temp_index_dir, {"_format_version": 99, "chunk_ids": [], "doc_lengths": []})

        indexer = BM25Indexer(index_dir=temp_index_dir)
        with pytest.raises(ValueError, match="_format_version"):
            indexer.load(collection="c")

    def test_missing_file_still_returns_false(self, temp_index_dir):
        """文件不存在不是错误 —— 沿用 v1 行为。"""
        assert BM25Indexer(index_dir=temp_index_dir).load(collection="nope") is False

    def test_corrupt_json_still_returns_false(self, temp_index_dir):
        (Path(temp_index_dir) / "c.json").write_text("{not json", encoding="utf-8")
        assert BM25Indexer(index_dir=temp_index_dir).load(collection="c") is False

    def test_length_mismatch_detected(self, temp_index_dir):
        self._write_raw(
            temp_index_dir,
            {"_format_version": 2, "chunk_ids": ["a", "b"], "doc_lengths": [1], "index": {}},
        )
        indexer = BM25Indexer(index_dir=temp_index_dir)
        with pytest.raises(ValueError, match="length mismatch"):
            indexer.load(collection="c")

    def test_out_of_range_index_detected(self, temp_index_dir):
        self._write_raw(
            temp_index_dir,
            {
                "_format_version": 2,
                "chunk_ids": ["a"],
                "doc_lengths": [3],
                "index": {"t": {"idf": 1.0, "postings": [[7, 1]]}},
            },
        )
        indexer = BM25Indexer(index_dir=temp_index_dir)
        with pytest.raises(ValueError, match="out of range"):
            indexer.load(collection="c")


class TestAtomicSave:
    """写入必须原子替换(FR-003)。"""

    def test_no_temp_files_left_after_success(self, temp_index_dir, sample_records):
        indexer = BM25Indexer(index_dir=temp_index_dir)
        indexer.build(sample_records, collection="c")
        indexer.save(collection="c")

        leftovers = [p.name for p in Path(temp_index_dir).glob(".*tmp")]
        assert leftovers == []

    def test_existing_index_survives_failed_save(self, temp_index_dir, sample_records, monkeypatch):
        """序列化中途抛错时,既有可用索引不得被破坏。"""
        indexer = BM25Indexer(index_dir=temp_index_dir)
        indexer.build(sample_records, collection="c")
        indexer.save(collection="c")

        good = (Path(temp_index_dir) / "c.json").read_text(encoding="utf-8")

        monkeypatch.setattr(
            BM25Indexer, "_serialize", lambda self: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        with pytest.raises(RuntimeError):
            indexer.save(collection="c")

        assert (Path(temp_index_dir) / "c.json").read_text(encoding="utf-8") == good
        assert [p.name for p in Path(temp_index_dir).glob(".*tmp")] == []
