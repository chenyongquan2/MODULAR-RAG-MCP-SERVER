"""MultimodalAssembler.assemble() trace stage 记录测试（feature-002 US3 / FR-008）。

验证 assemble() 在 trace 参数非 None 时，向 TraceContext 写入一条
stage=assemble_multimodal 的记录，且包含 5 个约定字段：
- image_count_requested
- image_count_returned
- image_count_failed
- max_images
- duration_ms

对应 contracts/query_knowledge_hub_tool.md §5.1。
"""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.core.response.multimodal_assembler import MultimodalAssembler
from src.core.trace.trace_context import TraceContext
from src.core.types import RetrievalResult
from src.ingestion.storage.image_storage import SQLiteImageStorage


_SAMPLE_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


@pytest.fixture
def temp_png_file() -> str:
    data = base64.b64decode(_SAMPLE_PNG_B64)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(data)
        path = f.name
    yield path
    Path(path).unlink(missing_ok=True)


def _make_storage(temp_png_file: str, known_ids: set[str]) -> MagicMock:
    storage = MagicMock(spec=SQLiteImageStorage)
    storage.get_image_path.side_effect = lambda img_id: temp_png_file if img_id in known_ids else None
    return storage


def _make_results(image_ids: list[str]) -> list[RetrievalResult]:
    """构造单个 chunk，附带指定 image_ids 的 metadata。"""
    return [
        RetrievalResult(
            chunk_id="chunk_trace",
            score=0.8,
            text="trace text",
            metadata={
                "images": [
                    {"id": img_id, "path": f"/fake/{img_id}.png", "text_offset": i, "text_length": 1}
                    for i, img_id in enumerate(image_ids)
                ]
            },
        )
    ]


class TestAssembleTraceStage:
    """feature-002 US3: FR-008 trace 字段契约。"""

    def test_records_assemble_multimodal_stage_with_five_fields(self, temp_png_file: str):
        """正常路径：5 张图都能加载 + max_images=3 截取 → stage 字段齐全且值正确。"""
        storage = _make_storage(temp_png_file, {"a1", "a2", "a3", "a4", "a5"})
        assembler = MultimodalAssembler(storage)
        results = _make_results(["a1", "a2", "a3", "a4", "a5"])
        trace = TraceContext(trace_type="query")

        assembler.assemble(
            markdown="text",
            results=results,
            trace=trace,
            max_images=3,
        )

        stage = trace.get_stage("assemble_multimodal")
        assert stage is not None, "assemble_multimodal stage 必须被记录"
        data = stage.data
        # 5 个约定字段齐全
        assert set(data.keys()) == {
            "image_count_requested",
            "image_count_returned",
            "image_count_failed",
            "max_images",
            "duration_ms",
        }
        # 值正确
        assert data["image_count_requested"] == 5
        assert data["image_count_returned"] == 3  # 截到 3
        assert data["image_count_failed"] == 0
        assert data["max_images"] == 3
        assert isinstance(data["duration_ms"], float) and data["duration_ms"] >= 0

    def test_records_stage_when_no_images_present(self, temp_png_file: str):
        """无图场景：仍写入 stage（requested=0 / returned=0），便于"为什么没图"诊断。"""
        storage = _make_storage(temp_png_file, set())
        assembler = MultimodalAssembler(storage)
        trace = TraceContext(trace_type="query")

        # chunk 没有 images 元数据
        results = [
            RetrievalResult(chunk_id="no_img", score=0.5, text="t", metadata={})
        ]
        assembler.assemble(markdown="text", results=results, trace=trace)

        stage = trace.get_stage("assemble_multimodal")
        assert stage is not None
        assert stage.data["image_count_requested"] == 0
        assert stage.data["image_count_returned"] == 0
        assert stage.data["image_count_failed"] == 0

    def test_failed_image_load_reflected_in_failed_count(self, temp_png_file: str):
        """a1/a2 存在，a3 在 storage 中缺失 → failed=1、returned=2、requested=3。"""
        # 只有 a1/a2 能被 storage 找到
        storage = _make_storage(temp_png_file, {"a1", "a2"})
        assembler = MultimodalAssembler(storage)
        results = _make_results(["a1", "a2", "a3"])
        trace = TraceContext(trace_type="query")

        assembler.assemble(markdown="text", results=results, trace=trace, max_images=None)

        stage = trace.get_stage("assemble_multimodal")
        assert stage is not None
        assert stage.data["image_count_requested"] == 3
        assert stage.data["image_count_returned"] == 2
        assert stage.data["image_count_failed"] == 1
        assert stage.data["max_images"] is None

    def test_trace_none_skips_recording_silently(self, temp_png_file: str):
        """trace=None（默认）时不写入任何 stage（向后兼容）。"""
        storage = _make_storage(temp_png_file, {"a1"})
        assembler = MultimodalAssembler(storage)
        results = _make_results(["a1"])

        # 传 trace=None 不应抛错，只是不写 stage
        contents = assembler.assemble(markdown="text", results=results, trace=None)

        assert contents[0].type == "text"

    def test_non_trace_like_object_is_gracefully_ignored(self, temp_png_file: str):
        """如果传入不是 TraceContext（例如测试中的 mock 漏配 record_stage），不应抛错。"""
        storage = _make_storage(temp_png_file, {"a1"})
        assembler = MultimodalAssembler(storage)
        results = _make_results(["a1"])

        class FakeTrace:
            """没有 record_stage 方法的对象。"""
            pass

        # 不应抛错（_record_trace_stage 用 getattr 保护）
        assembler.assemble(markdown="t", results=results, trace=FakeTrace())
