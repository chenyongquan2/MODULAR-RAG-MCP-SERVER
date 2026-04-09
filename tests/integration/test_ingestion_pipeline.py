"""IngestionPipeline 链路打点集成测试。"""

from pathlib import Path

from src.core.trace.trace_context import TraceContext
from src.core.types import Chunk, ChunkRecord, Document
from src.ingestion.pipeline import IngestionPipeline


class _FakeIntegrityChecker:
    """用于测试的完整性检查器。"""

    def compute_sha256(self, file_path: str) -> str:
        return f"sha256-{Path(file_path).name}"

    def should_skip(self, file_hash: str) -> bool:
        return False

    def mark_success(
        self,
        file_hash: str,
        file_path: str,
        file_size: int,
        chunk_count: int,
    ) -> None:
        return None

    def mark_failed(self, file_hash: str, file_path: str, error_msg: str) -> None:
        return None


class _FakeLoader:
    """用于测试的文档加载器。"""

    def load(self, file_path: str) -> Document:
        return Document(
            id="doc_test_001",
            text="这是一个用于 tracing 的测试文档。",
            metadata={"source_path": file_path, "images": []},
        )


class _FakeChunker:
    """用于测试的切分器。"""

    def split_document(self, document: Document, trace=None):
        return [
            Chunk(
                id="chunk_1",
                text="chunk text",
                metadata={"source_path": document.metadata["source_path"]},
                source_ref=document.id,
            )
        ]


class _PassThroughTransform:
    """用于测试的透传 transform。"""

    def transform(self, chunks, trace=None):
        return chunks


class _FakeDenseEncoder:
    """用于测试的稠密编码器。"""

    def encode(self, chunks, trace=None):
        return [
            ChunkRecord(
                id=c.id,
                text=c.text,
                metadata=c.metadata,
                dense_vector=[0.1, 0.2, 0.3],
            )
            for c in chunks
        ]


class _FakeSparseEncoder:
    """用于测试的稀疏编码器。"""

    def encode(self, chunks, trace=None):
        return [
            ChunkRecord(
                id=c.id,
                text=c.text,
                metadata=c.metadata,
                sparse_vector={"test": 1.0},
            )
            for c in chunks
        ]


class _FakeVectorUpserter:
    """用于测试的向量存储器。"""

    def upsert(self, records, trace=None):
        return None


class _FakeBM25Indexer:
    """用于测试的 BM25 索引器。"""

    def build(self, records, collection: str):
        return None

    def save(self, collection: str):
        # 返回一个稳定路径即可
        return Path("data/db/bm25") / f"{collection}.json"



def _build_pipeline() -> IngestionPipeline:
    """构造可控依赖的 pipeline，避免真实外部依赖。"""
    pipeline = IngestionPipeline(
        settings=object(),  # settings 在该测试路径中不会被实际使用
        collection="test_collection",
        chunker=_FakeChunker(),
        transform=_PassThroughTransform(),
        metadata_enricher=_PassThroughTransform(),
        image_captioner=_PassThroughTransform(),
        text_enricher=_PassThroughTransform(),
        dense_encoder=_FakeDenseEncoder(),
        sparse_encoder=_FakeSparseEncoder(),
        vector_upserter=_FakeVectorUpserter(),
        bm25_indexer=_FakeBM25Indexer(),
        integrity_checker=_FakeIntegrityChecker(),
    )
    # 用 fake loader 覆盖文件后缀分派逻辑，保持测试稳定
    pipeline._get_loader = lambda _file_path: _FakeLoader()
    return pipeline


def test_ingestion_pipeline_records_trace_stages(tmp_path):
    """验证 ingestion trace 包含 F4 要求的五个阶段。"""
    file_path = tmp_path / "input.md"
    file_path.write_text("test", encoding="utf-8")

    pipeline = _build_pipeline()
    trace = TraceContext(trace_type="ingestion")

    result = pipeline.run(str(file_path), force=True, trace=trace)
    trace.finish()
    trace_dict = trace.to_dict()

    assert result["status"] == "success"
    assert trace_dict["trace_type"] == "ingestion"

    stages = trace_dict["stages"]
    stage_names = [stage["name"] for stage in stages]

    # F4 验收标准：必须包含以下 5 个阶段
    assert "load" in stage_names
    assert "split" in stage_names
    assert "transform" in stage_names
    assert "embed" in stage_names
    assert "upsert" in stage_names

    for stage in stages:
        assert stage["duration_ms"] is not None
        assert "method" in stage["data"]

    stage_map = {stage["name"]: stage["data"] for stage in stages}
    assert stage_map["load"]["doc_id"] == "doc_test_001"
    assert stage_map["split"]["chunk_count"] == 1
    assert stage_map["embed"]["record_count"] == 1
    assert stage_map["upsert"]["chunk_count"] == 1
