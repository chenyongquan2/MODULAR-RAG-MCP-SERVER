"""ChunkRefiner 单元测试。"""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.core.types import Chunk
from src.core.trace.trace_context import TraceContext
from src.core.settings import Settings, IngestionSettings, ChunkRefinerSettings, LLMSettings, EmbeddingSettings, VisionLLMSettings, VectorStoreSettings, RetrievalSettings, RerankSettings, SplitterSettings, EvaluationSettings, ObservabilitySettings
from src.ingestion.transform.chunk_refiner import ChunkRefiner


@pytest.fixture
def settings_no_llm():
    return Settings(
        llm=LLMSettings(provider="azure", model="gpt-4o"),
        embedding=EmbeddingSettings(provider="openai", model="text-embedding-3-small"),
        vision_llm=VisionLLMSettings(provider="azure", model="gpt-4o"),
        vector_store=VectorStoreSettings(backend="chroma", persist_path="./data/db/chroma"),
        retrieval=RetrievalSettings(),
        rerank=RerankSettings(),
        splitter=SplitterSettings(),
        ingestion=IngestionSettings(chunk_refiner=ChunkRefinerSettings(use_llm=False)),
        evaluation=EvaluationSettings(),
        observability=ObservabilitySettings()
    )


@pytest.fixture
def settings_with_llm():
    return Settings(
        llm=LLMSettings(provider="azure", model="gpt-4o"),
        embedding=EmbeddingSettings(provider="openai", model="text-embedding-3-small"),
        vision_llm=VisionLLMSettings(provider="azure", model="gpt-4o"),
        vector_store=VectorStoreSettings(backend="chroma", persist_path="./data/db/chroma"),
        retrieval=RetrievalSettings(),
        rerank=RerankSettings(),
        splitter=SplitterSettings(),
        ingestion=IngestionSettings(chunk_refiner=ChunkRefinerSettings(use_llm=True)),
        evaluation=EvaluationSettings(),
        observability=ObservabilitySettings()
    )


@pytest.fixture
def mock_llm():
    llm = Mock()
    llm.chat.return_value = "This is refined text by LLM."
    return llm


@pytest.fixture
def sample_chunks():
    return [
        Chunk(id="doc1_0001_abc12345", text="This is a test chunk.",
              metadata={"source_path": "/test/doc1.pdf", "chunk_index": 0}),
        Chunk(id="doc1_0002_def67890", text="Another chunk for testing.",
              metadata={"source_path": "/test/doc1.pdf", "chunk_index": 1})
    ]


class TestRuleBasedRefine:
    def test_remove_page_header_footer(self, settings_no_llm):
        refiner = ChunkRefiner(settings_no_llm)
        text = "CONFIDENTIAL - Page 5\n\n# Important Section\n\nThis is the main content.\n\n--- Document ID: ABC123 ---"
        result = refiner._rule_based_refine(text)
        assert "CONFIDENTIAL" not in result
        assert "Page 5" not in result
        assert "Important Section" in result

    def test_remove_html_tags(self, settings_no_llm):
        refiner = ChunkRefiner(settings_no_llm)
        text = "<p>This is <b>bold</b> text.</p>"
        result = refiner._rule_based_refine(text)
        assert "<p>" not in result
        assert "bold" in result

    def test_normalize_excessive_whitespace(self, settings_no_llm):
        refiner = ChunkRefiner(settings_no_llm)
        # Test: 4+ newlines should become 2 newlines
        text = "Line one.\n\n\n\nLine two.\n\n\n\n\nLine three."
        result = refiner._rule_based_refine(text)
        # Should have at most 2 consecutive newlines
        assert "\n\n\n\n" not in result
        assert "Line one." in result
        assert "Line two." in result

    def test_preserve_code_blocks(self, settings_no_llm):
        refiner = ChunkRefiner(settings_no_llm)
        text = "Here is code:\n\n```python\ndef calculate(a, b):\n    return a + b\n```\nEnd."
        result = refiner._rule_based_refine(text)
        assert "```python" in result

    def test_empty_text(self, settings_no_llm):
        refiner = ChunkRefiner(settings_no_llm)
        result = refiner._rule_based_refine("")
        assert result == ""


class TestTransform:
    def test_transform_basic(self, settings_no_llm, sample_chunks):
        refiner = ChunkRefiner(settings_no_llm)
        result = refiner.transform(sample_chunks)
        assert len(result) == 2
        assert result[0].metadata["refined_by"] == "rule"

    def test_transform_empty_list(self, settings_no_llm):
        refiner = ChunkRefiner(settings_no_llm)
        result = refiner.transform([])
        assert result == []

    def test_transform_with_trace(self, settings_no_llm, sample_chunks):
        refiner = ChunkRefiner(settings_no_llm)
        trace = TraceContext(trace_type="ingestion")
        result = refiner.transform(sample_chunks, trace)
        assert trace.get_stage("chunk_refine") is not None

    def test_transform_with_llm(self, settings_with_llm, sample_chunks, mock_llm):
        refiner = ChunkRefiner(settings_with_llm, llm=mock_llm)
        result = refiner.transform(sample_chunks)
        assert mock_llm.chat.called
        assert result[0].metadata["refined_by"] == "llm"

    def test_transform_llm_failure_fallback(self, settings_with_llm, sample_chunks):
        mock_llm = Mock()
        mock_llm.chat.side_effect = Exception("LLM error")
        refiner = ChunkRefiner(settings_with_llm, llm=mock_llm)
        result = refiner.transform(sample_chunks)
        assert result[0].metadata["refined_by"] == "rule"

    def test_transform_preserves_chunk_id(self, settings_no_llm, sample_chunks):
        refiner = ChunkRefiner(settings_no_llm)
        result = refiner.transform(sample_chunks)
        assert result[0].id == sample_chunks[0].id


class TestErrorHandling:
    def test_llm_not_configured(self, settings_no_llm, sample_chunks):
        refiner = ChunkRefiner(settings_no_llm)
        result = refiner.transform(sample_chunks)
        assert result[0].metadata["refined_by"] == "rule"


class TestConfiguration:
    def test_default_use_llm_false(self, settings_no_llm):
        refiner = ChunkRefiner(settings_no_llm)
        assert refiner.use_llm == False

    def test_use_llm_true(self, settings_with_llm):
        refiner = ChunkRefiner(settings_with_llm)
        assert refiner.use_llm == True
