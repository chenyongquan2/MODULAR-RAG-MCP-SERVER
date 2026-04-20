"""Tests for PDF Loader contract.

单元测试通过 mock Docling converter 避免下载 ML 模型（HuggingFace Hub）。
集成测试（@pytest.mark.integration）才会真正调用 Docling 解析引擎。
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.libs.loader.pdf_loader import PdfLoader
from src.core.types import Document


def _make_mock_result(text: str = "# Hello, World!\nThis is a test document.\nLine 3: Testing PDF loading."):
    """构造 Docling ConversionResult 的最小 mock 对象。"""
    mock_doc = MagicMock()
    mock_doc.export_to_markdown.return_value = text
    mock_doc.pages = {1: MagicMock()}  # 1 页
    mock_doc.pictures = []             # 无图片

    mock_result = MagicMock()
    mock_result.document = mock_doc
    return mock_result


@pytest.fixture
def pdf_loader():
    """Create a PDF loader instance."""
    return PdfLoader(collection="test")


@pytest.fixture
def sample_pdf_path(tmp_path):
    """Create a minimal PDF file for testing."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    pdf_path = tmp_path / "test.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=letter)
    c.drawString(100, 750, "Hello, World!")
    c.drawString(100, 730, "This is a test document.")
    c.drawString(100, 710, "Line 3: Testing PDF loading.")
    c.save()
    return str(pdf_path)


def test_pdf_loader_returns_document(pdf_loader, sample_pdf_path):
    """Verify PDF loader returns a valid Document object."""
    with patch.object(pdf_loader._converter, "convert", return_value=_make_mock_result()):
        doc = pdf_loader.load(sample_pdf_path)

    assert isinstance(doc, Document)
    assert doc.id.startswith("doc_")
    assert len(doc.text) > 0
    assert "Hello, World!" in doc.text


def test_pdf_loader_metadata(pdf_loader, sample_pdf_path):
    """Verify PDF loader sets correct metadata."""
    with patch.object(pdf_loader._converter, "convert", return_value=_make_mock_result()):
        doc = pdf_loader.load(sample_pdf_path)

    assert doc.metadata["source_path"] == sample_pdf_path
    assert doc.metadata["collection"] == "test"
    assert doc.metadata["doc_type"] == "pdf"
    assert doc.metadata["parser"] == "docling"


def test_pdf_loader_file_not_found(pdf_loader):
    """Verify PDF loader raises error for non-existent file."""
    with pytest.raises(FileNotFoundError):
        pdf_loader.load("non_existent.pdf")


def test_pdf_loader_unsupported_format(pdf_loader, tmp_path):
    """Verify PDF loader raises error for non-PDF files."""
    txt_file = tmp_path / "test.txt"
    txt_file.write_text("Not a PDF")

    with pytest.raises(ValueError, match="不支持的文件格式"):
        pdf_loader.load(str(txt_file))


def test_pdf_loader_page_count_in_metadata(pdf_loader, sample_pdf_path):
    """Verify page count is stored in metadata."""
    mock_result = _make_mock_result()
    mock_result.document.pages = {1: MagicMock(), 2: MagicMock()}  # 2 页

    with patch.object(pdf_loader._converter, "convert", return_value=mock_result):
        doc = pdf_loader.load(sample_pdf_path)

    assert doc.metadata["page_count"] == 2


@pytest.mark.integration
def test_pdf_loader_real_docling(sample_pdf_path):
    """集成测试：真实调用 Docling（需要网络下载模型，首次运行较慢）。"""
    loader = PdfLoader(collection="integration_test")
    doc = loader.load(sample_pdf_path)

    assert isinstance(doc, Document)
    assert doc.id.startswith("doc_")
    assert len(doc.text) > 0
