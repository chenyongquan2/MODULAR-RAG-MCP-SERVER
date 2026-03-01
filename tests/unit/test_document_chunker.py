"""Unit tests for DocumentChunker.

This module tests the DocumentChunker class.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from src.core.settings import Settings, SplitterSettings
from src.core.types import Document, Chunk
from src.ingestion.chunking.document_chunker import DocumentChunker


@pytest.fixture
def default_settings() -> Settings:
    return Settings(
        llm=None,
        embedding=None,
        vision_llm=None,
        vector_store=None,
        splitter=SplitterSettings(
            strategy="recursive",
            chunk_size=1000,
            chunk_overlap=200,
        )
    )


@pytest.fixture
def mock_splitter():
    splitter = MagicMock()
    splitter.get_strategy_name.return_value = "mock"
    splitter.get_chunk_size.return_value = 1000
    splitter.get_chunk_overlap.return_value = 200
    return splitter


@pytest.fixture
def simple_document() -> Document:
    return Document(
        id="simpledoc",
        text="Hello world. This is a test. Foo bar baz.",
        metadata={"source_path": "/test.pdf"}
    )


@pytest.mark.unit
def test_init_with_settings(default_settings):
    chunker = DocumentChunker(default_settings)
    assert chunker._splitter is not None


@pytest.mark.unit
def test_init_with_injected_splitter(default_settings, mock_splitter):
    chunker = DocumentChunker(default_settings, splitter=mock_splitter)
    assert chunker._splitter == mock_splitter


@pytest.mark.unit
def test_split_document_basic(default_settings, mock_splitter, simple_document):
    mock_splitter.split_text.return_value = ["Hello world.", "This is a test.", "Foo bar baz."]
    chunker = DocumentChunker(default_settings, splitter=mock_splitter)
    chunks = chunker.split_document(simple_document)
    assert len(chunks) == 3


@pytest.mark.unit
def test_chunk_id_format(default_settings, mock_splitter, simple_document):
    mock_splitter.split_text.return_value = ["Test content"]
    chunker = DocumentChunker(default_settings, splitter=mock_splitter)
    chunks = chunker.split_document(simple_document)
    assert chunks[0].id.startswith("simpledoc_")


@pytest.mark.unit
def test_chunk_index_added(default_settings, mock_splitter, simple_document):
    mock_splitter.split_text.return_value = ["A", "B", "C", "D"]
    chunker = DocumentChunker(default_settings, splitter=mock_splitter)
    chunks = chunker.split_document(simple_document)
    assert chunks[0].metadata["chunk_index"] == 0
    assert chunks[3].metadata["chunk_index"] == 3


@pytest.mark.unit
def test_source_ref_points_to_document_id(default_settings, mock_splitter, simple_document):
    mock_splitter.split_text.return_value = ["Content"]
    chunker = DocumentChunker(default_settings, splitter=mock_splitter)
    chunks = chunker.split_document(simple_document)
    assert chunks[0].source_ref == "simpledoc"


@pytest.mark.unit
def test_metadata_inherited_from_document(default_settings, mock_splitter):
    mock_splitter.split_text.return_value = ["Content"]
    doc = Document(id="doc123", text="Test", metadata={"source_path": "/path.pdf", "title": "Test"})
    chunker = DocumentChunker(default_settings, splitter=mock_splitter)
    chunks = chunker.split_document(doc)
    assert chunks[0].metadata["source_path"] == "/path.pdf"
    assert chunks[0].metadata["title"] == "Test"


@pytest.mark.unit
def test_empty_text_returns_empty_list(default_settings, mock_splitter):
    doc = Document(id="empty", text="   ", metadata={"source_path": "/test.pdf"})
    chunker = DocumentChunker(default_settings, splitter=mock_splitter)
    chunks = chunker.split_document(doc)
    assert chunks == []


@pytest.mark.unit
def test_invalid_document_raises_error(default_settings, mock_splitter):
    chunker = DocumentChunker(default_settings, splitter=mock_splitter)
    with pytest.raises(ValueError, match="must be a Document instance"):
        chunker.split_document("not a document")


@pytest.mark.unit
def test_integration_with_recursive_splitter(default_settings):
    chunker = DocumentChunker(default_settings)
    doc = Document(id="testdoc", text="Title Section One Content", metadata={"source_path": "/test.pdf"})
    chunks = chunker.split_document(doc)
    assert len(chunks) > 0
    assert all(isinstance(c, Chunk) for c in chunks)
