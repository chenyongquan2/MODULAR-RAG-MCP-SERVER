"""Unit tests for `scripts/migrate_collections.py` (Feature-004 T008/T009/T010).

测试范围:

1. ``scan_source`` 的分组统计与可疑数据识别
2. **临时残留的判据**:必须靠源路径识别,不能靠 ``metadata.collection`` 缺失
   —— 实测那 10 条残留都老老实实标着 ``default``
3. ``migrate`` 的复制语义:源数据不变、向量随行、幂等
4. **单遍扫描**:多个目标集合只应扫描源集合一次(带向量重复读 5 万条代价很高)

不触碰真实向量库,全部用内存替身。
"""

from __future__ import annotations

import sys
from typing import Any, Dict, Iterator, List, Optional

import pytest

sys.path.insert(0, ".")

from scripts import migrate_collections as mc

pytestmark = pytest.mark.unit


class RecordingStore:
    """内存向量库替身,记录被调用的次数以便断言单遍扫描。"""

    def __init__(self, records: Optional[List[Dict[str, Any]]] = None) -> None:
        self._store: Dict[str, Dict[str, Any]] = {}
        for record in records or []:
            self._store[record["id"]] = record
        self.iter_calls = 0
        self.upsert_calls = 0

    def iter_records(
        self,
        include_vectors: bool = False,
        batch_size: int = 1000,
        **kwargs: Any,
    ) -> Iterator[Dict[str, Any]]:
        self.iter_calls += 1
        for record in list(self._store.values()):
            out: Dict[str, Any] = {
                "id": record["id"],
                "text": record.get("text", ""),
                "metadata": dict(record.get("metadata", {})),
            }
            if include_vectors:
                out["vector"] = list(record.get("vector", []))
            yield out

    def upsert(self, records: List[Dict[str, Any]], trace: Any = None, **kwargs: Any) -> None:
        self.upsert_calls += 1
        for record in records:
            self._store[record["id"]] = record

    def ids(self) -> set:
        return set(self._store)


def _record(rid: str, label: str, text: str = "hello") -> Dict[str, Any]:
    return {
        "id": rid,
        "vector": [1.0, 2.0, 3.0],
        "text": text,
        "metadata": {"collection": label, "doc_type": "md"},
    }


@pytest.fixture()
def source_records() -> List[Dict[str, Any]]:
    """构造一个缩微版的真实布局:两个大集合 + 同源集合 + 临时残留。"""
    records = [_record(f"C:\\ws\\ingest_source\\en.chm_{i}_h", "mt5_docs_english") for i in range(4)]
    records += [_record(f"C:\\ws\\ingest_source\\zh.chm_{i}_h", "mt5_docs_chinese") for i in range(3)]
    records += [_record("C:\\ws\\asset\\policy.md_0_h", "default")]
    # 临时残留:注意它标着 default,**不是**元数据缺失
    records += [
        _record(f"C:\\Users\\x\\AppData\\Local\\Temp\\tmpabc123.md_{i}_h", "default")
        for i in range(2)
    ]
    return records


class TestScanSource:
    def test_groups_by_metadata_collection(self, source_records):
        plan = mc.scan_source(RecordingStore(source_records), source="default")

        assert plan.total_scanned == 10
        assert plan.groups == {
            "mt5_docs_english": 4,
            "mt5_docs_chinese": 3,
            "default": 3,  # 1 正常 + 2 临时残留
        }

    def test_temp_residue_detected_by_path_not_by_missing_label(self, source_records):
        """核心判据回归。

        实测 10 条残留的 ``metadata.collection`` 都是 ``default`` —— 若按
        「元数据缺失」识别,一条都抓不到。判据必须是源路径指向临时目录。
        """
        plan = mc.scan_source(RecordingStore(source_records), source="default")

        assert len(plan.temp_residue) == 2
        assert all("Temp" in rid for rid in plan.temp_residue)
        # 它们并没有被当成 unlabeled
        assert plan.unlabeled == []
        # 而且仍被计入了 default 分组
        assert plan.groups["default"] == 3

    def test_unlabeled_records_reported_and_not_grouped(self):
        records = [_record("a_0_h", "alpha")]
        records.append({"id": "b_0_h", "vector": [1.0], "text": "t", "metadata": {}})
        records.append({"id": "c_0_h", "vector": [1.0], "text": "t", "metadata": {"collection": ""}})

        plan = mc.scan_source(RecordingStore(records), source="default")

        assert plan.groups == {"alpha": 1}
        assert set(plan.unlabeled) == {"b_0_h", "c_0_h"}

    def test_targets_excludes_source_named_group(self, source_records):
        plan = mc.scan_source(RecordingStore(source_records), source="default")
        assert plan.targets() == ["mt5_docs_chinese", "mt5_docs_english"]

    def test_empty_source(self):
        plan = mc.scan_source(RecordingStore([]), source="default")
        assert plan.total_scanned == 0
        assert plan.groups == {}
        assert plan.targets() == []


class TestMigrate:
    @pytest.fixture()
    def targets(self, monkeypatch):
        """把 ``_store_for`` 换成内存替身,避免触碰真实向量库。"""
        created: Dict[str, RecordingStore] = {}

        def fake_store_for(settings: Any, collection: str) -> RecordingStore:
            return created.setdefault(collection, RecordingStore())

        monkeypatch.setattr(mc, "_store_for", fake_store_for)
        return created

    def test_copies_only_matching_records(self, source_records, targets):
        source = RecordingStore(source_records)
        written = mc.migrate(None, source, ["mt5_docs_english", "mt5_docs_chinese"])

        assert written == {"mt5_docs_english": 4, "mt5_docs_chinese": 3}
        assert len(targets["mt5_docs_english"].ids()) == 4
        assert len(targets["mt5_docs_chinese"].ids()) == 3

    def test_source_unchanged_copy_semantics(self, source_records, targets):
        """复制语义:源集合必须一条不少、一条不改(FR-006 / SC-007)。"""
        source = RecordingStore(source_records)
        before = source.ids()

        mc.migrate(None, source, ["mt5_docs_english"])

        assert source.ids() == before
        assert source.upsert_calls == 0

    def test_vectors_carried_not_regenerated(self, source_records, targets):
        """向量必须随行 —— 重新生成有真实 API 成本(SC-005)。"""
        mc.migrate(None, RecordingStore(source_records), ["mt5_docs_english"])

        for record in targets["mt5_docs_english"]._store.values():
            assert record["vector"] == [1.0, 2.0, 3.0]

    def test_metadata_deep_copied(self, source_records, targets):
        """目标侧改元数据不得回写污染源数据。"""
        source = RecordingStore(source_records)
        mc.migrate(None, source, ["mt5_docs_english"])

        migrated = next(iter(targets["mt5_docs_english"]._store.values()))
        migrated["metadata"]["doc_type"] = "MUTATED"

        for record in source._store.values():
            assert record["metadata"]["doc_type"] == "md"

    def test_idempotent(self, source_records, targets):
        """重复执行不产生重复记录(按 id upsert)。"""
        source = RecordingStore(source_records)

        first = mc.migrate(None, source, ["mt5_docs_english"])
        count_after_first = len(targets["mt5_docs_english"].ids())
        second = mc.migrate(None, source, ["mt5_docs_english"])

        assert first == second
        assert len(targets["mt5_docs_english"].ids()) == count_after_first

    def test_single_pass_over_source(self, source_records, targets):
        """多个目标只扫描源集合一次。

        ``include_vectors=True`` 时每条记录带 1536 维向量,按目标逐个扫描
        会把 5 万条向量重复读 N 遍 —— 这条断言守住单遍实现。
        """
        source = RecordingStore(source_records)
        mc.migrate(None, source, ["mt5_docs_english", "mt5_docs_chinese", "default"])

        assert source.iter_calls == 1

    def test_no_targets_is_noop(self, source_records, targets):
        source = RecordingStore(source_records)
        assert mc.migrate(None, source, []) == {}
        assert source.iter_calls == 0

    def test_batching_does_not_change_result(self, source_records, targets):
        source = RecordingStore(source_records)
        written = mc.migrate(None, source, ["mt5_docs_english"], batch_size=1)

        assert written == {"mt5_docs_english": 4}
        assert len(targets["mt5_docs_english"].ids()) == 4


class TestTempPathPattern:
    """临时路径判据本身的边界。"""

    @pytest.mark.parametrize(
        "path",
        [
            r"C:\Users\x\AppData\Local\Temp\tmpg0csbti9.md_0_e28dd56b",
            r"/tmp/tmpabc123.md_0_h",
            r"C:\Users\x\AppData\Local\Temp\anything.md_1_h",
        ],
    )
    def test_matches_temp_paths(self, path):
        assert mc._TEMP_PATH_PATTERN.search(path)

    @pytest.mark.parametrize(
        "path",
        [
            r"C:\workspace\MODULAR-RAG-MCP-SERVER\ingest_source\MetaTrader5SDK_English.chm_1925_a09",
            r"C:\workspace\asset\finpoints_handbook\00_company.md_0_h",
            r"/home/user/documents/template.md_0_h",
        ],
    )
    def test_does_not_match_normal_paths(self, path):
        """不能误伤正常路径 —— 例如含 'template' 的文件名里有 'temp'。"""
        assert not mc._TEMP_PATH_PATTERN.search(path)
