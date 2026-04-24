"""MultimodalAssembler.assemble() max_images 参数边界测试。

对应 spec feature-002 FR-004：单次响应返回的图片数量 MUST 有上限，
该上限通过配置项 query.max_images_per_response 控制（默认 10）。
本测试覆盖 assembler 层对 max_images 参数的四种语义：
- None（默认）：不限制，向后兼容既有调用
- 正整数 N：在排序后截取前 N 张
- 0：退化为不返回任何 ImageContent（仅文本 + 空 images dict）
- 负数：抛 ValueError
"""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mcp.types import ImageContent, TextContent

from src.core.response.multimodal_assembler import MultimodalAssembler
from src.core.types import RetrievalResult
from src.ingestion.storage.image_storage import SQLiteImageStorage


# 1x1 透明 PNG 的 base64（复用 test_multimodal_assembler.py 里的相同常量）
_SAMPLE_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


@pytest.fixture
def temp_png_file() -> str:
    """写一份 1x1 PNG 到临时文件，用于多 image_id 共用一个磁盘文件。"""
    data = base64.b64decode(_SAMPLE_PNG_B64)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(data)
        path = f.name
    yield path
    Path(path).unlink(missing_ok=True)


@pytest.fixture
def mock_storage_five_images(temp_png_file: str) -> MagicMock:
    """mock 一个 ImageStorage，对 img_1~img_5 全部返回同一个 temp 文件。"""
    storage = MagicMock(spec=SQLiteImageStorage)

    def get_image_path_side_effect(image_id: str) -> str | None:
        if image_id in {"img_1", "img_2", "img_3", "img_4", "img_5"}:
            return temp_png_file
        return None

    storage.get_image_path.side_effect = get_image_path_side_effect
    return storage


@pytest.fixture
def results_with_five_images() -> list[RetrievalResult]:
    """构造含 5 张图的检索结果（文本 offset 0,10,20,30,40 依序递增）。"""
    return [
        RetrievalResult(
            chunk_id="chunk_1",
            score=0.95,
            text="Sample text with 5 images",
            metadata={
                "images": [
                    {"id": f"img_{i}", "path": f"/fake/img_{i}.png",
                     "text_offset": i * 10, "text_length": 12}
                    for i in range(1, 6)
                ]
            },
        )
    ]


class TestAssembleMaxImagesLimit:
    """覆盖 max_images 参数的四种语义。"""

    def test_max_images_none_returns_all_images(
        self,
        mock_storage_five_images: MagicMock,
        results_with_five_images: list[RetrievalResult],
    ):
        """max_images=None 时保持既有行为（不限制）——向后兼容。"""
        assembler = MultimodalAssembler(mock_storage_five_images)
        markdown = "No placeholders here, all 5 images应按 offset 顺序返回。"

        contents = assembler.assemble(
            markdown=markdown,
            results=results_with_five_images,
            max_images=None,
        )

        # 结构：[TextContent, *5×ImageContent, {"images":[...]}]
        assert len(contents) == 7
        assert isinstance(contents[0], TextContent)
        images = [c for c in contents if isinstance(c, ImageContent)]
        assert len(images) == 5
        # 最后一项是 {"images": [...]} 元数据
        assert isinstance(contents[-1], dict)
        assert len(contents[-1]["images"]) == 5

    def test_max_images_truncates_to_first_n(
        self,
        mock_storage_five_images: MagicMock,
        results_with_five_images: list[RetrievalResult],
    ):
        """max_images=3 时从 5 张截取前 3 张，并同步反映到 images 元数据。"""
        assembler = MultimodalAssembler(mock_storage_five_images)
        markdown = "plain text, no IMAGE placeholders"

        contents = assembler.assemble(
            markdown=markdown,
            results=results_with_five_images,
            max_images=3,
        )

        images = [c for c in contents if isinstance(c, ImageContent)]
        assert len(images) == 3

        # 元数据 dict 里的 images 数应与实际返回一致
        meta_dict = contents[-1]
        assert isinstance(meta_dict, dict)
        assert len(meta_dict["images"]) == 3

        # 截取的应当是前 3 个（text_offset 最小的 img_1/img_2/img_3）
        returned_ids = [img["id"] for img in meta_dict["images"]]
        assert returned_ids == ["img_1", "img_2", "img_3"]

    def test_max_images_zero_returns_text_only(
        self,
        mock_storage_five_images: MagicMock,
        results_with_five_images: list[RetrievalResult],
    ):
        """max_images=0 视为"图片上限为 0"——仅返回 TextContent + 空 images 元数据。

        注：这是 edge case 兼容（等效于"所有图片都被丢弃"），不抛 ValueError。
        """
        assembler = MultimodalAssembler(mock_storage_five_images)

        contents = assembler.assemble(
            markdown="some text",
            results=results_with_five_images,
            max_images=0,
        )

        images = [c for c in contents if isinstance(c, ImageContent)]
        assert len(images) == 0

        # 列表结构：[TextContent, {"images": []}]
        assert len(contents) == 2
        assert isinstance(contents[0], TextContent)
        assert isinstance(contents[1], dict)
        assert contents[1]["images"] == []

    def test_max_images_negative_raises_value_error(
        self,
        mock_storage_five_images: MagicMock,
        results_with_five_images: list[RetrievalResult],
    ):
        """max_images < 0 属于非法参数，MUST 抛 ValueError（Fail-Fast）。"""
        assembler = MultimodalAssembler(mock_storage_five_images)

        with pytest.raises(ValueError, match="max_images"):
            assembler.assemble(
                markdown="text",
                results=results_with_five_images,
                max_images=-1,
            )

    def test_max_images_larger_than_actual_is_noop(
        self,
        mock_storage_five_images: MagicMock,
        results_with_five_images: list[RetrievalResult],
    ):
        """max_images > 实际图片数时，等同于不截取（返回全部 5 张）。"""
        assembler = MultimodalAssembler(mock_storage_five_images)

        contents = assembler.assemble(
            markdown="text",
            results=results_with_five_images,
            max_images=100,
        )

        images = [c for c in contents if isinstance(c, ImageContent)]
        assert len(images) == 5
        assert len(contents[-1]["images"]) == 5
