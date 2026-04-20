"""Tests for PDF Loader image extraction functionality (Docling 引擎版).

单元测试通过 mock Docling converter 避免下载 ML 模型。
测试覆盖：
1. 无图片 PDF → metadata["images"] 为空列表
2. 图片提取后存储为 ImageReference 对象
3. Markdown 文本中插入 [IMAGE: id] 占位符
4. 清理临时目录功能
5. SHA256 哈希计算
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.libs.loader.pdf_loader import PdfLoader
from src.core.types import Document, ImageReference


def _make_mock_result(text: str = "Hello, World!", pictures=None):
    """构造 Docling ConversionResult 的最小 mock 对象。"""
    mock_doc = MagicMock()
    mock_doc.export_to_markdown.return_value = text
    mock_doc.pages = {1: MagicMock()}
    mock_doc.pictures = pictures or []

    mock_result = MagicMock()
    mock_result.document = mock_doc
    return mock_result


@pytest.fixture
def pdf_loader():
    """Create a PDF loader instance."""
    return PdfLoader(collection="test_collection")


@pytest.fixture
def temp_image_dir():
    """Create a temporary directory for extracted images."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


def _make_simple_pdf(path: Path) -> None:
    """创建一个包含文字的简单 PDF，供测试用。"""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=letter)
    c.drawString(100, 750, "Hello, World!")
    c.drawString(100, 730, "This is a test document.")
    c.save()


class TestPdfLoaderImageExtraction:
    """测试 PdfLoader 图片提取功能（Docling 引擎）。"""

    def test_pdf_without_images_returns_empty_list(self, pdf_loader, tmp_path):
        """无图片 PDF 应返回空图片列表。"""
        pdf_path = tmp_path / "no_image.pdf"
        _make_simple_pdf(pdf_path)

        with patch.object(pdf_loader._converter, "convert", return_value=_make_mock_result()):
            doc = pdf_loader.load(str(pdf_path))

        assert isinstance(doc, Document)
        assert len(doc.text) > 0
        images = doc.metadata.get("images", [])
        assert isinstance(images, list)
        assert len(images) == 0

    def test_pdf_with_mocked_images(self, pdf_loader, tmp_path):
        """通过 mock _extract_and_embed_images 验证图片信息正确写入 metadata。"""
        pdf_path = tmp_path / "test.pdf"
        _make_simple_pdf(pdf_path)

        img_path = tmp_path / "img_abc123_1_0.png"
        img_path.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)
        fake_ref = ImageReference(
            id="img_abc123_1_0",
            path=str(img_path),
            text_offset=0,
            text_length=20,
            page=1,
            position={"bbox": {"l": 0, "t": 0, "r": 100, "b": 100}},
        )

        with patch.object(pdf_loader._converter, "convert", return_value=_make_mock_result()):
            with patch.object(
                pdf_loader,
                "_extract_and_embed_images",
                return_value=("mock text with [IMAGE: img_abc123_1_0]", [fake_ref]),
            ):
                doc = pdf_loader.load(str(pdf_path))

        assert "images" in doc.metadata
        assert len(doc.metadata["images"]) == 1
        img_ref = doc.metadata["images"][0]
        assert isinstance(img_ref, ImageReference)
        assert img_ref.id == "img_abc123_1_0"
        assert img_ref.page == 1

    def test_image_placeholder_in_text(self, pdf_loader, tmp_path):
        """图片占位符应出现在 Markdown 文本中。"""
        pdf_path = tmp_path / "test.pdf"
        _make_simple_pdf(pdf_path)

        fake_ref = ImageReference(
            id="img_test_001",
            path=str(tmp_path / "img_test_001.png"),
            text_offset=10,
            text_length=22,
            page=0,
        )

        with patch.object(pdf_loader._converter, "convert", return_value=_make_mock_result()):
            with patch.object(
                pdf_loader,
                "_extract_and_embed_images",
                return_value=("Some text\n[IMAGE: img_test_001]\n", [fake_ref]),
            ):
                doc = pdf_loader.load(str(pdf_path))

        assert "[IMAGE: img_test_001]" in doc.text

    def test_multiple_images_in_metadata(self, pdf_loader, tmp_path):
        """多张图片应全部写入 metadata["images"]。"""
        pdf_path = tmp_path / "multi.pdf"
        _make_simple_pdf(pdf_path)

        fake_refs = [
            ImageReference(
                id=f"img_hash_{i}_0",
                path=str(tmp_path / f"img_{i}.png"),
                text_offset=0,
                text_length=20,
                page=i,
            )
            for i in range(3)
        ]

        with patch.object(pdf_loader._converter, "convert", return_value=_make_mock_result()):
            with patch.object(
                pdf_loader,
                "_extract_and_embed_images",
                return_value=("text", fake_refs),
            ):
                doc = pdf_loader.load(str(pdf_path))

        assert len(doc.metadata.get("images", [])) == 3

    def test_image_reference_has_required_fields(self, pdf_loader, tmp_path):
        """ImageReference 必须包含 id、path、page 字段。"""
        pdf_path = tmp_path / "test.pdf"
        _make_simple_pdf(pdf_path)

        fake_ref = ImageReference(
            id="img_struct_test",
            path="/tmp/img.png",
            text_offset=5,
            text_length=22,
            page=2,
            position={"bbox": {"l": 50, "t": 100, "r": 200, "b": 300}},
        )

        with patch.object(pdf_loader._converter, "convert", return_value=_make_mock_result()):
            with patch.object(
                pdf_loader,
                "_extract_and_embed_images",
                return_value=("text", [fake_ref]),
            ):
                doc = pdf_loader.load(str(pdf_path))

        img_ref = doc.metadata["images"][0]
        assert img_ref.id == "img_struct_test"
        assert img_ref.page == 2
        assert img_ref.position is not None


class TestPdfLoaderHashCompute:
    """测试 _compute_hash 生成稳定文档 ID。"""

    def test_hash_is_16_chars(self, pdf_loader, tmp_path):
        """哈希值应为 16 位十六进制字符串。"""
        pdf_path = tmp_path / "test.pdf"
        _make_simple_pdf(pdf_path)

        doc_hash = pdf_loader._compute_hash(pdf_path)
        assert len(doc_hash) == 16
        assert all(c in "0123456789abcdef" for c in doc_hash)

    def test_same_file_same_hash(self, pdf_loader, tmp_path):
        """同一文件两次计算哈希应一致。"""
        pdf_path = tmp_path / "test.pdf"
        _make_simple_pdf(pdf_path)

        h1 = pdf_loader._compute_hash(pdf_path)
        h2 = pdf_loader._compute_hash(pdf_path)
        assert h1 == h2

    def test_different_files_different_hash(self, pdf_loader, tmp_path):
        """不同文件内容应产生不同哈希。"""
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        pdf1 = tmp_path / "a.pdf"
        c = canvas.Canvas(str(pdf1), pagesize=letter)
        c.drawString(100, 750, "Content A")
        c.save()

        pdf2 = tmp_path / "b.pdf"
        c = canvas.Canvas(str(pdf2), pagesize=letter)
        c.drawString(100, 750, "Content B — different")
        c.save()

        assert pdf_loader._compute_hash(pdf1) != pdf_loader._compute_hash(pdf2)


class TestPdfLoaderCleanup:
    """测试临时目录清理功能。"""

    def test_cleanup_removes_temp_dirs(self, pdf_loader, tmp_path):
        """cleanup_temp_dirs 应清空 _temp_dirs 列表并删除目录。"""
        fake_dir = tmp_path / "fake_temp"
        fake_dir.mkdir()
        pdf_loader._temp_dirs.append(str(fake_dir))

        pdf_loader.cleanup_temp_dirs()

        assert len(pdf_loader._temp_dirs) == 0
        assert not fake_dir.exists()
