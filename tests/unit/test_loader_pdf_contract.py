"""Tests for PDF Loader contract."""

import pytest
from pathlib import Path

from libs.loader.pdf_loader import PdfLoader
from core.types import Document


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
    doc = pdf_loader.load(sample_pdf_path)

    assert isinstance(doc, Document)
    assert doc.id.startswith("doc_")
    assert len(doc.text) > 0
    assert "Hello, World!" in doc.text


def test_pdf_loader_metadata(pdf_loader, sample_pdf_path):
    """Verify PDF loader sets correct metadata."""
    doc = pdf_loader.load(sample_pdf_path)

    assert doc.metadata["source_path"] == sample_pdf_path
    assert doc.metadata["collection"] == "test"
    assert doc.metadata["doc_type"] == "pdf"


def test_pdf_loader_file_not_found(pdf_loader):
    """Verify PDF loader raises error for non-existent file."""
    with pytest.raises(FileNotFoundError):
        pdf_loader.load("non_existent.pdf")


def test_pdf_loader_unsupported_format(pdf_loader, tmp_path):
    """Verify PDF loader raises error for non-PDF files."""
    txt_file = tmp_path / "test.txt"
    txt_file.write_text("Not a PDF")

    with pytest.raises(ValueError, match="Unsupported file format"):
        pdf_loader.load(str(txt_file))
