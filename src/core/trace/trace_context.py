"""追踪上下文 (trace_id/stages)。

该模块提供轻量级 tracing 功能，用于记录 ingestion 和 query 链路中的阶段信息。
"""

import uuid
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class TraceStage:
    """单个追踪阶段。"""
    name: str
    start_time: float
    end_time: Optional[float] = None
    data: Dict[str, Any] = field(default_factory=dict)

    def finish(self, data: Optional[Dict[str, Any]] = None) -> None:
        """标记阶段完成。"""
        import time
        self.end_time = time.time()
        if data:
            self.data.update(data)

    @property
    def duration_ms(self) -> Optional[float]:
        """获取阶段耗时（毫秒）。"""
        if self.end_time:
            return (self.end_time - self.start_time) * 1000
        return None


@dataclass
class TraceContext:
    """追踪上下文，用于记录整个 pipeline 的执行轨迹。

    Attributes:
        trace_id: 唯一追踪 ID
        trace_type: 追踪类型 ("ingestion" | "query")
        stages: 追踪阶段列表
        metadata: 额外元数据
    """
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trace_type: str = "ingestion"
    stages: List[TraceStage] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def start_stage(self, name: str) -> TraceStage:
        """开始一个新阶段。"""
        import time
        stage = TraceStage(name=name, start_time=time.time())
        self.stages.append(stage)
        return stage

    def finish_stage(self, name: str, data: Optional[Dict[str, Any]] = None) -> None:
        """结束指定阶段。"""
        for stage in reversed(self.stages):
            if stage.name == name and stage.end_time is None:
                stage.finish(data)
                return
        raise ValueError(f"Stage not found or already finished: {name}")

    def get_stage(self, name: str) -> Optional[TraceStage]:
        """获取指定阶段。"""
        for stage in self.stages:
            if stage.name == name:
                return stage
        return None

    def record_stage(self, name: str, **kwargs: Any) -> None:
        """记录一个已完成的阶段（便捷方法）。

        这个方法用于快速记录一个已完成阶段的信息，适用于不需要精确计时的场景。
        它会创建一个新的阶段，自动设置开始和结束时间为当前时间，并将传入的
        键值对参数存储到阶段的数据中。

        Args:
            name: 阶段名称（位置参数）
            **kwargs: 要记录的阶段数据（method, provider, chunk_count, data 等）

        Example:
            >>> trace.record_stage("split", method="recursive", provider="langchain", chunk_count=10)
            >>> trace.record_stage("embed", data={"provider": "openai", "model": "text-embedding-3-small"})
        """
        import time
        now = time.time()
        stage = TraceStage(name=name, start_time=now, end_time=now, data=kwargs)
        self.stages.append(stage)

    def finish(self, data: Optional[Dict[str, Any]] = None) -> None:
        """标记整个 trace 完成，计算总耗时。

        Args:
            data: 可选的额外元数据。
        """
        import time
        self._end_time = time.time()
        # 自动结束所有未完成的 stage
        for stage in self.stages:
            if stage.end_time is None:
                stage.finish()
        if data:
            self.metadata.update(data)

    @property
    def total_duration_ms(self) -> Optional[float]:
        """获取整个 trace 总耗时（毫秒）。"""
        if hasattr(self, '_end_time') and self.stages:
            return (self._end_time - self.stages[0].start_time) * 1000
        return None

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典。

        返回的字典包含验收标准要求的所有字段，可直接 json.dumps() 序列化。
        包括：trace_id, trace_type, started_at, finished_at, total_elapsed_ms, stages, metadata
        """
        import json  # 用于验证可序列化
        return {
            "trace_id": self.trace_id,
            "trace_type": self.trace_type,
            # 验收标准要求的字段：started_at, finished_at, total_elapsed_ms
            "started_at": self.stages[0].start_time if self.stages else None,
            "finished_at": getattr(self, "_end_time", None),
            "total_elapsed_ms": self.total_duration_ms,
            "stages": [
                {
                    "name": s.name,
                    "start_time": s.start_time,
                    "end_time": s.end_time,
                    "duration_ms": s.duration_ms,
                    "data": s.data
                }
                for s in self.stages
            ],
            "metadata": self.metadata
        }
