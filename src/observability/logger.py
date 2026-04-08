"""结构化日志模块。

提供 get_logger 函数，输出到 stderr。同时提供 JSON Lines 格式的 trace 日志功能，
用于将 trace 追加写入 logs/traces.jsonl。
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


class JSONFormatter(logging.Formatter):
    """自定义 JSON 格式日志 Formatter。

    将每条日志记录转换为 JSON 字符串输出，便于结构化解析和分析。
    支持通过 LogRecord 的 extra_fields 属性添加额外字段。
    """

    def format(self, record: logging.LogRecord) -> str:
        log_dict: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # 支持通过 extra_fields 注入额外字段（如 trace_id, trace_type 等）
        if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
            log_dict.update(record.extra_fields)
        return json.dumps(log_dict, ensure_ascii=False)


def get_logger(name: str) -> logging.Logger:
    """获取配置好的 Logger 实例。

    日志输出到 stderr，避免污染 stdout（MCP 协议要求 stdout 仅用于协议消息）。

    Args:
        name: Logger 名称，通常使用 ``__name__``。

    Returns:
        配置好的 Logger 实例。
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    return logger


def get_trace_logger(name: str = "trace") -> logging.Logger:
    """获取配置了 JSON Lines 输出的 logger（输出到 logs/traces.jsonl）。

    该 logger 使用 JSONFormatter，将每条日志格式化为 JSON 行写入文件。
    适用于需要结构化 trace 输出的场景，如与 Streamlit dashboard 配合使用。

    Args:
        name: Logger 名称，默认为 "trace"

    Returns:
        配置好的 Logger 实例，输出到 logs/traces.jsonl
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "traces.jsonl", encoding="utf-8")
        file_handler.setFormatter(JSONFormatter())
        logger.addHandler(file_handler)
    return logger


def write_trace(trace_dict: Dict[str, Any]) -> None:
    """将 trace 字典追加写入 logs/traces.jsonl（每行一个 JSON）。

    写入时自动添加 timestamp 字段（如果不存在），格式为 ISO 8601 UTC 时间。
    每次调用追加一行，是 JSONL 格式的追加写入操作。

    Args:
        trace_dict: trace 数据字典，通常由 TraceContext.to_dict() 生成

    Example:
        >>> from core.trace.trace_context import TraceContext
        >>> from observability.logger import write_trace
        >>> trace = TraceContext(trace_type="query")
        >>> trace.start_stage("search")
        >>> trace.finish()
        >>> write_trace(trace.to_dict())  # 追加写入 traces.jsonl
    """
    # 追加 timestamp 如果未提供
    trace_dict.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    trace_file = log_dir / "traces.jsonl"
    with open(trace_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(trace_dict, ensure_ascii=False) + "\n")
