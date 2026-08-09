"""Unit tests for `scripts/rebuild_bm25_index.py` (Feature-004 T018/T019/T020)。

测试范围：

1. **标识同源**（FR-001 的核心）：重建出的索引，其 chunk 标识必须与向量库一致
2. 正文为空的记录被跳过并计入报告，而非中断重建
3. 统计报告的各项数字正确（FR-013）
4. 零 embedding 调用（SC-005）—— 重建只读正文，不碰 embedding provider

不触碰真实向量库，全部用内存替身。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import pytest

sys.path.insert(0, ".")

from scripts import rebuild_bm25_index as rbi
from src.core.settings import load_settings

pytestmark = pytest.mark.unit


_REAL_CONFIG = "config/settings.yaml"


class FakeStore:
    """内存向量库替身。"""

    def __init__(self, records: List[Dict[str, Any]]) -> None:
        self._records = records
        self.include_vectors_seen: List[bool] = []

    def iter_records(
        self,
        include_vectors: bool = False,
        batch_size: int = 1000,
        **kwargs: Any,
    ) -> Iterator[Dict[str, Any]]:
        self.include_vectors_seen.append(include_vectors)
        for record in self._records:
            out = {
                "id": record["id"],
                "text": record.get("text", ""),
                "metadata": dict(record.get("metadata", {})),
            }
            if include_vectors:
                out["vector"] = record.get("vector", [])
            yield out

    def get_by_ids(self, ids: List[str], trace: Any = None, **kwargs: Any) -> List[Dict[str, Any]]:
        known = {r["id"] for r in self._records}
        return [{"id": i, "text": "", "metadata": {}} for i in ids if i in known]


def _record(rid: str, text: str, collection: str = "alpha") -> Dict[str, Any]:
    return {"id": rid, "text": text, "metadata": {"collection": collection}}


@pytest.fixture()
def settings(tmp_path):
    s = load_settings(_REAL_CONFIG)
    s.vector_store.bm25_index_path = str(tmp_path)
    return s


@pytest.fixture()
def records():
    return [
        _record("C:\\ws\\ingest_source\\doc.chm_0_aaa", "hello world hello retrieval"),
        _record("C:\\ws\\ingest_source\\doc.chm_1_bbb", "world of vector search"),
        _record("C:\\ws\\ingest_source\\doc.chm_2_ccc", "retrieval augmented generation"),
    ]


class TestIdentifierProvenance:
    """FR-001 的核心：索引标识必须与向量库同源。"""

    def test_index_chunk_ids_match_store_ids(self, settings, records, monkeypatch, tmp_path):
        store = FakeStore(records)
        monkeypatch.setattr(rbi, "_store_for", lambda s, c: store)

        rbi.rebuild_collection(settings, "alpha")

        raw = json.loads((tmp_path / "alpha.json").read_text(encoding="utf-8"))
        assert set(raw["chunk_ids"]) == {r["id"] for r in records}

    def test_id_verification_reports_full_hit(self, settings, records, monkeypatch):
        """回查命中率必须是 100% —— 修复前实测 0/200。"""
        store = FakeStore(records)
        monkeypatch.setattr(rbi, "_store_for", lambda s, c: store)

        stats = rbi.rebuild_collection(settings, "alpha")

        assert stats.id_verify_sampled == 3
        assert stats.id_verify_hit == 3
        assert stats.id_hit_rate == 1.0

    def test_id_verification_detects_mismatch(self, settings, records, monkeypatch):
        """回查是真检查而非摆设：向量库取不到时命中率必须掉下来。"""
        store = FakeStore(records)
        monkeypatch.setattr(rbi, "_store_for", lambda s, c: store)
        monkeypatch.setattr(store, "get_by_ids", lambda ids, **kw: [])

        stats = rbi.rebuild_collection(settings, "alpha")

        assert stats.id_verify_sampled == 3
        assert stats.id_verify_hit == 0
        assert stats.id_hit_rate == 0.0


class TestEmptyTextHandling:
    def test_empty_text_skipped_and_reported(self, settings, monkeypatch):
        records = [
            _record("a_0_h", "real content here"),
            _record("b_0_h", ""),
            _record("c_0_h", "   "),
        ]
        store = FakeStore(records)
        monkeypatch.setattr(rbi, "_store_for", lambda s, c: store)

        stats = rbi.rebuild_collection(settings, "alpha")

        assert stats.chunk_count == 1
        assert set(stats.skipped_empty_text) == {"b_0_h", "c_0_h"}

    def test_all_empty_writes_no_index(self, settings, monkeypatch, tmp_path):
        """全空时不写出索引 —— 免得用一个空索引覆盖掉可用的旧索引。"""
        store = FakeStore([_record("a_0_h", "")])
        monkeypatch.setattr(rbi, "_store_for", lambda s, c: store)

        stats = rbi.rebuild_collection(settings, "alpha")

        assert stats.index_path is None
        assert not (tmp_path / "alpha.json").exists()


class TestNoEmbeddingCalls:
    def test_reads_without_vectors(self, settings, records, monkeypatch):
        """重建只需正文 —— 带上向量纯属浪费内存（SC-005 的实现侧保证）。"""
        store = FakeStore(records)
        monkeypatch.setattr(rbi, "_store_for", lambda s, c: store)

        rbi.rebuild_collection(settings, "alpha")

        assert store.include_vectors_seen == [False]

    def test_script_does_not_import_embedding_factory(self):
        """脚本不得引入 embedding 工厂 —— 引入即有误调 API 的可能。"""
        source = Path("scripts/rebuild_bm25_index.py").read_text(encoding="utf-8")
        assert "EmbeddingFactory" not in source
        assert "DenseEncoder" not in source


class TestStatsReport:
    """FR-013：统计报告让验收者不读代码也能判断达标与否。"""

    def test_term_and_chunk_counts(self, settings, records, monkeypatch):
        store = FakeStore(records)
        monkeypatch.setattr(rbi, "_store_for", lambda s, c: store)

        stats = rbi.rebuild_collection(settings, "alpha")

        assert stats.chunk_count == 3
        assert stats.term_count > 0
        assert stats.index_bytes > 0

    def test_cjk_ratio_zero_for_ascii_corpus(self, settings, records, monkeypatch):
        store = FakeStore(records)
        monkeypatch.setattr(rbi, "_store_for", lambda s, c: store)

        stats = rbi.rebuild_collection(settings, "alpha")

        assert stats.cjk_term_count == 0
        assert stats.cjk_ratio == 0.0

    def test_cjk_ratio_counts_chinese_terms(self, settings, monkeypatch):
        """中文词条统计本身要正确，否则 SC-003 无法验收。

        注：此处直接构造带中文词条的索引来验证**统计逻辑**；切分器能否产出
        中文词条是 T022 之后的事（见 tests/unit/test_tokenizer.py）。
        """
        stats = rbi.CollectionStats(collection="x", term_count=10, cjk_term_count=6)
        assert stats.cjk_ratio == pytest.approx(0.6)

    def test_zero_division_guarded(self):
        stats = rbi.CollectionStats(collection="x")
        assert stats.cjk_ratio == 0.0
        assert stats.id_hit_rate == 0.0


class TestInspectOnly:
    def test_detects_v1_index_as_missing_version(self, settings, tmp_path):
        (tmp_path / "legacy.json").write_text(
            json.dumps({"index": {"a": {}}, "total_documents": 1}), encoding="utf-8"
        )

        info = rbi.inspect_collection(settings, "legacy")

        assert info["exists"] is True
        assert "缺失" in str(info["format_version"])

    def test_missing_index_reported(self, settings):
        info = rbi.inspect_collection(settings, "nope")
        assert info["exists"] is False

    def test_corrupt_index_reported_not_raised(self, settings, tmp_path):
        (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
        info = rbi.inspect_collection(settings, "bad")
        assert "error" in info
