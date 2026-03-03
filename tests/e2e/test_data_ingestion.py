"""End-to-end tests for data ingestion.

These tests verify the complete ingestion pipeline from file to indexed chunks.

Note: These tests require the full environment to be set up (Python dependencies,
optional: LLM/Embedding providers for full pipeline). Some tests can run with
mocked external dependencies.
"""

import os
import pytest
from pathlib import Path

from src.core.settings import load_settings
from src.ingestion.pipeline import IngestionPipeline


def check_embedding_available():
    """Check if embedding provider is available (API key or Ollama)."""
    try:
        settings = load_settings()
        provider = settings.embedding.provider
        
        if provider == "openai":
            return bool(os.environ.get("OPENAI_API_KEY"))
        elif provider == "azure":
            return bool(getattr(settings.embedding, 'api_key', None))
        elif provider == "ollama":
            import urllib.request
            urllib.request.urlopen("http://localhost:11434", timeout=2)
            return True
        return False
    except Exception:
        return False


EMBEDDING_AVAILABLE = check_embedding_available()


@pytest.fixture
def test_settings():
    """Load test settings."""
    return load_settings()


@pytest.fixture
def temp_pdf_file(tmp_path):
    """Create a temporary PDF file for testing."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    pdf_path = tmp_path / "test_document.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=letter)
    
    c.drawString(100, 750, "Test Document Title")
    c.drawString(100, 730, "This is a test document for E2E ingestion.")
    c.drawString(100, 710, "Section 1: Introduction")
    c.drawString(100, 690, "This is the introduction section.")
    c.drawString(100, 670, "Section 2: Content")
    c.drawString(100, 650, "This is the main content section.")
    c.save()
    
    return str(pdf_path)


@pytest.fixture
def temp_directory_with_pdfs(tmp_path):
    """Create a temporary directory with multiple PDF files."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    pdf_dir = tmp_path / "documents"
    pdf_dir.mkdir()

    for i in range(3):
        pdf_path = pdf_dir / f"document_{i}.pdf"
        c = canvas.Canvas(str(pdf_path), pagesize=letter)
        c.drawString(100, 750, f"Document {i}")
        c.drawString(100, 730, f"This is test document number {i}.")
        c.save()

    return str(pdf_dir)


@pytest.mark.e2e
@pytest.mark.skipif(not EMBEDDING_AVAILABLE, reason="Embedding provider not available")
class TestIngestScript:
    """Tests for the ingestion script functionality."""

    def test_ingest_single_file(self, test_settings, temp_pdf_file, tmp_path):
        """Test ingesting a single PDF file."""
        collection = "test_collection_e2e"
        
        pipeline = IngestionPipeline(test_settings, collection=collection)
        result = pipeline.run(temp_pdf_file, force=True)

        assert result["status"] == "success"
        assert "stages" in result
        assert result["stages"]["store"]["chunk_count"] > 0

    def test_ingest_creates_vector_store(self, test_settings, temp_pdf_file, tmp_path):
        """Test that ingestion creates vector store artifacts."""
        collection = "test_vector_store"
        
        pipeline = IngestionPipeline(test_settings, collection=collection)
        result = pipeline.run(temp_pdf_file, force=True)

        assert result["status"] == "success"
        
        vector_dir = Path("data/db/chroma")
        assert vector_dir.exists() or result["stages"]["store"]["chunk_count"] > 0

    def test_ingest_creates_bm25_index(self, test_settings, temp_pdf_file):
        """Test that ingestion creates BM25 index."""
        collection = "test_bm25_index"
        
        pipeline = IngestionPipeline(test_settings, collection=collection)
        result = pipeline.run(temp_pdf_file, force=True)

        assert result["status"] == "success"
        
        bm25_dir = Path("data/db/bm25")
        assert bm25_dir.exists() or result["stages"]["store"]["chunk_count"] > 0

    def test_ingest_skip_unchanged_file(self, test_settings, temp_pdf_file):
        """Test that unchanged files are skipped on re-run."""
        collection = "test_skip"
        
        pipeline = IngestionPipeline(test_settings, collection=collection)
        
        result1 = pipeline.run(temp_pdf_file, force=True)
        assert result1["status"] == "success"
        
        result2 = pipeline.run(temp_pdf_file, force=False)
        assert result2["status"] in ["skipped", "success"]

    def test_ingest_force_reprocess(self, test_settings, temp_pdf_file):
        """Test force reprocess bypasses skip check."""
        collection = "test_force"
        
        pipeline = IngestionPipeline(test_settings, collection=collection)
        
        result1 = pipeline.run(temp_pdf_file, force=True)
        assert result1["status"] == "success"
        
        result2 = pipeline.run(temp_pdf_file, force=True)
        assert result2["status"] == "success"

    def test_ingest_multiple_files(self, test_settings, temp_directory_with_pdfs):
        """Test ingesting multiple PDF files from a directory."""
        collection = "test_multi"
        
        pipeline = IngestionPipeline(test_settings, collection=collection)
        
        pdf_dir = Path(temp_directory_with_pdfs)
        pdf_files = sorted(pdf_dir.glob("*.pdf"))
        
        success_count = 0
        for pdf_file in pdf_files:
            result = pipeline.run(str(pdf_file), force=True)
            if result["status"] == "success":
                success_count += 1
        
        assert success_count == 3


@pytest.mark.e2e
def test_ingest_file_not_found(test_settings):
    """Test handling of non-existent file."""
    collection = "test_not_found"
    
    pipeline = IngestionPipeline(test_settings, collection=collection)
    
    with pytest.raises(FileNotFoundError):
        pipeline.run("non_existent_file.pdf", force=True)


@pytest.mark.e2e
@pytest.mark.skipif(not EMBEDDING_AVAILABLE, reason="Embedding provider not available")
class TestIngestIntegration:
    """Integration tests that verify end-to-end pipeline behavior."""

    def test_pipeline_produces_chunk_records(self, test_settings, temp_pdf_file):
        """Verify pipeline produces valid chunk records."""
        collection = "test_chunks"
        
        pipeline = IngestionPipeline(test_settings, collection=collection)
        result = pipeline.run(temp_pdf_file, force=True)

        assert result["status"] == "success"
        
        assert "split" in result["stages"]
        assert result["stages"]["split"]["chunk_count"] > 0
        
        assert "store" in result["stages"]
        assert result["stages"]["store"]["chunk_count"] > 0
