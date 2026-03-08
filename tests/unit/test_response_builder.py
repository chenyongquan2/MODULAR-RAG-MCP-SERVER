"""单元测试：响应构建器。"""

import pytest
from unittest.mock import Mock

from src.core.types import RetrievalResult
from src.core.response.response_builder import ResponseBuilder
from src.core.response.citation_generator import StructuredContent, CitationGenerator
from src.libs.llm.base_llm import BaseLLM


class MockSettings:
    """Mock settings for testing."""
    llm = Mock()
    llm.provider = "glm"  # Use a valid provider
    llm.model = "test-model"
    llm.api_key = "test-key"


class MockLLM(BaseLLM):
    """Mock LLM for testing."""

    def __init__(self, settings=None, **kwargs):
        self.settings = settings
        self.model_name = "test-model"

    def chat(self, messages, trace=None, **kwargs):
        return "Generated response based on context [1]."

    def get_model_name(self) -> str:
        return self.model_name

    def validate_messages(self, messages):
        """Skip validation for tests."""
        pass


class TestResponseBuilder:
    """测试 ResponseBuilder 类。"""

    def test_build_with_empty_results(self):
        """测试空检索结果。"""
        mock_settings = MockSettings()
        mock_llm = MockLLM()
        mock_llm.chat = Mock(return_value="No results found.")
        citation_gen = CitationGenerator()

        builder = ResponseBuilder.__new__(ResponseBuilder)
        builder.settings = mock_settings
        builder.llm = mock_llm
        builder.citation_generator = citation_gen
        builder.prompt_template = "Query: {query}\n\nContext:\n{context}"

        results = []

        structured_content = builder.build(query="test query", results=results)

        assert isinstance(structured_content, StructuredContent)
        assert len(structured_content.citations) == 0

    def test_build_with_single_result(self):
        """测试单个检索结果。"""
        mock_settings = MockSettings()
        mock_llm = MockLLM()
        mock_llm.chat = Mock(return_value="Generated response [1].")
        citation_gen = CitationGenerator()

        builder = ResponseBuilder.__new__(ResponseBuilder)
        builder.settings = mock_settings
        builder.llm = mock_llm
        builder.citation_generator = citation_gen
        builder.prompt_template = "Query: {query}\n\nContext:\n{context}"

        results = [
            RetrievalResult(
                chunk_id="chunk_001",
                score=0.95,
                text="Sample text about RAG system",
                metadata={"source_path": "doc.pdf", "page": 10},
            )
        ]

        structured_content = builder.build(query="What is RAG?", results=results)

        assert isinstance(structured_content, StructuredContent)
        assert len(structured_content.citations) == 1
        assert structured_content.citations[0].id == 1
        assert structured_content.citations[0].source == "doc.pdf"
        assert structured_content.citations[0].page == 10

    def test_build_with_multiple_results(self):
        """测试多个检索结果。"""
        mock_settings = MockSettings()
        mock_llm = MockLLM()
        mock_llm.chat = Mock(return_value="Generated response [1] [2] [3].")
        citation_gen = CitationGenerator()

        builder = ResponseBuilder.__new__(ResponseBuilder)
        builder.settings = mock_settings
        builder.llm = mock_llm
        builder.citation_generator = citation_gen
        builder.prompt_template = "Query: {query}\n\nContext:\n{context}"

        results = [
            RetrievalResult(
                chunk_id="chunk_001",
                score=0.95,
                text="Text 1",
                metadata={"source_path": "doc1.pdf", "page": 10},
            ),
            RetrievalResult(
                chunk_id="chunk_002",
                score=0.85,
                text="Text 2",
                metadata={"source_path": "doc2.pdf", "page": 20},
            ),
            RetrievalResult(
                chunk_id="chunk_003",
                score=0.75,
                text="Text 3",
                metadata={"source_path": "doc3.pdf", "page": 30},
            ),
        ]

        structured_content = builder.build(query="test query", results=results)

        assert isinstance(structured_content, StructuredContent)
        assert len(structured_content.citations) == 3
        assert [c.id for c in structured_content.citations] == [1, 2, 3]

    def test_build_includes_query_and_context(self):
        """测试构建的提示词包含查询和上下文。"""
        mock_settings = MockSettings()
        mock_llm = MockLLM()
        captured_messages = []

        def capture_chat(messages, trace=None, **kwargs):
            captured_messages.extend(messages)
            return "Generated response"

        mock_llm.chat = capture_chat
        citation_gen = CitationGenerator()

        builder = ResponseBuilder.__new__(ResponseBuilder)
        builder.settings = mock_settings
        builder.llm = mock_llm
        builder.citation_generator = citation_gen
        builder.prompt_template = "Query: {query}\n\nContext:\n{context}"

        results = [
            RetrievalResult(
                chunk_id="chunk_001",
                score=0.95,
                text="Sample text",
                metadata={"source_path": "doc.pdf", "page": 10},
            )
        ]

        builder.build(query="What is RAG?", results=results)

        # Verify messages were passed correctly
        assert len(captured_messages) == 2
        assert captured_messages[0]["role"] == "system"
        assert captured_messages[1]["role"] == "user"
        assert "What is RAG?" in captured_messages[1]["content"]
        assert "Context" in captured_messages[1]["content"]

    def test_build_context_format(self):
        """测试上下文格式包含引用序号。"""
        mock_settings = MockSettings()
        mock_llm = MockLLM()
        captured_prompt = None

        def capture_chat(messages, trace=None, **kwargs):
            nonlocal captured_prompt
            captured_prompt = messages[1]["content"]
            return "Generated response"

        mock_llm.chat = capture_chat
        citation_gen = CitationGenerator()

        builder = ResponseBuilder.__new__(ResponseBuilder)
        builder.settings = mock_settings
        builder.llm = mock_llm
        builder.citation_generator = citation_gen
        builder.prompt_template = "Query: {query}\n\nContext:\n{context}"

        results = [
            RetrievalResult(
                chunk_id="chunk_001",
                score=0.95,
                text="Sample text",
                metadata={"source_path": "doc.pdf", "page": 10},
            )
        ]

        builder.build(query="test", results=results)

        # Verify context contains citation marker
        assert "[1]" in captured_prompt
        assert "来源文档" in captured_prompt
        assert "doc.pdf" in captured_prompt
        assert "页 10" in captured_prompt

    def test_build_context_with_missing_page(self):
        """测试缺失页码时上下文格式。"""
        mock_settings = MockSettings()
        mock_llm = MockLLM()
        captured_prompt = None

        def capture_chat(messages, trace=None, **kwargs):
            nonlocal captured_prompt
            captured_prompt = messages[1]["content"]
            return "Generated response"

        mock_llm.chat = capture_chat
        citation_gen = CitationGenerator()

        builder = ResponseBuilder.__new__(ResponseBuilder)
        builder.settings = mock_settings
        builder.llm = mock_llm
        builder.citation_generator = citation_gen
        builder.prompt_template = "Query: {query}\n\nContext:\n{context}"

        results = [
            RetrievalResult(
                chunk_id="chunk_001",
                score=0.95,
                text="Sample text",
                metadata={"source_path": "doc.md"},
            )
        ]

        builder.build(query="test", results=results)

        # Verify no page info is included
        assert "doc.md" in captured_prompt
        assert "(页" not in captured_prompt  # No page info

    def test_build_with_trace(self):
        """测试传递 trace 参数。"""
        mock_settings = MockSettings()
        mock_llm = MockLLM()
        mock_llm.chat = Mock(return_value="Generated response")
        citation_gen = CitationGenerator()

        builder = ResponseBuilder.__new__(ResponseBuilder)
        builder.settings = mock_settings
        builder.llm = mock_llm
        builder.citation_generator = citation_gen
        builder.prompt_template = "Query: {query}\n\nContext:\n{context}"

        results = [
            RetrievalResult(
                chunk_id="chunk_001",
                score=0.95,
                text="Sample text",
                metadata={"source_path": "doc.pdf"},
            )
        ]

        mock_trace = Mock()

        builder.build(query="test", results=results, trace=mock_trace)

        # Verify trace was passed to LLM
        mock_llm.chat.assert_called_once()
        call_kwargs = mock_llm.chat.call_args[1]
        assert call_kwargs.get("trace") == mock_trace

    def test_build_with_additional_kwargs(self):
        """测试传递额外的 LLM 参数。"""
        mock_settings = MockSettings()
        mock_llm = MockLLM()
        mock_llm.chat = Mock(return_value="Generated response")
        citation_gen = CitationGenerator()

        builder = ResponseBuilder.__new__(ResponseBuilder)
        builder.settings = mock_settings
        builder.llm = mock_llm
        builder.citation_generator = citation_gen
        builder.prompt_template = "Query: {query}\n\nContext:\n{context}"

        results = [
            RetrievalResult(
                chunk_id="chunk_001",
                score=0.95,
                text="Sample text",
                metadata={"source_path": "doc.pdf"},
            )
        ]

        builder.build(query="test", results=results, temperature=0.7, max_tokens=1000)

        # Verify additional kwargs were passed to LLM
        call_kwargs = mock_llm.chat.call_args[1]
        assert call_kwargs.get("temperature") == 0.7
        assert call_kwargs.get("max_tokens") == 1000

    def test_build_context_format_multiple_citations(self):
        """测试多个引用时的上下文格式。"""
        mock_settings = MockSettings()
        mock_llm = MockLLM()
        captured_prompt = None

        def capture_chat(messages, trace=None, **kwargs):
            nonlocal captured_prompt
            captured_prompt = messages[1]["content"]
            return "Generated response"

        mock_llm.chat = capture_chat
        citation_gen = CitationGenerator()

        builder = ResponseBuilder.__new__(ResponseBuilder)
        builder.settings = mock_settings
        builder.llm = mock_llm
        builder.citation_generator = citation_gen
        builder.prompt_template = "Query: {query}\n\nContext:\n{context}"

        results = [
            RetrievalResult(
                chunk_id="chunk_001",
                score=0.95,
                text="Text 1",
                metadata={"source_path": "doc1.pdf", "page": 10},
            ),
            RetrievalResult(
                chunk_id="chunk_002",
                score=0.85,
                text="Text 2",
                metadata={"source_path": "doc2.pdf", "page": 20},
            ),
        ]

        builder.build(query="test", results=results)

        # Verify context contains both citation markers
        assert "[1]" in captured_prompt
        assert "[2]" in captured_prompt
        assert "doc1.pdf" in captured_prompt
        assert "doc2.pdf" in captured_prompt