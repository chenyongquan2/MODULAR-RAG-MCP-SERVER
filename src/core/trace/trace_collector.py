"""追踪收集器 - 收集并持久化 trace 到 JSONL 文件。

该模块提供 TraceCollector 类，用于将 TraceContext 实例收集并持久化到日志文件。
遵循 tracing 系统的配置驱动原则，输出路径可通过参数配置。
"""

import json
import os
from typing import Any, Dict, List, Optional

from .trace_context import TraceContext


class TraceCollector:
    """追踪收集器，将 trace 持久化到 JSONL 文件。

    TraceCollector 负责将 TraceContext 实例写入 JSONL 格式的日志文件。
    JSONL 格式便于流式追加写入，适合生产环境的高频 tracing。

    Attributes:
        output_path: 输出文件路径（包含目录和文件名）

    Example:
        >>> collector = TraceCollector()
        >>> trace = TraceContext(trace_type="query")
        >>> trace.start_stage("search")
        >>> trace.finish()
        >>> collector.collect(trace)  # 写入 logs/traces.jsonl

        >>> # 读取 trace
        >>> traces = collector.get_traces(trace_type="query", limit=10)
    """

    def __init__(self, output_dir: str = "logs", output_file: str = "traces.jsonl"):
        """初始化收集器。

        Args:
            output_dir: 输出目录，默认为 "logs"
            output_file: 输出文件名，默认为 "traces.jsonl"
        """
        self.output_path = os.path.join(output_dir, output_file)
        os.makedirs(output_dir, exist_ok=True)

    def collect(self, trace: TraceContext) -> None:
        """收集 trace 并持久化到 JSONL 文件。

        将 TraceContext.to_dict() 的结果追加到 JSONL 文件末尾。
        每次调用写入一条 JSON 行，便于流式处理。

        Args:
            trace: TraceContext 实例

        Raises:
            IOError: 文件写入失败时抛出异常
        """
        trace_dict = trace.to_dict()
        with open(self.output_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(trace_dict, ensure_ascii=False) + "\n")

    def get_traces(
        self,
        trace_type: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """从 JSONL 文件读取 trace。

        Args:
            trace_type: 可选，按 trace_type 过滤（如 "query", "ingestion"）
            limit: 返回条数限制，默认为 100

        Returns:
            trace 字典列表，按写入顺序返回
        """
        traces: List[Dict[str, Any]] = []
        if not os.path.exists(self.output_path):
            return traces

        with open(self.output_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    trace = json.loads(line)
                    if trace_type is None or trace.get("trace_type") == trace_type:
                        traces.append(trace)
                        if len(traces) >= limit:
                            break
        return traces

    def clear(self) -> None:
        """清空 trace 文件。

        删除输出文件（如果存在），常用于测试或日志轮转。
        """
        if os.path.exists(self.output_path):
            os.remove(self.output_path)