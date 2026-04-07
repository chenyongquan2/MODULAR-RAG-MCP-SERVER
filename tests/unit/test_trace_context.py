"""单元测试：TraceContext 追踪上下文。"""

import time
import pytest

from src.core.trace.trace_context import TraceContext, TraceStage


class TestTraceStage:
    """TraceStage 类的单元测试。"""

    def test_basic_creation(self):
        """测试基本创建。"""
        stage = TraceStage(name="test_stage", start_time=time.time())
        assert stage.name == "test_stage"
        assert stage.end_time is None
        assert stage.data == {}

    def test_finish_sets_end_time(self):
        """测试 finish() 设置 end_time。"""
        stage = TraceStage(name="test_stage", start_time=time.time())
        time.sleep(0.01)  # 等待一小段时间
        stage.finish()
        assert stage.end_time is not None
        assert stage.end_time > stage.start_time

    def test_finish_with_data(self):
        """测试 finish() 携带额外数据。"""
        stage = TraceStage(name="test_stage", start_time=time.time())
        stage.finish({"key": "value"})
        assert stage.data["key"] == "value"

    def test_duration_ms_when_finished(self):
        """测试已结束时 duration_ms 计算正确。"""
        stage = TraceStage(name="test_stage", start_time=1000.0)
        stage.end_time = 1000.5  # 500ms
        assert stage.duration_ms == 500.0

    def test_duration_ms_when_not_finished(self):
        """测试未结束时 duration_ms 返回 None。"""
        stage = TraceStage(name="test_stage", start_time=time.time())
        assert stage.duration_ms is None


class TestTraceContext:
    """TraceContext 类的单元测试。"""

    def test_basic_creation(self):
        """测试基本创建。"""
        ctx = TraceContext(trace_type="query")
        assert ctx.trace_id is not None
        assert ctx.trace_type == "query"
        assert ctx.stages == []
        assert ctx.metadata == {}

    def test_start_stage(self):
        """测试开始新阶段。"""
        ctx = TraceContext()
        stage = ctx.start_stage("ingestion")
        assert stage.name == "ingestion"
        assert stage.end_time is None
        assert len(ctx.stages) == 1

    def test_finish_stage(self):
        """测试结束指定阶段。"""
        ctx = TraceContext()
        ctx.start_stage("ingestion")
        time.sleep(0.01)
        ctx.finish_stage("ingestion")
        stage = ctx.get_stage("ingestion")
        assert stage is not None
        assert stage.end_time is not None

    def test_finish_stage_not_found(self):
        """测试结束不存在的阶段抛出错误。"""
        ctx = TraceContext()
        with pytest.raises(ValueError, match="Stage not found or already finished"):
            ctx.finish_stage("nonexistent")

    def test_get_stage(self):
        """测试获取指定阶段。"""
        ctx = TraceContext()
        ctx.start_stage("stage1")
        ctx.start_stage("stage2")
        stage = ctx.get_stage("stage1")
        assert stage is not None
        assert stage.name == "stage1"

    def test_get_stage_not_found(self):
        """测试获取不存在的阶段返回 None。"""
        ctx = TraceContext()
        ctx.start_stage("stage1")
        assert ctx.get_stage("nonexistent") is None

    def test_finish_marks_trace_complete(self):
        """测试 finish() 标记整个 trace 完成。"""
        ctx = TraceContext()
        ctx.start_stage("stage1")
        time.sleep(0.01)
        ctx.finish()
        assert hasattr(ctx, "_end_time")
        assert ctx._end_time is not None

    def test_finish_closes_open_stages(self):
        """测试 finish() 自动关闭未结束的 stage。"""
        ctx = TraceContext()
        stage1 = ctx.start_stage("stage1")
        ctx.start_stage("stage2")  # 未关闭
        ctx.start_stage("stage3")  # 未关闭
        ctx.finish()
        # stage1 应该已经被 finish() 自动关闭
        assert stage1.end_time is not None
        # stage2 和 stage3 也应该被自动关闭
        assert ctx.get_stage("stage2").end_time is not None
        assert ctx.get_stage("stage3").end_time is not None

    def test_finish_with_metadata(self):
        """测试 finish() 携带额外元数据。"""
        ctx = TraceContext()
        ctx.start_stage("stage1")
        ctx.finish({"final_status": "success"})
        assert ctx.metadata["final_status"] == "success"

    def test_total_duration_ms(self):
        """测试总耗时计算正确。"""
        ctx = TraceContext()
        ctx.start_stage("stage1")
        time.sleep(0.05)
        ctx.finish()
        duration = ctx.total_duration_ms
        assert duration is not None
        assert duration >= 50  # 至少 50ms
        assert duration < 1000  # 不超过 1 秒

    def test_total_duration_ms_before_finish(self):
        """测试未 finish() 前 total_duration_ms 返回 None。"""
        ctx = TraceContext()
        ctx.start_stage("stage1")
        assert ctx.total_duration_ms is None

    def test_total_duration_ms_empty_stages(self):
        """测试没有 stage 时 total_duration_ms 返回 None。"""
        ctx = TraceContext()
        assert ctx.total_duration_ms is None

    def test_to_dict(self):
        """测试序列化为字典。"""
        ctx = TraceContext(trace_type="query", metadata={"key": "value"})
        ctx.start_stage("stage1")
        ctx.finish_stage("stage1", {"info": "test"})
        data = ctx.to_dict()
        assert data["trace_id"] == ctx.trace_id
        assert data["trace_type"] == "query"
        assert data["metadata"]["key"] == "value"
        assert len(data["stages"]) == 1
        assert data["stages"][0]["name"] == "stage1"
        assert data["stages"][0]["end_time"] is not None
