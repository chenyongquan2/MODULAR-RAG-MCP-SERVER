"""单元测试：TraceService。

测试 TraceService 从 traces.jsonl 读取并解析追踪数据的功能。
"""

from pathlib import Path
from datetime import datetime

import pytest
from src.observability.dashboard.services.trace_service import TraceService, TraceRecord


TEST_TRACE_DATA = [
    {
        "trace_id": "test-trace-001",
        "trace_type": "ingestion",
        "started_at": 1234567890.123,
        "finished_at": 1234567895.456,
        "total_elapsed_ms": 5333.0,
        "stages": [
            {
                "name": "load",
                "start_time": 1234567890.123,
                "end_time": 1234567891.234,
                "duration_ms": 1111.0,
                "data": {
                    "method": "PdfLoader",
                    "doc_id": "doc_123",
                    "text_length": 5000,
                    "image_count": 2,
                    "error": None,
                },
            },
            {
                "name": "split",
                "start_time": 1234567891.234,
                "end_time": 1234567892.345,
                "duration_ms": 1111.0,
                "data": {
                    "method": "RecursiveCharacterTextSplitter",
                    "doc_id": "doc_123",
                    "chunk_count": 10,
                    "error": None,
                },
            },
            {
                "name": "transform",
                "start_time": 1234567892.345,
                "end_time": 1234567893.456,
                "duration_ms": 1111.0,
                "data": {
                    "method": "ChunkRefiner",
                    "input_count": 10,
                    "output_count": 10,
                    "has_images": True,
                    "error": None,
                },
            },
            {
                "name": "embed",
                "start_time": 1234567893.456,
                "end_time": 1234567894.567,
                "duration_ms": 1111.0,
                "data": {
                    "method": "OpenAIEmbedding",
                    "input_count": 10,
                    "record_count": 10,
                    "error": None,
                },
            },
            {
                "name": "upsert",
                "start_time": 1234567894.567,
                "end_time": 1234567895.456,
                "duration_ms": 889.0,
                "data": {
                    "method": "ChromaStore",
                    "collection": "test_collection",
                    "chunk_count": 10,
                    "bm25_index_path": "/tmp/bm25.idx",
                    "error": None,
                },
            },
        ],
        "metadata": {
            "file_path": "/path/to/test.pdf",
            "collection": "test_collection",
            "status": "success",
            "stage_count": 5,
        },
        "timestamp": "2024-01-01T12:00:00.000000+00:00",
    },
    {
        "trace_id": "test-trace-002",
        "trace_type": "ingestion",
        "started_at": 1234567896.789,
        "finished_at": 1234567897.890,
        "total_elapsed_ms": 1101.0,
        "stages": [
            {
                "name": "load",
                "start_time": 1234567896.789,
                "end_time": 1234567897.890,
                "duration_ms": 1101.0,
                "data": {
                    "method": "PdfLoader",
                    "doc_id": "",
                    "text_length": 0,
                    "image_count": 0,
                    "error": "PDF解析失败",
                },
            },
        ],
        "metadata": {
            "file_path": "/path/to/failed.pdf",
            "collection": "test_collection",
            "status": "failed",
            "stage_count": 1,
        },
        "timestamp": "2024-01-01T12:01:00.000000+00:00",
    },
    {
        "trace_id": "test-trace-003",
        "trace_type": "query",
        "started_at": 1234567900.123,
        "finished_at": 1234567902.456,
        "total_elapsed_ms": 2333.0,
        "stages": [
            {
                "name": "query_processing",
                "start_time": 1234567900.123,
                "end_time": 1234567900.234,
                "duration_ms": 111.0,
                "data": {
                    "query": "北极星是什么",
                    "filters": {},
                    "error": None,
                },
            },
            {
                "name": "dense",
                "start_time": 1234567900.234,
                "end_time": 1234567901.234,
                "duration_ms": 1000.0,
                "data": {
                    "method": "ChromaStore",
                    "collection": "test_collection",
                    "result_count": 10,
                    "error": None,
                },
            },
            {
                "name": "sparse",
                "start_time": 1234567901.234,
                "end_time": 1234567901.567,
                "duration_ms": 333.0,
                "data": {
                    "method": "BM25",
                    "collection": "test_collection",
                    "result_count": 10,
                    "error": None,
                },
            },
            {
                "name": "fusion",
                "start_time": 1234567901.567,
                "end_time": 1234567902.234,
                "duration_ms": 667.0,
                "data": {
                    "method": "RRF",
                    "final_count": 10,
                    "error": None,
                },
            },
            {
                "name": "rerank",
                "start_time": 1234567902.234,
                "end_time": 1234567902.456,
                "duration_ms": 222.0,
                "data": {
                    "method": "LLMReranker",
                    "reranked_count": 10,
                    "error": None,
                },
            },
        ],
        "metadata": {
            "query": "北极星是什么",
            "status": "success",
            "stage_count": 5,
        },
        "timestamp": "2024-01-01T12:05:00.000000+00:00",
    },
]


class TestTraceRecord:
    """测试 TraceRecord 类。"""

    def test_properties(self) -> None:
        """测试 TraceRecord 的属性访问。"""
        data = TEST_TRACE_DATA[0]
        record = TraceRecord(data)

        assert record.trace_id == "test-trace-001"
        assert record.trace_type == "ingestion"
        assert record.status == "success"
        assert record.collection == "test_collection"
        assert record.file_path == "/path/to/test.pdf"
        assert record.total_elapsed_ms == 5333.0
        assert record.stage_count == 5
        assert len(record.stages) == 5
        assert record.timestamp == "2024-01-01T12:00:00.000000+00:00"

    def test_stage_duration(self) -> None:
        """测试获取阶段耗时。"""
        record = TraceRecord(TEST_TRACE_DATA[0])

        assert record.get_stage_duration("load") == 1111.0
        assert record.get_stage_duration("split") == 1111.0
        assert record.get_stage_duration("transform") == 1111.0
        assert record.get_stage_duration("embed") == 1111.0
        assert record.get_stage_duration("upsert") == 889.0
        assert record.get_stage_duration("nonexistent") is None

    def test_stage_data(self) -> None:
        """测试获取阶段数据。"""
        record = TraceRecord(TEST_TRACE_DATA[0])

        load_data = record.get_stage_data("load")
        assert load_data is not None
        assert load_data["method"] == "PdfLoader"
        assert load_data["doc_id"] == "doc_123"
        assert load_data["image_count"] == 2

        assert record.get_stage_data("nonexistent") is None

    def test_to_dict(self) -> None:
        """测试转换为字典。"""
        data = TEST_TRACE_DATA[0]
        record = TraceRecord(data)

        assert record.to_dict() == data


class TestTraceService:
    """测试 TraceService 类。"""

    def test_load_empty_file(self, tmp_path: Path) -> None:
        """测试加载不存在的文件。"""
        trace_file = tmp_path / "nonexistent.jsonl"
        service = TraceService(trace_file)

        records = service.load()

        assert records == []
        assert not service.is_available

    def test_load_valid_file(self, tmp_path: Path) -> None:
        """测试加载有效的 trace 文件。"""
        trace_file = tmp_path / "traces.jsonl"

        # 写入测试数据
        import json

        with open(trace_file, "w", encoding="utf-8") as f:
            for trace in TEST_TRACE_DATA:
                f.write(json.dumps(trace) + "\n")

        service = TraceService(trace_file)
        records = service.load()

        assert len(records) == 3
        assert service.is_available

        # 验证按时间倒序排列
        assert records[0].timestamp_dt > records[1].timestamp_dt
        assert records[1].timestamp_dt > records[2].timestamp_dt

    def test_get_ingestion_traces(self, tmp_path: Path) -> None:
        """测试获取 ingestion 类型的追踪记录。"""
        trace_file = tmp_path / "traces.jsonl"

        # 写入测试数据
        import json

        with open(trace_file, "w", encoding="utf-8") as f:
            for trace in TEST_TRACE_DATA:
                f.write(json.dumps(trace) + "\n")

        service = TraceService(trace_file)
        ingestion_traces = service.get_ingestion_traces()

        assert len(ingestion_traces) == 2
        assert all(t.trace_type == "ingestion" for t in ingestion_traces)

    def test_get_query_traces(self, tmp_path: Path) -> None:
        """测试获取 query 类型的追踪记录。"""
        trace_file = tmp_path / "traces.jsonl"

        # 写入测试数据
        import json

        with open(trace_file, "w", encoding="utf-8") as f:
            for trace in TEST_TRACE_DATA:
                f.write(json.dumps(trace) + "\n")

        service = TraceService(trace_file)
        query_traces = service.get_query_traces()

        assert len(query_traces) == 1
        assert query_traces[0].trace_type == "query"

    def test_get_trace_by_id(self, tmp_path: Path) -> None:
        """测试根据 trace_id 获取追踪记录。"""
        trace_file = tmp_path / "traces.jsonl"

        # 写入测试数据
        import json

        with open(trace_file, "w", encoding="utf-8") as f:
            for trace in TEST_TRACE_DATA:
                f.write(json.dumps(trace) + "\n")

        service = TraceService(trace_file)

        # 测试存在的 ID
        trace = service.get_trace_by_id("test-trace-001")
        assert trace is not None
        assert trace.trace_id == "test-trace-001"

        # 测试不存在的 ID
        trace = service.get_trace_by_id("nonexistent")
        assert trace is None

    def test_invalid_json_lines(self, tmp_path: Path) -> None:
        """测试处理包含无效 JSON 行的文件。"""
        trace_file = tmp_path / "traces.jsonl"

        # 写入包含无效行的测试数据
        with open(trace_file, "w", encoding="utf-8") as f:
            import json

            f.write(json.dumps(TEST_TRACE_DATA[0]) + "\n")
            f.write("invalid json\n")
            f.write(json.dumps(TEST_TRACE_DATA[1]) + "\n")

        service = TraceService(trace_file)
        records = service.load()

        # 应该跳过无效行，只解析有效的记录
        assert len(records) == 2

    def test_records_without_trace_id(self, tmp_path: Path) -> None:
        """测试处理不包含 trace_id 的记录。"""
        trace_file = tmp_path / "traces.jsonl"

        # 写入包含 trace_id 和不包含 trace_id 的记录
        with open(trace_file, "w", encoding="utf-8") as f:
            import json

            f.write(json.dumps(TEST_TRACE_DATA[0]) + "\n")  # 包含 trace_id
            f.write(json.dumps({"trace_type": "test", "data": "no id"}) + "\n")  # 不包含 trace_id
            f.write(json.dumps(TEST_TRACE_DATA[1]) + "\n")  # 包含 trace_id

        service = TraceService(trace_file)
        records = service.load()

        # 应该只包含有 trace_id 的记录
        assert len(records) == 2

    def test_get_all(self, tmp_path: Path) -> None:
        """测试获取所有追踪记录。"""
        trace_file = tmp_path / "traces.jsonl"

        # 写入测试数据
        import json

        with open(trace_file, "w", encoding="utf-8") as f:
            for trace in TEST_TRACE_DATA:
                f.write(json.dumps(trace) + "\n")

        service = TraceService(trace_file)
        all_records = service.get_all()

        assert len(all_records) == 3