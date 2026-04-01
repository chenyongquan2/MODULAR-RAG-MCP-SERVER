"""Tests for CHM Loader contract.

测试 ChmLoader 的基本契约：
1. 正确返回 Document 对象
2. 元数据设置正确
3. 错误处理（文件不存在、格式不支持等）
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.libs.loader.chm_loader import ChmLoader, HHCParser
from src.core.types import Document


@pytest.fixture
def chm_loader():
    """Create a CHM loader instance."""
    return ChmLoader(collection="test")


@pytest.fixture
def sample_hhc_content():
    """Sample .hhc file content for testing."""
    return """<!DOCTYPE HTML PUBLIC "-//IETF//DTD HTML//EN">
<HTML>
<BODY>
<OBJECT type="text/site properties">
    <param name="Window Styles" value="0x800025">
</OBJECT>
<UL>
<LI><OBJECT type="text/sitemap">
    <param name="Name" value="MetaTrader 5 API">
    <param name="Local" value="beginning.htm">
</OBJECT>

<UL>
<LI><OBJECT type="text/sitemap">
    <param name="Name" value="Getting Started">
    <param name="Local" value="getting_started.htm">
</OBJECT>

<LI><OBJECT type="text/sitemap">
    <param name="Name" value="System Requirements">
    <param name="Local" value="system_requirements.htm">
</OBJECT>
</UL>
</UL>
</BODY>
</HTML>"""


@pytest.fixture
def sample_html_content():
    """Sample HTML content for testing."""
    return """<!DOCTYPE html>
<html>
<head><title>Test Page</title></head>
<body>
<h1>Getting Started</h1>
<p>This is a test paragraph.</p>
<ul>
<li>Item 1</li>
<li>Item 2</li>
</ul>
</body>
</html>"""


class TestHHCParser:
    """测试 HHC 目录解析器。"""

    def test_parse_basic_toc(self, sample_hhc_content):
        """验证基本 TOC 解析。"""
        parser = HHCParser()
        parser.feed(sample_hhc_content)

        assert len(parser.entries) >= 1
        # 第一个条目应该是顶级条目
        assert parser.entries[0]["name"] == "MetaTrader 5 API"
        assert parser.entries[0]["path"] == "beginning.htm"

    def test_parse_toc_levels(self, sample_hhc_content):
        """验证 TOC 层级解析。"""
        parser = HHCParser()
        parser.feed(sample_hhc_content)

        # 找到 Getting Started 条目
        getting_started = next(
            (e for e in parser.entries if e["name"] == "Getting Started"),
            None
        )
        assert getting_started is not None
        assert getting_started["level"] >= 1  # 应该是子级

    def test_parse_empty_content(self):
        """验证空内容解析。"""
        parser = HHCParser()
        parser.feed("")

        assert len(parser.entries) == 0


class TestChmLoaderContract:
    """测试 ChmLoader 契约（使用 mock）。"""

    @pytest.mark.skipif(os.name != 'nt', reason="CHM loading requires Windows")
    def test_chm_loader_returns_document(self, chm_loader, tmp_path, sample_hhc_content, sample_html_content):
        """验证 CHM loader 返回有效的 Document 对象。"""
        # 创建模拟的解压目录结构
        chm_path = tmp_path / "test.chm"
        chm_path.write_bytes(b"fake chm content for hash")

        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()

        # 创建 .hhc 文件
        hhc_file = extract_dir / "test.hhc"
        hhc_file.write_text(sample_hhc_content, encoding='utf-8')

        # 创建 HTML 文件
        for filename in ["beginning.htm", "getting_started.htm", "system_requirements.htm"]:
            html_file = extract_dir / filename
            html_file.write_text(sample_html_content, encoding='utf-8')

        # Mock subprocess.run 来模拟 hh.exe
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            # Mock tempfile.mkdtemp 返回我们的测试目录
            with patch('tempfile.mkdtemp', return_value=str(extract_dir)):
                # 重新创建 loader 以使用 mock
                loader = ChmLoader(collection="test")
                doc = loader.load(str(chm_path))

        assert isinstance(doc, Document)
        assert doc.id.startswith("doc_")
        assert len(doc.text) > 0
        assert "Getting Started" in doc.text or "test paragraph" in doc.text.lower()

    @pytest.mark.skipif(os.name != 'nt', reason="CHM loading requires Windows")
    def test_chm_loader_metadata(self, chm_loader, tmp_path, sample_hhc_content, sample_html_content):
        """验证 CHM loader 设置正确的元数据。"""
        chm_path = tmp_path / "test.chm"
        chm_path.write_bytes(b"fake chm content")

        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()

        hhc_file = extract_dir / "test.hhc"
        hhc_file.write_text(sample_hhc_content, encoding='utf-8')

        html_file = extract_dir / "beginning.htm"
        html_file.write_text(sample_html_content, encoding='utf-8')

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            with patch('tempfile.mkdtemp', return_value=str(extract_dir)):
                loader = ChmLoader(collection="test_collection")
                doc = loader.load(str(chm_path))

        assert doc.metadata["source_path"] == str(chm_path)
        assert doc.metadata["collection"] == "test_collection"
        assert doc.metadata["doc_type"] == "chm"
        assert "section_count" in doc.metadata

    def test_chm_loader_file_not_found(self, chm_loader):
        """验证 CHM loader 对不存在的文件抛出错误。"""
        with pytest.raises(FileNotFoundError):
            chm_loader.load("non_existent.chm")

    def test_chm_loader_unsupported_format(self, chm_loader, tmp_path):
        """验证 CHM loader 对非 CHM 文件抛出错误。"""
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("Not a CHM")

        with pytest.raises(ValueError, match="Unsupported file format"):
            chm_loader.load(str(txt_file))

    @pytest.mark.skipif(os.name == 'nt', reason="Test non-Windows error")
    def test_chm_loader_non_windows(self, chm_loader, tmp_path):
        """验证非 Windows 系统上的错误。"""
        chm_path = tmp_path / "test.chm"
        chm_path.write_bytes(b"fake chm content")

        with patch('os.name', 'posix'):
            with pytest.raises(RuntimeError, match="only supported on Windows"):
                chm_loader.load(str(chm_path))


class TestChmLoaderHTMLConversion:
    """测试 HTML 到 Markdown 的转换。"""

    def test_html_to_markdown_conversion(self, chm_loader):
        """验证 HTML 正确转换为 Markdown。"""
        html_contents = [
            {
                "title": "Test Section",
                "html": "<h1>Title</h1><p>Paragraph</p><ul><li>Item 1</li><li>Item 2</li></ul>",
                "path": "test.htm",
                "level": 0,
            }
        ]

        markdown = chm_loader._convert_to_markdown(html_contents)

        assert "# Test Section" in markdown
        assert "Title" in markdown
        assert "Paragraph" in markdown

    def test_html_to_markdown_with_level(self, chm_loader):
        """验证层级标题正确生成。"""
        html_contents = [
            {
                "title": "Main Section",
                "html": "<p>Content</p>",
                "path": "main.htm",
                "level": 0,
            },
            {
                "title": "Sub Section",
                "html": "<p>More content</p>",
                "path": "sub.htm",
                "level": 1,
            }
        ]

        markdown = chm_loader._convert_to_markdown(html_contents)

        assert "# Main Section" in markdown  # Level 0 -> # (h1)
        assert "## Sub Section" in markdown  # Level 1 -> ## (h2)

    def test_clean_markdown(self, chm_loader):
        """验证 Markdown 清理。"""
        dirty_markdown = """
Line 1


Line 2




Line 3
"""
        clean = chm_loader._clean_markdown(dirty_markdown)

        # 不应该有超过2个连续换行
        assert "\n\n\n" not in clean


class TestChmLoaderEncoding:
    """测试编码处理。"""

    def test_extract_html_with_gbk_encoding(self, chm_loader, tmp_path):
        """验证 GBK 编码的 HTML 正确处理。"""
        # 创建 GBK 编码的 HTML 文件
        html_content = "<html><body><h1>中文标题</h1><p>中文内容测试。</p></body></html>"
        html_file = tmp_path / "test.htm"
        html_file.write_bytes(html_content.encode('gbk'))

        # 模拟 toc_entries
        toc_entries = [{"name": "测试", "path": "test.htm", "level": 0}]

        # 调用 _extract_html_pages
        html_contents = chm_loader._extract_html_pages(str(tmp_path), toc_entries)

        assert len(html_contents) == 1
        assert "中文" in html_contents[0]["html"]

    def test_extract_html_with_utf8_encoding(self, chm_loader, tmp_path):
        """验证 UTF-8 编码的 HTML 正确处理。"""
        html_content = "<html><body><h1>Title</h1><p>Content with special chars</p></body></html>"
        html_file = tmp_path / "test.htm"
        html_file.write_text(html_content, encoding='utf-8')

        toc_entries = [{"name": "Test", "path": "test.htm", "level": 0}]

        html_contents = chm_loader._extract_html_pages(str(tmp_path), toc_entries)

        assert len(html_contents) == 1
        assert "Title" in html_contents[0]["html"]
        assert "special chars" in html_contents[0]["html"]