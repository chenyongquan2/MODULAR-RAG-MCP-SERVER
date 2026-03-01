"""Chunk 智能重组/去噪。

该模块提供两种 chunk 精炼模式：
1. 规则去噪：去除页眉页脚、多余空白、HTML 标签等噪声
2. LLM 增强：通过 LLM 进行智能重写（可选）

设计原则：
- 规则模式始终启用，作为兜底逻辑
- LLM 模式可选，失败时自动降级到规则模式
- 单个 chunk 处理异常不影响其他 chunk
"""

import re
from typing import List, Optional
from pathlib import Path

from src.core.types import Chunk
from src.core.trace.trace_context import TraceContext
from src.ingestion.transform.base_transform import BaseTransform
from src.core.settings import Settings
from src.libs.llm.base_llm import BaseLLM


DEFAULT_PROMPT = """You are a text refinement assistant. Your task is to clean and improve the given text chunk by:

1. Removing noise like page headers, footers, and excessive whitespace
2. Fixing obvious OCR errors if present
3. Removing HTML tags and comments
4. Preserving important content structure (Markdown headings, code blocks, lists)
5. Keeping meaningful formatting (bold, italic, links)

Original chunk:
{text}

Refined chunk:"""


class ChunkRefiner(BaseTransform):
    """Chunk 精炼器。

    支持规则去噪和可选的 LLM 增强两种模式。

    Attributes:
        settings: 配置对象
        llm: LLM 实例（可选）
        prompt_template: LLM prompt 模板
    """

    def __init__(
        self,
        settings: Settings,
        llm: Optional[BaseLLM] = None,
        prompt_path: Optional[str] = None
    ):
        """初始化 ChunkRefiner。

        Args:
            settings: 配置对象
            llm: LLM 实例（可选）
            prompt_path: prompt 模板文件路径（可选）
        """
        self.settings = settings
        self.llm = llm
        self.use_llm = settings.ingestion.chunk_refiner.use_llm if hasattr(settings.ingestion, 'chunk_refiner') else False
        self.prompt_template = self._load_prompt(prompt_path)

    def _load_prompt(self, prompt_path: Optional[str] = None) -> str:
        """加载 prompt 模板。

        Args:
            prompt_path: prompt 文件路径

        Returns:
            prompt 模板字符串
        """
        if prompt_path and Path(prompt_path).exists():
            with open(prompt_path, 'r', encoding='utf-8') as f:
                return f.read()

        # Try default location
        default_path = Path("config/prompts/chunk_refinement.txt")
        if default_path.exists():
            with open(default_path, 'r', encoding='utf-8') as f:
                return f.read()

        return DEFAULT_PROMPT

    def transform(
        self,
        chunks: List[Chunk],
        trace: Optional[TraceContext] = None
    ) -> List[Chunk]:
        """转换 chunks。

        对每个 chunk 先进行规则去噪，然后可选地使用 LLM 增强。

        Args:
            chunks: 待转换的 chunks
            trace: 追踪上下文

        Returns:
            转换后的 chunks
        """
        if not chunks:
            return chunks

        # Start stage if trace provided
        stage = None
        if trace:
            stage = trace.start_stage("chunk_refine")

        refined_chunks = []
        for chunk in chunks:
            try:
                # Step 1: Rule-based refinement (always)
                refined_text = self._rule_based_refine(chunk.text)
                refined_chunk = Chunk(
                    id=chunk.id,
                    text=refined_text,
                    metadata=chunk.metadata.copy(),
                    start_offset=chunk.start_offset,
                    end_offset=chunk.end_offset,
                    source_ref=chunk.source_ref
                )
                refined_chunk.metadata["refined_by"] = "rule"

                # Step 2: LLM enhancement (optional)
                if self.use_llm and self.llm:
                    llm_result = self._llm_refine(refined_text, trace)
                    if llm_result:
                        refined_chunk.text = llm_result
                        refined_chunk.metadata["refined_by"] = "llm"

                refined_chunks.append(refined_chunk)

            except Exception as e:
                # Preserve original chunk on failure
                chunk.metadata["refine_error"] = str(e)
                chunk.metadata["refined_by"] = "rule"
                refined_chunks.append(chunk)

        # Finish stage
        if stage:
            trace.finish_stage("chunk_refine", {
                "input_chunks": len(chunks),
                "output_chunks": len(refined_chunks),
                "use_llm": self.use_llm
            })

        return refined_chunks

    def _rule_based_refine(self, text: str) -> str:
        """规则去噪。

        去除页眉页脚、多余空白、HTML 标签等噪声。

        Args:
            text: 原始文本

        Returns:
            去噪后的文本
        """
        if not text:
            return text

        # Step 1: Preserve code blocks (they should not be processed)
        code_blocks = []
        pattern = re.compile(r'(```[\s\S]*?```|~~~[\s\S]*?~~~)')

        def replace_code(match):
            placeholder = f"__CODE_BLOCK_{len(code_blocks)}__"
            code_blocks.append(match.group(1))
            return placeholder

        text = pattern.sub(replace_code, text)

        # Step 2: Remove HTML tags
        text = re.sub(r'<[^>]+>', '', text)

        # Step 3: Remove HTML comments
        text = re.sub(r'<!--[\s\S]*?-->', '', text)

        # Step 4: Remove common page headers/footers
        # Remove lines that look like page numbers
        text = re.sub(r'^Page \d+ of \d+$', '', text, flags=re.MULTILINE)
        
        # Remove CONFIDENTIAL or similar markings
        text = re.sub(r'^CONFIDENTIAL.*$', '', text, flags=re.MULTILINE | re.IGNORECASE)
        
        # Remove document IDs at the end
        text = re.sub(r'^---.*Document ID:.*$', '', text, flags=re.MULTILINE)

        # Step 5: Normalize horizontal rules
        text = re.sub(r'^[*_-]{3,}$', '', text, flags=re.MULTILINE)

        # Step 6: Normalize excessive whitespace (but preserve paragraph breaks)
        # Replace 3+ newlines with double newline (paragraph break)
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # Replace multiple spaces within a line with single space
        text = re.sub(r' +', ' ', text)

        # Restore code blocks
        for i, code in enumerate(code_blocks):
            text = text.replace(f"__CODE_BLOCK_{i}__", code)

        # Step 7: Strip leading/trailing whitespace from each line
        lines = text.split('\n')
        lines = [line.strip() for line in lines]
        text = '\n'.join(lines)

        # Step 8: Remove empty lines at start/end
        text = text.strip()

        return text

    def _llm_refine(
        self,
        text: str,
        trace: Optional[TraceContext] = None
    ) -> Optional[str]:
        """LLM 增强。

        使用 LLM 对文本进行智能重写。

        Args:
            text: 规则处理后的文本
            trace: 追踪上下文

        Returns:
            LLM 重写后的文本，失败返回 None
        """
        if not self.llm:
            return None

        try:
            prompt = self.prompt_template.format(text=text)
            messages = [
                {"role": "system", "content": "You are a text refinement assistant."},
                {"role": "user", "content": prompt}
            ]
            result = self.llm.chat(messages)
            return result.strip() if result else None
        except Exception as e:
            # Log error but don\'t raise - fallback to rule-based
            return None
