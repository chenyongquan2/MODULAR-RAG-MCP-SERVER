"""CHM Loader - 支持编译HTML帮助文档的加载。

CHM (Compiled HTML Help) 是 Windows 帮助文档格式，内部包含多个 HTML 页面。
本加载器的工作流程：
1. 使用 Windows 自带的 hh.exe -decompile 解压 CHM 文件
2. 解析 .hhc 目录文件，确定页面阅读顺序
3. 遍历所有 HTML 页面，提取文本内容
4. 使用 markdownify 将 HTML 转换为 Markdown
5. 按目录顺序合并为单一 Document 对象

CHM 结构说明：
- .chm 文件是一个压缩包，包含多个 HTML、CSS、图片等资源
- .hhc 文件是目录索引（HTML 格式）
- .hhk 文件是关键词索引
- 每个 HTML 页面对应一个主题或章节

优势：
- 使用 Windows 原生 hh.exe，无需额外依赖
- 兼容性好，支持所有 CHM 格式
"""

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional
from html.parser import HTMLParser
from xml.etree import ElementTree as ET

from markdownify import markdownify as md

from src.core.types import Document
from src.observability.logger import get_logger
from .base_loader import BaseLoader

logger = get_logger(__name__)


class HHCParser(HTMLParser):
    """解析 CHM 目录文件 (.hhc) 的解析器。

    .hhc 文件是一个特殊的 HTML 文件，包含目录结构。
    格式类似：
        <html>
        <body>
        <ul>
            <li><object type="text/sitemap">
                <param name="Name" value="章节名称">
                <param name="Local" value="page.htm">
            </object></li>
        </ul>
        </body>
        </html>
    """

    def __init__(self):
        super().__init__()
        self.entries: List[Dict[str, Any]] = []
        self.current_entry: Dict[str, Any] = {}
        self.current_param = None
        self.level = 0

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        """处理开始标签。"""
        attrs_dict = dict(attrs)

        if tag == "ul":
            # <ul> 表示进入下一级
            self.level += 1
        elif tag == "li":
            # <li> 开始新的目录项
            self.current_entry = {"level": self.level}
        elif tag == "param":
            # <param> 包含 Name 或 Local 信息
            name = attrs_dict.get("name", "").lower()
            value = attrs_dict.get("value", "")
            if name == "name":
                self.current_entry["name"] = value
            elif name == "local":
                self.current_entry["path"] = value

    def handle_endtag(self, tag: str) -> None:
        """处理结束标签。"""
        if tag == "ul":
            # </ul> 表示退出一级
            self.level = max(0, self.level - 1)
        elif tag == "object":
            # </object> 结束当前目录项，保存到列表
            # 注意：HTMLParser 会将标签名转为小写
            if self.current_entry.get("name") or self.current_entry.get("path"):
                self.entries.append(self.current_entry.copy())
            self.current_entry = {}


class ChmLoader(BaseLoader):
    """CHM 文档加载器。

    使用 Windows 原生 hh.exe 解压 CHM 文件，
    并转换为 Markdown 格式供后续处理。

    Attributes:
        collection: 文档所属集合名称
        encoding: HTML 内容的默认编码（默认 UTF-8）

    Example:
        >>> loader = ChmLoader(collection="mt5_docs")
        >>> doc = loader.load("path/to/MetaTrader5.chm")
        >>> print(doc.text[:100])
    """

    # 支持的文件扩展名
    SUPPORTED_EXTENSIONS = [".chm"]

    def __init__(self, collection: str = "default", encoding: str = "utf-8"):
        """初始化 CHM 加载器。

        Args:
            collection: 文档所属集合名称
            encoding: HTML 内容的默认编码，默认 UTF-8
        """
        super().__init__(collection)
        self.encoding = encoding
        self._temp_dirs: List[str] = []  # 跟踪临时目录

    def load(self, path: str | Path) -> Document:
        """加载 CHM 文档。

        Args:
            path: CHM 文件路径

        Returns:
            Document: 加载后的文档对象，包含合并后的 Markdown 文本

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文件格式不支持或解析失败
            RuntimeError: 解压失败（非 Windows 系统或 hh.exe 不可用）
        """
        path = self._validate_path(path)

        if path.suffix.lower() != ".chm":
            raise ValueError(f"Unsupported file format: {path.suffix}. Expected .chm")

        logger.info(f"Loading CHM file: {path}")

        # 计算 CHM 文件哈希作为文档 ID
        doc_hash = hashlib.sha256(path.read_bytes()).hexdigest()[:16]

        # 创建临时目录用于解压
        temp_dir = tempfile.mkdtemp(prefix="chm_extract_")
        self._temp_dirs.append(temp_dir)

        try:
            # 1. 使用 hh.exe 解压 CHM
            self._decompile_chm(path, temp_dir)

            # 2. 解析目录结构 (.hhc 文件)
            toc_entries = self._parse_hhc_file(temp_dir)
            logger.info(f"Extracted {len(toc_entries)} TOC entries from CHM")

            # 3. 提取所有 HTML 页面内容
            html_contents = self._extract_html_pages(temp_dir, toc_entries)

            # 4. 转换并合并为 Markdown
            markdown_text = self._convert_to_markdown(html_contents)

            if not markdown_text.strip():
                raise ValueError(f"No text content extracted from CHM: {path}")

            # 5. 提取文档元数据
            title = self._extract_title(temp_dir, path)

            logger.info(
                f"CHM loaded successfully: {path} -> "
                f"{len(markdown_text)} chars, {len(toc_entries)} sections"
            )

            return Document(
                id=f"doc_{doc_hash}",
                text=markdown_text,
                metadata={
                    "source_path": str(path),
                    "collection": self.collection,
                    "doc_type": "chm",
                    "title": title,
                    "section_count": len(toc_entries),
                    "encoding": self.encoding,
                }
            )

        finally:
            # 清理临时目录
            self._cleanup_temp_dirs()

    def _decompile_chm(self, chm_path: Path, output_dir: str) -> None:
        """使用 hh.exe 解压 CHM 文件。

        Args:
            chm_path: CHM 文件路径
            output_dir: 输出目录

        Raises:
            RuntimeError: 解压失败
        """
        # 检查是否为 Windows 系统
        if os.name != 'nt':
            raise RuntimeError(
                "CHM loading is currently only supported on Windows. "
                "Please use a Windows system or extract the CHM manually."
            )

        # 使用 hh.exe -decompile 解压
        # 语法: hh.exe -decompile <输出目录> <CHM文件>
        try:
            result = subprocess.run(
                ["hh.exe", "-decompile", output_dir, str(chm_path)],
                capture_output=True,
                timeout=60,  # 60秒超时
                check=False,
            )

            # hh.exe 即使成功也不返回 0，检查输出目录
            if not Path(output_dir).exists() or not list(Path(output_dir).iterdir()):
                raise RuntimeError(
                    f"Failed to decompile CHM file. "
                    f"stderr: {result.stderr.decode('utf-8', errors='ignore')}"
                )

            logger.debug(f"CHM decompiled to: {output_dir}")

        except subprocess.TimeoutExpired:
            raise RuntimeError("CHM decompilation timed out after 60 seconds")
        except FileNotFoundError:
            raise RuntimeError(
                "hh.exe not found. This command requires Windows with hh.exe available."
            )

    def _parse_hhc_file(self, extract_dir: str) -> List[Dict[str, Any]]:
        """解析 CHM 目录文件 (.hhc)。

        Args:
            extract_dir: CHM 解压目录

        Returns:
            List[Dict]: 目录条目列表
        """
        extract_path = Path(extract_dir)

        # 查找 .hhc 文件
        hhc_files = list(extract_path.glob("*.hhc"))

        if not hhc_files:
            logger.warning("No .hhc file found, will scan all HTML files")
            return self._scan_html_files(extract_path)

        # 使用第一个 .hhc 文件
        hhc_file = hhc_files[0]
        logger.debug(f"Parsing HHC file: {hhc_file}")

        try:
            # 尝试多种编码读取 .hhc 内容
            content = None
            for encoding in ['utf-8', 'gbk', 'gb2312', 'gb18030', 'latin-1']:
                try:
                    content = hhc_file.read_text(encoding=encoding)
                    # 检查是否有乱码（大量替换字符）
                    if content.count('') < len(content) * 0.1:
                        logger.debug(f"HHC decoded successfully with {encoding}")
                        break
                except UnicodeDecodeError:
                    continue

            if content is None:
                content = hhc_file.read_text(encoding='utf-8', errors='ignore')

            # 使用 HTML 解析器解析
            parser = HHCParser()
            parser.feed(content)

            if parser.entries:
                logger.info(f"HHC parsed {len(parser.entries)} entries")
                return parser.entries
            else:
                logger.warning("HHC parser found no entries, falling back to file scan")
                return self._scan_html_files(extract_path)

        except Exception as e:
            logger.warning(f"Failed to parse HHC file: {e}, scanning HTML files")
            return self._scan_html_files(extract_path)

    def _scan_html_files(self, extract_path: Path) -> List[Dict[str, Any]]:
        """扫描目录中的所有 HTML 文件（当没有 .hhc 时）。

        Args:
            extract_path: CHM 解压目录

        Returns:
            List[Dict]: 文件条目列表
        """
        entries = []

        # 查找所有 HTML 文件
        html_files = list(extract_path.glob("*.htm")) + list(extract_path.glob("*.html"))

        for html_file in sorted(html_files):
            # 跳过目录文件本身
            if html_file.suffix.lower() in ['.hhc', '.hhk']:
                continue

            entries.append({
                "name": html_file.stem,
                "path": html_file.name,
                "level": 0,
            })

        return entries

    def _extract_html_pages(
        self,
        extract_dir: str,
        toc_entries: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """从解压目录中提取 HTML 页面内容。

        Args:
            extract_dir: CHM 解压目录
            toc_entries: 目录条目列表

        Returns:
            List[Dict]: 提取的页面内容
        """
        extract_path = Path(extract_dir)
        html_contents = []

        for entry in toc_entries:
            path = entry.get("path", "")
            if not path:
                continue

            # 构建 HTML 文件路径
            html_file = extract_path / path

            # 尝试不同的路径变体
            if not html_file.exists():
                # 尝试直接文件名
                html_file = extract_path / Path(path).name
            if not html_file.exists():
                # 尝试小写
                html_file = extract_path / path.lower()
            if not html_file.exists():
                continue

            # 读取 HTML 内容
            try:
                html_content = html_file.read_text(encoding='utf-8', errors='ignore')

                # 如果 UTF-8 解码效果不好，尝试其他编码
                if '' in html_content or html_content.count('') > 10:
                    for encoding in ['gbk', 'gb2312', 'gb18030']:
                        try:
                            html_content = html_file.read_text(encoding=encoding)
                            break
                        except UnicodeDecodeError:
                            continue

                if html_content.strip():
                    html_contents.append({
                        "title": entry.get("name", ""),
                        "html": html_content,
                        "path": path,
                        "level": entry.get("level", 0),
                    })

            except Exception as e:
                logger.debug(f"Failed to read HTML file {html_file}: {e}")
                continue

        return html_contents

    def _convert_to_markdown(
        self,
        html_contents: List[Dict[str, Any]]
    ) -> str:
        """将 HTML 内容转换为 Markdown 并合并。

        Args:
            html_contents: HTML 内容列表

        Returns:
            str: 合并后的 Markdown 文本
        """
        markdown_parts = []

        for page in html_contents:
            title = page.get("title", "")
            html = page.get("html", "")
            level = page.get("level", 0)

            if not html.strip():
                continue

            # 转换 HTML 到 Markdown
            try:
                # 使用 markdownify 转换
                # strip 移除 script 和 style 标签
                markdown = md(
                    html,
                    heading_style="atx",  # 使用 # 风格的标题
                    strip=['script', 'style', 'head', 'meta', 'link'],
                    escape_asterisks=False,
                    escape_underscores=False,
                )

                # 清理多余的空白行
                markdown = self._clean_markdown(markdown)

                if markdown.strip():
                    # 根据目录层级添加标题
                    # level 从 1 开始，所以加 1
                    heading_level = min(level + 1, 6)  # Markdown 最多支持 6 级标题
                    heading_prefix = "#" * heading_level
                    section_text = f"\n\n{heading_prefix} {title}\n\n{markdown}"
                    markdown_parts.append(section_text)

            except Exception as e:
                logger.warning(f"Failed to convert HTML to Markdown: {e}")
                continue

        return "\n".join(markdown_parts)

    def _clean_markdown(self, markdown: str) -> str:
        """清理 Markdown 文本。

        移除多余的空白行和空白字符。

        Args:
            markdown: 原始 Markdown 文本

        Returns:
            str: 清理后的 Markdown 文本
        """
        # 移除连续超过2个的空行
        markdown = re.sub(r'\n{3,}', '\n\n', markdown)

        # 移除行首行尾的空白（保留代码块内的缩进）
        lines = markdown.split('\n')
        cleaned_lines = []
        in_code_block = False

        for line in lines:
            # 检测代码块边界
            if line.strip().startswith('```'):
                in_code_block = not in_code_block
                cleaned_lines.append(line.rstrip())
            elif in_code_block:
                # 代码块内保留缩进
                cleaned_lines.append(line.rstrip())
            else:
                # 普通文本移除首尾空白
                cleaned_lines.append(line.strip())

        return '\n'.join(cleaned_lines).strip()

    def _extract_title(self, extract_dir: str, path: Path) -> str:
        """提取 CHM 文档标题。

        Args:
            extract_dir: CHM 解压目录
            path: CHM 文件路径

        Returns:
            str: 文档标题
        """
        extract_path = Path(extract_dir)

        # 尝试从 .hhc 文件中提取标题
        hhc_files = list(extract_path.glob("*.hhc"))
        if hhc_files:
            try:
                content = hhc_files[0].read_text(encoding='utf-8', errors='ignore')
                # 尝试提取第一个条目作为标题
                match = re.search(r'<param\s+name="Name"\s+value="([^"]+)"', content)
                if match:
                    return match.group(1)
            except Exception:
                pass

        # 使用文件名作为标题
        return path.stem

    def _cleanup_temp_dirs(self) -> None:
        """清理临时目录。"""
        for temp_dir in self._temp_dirs:
            try:
                if Path(temp_dir).exists():
                    shutil.rmtree(temp_dir)
                    logger.debug(f"Cleaned up temp directory: {temp_dir}")
            except Exception as e:
                logger.warning(f"Failed to cleanup temp directory {temp_dir}: {e}")
        self._temp_dirs.clear()