"""Integration tests: query_knowledge_hub 多模态返图端到端（feature-002 US1）。

本测试目标：
- 验证摄取侧产生的 images 元数据经过 QueryKnowledgeHubTool → MultimodalAssembler
  真实地被读取、base64 编码，构成 MCP ImageContent 返回。
- 验证图片文件缺失时的优雅降级（文本仍正常返回）。
- 不依赖 ChromaDB 或真实 LLM；HybridSearch 用 mock，但 ImageStorage 用真实 SQLite 实例
  指向一个临时目录，接近真实 I/O 路径。

对应 spec FR-001 / FR-005 / FR-011、SC-002 / SC-005。
"""

from __future__ import annotations

import base64
import shutil
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mcp.types import ImageContent, TextContent

from src.core.response.citation_generator import StructuredContent
from src.core.response.multimodal_assembler import MultimodalAssembler
from src.core.types import RetrievalResult
from src.ingestion.storage.image_storage import SQLiteImageStorage
from src.mcp_server.tools.query_knowledge_hub import QueryKnowledgeHubTool


pytestmark = pytest.mark.integration


_SAMPLE_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


@pytest.fixture
def temp_data_dir() -> Path:
    """提供一个独立临时目录，含 images/ 与 db/，测试完清理。"""
    tmp = Path(tempfile.mkdtemp(prefix="feat002_"))
    (tmp / "images").mkdir()
    (tmp / "db").mkdir()
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def real_image_storage_with_two_images(temp_data_dir: Path) -> SQLiteImageStorage:
    """初始化真实 SQLiteImageStorage，插入 2 张 PNG 文件与对应索引行。"""
    storage = SQLiteImageStorage(
        db_path=str(temp_data_dir / "db" / "image_index.db"),
        images_root=str(temp_data_dir / "images"),
    )

    png_bytes = base64.b64decode(_SAMPLE_PNG_B64)

    # 写两张真实图片文件
    img_ids = ["img_A", "img_B"]
    for img_id in img_ids:
        collection_dir = temp_data_dir / "images" / "test_col"
        collection_dir.mkdir(parents=True, exist_ok=True)
        file_path = collection_dir / f"{img_id}.png"
        file_path.write_bytes(png_bytes)

        # 直接插入索引表（避免依赖 ImageStorage 的 ingest API，聚焦查询侧）
        with sqlite3.connect(storage.db_path) as conn:
            conn.execute(
                "INSERT INTO image_index (image_id, file_path, collection) VALUES (?, ?, ?)",
                (img_id, str(file_path), "test_col"),
            )
            conn.commit()

    return storage


@pytest.fixture
def mock_hybrid_search_with_image_chunk():
    """HybridSearch mock：返回一个 chunk，其 metadata 引用 img_A 与 img_B。"""
    mock = MagicMock()
    mock.search.return_value = [
        RetrievalResult(
            chunk_id="chunk_with_images",
            score=0.91,
            text="这是关于架构图的文本块",
            metadata={
                "source_path": "doc.pdf",
                "page": 3,
                "collection": "test_col",
                "images": [
                    {"id": "img_A", "path": "ignored", "text_offset": 5, "text_length": 12},
                    {"id": "img_B", "path": "ignored", "text_offset": 25, "text_length": 12},
                ],
            },
        ),
    ]
    return mock


@pytest.fixture
def mock_response_builder():
    """ResponseBuilder mock —— 本测试专注 use_llm=False 路径，LLM 不应被触发。"""
    mock = MagicMock()
    # 若被调用则抛错，帮助捕捉"US1 意外触发了 LLM"的情况
    mock.build.side_effect = AssertionError("ResponseBuilder should NOT be called in use_llm=False path")
    return mock


@pytest.fixture
def mock_response_builder_with_llm_output():
    """ResponseBuilder mock —— 用于 use_llm=True 路径：返回合法 StructuredContent。"""
    mock = MagicMock()
    mock.build.return_value = StructuredContent(
        markdown="根据检索到的文档，架构图中 Reranker 位于 Fusion 之后 [1][2]。",
        citations=[
            MagicMock(
                id=1, source="doc.pdf", page=3, chunk_id="chunk_with_images",
                score=0.91, text="架构图的文本块"
            ),
        ],
    )
    return mock


class TestMultimodalQueryEndToEnd:
    """feature-002 US1 端到端验证。"""

    @pytest.mark.asyncio
    async def test_use_llm_false_returns_text_and_images_with_valid_base64(
        self,
        real_image_storage_with_two_images,
        mock_hybrid_search_with_image_chunk,
        mock_response_builder,
    ):
        """命中含图 chunk → 响应含 TextContent + 2 张 ImageContent，base64 合法。"""
        assembler = MultimodalAssembler(image_storage=real_image_storage_with_two_images)
        tool = QueryKnowledgeHubTool(
            mock_hybrid_search_with_image_chunk,
            mock_response_builder,
            assembler,
            max_images_per_response=10,
        )

        result = await tool.execute({"query": "什么是架构图？", "use_llm": False})

        # 至少一个 TextContent + 两个 ImageContent + 末尾 images 元数据 dict
        text_items = [c for c in result if isinstance(c, TextContent)]
        image_items = [c for c in result if isinstance(c, ImageContent)]

        assert len(text_items) >= 1, "应至少返回一个 TextContent"
        assert len(image_items) == 2, f"期望返回 2 张图片，实际 {len(image_items)}"

        # 每张图 base64 合法且非空、mimeType 以 image/ 开头
        for img in image_items:
            assert img.mimeType.startswith("image/"), f"非法 mimeType: {img.mimeType}"
            assert img.data, "base64 data 不应为空"
            # 可解码
            try:
                base64.b64decode(img.data, validate=True)
            except Exception as e:
                pytest.fail(f"base64 解码失败: {e}")

        # 末尾 images 元数据 dict 与实际返回图数量一致
        meta = next((c for c in result if isinstance(c, dict)), None)
        assert meta is not None and "images" in meta
        assert len(meta["images"]) == 2

    @pytest.mark.asyncio
    async def test_image_file_missing_degrades_gracefully(
        self,
        real_image_storage_with_two_images,
        mock_hybrid_search_with_image_chunk,
        mock_response_builder,
        temp_data_dir,
    ):
        """人为删掉一张图片文件后，响应仍含 TextContent 且至少含剩余图（FR-005 / SC-005）。"""
        # 删除 img_A 对应的文件（保留索引）
        img_a_path = temp_data_dir / "images" / "test_col" / "img_A.png"
        img_a_path.unlink()

        assembler = MultimodalAssembler(image_storage=real_image_storage_with_two_images)
        tool = QueryKnowledgeHubTool(
            mock_hybrid_search_with_image_chunk,
            mock_response_builder,
            assembler,
            max_images_per_response=10,
        )

        result = await tool.execute({"query": "query", "use_llm": False})

        # 必须含文本（不得整体失败）
        text_items = [c for c in result if isinstance(c, TextContent)]
        assert len(text_items) >= 1

        # 仅剩下的那张图（img_B）应该还在
        image_items = [c for c in result if isinstance(c, ImageContent)]
        assert len(image_items) == 1, f"删一张后应剩 1 张图，实际 {len(image_items)}"

    @pytest.mark.asyncio
    async def test_max_images_limit_truncates_response(
        self,
        real_image_storage_with_two_images,
        mock_hybrid_search_with_image_chunk,
        mock_response_builder,
    ):
        """max_images_per_response=1 时，即使 chunk 关联 2 张图，响应只返回 1 张。"""
        assembler = MultimodalAssembler(image_storage=real_image_storage_with_two_images)
        tool = QueryKnowledgeHubTool(
            mock_hybrid_search_with_image_chunk,
            mock_response_builder,
            assembler,
            max_images_per_response=1,
        )

        result = await tool.execute({"query": "query", "use_llm": False})

        image_items = [c for c in result if isinstance(c, ImageContent)]
        assert len(image_items) == 1

    @pytest.mark.asyncio
    async def test_no_hits_returns_friendly_text_without_error(
        self,
        real_image_storage_with_two_images,
        mock_response_builder,
    ):
        """命中为空时返回友好提示，不调用 assembler，不抛错。"""
        empty_hybrid = MagicMock()
        empty_hybrid.search.return_value = []

        assembler = MultimodalAssembler(image_storage=real_image_storage_with_two_images)
        tool = QueryKnowledgeHubTool(
            empty_hybrid,
            mock_response_builder,
            assembler,
            max_images_per_response=10,
        )

        result = await tool.execute({"query": "nothing will hit", "use_llm": False})

        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "未找到" in result[0].text

    # ----------- feature-002 US2：LLM 总结模式端到端返图 -----------

    @pytest.mark.asyncio
    async def test_use_llm_true_returns_llm_markdown_and_images(
        self,
        real_image_storage_with_two_images,
        mock_hybrid_search_with_image_chunk,
        mock_response_builder_with_llm_output,
    ):
        """US2：LLM 模式同时返回 LLM 生成的 Markdown + 命中 chunk 的 2 张图片。"""
        assembler = MultimodalAssembler(image_storage=real_image_storage_with_two_images)
        tool = QueryKnowledgeHubTool(
            mock_hybrid_search_with_image_chunk,
            mock_response_builder_with_llm_output,
            assembler,
            max_images_per_response=10,
        )

        result = await tool.execute({"query": "架构图中 Reranker 的位置？", "use_llm": True})

        # 含 LLM 生成的 Markdown
        text_items = [c for c in result if isinstance(c, TextContent)]
        assert len(text_items) >= 1
        first_text = text_items[0].text
        assert "Reranker" in first_text
        assert "Citations" in first_text

        # 含 2 张图
        image_items = [c for c in result if isinstance(c, ImageContent)]
        assert len(image_items) == 2

    @pytest.mark.asyncio
    async def test_both_modes_return_same_image_set(
        self,
        real_image_storage_with_two_images,
        mock_hybrid_search_with_image_chunk,
        mock_response_builder_with_llm_output,
    ):
        """US2：同一 query 同一命中 chunk，use_llm=True/False 返回的 image_id 集合一致（clarify Q2 选项 A）。"""
        assembler = MultimodalAssembler(image_storage=real_image_storage_with_two_images)
        tool = QueryKnowledgeHubTool(
            mock_hybrid_search_with_image_chunk,
            mock_response_builder_with_llm_output,
            assembler,
            max_images_per_response=10,
        )

        result_false = await tool.execute({"query": "q", "use_llm": False})
        result_true = await tool.execute({"query": "q", "use_llm": True})

        # 从末尾 images 元数据 dict 提取 id
        def ids(result):
            meta = next((c for c in result if isinstance(c, dict)), None)
            assert meta is not None
            return sorted(img["id"] for img in meta["images"])

        assert ids(result_false) == ids(result_true)
        assert set(ids(result_false)) == {"img_A", "img_B"}
