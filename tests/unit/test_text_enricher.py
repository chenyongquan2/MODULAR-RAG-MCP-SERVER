"""TextEnricher 单元测试。"""

import pytest

from src.core.types import Chunk
from src.core.settings import Settings, TextEnricherSettings, IngestionSettings
from src.ingestion.transform.text_enricher import TextEnricher


def _make_settings(enabled: bool = True, caption_format: str = "[图片描述: {caption}]") -> Settings:
    """创建测试用的 Settings 对象。"""
    from src.core.settings import (
        LLMSettings, EmbeddingSettings, VisionLLMSettings, VectorStoreSettings
    )

    return Settings(
        llm=LLMSettings(provider="test", model="test-model"),
        embedding=EmbeddingSettings(provider="test", model="test-model"),
        vision_llm=VisionLLMSettings(provider="test", model="test-model"),
        vector_store=VectorStoreSettings(backend="test"),
        ingestion=IngestionSettings(
            text_enricher=TextEnricherSettings(
                enabled=enabled,
                caption_format=caption_format
            )
        )
    )


def _make_chunk(
    chunk_id: str = "test_chunk",
    text: str = "这是测试文本",
    image_captions: dict = None,
) -> Chunk:
    """创建测试用的 Chunk 对象。"""
    metadata = {}
    if image_captions:
        metadata["image_captions"] = image_captions

    return Chunk(
        id=chunk_id,
        text=text,
        metadata=metadata
    )


class TestTextEnricher:
    """TextEnricher 测试类。"""

    def test_no_captions_chunk_unchanged(self):
        """无图片描述的 chunk 应保持不变。"""
        settings = _make_settings()
        enricher = TextEnricher(settings)

        chunk = _make_chunk(text="纯文本内容", image_captions=None)
        result = enricher.transform([chunk])

        assert len(result) == 1
        assert result[0].text == "纯文本内容"
        assert result[0].metadata.get("caption_enriched") is None

    def test_empty_captions_chunk_unchanged(self):
        """空图片描述的 chunk 应保持不变。"""
        settings = _make_settings()
        enricher = TextEnricher(settings)

        chunk = _make_chunk(text="文本内容", image_captions={})
        result = enricher.transform([chunk])

        assert len(result) == 1
        assert result[0].text == "文本内容"

    def test_single_caption_fused_correctly(self):
        """单个图片描述应正确融合。"""
        settings = _make_settings()
        enricher = TextEnricher(settings)

        chunk = _make_chunk(
            text="这是正文内容",
            image_captions={"img_001": "一张展示架构图的图片"}
        )
        result = enricher.transform([chunk])

        assert len(result) == 1
        assert "[图片描述: 一张展示架构图的图片]" in result[0].text
        assert "这是正文内容" in result[0].text
        assert result[0].metadata.get("caption_enriched") is True
        assert result[0].metadata.get("original_text_length") == len("这是正文内容")

    def test_multiple_captions_fused_correctly(self):
        """多个图片描述应正确拼接。"""
        settings = _make_settings()
        enricher = TextEnricher(settings)

        chunk = _make_chunk(
            text="文档正文",
            image_captions={
                "img_001": "第一张图片描述",
                "img_002": "第二张图片描述"
            }
        )
        result = enricher.transform([chunk])

        assert len(result) == 1
        assert "[图片描述: 第一张图片描述]" in result[0].text
        assert "[图片描述: 第二张图片描述]" in result[0].text
        assert result[0].metadata.get("caption_enriched") is True

    def test_custom_caption_format(self):
        """自定义格式应正确应用。"""
        settings = _make_settings(caption_format="<图片>{caption}</图片>")
        enricher = TextEnricher(settings)

        chunk = _make_chunk(
            text="正文",
            image_captions={"img_001": "测试描述"}
        )
        result = enricher.transform([chunk])

        assert "<图片>测试描述</图片>" in result[0].text

    def test_caption_with_braces_not_broken(self):
        """caption 中包含花括号时不应报错。"""
        settings = _make_settings()
        enricher = TextEnricher(settings)

        # caption 包含 { 和 } 字符
        chunk = _make_chunk(
            text="正文",
            image_captions={"img_001": "这是一段包含{变量}的描述"}
        )
        result = enricher.transform([chunk])

        assert len(result) == 1
        assert "[图片描述: 这是一段包含{变量}的描述]" in result[0].text

    def test_disabled_skips_processing(self):
        """禁用时应跳过处理。"""
        settings = _make_settings(enabled=False)
        enricher = TextEnricher(settings)

        chunk = _make_chunk(
            text="原始文本",
            image_captions={"img_001": "不应出现"}
        )
        result = enricher.transform([chunk])

        assert len(result) == 1
        assert result[0].text == "原始文本"
        assert "不应出现" not in result[0].text
        assert enricher.enabled is False

    def test_idempotent_double_transform(self):
        """重复调用应保持幂等性。"""
        settings = _make_settings()
        enricher = TextEnricher(settings)

        chunk = _make_chunk(
            text="文本",
            image_captions={"img_001": "描述"}
        )

        # 第一次转换
        result1 = enricher.transform([chunk])
        # 第二次转换（使用第一次结果）
        result2 = enricher.transform(result1)

        assert len(result2) == 1
        # 应只融合一次
        assert result2[0].text.count("[图片描述:") == 1

    def test_multiple_chunks_processed(self):
        """多个 chunks 应分别处理。"""
        settings = _make_settings()
        enricher = TextEnricher(settings)

        chunks = [
            _make_chunk(chunk_id="c1", text="文本1", image_captions={"i1": "描述1"}),
            _make_chunk(chunk_id="c2", text="文本2", image_captions={}),
            _make_chunk(chunk_id="c3", text="文本3", image_captions={"i3": "描述3"}),
        ]
        result = enricher.transform(chunks)

        assert len(result) == 3
        assert "[图片描述: 描述1]" in result[0].text
        assert result[1].text == "文本2"  # 无描述，不变
        assert "[图片描述: 描述3]" in result[2].text

    def test_empty_chunks_returns_empty(self):
        """空列表应返回空列表。"""
        settings = _make_settings()
        enricher = TextEnricher(settings)

        result = enricher.transform([])
        assert result == []

    def test_original_text_length_recorded(self):
        """应记录原始文本长度。"""
        settings = _make_settings()
        enricher = TextEnricher(settings)

        original_text = "原始内容"
        chunk = _make_chunk(
            text=original_text,
            image_captions={"img_001": "描述"}
        )
        result = enricher.transform([chunk])

        assert result[0].metadata["original_text_length"] == len(original_text)

    def test_caption_format_property(self):
        """caption_format 属性应正确返回。"""
        settings = _make_settings(caption_format="自定义: {caption}")
        enricher = TextEnricher(settings)

        assert enricher.caption_format == "自定义: {caption}"
