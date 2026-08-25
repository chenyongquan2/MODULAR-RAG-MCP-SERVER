"""Trace 数据服务。

负责从 traces.jsonl 读取追踪数据并提供查询接口。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.trace.trace_context import TraceContext
from src.observability.logger import get_logger

logger = get_logger(__name__)


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
        matches = [s for s in self.stages if s.get("name") == stage_name]
        if not matches:
            return None
        self._warn_if_ambiguous(stage_name, len(matches))
        return matches[0].get("duration_ms")

    def get_stage_data(self, stage_name: str) -> Optional[Dict[str, Any]]:
        """获取指定阶段的额外数据。

        Args:
            stage_name: 阶段名称

        Returns:
            阶段的 data 字段内容
        """
        matches = [s for s in self.stages if s.get("name") == stage_name]
        if not matches:
            return None
        self._warn_if_ambiguous(stage_name, len(matches))
        return matches[0].get("data")

    def _warn_if_ambiguous(self, stage_name: str, count: int) -> None:
        """同名阶段多于一个时喊出来 —— 「只取第一个」不能是静默行为。

        写入侧(``TraceContext.start_stage``)**允许**重名:它无条件 append,
        ``finish_stage`` 逆序配对,所以嵌套的同名阶段能正常收尾、不报错。
        而这里的读取侧一直是「命中即返回」—— 两端不对称。

        2026-08-25 补:目前五个阶段名各不相同(实测最近 200 条 trace 零重名),
        所以这是**潜伏态**而不是当下的 bug。但多路检索一上(N 个改写各产生一个
        ``dense_retrieval``),面板就只会显示第 1 路的耗时与命中数,**其余静默丢失**
        —— 而延迟分析恰恰是多路场景下最要紧的东西。

        刻意**不实现**「返回全部同名阶段」:现在没有调用方需要它,为不存在的需求
        做设计就是又一个 ``rerank.top_m``。这里只负责让信息丢失**可见** ——
        真要引入多路时,这条 warning 会是第一个撞上的东西。
        """
        if count > 1:
            logger.warning(
                "trace %s 有 %d 个同名阶段 %r,读取侧只取第一个 —— "
                "其余 %d 个的耗时与数据在面板上不可见。"
                "若这是多路检索引入的,需先让阶段名可区分(例如带路径后缀)",
                self.trace_id[:8],
                count,
                stage_name,
                count - 1,
            )

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
