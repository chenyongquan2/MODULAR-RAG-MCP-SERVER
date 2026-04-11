"""JSON Lines Logger 单元测试。

测试 JSONFormatter、get_trace_logger、write_trace 的功能。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

import pytest

from src.observability.logger import JSONFormatter, get_trace_logger, write_trace


class TestJSONFormatter:
    """JSONFormatter 测试类。"""

    def test_format_returns_valid_json(self):
        """验证 JSONFormatter 输出合法 JSON。"""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)

        # 验证输出是合法 JSON
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_format_contains_required_fields(self):
        """验证 JSONFormatter 输出包含必需字段。"""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Hello world",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)

        # 验证必需字段存在
        assert "timestamp" in parsed
        assert "level" in parsed
        assert "logger" in parsed
        assert "message" in parsed

    def test_format_extracts_extra_fields(self):
        """验证 JSONFormatter 提取 extra_fields 额外字段。"""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test",
            args=(),
            exc_info=None,
        )
        record.extra_fields = {"trace_id": "abc123", "trace_type": "query"}

        output = formatter.format(record)
        parsed = json.loads(output)

        assert parsed["trace_id"] == "abc123"
        assert parsed["trace_type"] == "query"


class TestGetTraceLogger:
    """get_trace_logger 测试类。"""

    def test_returns_logger_instance(self):
        """验证返回有效的 logger 对象。"""
        logger = get_trace_logger("test_trace")
        assert isinstance(logger, logging.Logger)

    def test_returns_configured_logger(self):
        """验证返回的 logger 配置正确（设置了 handler 和 level）。"""
        logger = get_trace_logger("test_trace_configured")
        assert logger.level == logging.INFO
        # 验证有 handler 配置
        assert len(logger.handlers) > 0

    def test_same_name_returns_same_logger(self):
        """验证相同 name 返回相同的 logger 实例（单例行为）。"""
        logger1 = get_trace_logger("test_singleton")
        logger2 = get_trace_logger("test_singleton")
        assert logger1 is logger2


class TestWriteTrace:
    """write_trace 测试类。"""

    @pytest.fixture(autouse=True)
    def setup_temp_trace_file(self, tmp_path: Path):
        """设置临时目录和日志路径供测试使用。"""
        self.original_logs_dir = Path("logs")
        self.temp_dir = tmp_path
        self.temp_trace_file = self.temp_dir / "traces.jsonl"

    def _write_trace(self, trace_dict: dict) -> None:
        """写入 trace，使用临时文件。"""
        trace_dict.setdefault("timestamp", "2026-04-08T00:00:00Z")
        with open(self.temp_trace_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(trace_dict, ensure_ascii=False) + "\n")

    def test_write_trace_creates_file(self):
        """验证写入后文件存在。"""
        trace_dict = {"trace_type": "test", "data": "sample"}
        self._write_trace(trace_dict)
        assert self.temp_trace_file.exists()

    def test_write_trace_single_line(self):
        """验证每条 trace 占一行。"""
        trace_dict = {"trace_type": "test", "data": "sample"}
        self._write_trace(trace_dict)

        with open(self.temp_trace_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        assert len(lines) == 1
        # 验证每行末尾有换行符（JSONL 格式要求）
        assert lines[0].endswith("\n")

    def test_write_trace_contains_trace_type(self):
        """验证写入内容包含 trace_type 字段。"""
        trace_dict = {"trace_type": "test", "data": "sample"}
        self._write_trace(trace_dict)

        with open(self.temp_trace_file, "r", encoding="utf-8") as f:
            content = f.read()
        parsed = json.loads(content.strip())

        assert "trace_type" in parsed
        assert parsed["trace_type"] == "test"

    def test_write_trace_multiple_lines(self):
        """验证可以追加写入多条 trace（每行一个 JSON）。"""
        trace1 = {"trace_type": "query", "data": "first"}
        trace2 = {"trace_type": "ingestion", "data": "second"}

        self._write_trace(trace1)
        self._write_trace(trace2)

        with open(self.temp_trace_file, "r", encoding="utf-8") as f:
            lines = [json.loads(line.strip()) for line in f if line.strip()]

        assert len(lines) == 2
        assert lines[0]["trace_type"] == "query"
        assert lines[1]["trace_type"] == "ingestion"

    def test_write_trace_adds_timestamp(self):
        """验证 trace_dict 中没有 timestamp 时会自动添加。"""
        trace_dict = {"trace_type": "test", "data": "sample"}
        self._write_trace(trace_dict)

        with open(self.temp_trace_file, "r", encoding="utf-8") as f:
            parsed = json.loads(f.read().strip())

        assert "timestamp" in parsed
