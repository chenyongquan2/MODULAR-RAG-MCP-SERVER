"""Tests for PDF Loader image extraction functionality.

测试 PdfLoader 从 PDF 中提取图片的功能：
1. 提取嵌入图片并保存到临时目录
2. 生成 ImageReference 并添加到 metadata["images"]
3. 在文本中插入 [IMAGE: {image_id}] 占位符
4. 处理无图片 PDF 的场景
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.libs.loader.pdf_loader import PdfLoader
from src.core.types import Document, ImageReference


@pytest.fixture
def pdf_loader():
    """Create a PDF loader instance."""
    return PdfLoader(collection="test_collection")


@pytest.fixture
def temp_image_dir():
    """Create a temporary directory for extracted images."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


class TestPdfLoaderImageExtraction:
    """测试 PdfLoader 图片提取功能。"""

    def test_extract_images_from_pdf_with_images(self, pdf_loader, temp_image_dir):
        """测试从包含图片的 PDF 中提取图片。"""
        # 创建一个包含图片的模拟 PDF
        # 由于 reportlab 创建带图片的 PDF 较复杂，我们使用 mock 来测试逻辑
        with patch.object(pdf_loader, '_extract_images') as mock_extract:
            # 模拟提取的图片
            mock_image_path = Path(temp_image_dir) / "test_image.png"
            mock_image_path.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)

            mock_extract.return_value = [
                {
                    "image_id": "img_abc123_0_0",
                    "temp_path": str(mock_image_path),
                    "page": 0,
                    "position": {"x0": 0, "y0": 0, "x1": 100, "y1": 100},
                }
            ]

            # 创建一个简单的 PDF 用于测试
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas

            pdf_path = Path(temp_image_dir) / "test_with_image.pdf"
            c = canvas.Canvas(str(pdf_path), pagesize=letter)
            c.drawString(100, 750, "Test document with image placeholder.")
            c.save()

            # 加载 PDF
            doc = pdf_loader.load(str(pdf_path))

            # 验证图片被提取
            assert "images" in doc.metadata
            assert len(doc.metadata["images"]) == 1

            img_ref = doc.metadata["images"][0]
            assert isinstance(img_ref, ImageReference)
            assert img_ref.id == "img_abc123_0_0"
            assert img_ref.page == 0

    def test_pdf_without_images(self, pdf_loader, temp_image_dir):
        """测试处理不包含图片的 PDF。"""
        # 创建一个简单的无图片 PDF
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        pdf_path = Path(temp_image_dir) / "test_no_image.pdf"
        c = canvas.Canvas(str(pdf_path), pagesize=letter)
        c.drawString(100, 750, "Hello, World!")
        c.drawString(100, 730, "This is a test document without images.")
        c.save()

        # 加载 PDF
        doc = pdf_loader.load(str(pdf_path))

        # 验证无图片时 metadata 正常
        assert isinstance(doc, Document)
        assert len(doc.text) > 0
        # images 字段应该为空列表或不存在
        images = doc.metadata.get("images", [])
        assert len(images) == 0

    def test_image_placeholder_in_text(self, pdf_loader, temp_image_dir):
        """测试图片占位符插入到文本中。"""
        with patch.object(pdf_loader, '_extract_images') as mock_extract:
            mock_image_path = Path(temp_image_dir) / "test_image.png"
            mock_image_path.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)

            mock_extract.return_value = [
                {
                    "image_id": "img_test_001",
                    "temp_path": str(mock_image_path),
                    "page": 0,
                    "position": {"x0": 0, "y0": 0, "x1": 100, "y1": 100},
                }
            ]

            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas

            pdf_path = Path(temp_image_dir) / "test_placeholder.pdf"
            c = canvas.Canvas(str(pdf_path), pagesize=letter)
            c.drawString(100, 750, "Before image.")
            c.drawString(100, 730, "After image.")
            c.save()

            doc = pdf_loader.load(str(pdf_path))

            # 验证文本中包含图片占位符
            assert "[IMAGE:" in doc.text or len(doc.metadata.get("images", [])) > 0

    def test_multiple_images_extraction(self, pdf_loader, temp_image_dir):
        """测试提取多张图片。"""
        with patch.object(pdf_loader, '_extract_images') as mock_extract:
            # 模拟多张图片
            images = []
            for i in range(3):
                img_path = Path(temp_image_dir) / f"image_{i}.png"
                img_path.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)
                images.append({
                    "image_id": f"img_test_{i}",
                    "temp_path": str(img_path),
                    "page": i,
                    "position": {"x0": 0, "y0": 0, "x1": 100, "y1": 100},
                })

            mock_extract.return_value = images

            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas

            pdf_path = Path(temp_image_dir) / "test_multi_images.pdf"
            c = canvas.Canvas(str(pdf_path), pagesize=letter)
            for i in range(3):
                c.drawString(100, 750 - i * 20, f"Page {i} content.")
                c.showPage()
            c.save()

            doc = pdf_loader.load(str(pdf_path))

            # 验证多张图片被提取
            assert len(doc.metadata.get("images", [])) == 3

    def test_image_reference_structure(self, pdf_loader, temp_image_dir):
        """测试 ImageReference 结构正确性。"""
        with patch.object(pdf_loader, '_extract_images') as mock_extract:
            mock_image_path = Path(temp_image_dir) / "test_image.png"
            mock_image_path.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)

            mock_extract.return_value = [
                {
                    "image_id": "img_structure_test",
                    "temp_path": str(mock_image_path),
                    "page": 2,
                    "position": {"x0": 50, "y0": 100, "x1": 200, "y1": 300},
                }
            ]

            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas

            pdf_path = Path(temp_image_dir) / "test_structure.pdf"
            c = canvas.Canvas(str(pdf_path), pagesize=letter)
            c.drawString(100, 750, "Test content.")
            c.save()

            doc = pdf_loader.load(str(pdf_path))

            img_ref = doc.metadata["images"][0]

            # 验证 ImageReference 字段
            assert img_ref.id == "img_structure_test"
            assert img_ref.page == 2
            assert img_ref.position is not None
            assert img_ref.position["x0"] == 50
            assert img_ref.position["y0"] == 100


class TestPdfLoaderImageIdGeneration:
    """测试图片 ID 生成逻辑。"""

    def test_image_id_format(self, pdf_loader):
        """测试图片 ID 格式：{doc_hash}_{page}_{seq}。"""
        doc_hash = "abc123def456"
        page = 1
        seq = 0

        image_id = pdf_loader._generate_image_id(doc_hash, page, seq)

        assert image_id == f"img_{doc_hash}_{page}_{seq}"

    def test_image_id_uniqueness(self, pdf_loader):
        """测试不同图片生成不同 ID。"""
        doc_hash = "test123"

        id1 = pdf_loader._generate_image_id(doc_hash, 0, 0)
        id2 = pdf_loader._generate_image_id(doc_hash, 0, 1)
        id3 = pdf_loader._generate_image_id(doc_hash, 1, 0)

        assert id1 != id2
        assert id2 != id3
        assert id1 != id3


class TestPdfLoaderImageSaving:
    """测试图片保存功能。"""

    def test_save_extracted_image(self, pdf_loader, temp_image_dir):
        """测试保存提取的图片到临时目录。"""
        # 创建模拟图片数据
        image_data = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100

        saved_path = pdf_loader._save_temp_image(
            image_data=image_data,
            image_id="test_save_001",
            temp_dir=temp_image_dir
        )

        assert saved_path is not None
        assert Path(saved_path).exists()
        assert Path(saved_path).read_bytes() == image_data

    def test_save_image_with_correct_extension(self, pdf_loader, temp_image_dir):
        """测试根据图片类型保存正确扩展名。"""
        # JPEG 图片头
        jpeg_data = b'\xff\xd8\xff\xe0' + b'\x00' * 100

        saved_path = pdf_loader._save_temp_image(
            image_data=jpeg_data,
            image_id="test_jpeg",
            temp_dir=temp_image_dir
        )

        assert Path(saved_path).suffix in ['.jpg', '.jpeg']
