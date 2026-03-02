"""MetadataEnricher 契约测试。

验收标准:
1. 规则模式:作为兜底逻辑,输出 metadata 必须包含 title/summary/tags(至少非空)
2. LLM 模式(核心):在 LLM 打开的情况下,确保真实调用 LLM(或高质量 Mock)并生成语义丰富的 metadata
3. 降级行为:LLM 调用失败时回退到规则模式结果(可在 metadata 标记降级原因,但不抛出致命异常)
"""

import json
from unittest.mock import Mock
import pytest

from src.core.types import Chunk
from src.core.trace.trace_context import TraceContext
from src.core.settings import (
    Settings, IngestionSettings, MetadataEnricherSettings,
    LLMSettings, EmbeddingSettings, VisionLLMSettings,
    VectorStoreSettings, RetrievalSettings, RerankSettings,
    SplitterSettings, EvaluationSettings, ObservabilitySettings
)
from src.ingestion.transform.metadata_enricher import MetadataEnricher


@pytest.fixture
def settings_no_llm():
    """无 LLM 的配置(规则模式)。"""
    return Settings(
        llm=LLMSettings(provider="azure", model="gpt-4o"),
        embedding=EmbeddingSettings(provider="openai", model="text-embedding-3-small"),
        vision_llm=VisionLLMSettings(provider="azure", model="gpt-4o"),
        vector_store=VectorStoreSettings(backend="chroma", persist_path="./data/db/chroma"),
        retrieval=RetrievalSettings(),
        rerank=RerankSettings(),
        splitter=SplitterSettings(),
        ingestion=IngestionSettings(metadata_enricher=MetadataEnricherSettings(use_llm=False)),
        evaluation=EvaluationSettings(),
        observability=ObservabilitySettings()
    )


@pytest.fixture
def settings_with_llm():
    """有 LLM 的配置(LLM 模式)。"""
    return Settings(
        llm=LLMSettings(provider="azure", model="gpt-4o"),
        embedding=EmbeddingSettings(provider="openai", model="text-embedding-3-small"),
        vision_llm=VisionLLMSettings(provider="azure", model="gpt-4o"),
        vector_store=VectorStoreSettings(backend="chroma", persist_path="./data/db/chroma"),
        retrieval=RetrievalSettings(),
        rerank=RerankSettings(),
        splitter=SplitterSettings(),
        ingestion=IngestionSettings(metadata_enricher=MetadataEnricherSettings(use_llm=True)),
        evaluation=EvaluationSettings(),
        observability=ObservabilitySettings()
    )


@pytest.fixture
def mock_llm_success():
    """成功的 Mock LLM。"""
    llm = Mock()
    llm.chat.return_value = json.dumps({
        "title": "Azure OpenAI Configuration Guide",
        "summary": "This document explains how to configure Azure OpenAI services with API keys and endpoints. It covers authentication setup and best practices.",
        "tags": ["Azure", "OpenAI", "configuration", "authentication", "API"]
    })
    return llm


@pytest.fixture
def mock_llm_failure():
    """失败的 Mock LLM(抛出异常)。"""
    llm = Mock()
    llm.chat.side_effect = Exception("LLM API timeout")
    return llm


@pytest.fixture
def mock_llm_invalid_json():
    """返回无效 JSON 的 Mock LLM。"""
    llm = Mock()
    llm.chat.return_value = "This is not a valid JSON response"
    return llm


@pytest.fixture
def sample_chunks():
    """样例 chunks。"""
    return [
        Chunk(
            id="doc1_0001_abc12345",
            text="# Azure OpenAI Configuration\n\nThis guide explains how to configure Azure OpenAI. First, obtain your API key from the Azure portal. Then, set up the endpoint URL in your configuration file.",
            metadata={"source_path": "/test/azure_guide.pdf", "chunk_index": 0}
        ),
        Chunk(
            id="doc1_0002_def67890",
            text="The authentication process requires three components: API key, endpoint URL, and deployment name. Make sure all three are correctly configured.",
            metadata={"source_path": "/test/azure_guide.pdf", "chunk_index": 1}
        ),
        Chunk(
            id="doc1_0003_ghi11223",
            text="",  # Empty chunk
            metadata={"source_path": "/test/azure_guide.pdf", "chunk_index": 2}
        )
    ]


class TestRuleBasedEnrich:
    """测试规则增强模式。"""

    def test_basic_metadata_structure(self, settings_no_llm, sample_chunks):
        """验收标准 1: 规则模式必须输出 title/summary/tags。"""
        enricher = MetadataEnricher(settings_no_llm)
        enriched = enricher.transform(sample_chunks[:1])

        assert len(enriched) == 1
        chunk = enriched[0]
        assert "title" in chunk.metadata
        assert "summary" in chunk.metadata
        assert "tags" in chunk.metadata
        assert chunk.metadata["enriched"] is True
        assert chunk.metadata["enriched_by"] == "rule"

    def test_extract_title_from_markdown_heading(self, settings_no_llm):
        """测试从 Markdown 标题提取 title。"""
        enricher = MetadataEnricher(settings_no_llm)
        text = "# Azure OpenAI Configuration\n\nSome content here."
        metadata = enricher._rule_based_enrich(text)

        assert metadata["title"] == "Azure OpenAI Configuration"

    def test_extract_title_from_first_line(self, settings_no_llm):
        """测试从首行提取 title。"""
        enricher = MetadataEnricher(settings_no_llm)
        text = "This is a short first line.\n\nMore content follows."
        metadata = enricher._rule_based_enrich(text)

        assert metadata["title"] == "This is a short first line."

    def test_extract_title_from_first_sentence(self, settings_no_llm):
        """测试从首句提取 title。"""
        enricher = MetadataEnricher(settings_no_llm)
        text = "This is a long first sentence that spans multiple lines and contains a lot of information. Second sentence here."
        metadata = enricher._rule_based_enrich(text)

        assert "This is a long first sentence" in metadata["title"]
        # Title is extracted from first sentence (before period)
        assert len(metadata["title"]) <= 100

    def test_generate_summary_from_sentences(self, settings_no_llm):
        """测试从前 2-3 句生成摘要。"""
        enricher = MetadataEnricher(settings_no_llm)
        text = "First sentence explains the topic. Second sentence provides details. Third sentence adds more context. Fourth sentence is extra."
        metadata = enricher._rule_based_enrich(text)

        summary = metadata["summary"]
        assert "First sentence" in summary
        assert "Second sentence" in summary
        # Third sentence might be included depending on length

    def test_extract_tags_from_capitalized_words(self, settings_no_llm):
        """测试从大写单词提取标签。"""
        enricher = MetadataEnricher(settings_no_llm)
        text = "Azure OpenAI provides powerful API capabilities for developers. Configuration is simple."
        metadata = enricher._rule_based_enrich(text)

        tags = metadata["tags"]
        assert isinstance(tags, list)
        assert any("Azure" in tag or "OpenAI" in tag for tag in tags)

    def test_extract_tags_from_technical_keywords(self, settings_no_llm):
        """测试提取技术关键词作为标签。"""
        enricher = MetadataEnricher(settings_no_llm)
        text = "This API configuration example demonstrates authentication and security best practices. The database integration uses proper error handling."
        metadata = enricher._rule_based_enrich(text)

        tags = metadata["tags"]
        # Should extract technical keywords like API, authentication, security, database, error
        assert len(tags) > 0
        assert any(tag.lower() in ['api', 'authentication', 'security', 'database', 'error'] for tag in tags)

    def test_tags_limited_to_five(self, settings_no_llm):
        """测试标签限制在 5 个以内。"""
        enricher = MetadataEnricher(settings_no_llm)
        text = "This text contains many technical terms: API, configuration, database, server, client, authentication, authorization, security, encryption, performance, optimization, error, exception, logging, deployment, testing, integration."
        metadata = enricher._rule_based_enrich(text)

        assert len(metadata["tags"]) <= 5

    def test_empty_chunk(self, settings_no_llm):
        """测试空 chunk 的处理。"""
        enricher = MetadataEnricher(settings_no_llm)
        metadata = enricher._rule_based_enrich("")

        assert metadata["title"] == "Empty chunk"
        assert "no text" in metadata["summary"].lower()
        assert metadata["tags"] == []


class TestLLMEnrich:
    """测试 LLM 增强模式。"""

    def test_llm_mode_enabled(self, settings_with_llm, mock_llm_success, sample_chunks):
        """验收标准 2: LLM 模式下确保真实调用 LLM(Mock)。"""
        enricher = MetadataEnricher(settings_with_llm, llm=mock_llm_success)
        enriched = enricher.transform(sample_chunks[:1])

        assert len(enriched) == 1
        chunk = enriched[0]
        assert chunk.metadata["enriched_by"] == "llm"
        mock_llm_success.chat.assert_called_once()

    def test_llm_override_rule_based(self, settings_with_llm, mock_llm_success, sample_chunks):
        """测试 LLM 结果覆盖规则结果。"""
        enricher = MetadataEnricher(settings_with_llm, llm=mock_llm_success)
        enriched = enricher.transform(sample_chunks[:1])

        chunk = enriched[0]
        # LLM response should override rule-based
        assert chunk.metadata["title"] == "Azure OpenAI Configuration Guide"
        assert "Azure OpenAI services" in chunk.metadata["summary"]
        assert "Azure" in chunk.metadata["tags"]

    def test_llm_failure_fallback_to_rule(self, settings_with_llm, mock_llm_failure, sample_chunks):
        """验收标准 3: LLM 失败时回退到规则模式。"""
        enricher = MetadataEnricher(settings_with_llm, llm=mock_llm_failure)
        enriched = enricher.transform(sample_chunks[:1])

        assert len(enriched) == 1
        chunk = enriched[0]
        # Should fallback to rule-based
        assert chunk.metadata["enriched_by"] == "rule"
        # Metadata should still exist (from rule-based)
        assert "title" in chunk.metadata
        assert "summary" in chunk.metadata
        assert "tags" in chunk.metadata

    def test_llm_invalid_json_fallback(self, settings_with_llm, mock_llm_invalid_json, sample_chunks):
        """测试 LLM 返回无效 JSON 时的降级。"""
        enricher = MetadataEnricher(settings_with_llm, llm=mock_llm_invalid_json)
        enriched = enricher.transform(sample_chunks[:1])

        chunk = enriched[0]
        # Should fallback to rule-based
        assert chunk.metadata["enriched_by"] == "rule"
        assert "title" in chunk.metadata

    def test_parse_llm_response_valid_json(self, settings_no_llm):
        """测试解析有效的 LLM JSON 响应。"""
        enricher = MetadataEnricher(settings_no_llm)
        response = json.dumps({
            "title": "Test Title",
            "summary": "This is a test summary.",
            "tags": ["test", "example"]
        })
        metadata = enricher._parse_llm_response(response)

        assert metadata is not None
        assert metadata["title"] == "Test Title"
        assert metadata["summary"] == "This is a test summary."
        assert metadata["tags"] == ["test", "example"]

    def test_parse_llm_response_with_markdown_wrapper(self, settings_no_llm):
        """测试解析被 markdown 包裹的 JSON。"""
        enricher = MetadataEnricher(settings_no_llm)
        response = """Here is the metadata:
```json
{
  "title": "Wrapped Title",
  "summary": "Wrapped summary.",
  "tags": ["tag1", "tag2"]
}
```
"""
        metadata = enricher._parse_llm_response(response)

        assert metadata is not None
        assert metadata["title"] == "Wrapped Title"

    def test_parse_llm_response_missing_fields(self, settings_no_llm):
        """测试解析缺少字段的 JSON。"""
        enricher = MetadataEnricher(settings_no_llm)
        response = json.dumps({
            "title": "Test Title",
            "summary": "Test summary."
            # Missing "tags"
        })
        metadata = enricher._parse_llm_response(response)

        assert metadata is None

    def test_parse_llm_response_truncate_long_fields(self, settings_no_llm):
        """测试截断过长的字段。"""
        enricher = MetadataEnricher(settings_no_llm)
        response = json.dumps({
            "title": "A" * 200,  # Too long
            "summary": "B" * 500,  # Too long
            "tags": [f"tag{i}" for i in range(10)]  # Too many
        })
        metadata = enricher._parse_llm_response(response)

        assert metadata is not None
        assert len(metadata["title"]) <= 100
        assert len(metadata["summary"]) <= 300
        assert len(metadata["tags"]) <= 5


class TestTransformContract:
    """测试 transform 方法的契约。"""

    def test_empty_input(self, settings_no_llm):
        """测试空输入。"""
        enricher = MetadataEnricher(settings_no_llm)
        result = enricher.transform([])
        assert result == []

    def test_preserve_original_fields(self, settings_no_llm, sample_chunks):
        """测试保留原始字段。"""
        enricher = MetadataEnricher(settings_no_llm)
        enriched = enricher.transform(sample_chunks[:1])

        chunk = enriched[0]
        assert chunk.id == sample_chunks[0].id
        assert chunk.text == sample_chunks[0].text
        assert chunk.start_offset == sample_chunks[0].start_offset
        assert chunk.end_offset == sample_chunks[0].end_offset
        assert chunk.source_ref == sample_chunks[0].source_ref
        assert chunk.metadata["source_path"] == sample_chunks[0].metadata["source_path"]
        assert chunk.metadata["chunk_index"] == sample_chunks[0].metadata["chunk_index"]

    def test_batch_processing(self, settings_no_llm, sample_chunks):
        """测试批量处理。"""
        enricher = MetadataEnricher(settings_no_llm)
        enriched = enricher.transform(sample_chunks)

        assert len(enriched) == len(sample_chunks)
        for chunk in enriched:
            assert "title" in chunk.metadata
            assert "summary" in chunk.metadata
            assert "tags" in chunk.metadata

    def test_trace_integration(self, settings_no_llm, sample_chunks):
        """测试 trace 集成。"""
        enricher = MetadataEnricher(settings_no_llm)
        trace = TraceContext(trace_type="ingestion")
        enriched = enricher.transform(sample_chunks, trace=trace)

        assert len(enriched) == len(sample_chunks)
        # Trace should have recorded the stage
        # (Detailed trace validation would require inspecting trace.stages)

    def test_error_handling_preserves_chunks(self, settings_no_llm):
        """测试异常处理不丢失 chunks。"""
        enricher = MetadataEnricher(settings_no_llm)

        # Create a chunk that might cause issues (but shouldn't crash)
        problematic_chunk = Chunk(
            id="test_0001",
            text="x" * 10000,  # Very long text
            metadata={"source_path": "/test.pdf"}
        )

        enriched = enricher.transform([problematic_chunk])
        assert len(enriched) == 1
        assert "enriched" in enriched[0].metadata
