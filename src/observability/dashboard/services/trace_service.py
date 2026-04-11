"""Trace 数据服务。

负责从 traces.jsonl 读取追踪数据并提供查询接口。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.trace.trace_context import TraceContext


class TraceRecord:
    """追踪记录封装类。

    从 traces.jsonl 解析的单条追踪记录，提供便捷的访问方法。
    """

    def __init__(self, data: Dict[str, Any]) -> None:
        """初始化追踪记录。

        Args:
            data: 从 traces.jsonl 解析的字典数据
        """
        self._data = data

    @property
    def trace_id(self) -> str:
        """获取追踪 ID。"""
        return self._data.get("trace_id", "")

    @property
    def trace_type(self) -> str:
        """获取追踪类型 (ingestion/query)。"""
        return self._data.get("trace_type", "unknown")

    @property
    def status(self) -> str:
        """获取状态 (success/failed/skipped)。"""
        return self._data.get("metadata", {}).get("status", "unknown")

    @property
    def collection(self) -> str:
        """获取集合名称。"""
        return self._data.get("metadata", {}).get("collection", "")

    @property
    def file_path(self) -> str:
        """获取文件路径。"""
        return self._data.get("metadata", {}).get("file_path", "")

    @property
    def total_elapsed_ms(self) -> Optional[float]:
        """获取总耗时（毫秒）。"""
        return self._data.get("total_elapsed_ms")

    @property
    def stage_count(self) -> int:
        """获取阶段数量。"""
        return self._data.get("metadata", {}).get("stage_count", 0)

    @property
    def stages(self) -> List[Dict[str, Any]]:
        """获取所有阶段数据。"""
        return self._data.get("stages", [])

    @property
    def timestamp(self) -> Optional[str]:
        """获取时间戳字符串。"""
        return self._data.get("timestamp")

    @property
    def timestamp_dt(self) -> Optional[datetime]:
        """获取时间戳的 datetime 对象。"""
        ts = self.timestamp
        if ts:
            try:
                return datetime.fromisoformat(ts)
            except ValueError:
                return None
        return None

    def get_stage_duration(self, stage_name: str) -> Optional[float]:
        """获取指定阶段的耗时。

        Args:
            stage_name: 阶段名称 (load/split/transform/embed/upsert)

        Returns:
            阶段耗时（毫秒），未找到返回 None
        """
        for stage in self.stages:
            if stage.get("name") == stage_name:
                return stage.get("duration_ms")
        return None

    def get_stage_data(self, stage_name: str) -> Optional[Dict[str, Any]]:
        """获取指定阶段的额外数据。

        Args:
            stage_name: 阶段名称

        Returns:
            阶段的 data 字段内容
        """
        for stage in self.stages:
            if stage.get("name") == stage_name:
                return stage.get("data")
        return None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典。"""
        return self._data


class TraceService:
    """Trace 数据服务。

    负责读取并解析 traces.jsonl 文件，提供查询接口。
    """

    # 默认 trace 日志文件路径
    DEFAULT_TRACE_FILE = Path("logs/traces.jsonl")

    def __init__(self, trace_file: Optional[Path] = None) -> None:
        """初始化 Trace 服务。

        Args:
            trace_file: trace 日志文件路径，默认为 logs/traces.jsonl
        """
        self._trace_file = trace_file or self.DEFAULT_TRACE_FILE
        self._records: List[TraceRecord] = []

    def load(self) -> List[TraceRecord]:
        """加载并解析 trace 日志文件。

        Returns:
            解析后的追踪记录列表，按时间倒序排列
        """
        self._records = []

        if not self._trace_file.exists():
            return []

        try:
            with open(self._trace_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        # 只解析完整的 trace 记录（包含 trace_id）
                        if "trace_id" in data:
                            self._records.append(TraceRecord(data))
                    except json.JSONDecodeError:
                        # 跳过无效的 JSON 行
                        continue

            # 按时间倒序排列
            self._records.sort(key=lambda r: r.timestamp_dt or datetime.min, reverse=True)
        except Exception:
            # 文件读取失败时返回空列表
            self._records = []

        return self._records

    def get_ingestion_traces(self, limit: int = 100) -> List[TraceRecord]:
        """获取 Ingestion 类型的追踪记录。

        Args:
            limit: 最大返回数量

        Returns:
            ingestion 类型的追踪记录列表
        """
        if not self._records:
            self.load()

        return [r for r in self._records if r.trace_type == "ingestion"][:limit]

    def get_query_traces(self, limit: int = 100) -> List[TraceRecord]:
        """获取 Query 类型的追踪记录。

        Args:
            limit: 最大返回数量

        Returns:
            query 类型的追踪记录列表
        """
        if not self._records:
            self.load()

        return [r for r in self._records if r.trace_type == "query"][:limit]

    def get_trace_by_id(self, trace_id: str) -> Optional[TraceRecord]:
        """根据 trace_id 获取追踪记录。

        Args:
            trace_id: 追踪 ID

        Returns:
            追踪记录，未找到返回 None
        """
        if not self._records:
            self.load()

        for record in self._records:
            if record.trace_id == trace_id:
                return record
        return None

    def get_all(self) -> List[TraceRecord]:
        """获取所有追踪记录。

        Returns:
            所有追踪记录列表
        """
        if not self._records:
            self.load()
        return self._records

    @property
    def trace_file(self) -> Path:
        """获取 trace 文件路径。"""
        return self._trace_file

    @property
    def is_available(self) -> bool:
        """检查 trace 文件是否可用。"""
        return self._trace_file.exists() and self._trace_file.stat().st_size > 0
