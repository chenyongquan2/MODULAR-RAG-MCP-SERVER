"""元数据增强器。

该模块提供两种元数据增强模式:
1. 规则增强:基于启发式规则生成 title/summary/tags
2. LLM 增强:通过 LLM 进行智能元数据生成(可选)

设计原则:
- 规则模式始终启用,作为兜底逻辑
- LLM 模式可选,失败时自动降级到规则模式
- 单个 chunk 处理异常不影响其他 chunk
- 生成的 metadata 必须包含 title/summary/tags 字段
"""

import re
from typing import List, Optional, Dict, Any
from pathlib import Path
import json

from src.core.types import Chunk
from src.core.trace.trace_context import TraceContext
from src.ingestion.transform.base_transform import BaseTransform
from src.core.settings import Settings
from src.libs.llm.base_llm import BaseLLM


DEFAULT_PROMPT = """You are a metadata enrichment assistant. Analyze the given text chunk and generate high-quality metadata.

Requirements:
1. Generate a concise title (max 10 words) that captures the main topic
2. Write a brief summary (2-3 sentences) highlighting key information
3. Extract 3-5 relevant tags/keywords that describe the content

Output format (JSON):
{{
  "title": "Concise chunk title",
  "summary": "Brief summary of the chunk content highlighting key points.",
  "tags": ["keyword1", "keyword2", "keyword3"]
}}

Text chunk:
{text}

Metadata (JSON only):"""


class MetadataEnricher(BaseTransform):
    """元数据增强器。

    支持规则增强和可选的 LLM 增强两种模式。

    Attributes:
        settings: 配置对象
        llm: LLM 实例(可选)
        prompt_template: LLM prompt 模板
        use_llm: 是否使用 LLM 增强
    """

    def __init__(
        self,
        settings: Settings,
        llm: Optional[BaseLLM] = None,
        prompt_path: Optional[str] = None
    ):
        """初始化 MetadataEnricher。

        Args:
            settings: 配置对象
            llm: LLM 实例(可选)
            prompt_path: prompt 模板文件路径(可选)
        """
        self.settings = settings
        self.llm = llm
        # Check if metadata_enricher config exists and use_llm is set
        self.use_llm = False
        if hasattr(settings.ingestion, 'metadata_enricher'):
            self.use_llm = settings.ingestion.metadata_enricher.use_llm
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
        default_path = Path("config/prompts/metadata_enrichment.txt")
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

        对每个 chunk 先进行规则增强,然后可选地使用 LLM 增强。

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
            stage = trace.start_stage("metadata_enrich")

        enriched_chunks = []
        for chunk in chunks:
            try:
                # Step 1: Rule-based enrichment (always)
                rule_metadata = self._rule_based_enrich(chunk.text)
                enriched_chunk = Chunk(
                    id=chunk.id,
                    text=chunk.text,
                    metadata=chunk.metadata.copy(),
                    start_offset=chunk.start_offset,
                    end_offset=chunk.end_offset,
                    source_ref=chunk.source_ref
                )
                # Merge rule-based metadata
                enriched_chunk.metadata.update(rule_metadata)
                enriched_chunk.metadata["enriched"] = True
                enriched_chunk.metadata["enriched_by"] = "rule"

                # Step 2: LLM enhancement (optional)
                if self.use_llm and self.llm:
                    llm_metadata = self._llm_enrich(chunk.text, trace)
                    if llm_metadata:
                        # Override with LLM metadata if successful
                        enriched_chunk.metadata.update(llm_metadata)
                        enriched_chunk.metadata["enriched_by"] = "llm"

                enriched_chunks.append(enriched_chunk)

            except Exception as e:
                # Preserve original chunk on failure
                chunk.metadata["enrich_error"] = str(e)
                chunk.metadata["enriched"] = False
                enriched_chunks.append(chunk)

        # Finish stage
        if stage:
            trace.finish_stage("metadata_enrich", {
                "input_chunks": len(chunks),
                "output_chunks": len(enriched_chunks),
                "use_llm": self.use_llm
            })

        return enriched_chunks

    def _rule_based_enrich(self, text: str) -> Dict[str, Any]:
        """规则增强。

        基于启发式规则生成元数据。

        Args:
            text: chunk 文本

        Returns:
            包含 title/summary/tags 的字典
        """
        if not text:
            return {
                "title": "Empty chunk",
                "summary": "This chunk contains no text.",
                "tags": []
            }

        # Extract title: use first line or first sentence
        title = self._extract_title(text)

        # Generate summary: first 2-3 sentences or truncate to ~200 chars
        summary = self._generate_summary(text)

        # Extract tags: extract capitalized words and common nouns
        tags = self._extract_tags(text)

        return {
            "title": title,
            "summary": summary,
            "tags": tags
        }

    def _extract_title(self, text: str) -> str:
        """提取标题。

        优先级:
        1. Markdown 标题(# xxx)
        2. 首行(如果短于 100 字符)
        3. 首句(句号前的内容)
        4. 前 50 字符

        Args:
            text: 文本

        Returns:
            标题字符串(max 100 chars)
        """
        # Try Markdown heading
        heading_match = re.match(r'^#{1,6}\s+(.+)$', text, re.MULTILINE)
        if heading_match:
            return heading_match.group(1).strip()[:100]

        # Try first line
        first_line = text.split('\n')[0].strip()
        if first_line and len(first_line) < 100:
            return first_line

        # Try first sentence
        sentence_match = re.match(r'^(.+?)[.!?]', text)
        if sentence_match:
            return sentence_match.group(1).strip()[:100]

        # Fallback: first 50 chars
        return text[:50].strip() + ('...' if len(text) > 50 else '')

    def _generate_summary(self, text: str) -> str:
        """生成摘要。

        提取前 2-3 句话作为摘要,或截断到约 200 字符。

        Args:
            text: 文本

        Returns:
            摘要字符串(max 300 chars)
        """
        # Extract first 2-3 sentences
        sentences = re.split(r'[.!?]\s+', text)
        if len(sentences) >= 2:
            summary = '. '.join(sentences[:2]) + '.'
        elif sentences:
            summary = sentences[0]
        else:
            summary = text

        # Truncate to max 300 chars
        if len(summary) > 300:
            summary = summary[:297] + '...'

        return summary.strip()

    def _extract_tags(self, text: str) -> List[str]:
        """提取标签。

        启发式规则:
        1. 提取大写开头的单词(可能是专有名词)
        2. 提取常见技术词汇
        3. 去重并限制到 5 个

        Args:
            text: 文本

        Returns:
            标签列表(max 5 items)
        """
        tags = set()

        # Extract capitalized words (potential proper nouns)
        # Match words starting with capital letter (length >= 3)
        capitalized = re.findall(r'\b[A-Z][a-z]{2,}\b', text)
        tags.update(capitalized[:5])

        # Extract technical keywords (case-insensitive)
        common_keywords = [
            'API', 'configuration', 'database', 'server', 'client',
            'authentication', 'authorization', 'security', 'encryption',
            'performance', 'optimization', 'error', 'exception', 'logging',
            'deployment', 'testing', 'integration', 'module', 'function',
            'class', 'method', 'parameter', 'return', 'example'
        ]
        text_lower = text.lower()
        for keyword in common_keywords:
            if keyword.lower() in text_lower:
                tags.add(keyword)

        # Limit to 5 tags
        return sorted(list(tags))[:5]

    def _llm_enrich(
        self,
        text: str,
        trace: Optional[TraceContext] = None
    ) -> Optional[Dict[str, Any]]:
        """LLM 增强。

        使用 LLM 生成高质量元数据。

        Args:
            text: chunk 文本
            trace: 追踪上下文

        Returns:
            包含 title/summary/tags 的字典,失败返回 None
        """
        if not self.llm:
            return None

        try:
            prompt = self.prompt_template.format(text=text[:1000])  # Limit input length
            messages = [
                {"role": "system", "content": "You are a metadata enrichment assistant."},
                {"role": "user", "content": prompt}
            ]
            result = self.llm.chat(messages)

            if not result:
                return None

            # Parse JSON response
            metadata = self._parse_llm_response(result)
            return metadata

        except Exception as e:
            # Log error but don't raise - fallback to rule-based
            return None

    def _parse_llm_response(self, response: str) -> Optional[Dict[str, Any]]:
        """解析 LLM 返回的 JSON 格式元数据。

        Args:
            response: LLM 响应文本

        Returns:
            解析后的元数据字典,失败返回 None
        """
        try:
            # Try to extract JSON from response
            # LLM might wrap JSON in markdown code blocks
            json_match = re.search(r'\{[\s\S]*\}', response)
            if not json_match:
                return None

            json_str = json_match.group(0)
            metadata = json.loads(json_str)

            # Validate required fields
            if not all(k in metadata for k in ['title', 'summary', 'tags']):
                return None

            # Validate types
            if not isinstance(metadata['title'], str):
                return None
            if not isinstance(metadata['summary'], str):
                return None
            if not isinstance(metadata['tags'], list):
                return None

            # Truncate if too long
            metadata['title'] = metadata['title'][:100]
            metadata['summary'] = metadata['summary'][:300]
            metadata['tags'] = metadata['tags'][:5]

            return metadata

        except (json.JSONDecodeError, KeyError, TypeError):
            return None
