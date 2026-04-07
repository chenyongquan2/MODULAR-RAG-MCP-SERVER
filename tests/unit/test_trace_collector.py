"""单元测试：TraceCollector 追踪收集器。"""

import json
import os
import pytest

from src.core.trace.trace_context import TraceContext
from src.core.trace.trace_collector import TraceCollector


class TestTraceCollector:
    """TraceCollector 类的单元测试。"""

    def test_collect_single_trace(self, tmp_path):
        """测试收集单条 trace。

        验证 TraceCollector.collect() 能正确将 trace 写入文件。
        """
        collector = TraceCollector(output_dir=str(tmp_path))
        trace = TraceContext(trace_type="query")
        trace.start_stage("test")
        trace.finish()

        collector.collect(trace)

        # 验证文件存在且内容正确
        traces = collector.get_traces()
        assert len(traces) == 1
        assert traces[0]["trace_id"] == trace.trace_id
        assert traces[0]["trace_type"] == "query"

    def test_collect_multiple_traces(self, tmp_path):
        """测试收集多条 trace。

        验证多次 collect() 调用能正确追加到文件。
        """
        collector = TraceCollector(output_dir=str(tmp_path))

        for i in range(3):
            trace = TraceContext(trace_type="query")
            trace.start_stage(f"stage_{i}")
            trace.finish()
            collector.collect(trace)

        traces = collector.get_traces()
        assert len(traces) == 3

    def test_get_traces_by_type(self, tmp_path):
        """测试按类型过滤 trace。

        验证 get_traces(trace_type=...) 能正确过滤不同类型的 trace。
        """
        collector = TraceCollector(output_dir=str(tmp_path))

        # 创建 query 类型 trace
        query_trace = TraceContext(trace_type="query")
        query_trace.start_stage("search")
        query_trace.finish()
        collector.collect(query_trace)

        # 创建 ingestion 类型 trace
        ingestion_trace = TraceContext(trace_type="ingestion")
        ingestion_trace.start_stage("load")
        ingestion_trace.finish()
        collector.collect(ingestion_trace)

        # 过滤 query 类型
        query_traces = collector.get_traces(trace_type="query")
        assert len(query_traces) == 1
        assert query_traces[0]["trace_type"] == "query"

        # 过滤 ingestion 类型
        ingestion_traces = collector.get_traces(trace_type="ingestion")
        assert len(ingestion_traces) == 1
        assert ingestion_traces[0]["trace_type"] == "ingestion"

    def test_get_traces_with_limit(self, tmp_path):
        """测试限制返回条数。

        验证 limit 参数能正确限制返回的 trace 数量。
        """
        collector = TraceCollector(output_dir=str(tmp_path))

        # 创建 5 条 trace
        for i in range(5):
            trace = TraceContext(trace_type="query")
            trace.start_stage(f"stage_{i}")
            trace.finish()
            collector.collect(trace)

        # 只返回 3 条
        traces = collector.get_traces(limit=3)
        assert len(traces) == 3

    def test_get_traces_empty_file(self, tmp_path):
        """测试文件不存在时返回空列表。

        验证文件不存在时 get_traces() 返回空列表而非报错。
        """
        collector = TraceCollector(output_dir=str(tmp_path))
        collector.clear()  # 确保文件不存在

        traces = collector.get_traces()
        assert traces == []

    def test_clear(self, tmp_path):
        """测试清空 trace 文件。

        验证 clear() 能正确删除输出文件。
        """
        collector = TraceCollector(output_dir=str(tmp_path))

        # 创建一条 trace
        trace = TraceContext(trace_type="query")
        trace.start_stage("test")
        trace.finish()
        collector.collect(trace)

        # 验证文件存在
        assert os.path.exists(collector.output_path)

        # 清空
        collector.clear()

        # 验证文件已删除
        assert not os.path.exists(collector.output_path)


class TestTraceContextToDictFields:
    """验证 TraceContext.to_dict() 包含验收标准要求的所有字段。"""

    def test_to_dict_includes_required_fields(self):
        """验证 to_dict() 包含所有验收标准字段。

        验收标准要求：trace_id, trace_type, started_at, finished_at, total_elapsed_ms, stages
        """
        trace = TraceContext(trace_type="query")
        trace.start_stage("test")
        trace.finish()

        trace_dict = trace.to_dict()

        # 验收标准要求的字段
        assert "trace_id" in trace_dict, "缺少 trace_id 字段"
        assert "trace_type" in trace_dict, "缺少 trace_type 字段"
        assert "started_at" in trace_dict, "缺少 started_at 字段"
        assert "finished_at" in trace_dict, "缺少 finished_at 字段"
        assert "total_elapsed_ms" in trace_dict, "缺少 total_elapsed_ms 字段"
        assert "stages" in trace_dict, "缺少 stages 字段"

    def test_to_dict_started_at_value(self):
        """验证 started_at 值为第一个 stage 的 start_time。"""
        trace = TraceContext(trace_type="query")
        trace.start_stage("first")
        trace.start_stage("second")
        trace.finish()

        trace_dict = trace.to_dict()
        first_stage = trace.stages[0]

        assert trace_dict["started_at"] == first_stage.start_time

    def test_to_dict_finished_at_value(self):
        """验证 finished_at 值为 _end_time 属性。"""
        trace = TraceContext(trace_type="query")
        trace.start_stage("test")
        trace.finish()

        trace_dict = trace.to_dict()
        assert trace_dict["finished_at"] == trace._end_time

    def test_to_dict_total_elapsed_ms_value(self):
        """验证 total_elapsed_ms 值为总耗时毫秒数。"""
        trace = TraceContext(trace_type="query")
        trace.start_stage("test")
        trace.finish()

        trace_dict = trace.to_dict()
        assert trace_dict["total_elapsed_ms"] == trace.total_duration_ms

    def test_to_dict_json_serializable(self):
        """验证 to_dict() 输出可被 json.dumps() 序列化。

        这是验收标准之一：输出 dict 可直接 json.dumps() 序列化。
        """
        trace = TraceContext(trace_type="query")
        trace.start_stage("test")
        trace.finish()

        trace_dict = trace.to_dict()

        # 如果可序列化则不抛异常
        json_str = json.dumps(trace_dict)
        assert len(json_str) > 0

        # 反序列化验证数据完整性
        parsed = json.loads(json_str)
        assert parsed["trace_id"] == trace.trace_id
        assert parsed["trace_type"] == "query"

    def test_to_dict_without_finish(self):
        """验证未调用 finish() 时字段值正确。"""
        trace = TraceContext(trace_type="query")
        trace.start_stage("test")
        # 不调用 finish()

        trace_dict = trace.to_dict()

        # started_at 仍应有值
        assert trace_dict["started_at"] is not None
        # finished_at 应为 None（未完成）
        assert trace_dict["finished_at"] is None
        # total_elapsed_ms 应为 None（未完成）
        assert trace_dict["total_elapsed_ms"] is None

    def test_to_dict_empty_stages(self):
        """验证没有 stage 时 started_at 为 None。"""
        trace = TraceContext(trace_type="query")
        # 不创建任何 stage

        trace_dict = trace.to_dict()

        assert trace_dict["started_at"] is None
        assert trace_dict["finished_at"] is None
        assert trace_dict["total_elapsed_ms"] is None