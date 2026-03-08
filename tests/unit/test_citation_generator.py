"""单元测试：引用生成器。"""

import pytest
from src.core.types import RetrievalResult
from src.core.response.citation_generator import Citation, CitationGenerator


class TestCitation:
    """测试 Citation 数据类。"""

    def test_basic_creation(self):
        """测试基本创建。"""
        citation = Citation(
            id=1,
            source="doc.pdf",
            page=10,
            chunk_id="chunk_001",
            score=0.95,
            text="Sample text",
        )
        assert citation.id == 1
        assert citation.source == "doc.pdf"
        assert citation.page == 10
        assert citation.chunk_id == "chunk_001"
        assert citation.score == 0.95
        assert citation.text == "Sample text"

    def test_creation_without_page(self):
        """测试不包含页码的创建。"""
        citation = Citation(
            id=1,
            source="doc.md",
            page=None,
            chunk_id="chunk_001",
            score=0.85,
            text="Sample text",
        )
        assert citation.page is None


class TestCitationGenerator:
    """测试 CitationGenerator 类。"""

    def test_generate_empty_results(self):
        """测试空结果列表。"""
        generator = CitationGenerator()
        citations = generator.generate([])
        assert citations == []

    def test_generate_single_result(self):
        """测试单个检索结果。"""
        generator = CitationGenerator()
        results = [
            RetrievalResult(
                chunk_id="chunk_001",
                score=0.95,
                text="Sample text",
                metadata={"source_path": "doc.pdf", "page": 10},
            )
        ]
        citations = generator.generate(results)
        assert len(citations) == 1
        assert citations[0].id == 1
        assert citations[0].source == "doc.pdf"
        assert citations[0].page == 10
        assert citations[0].chunk_id == "chunk_001"
        assert citations[0].score == 0.95
        assert citations[0].text == "Sample text"

    def test_generate_multiple_results(self):
        """测试多个检索结果。"""
        generator = CitationGenerator()
        results = [
            RetrievalResult(
                chunk_id="chunk_001",
                score=0.95,
                text="Text 1",
                metadata={"source_path": "doc1.pdf", "page": 10},
            ),
            RetrievalResult(
                chunk_id="chunk_002",
                score=0.85,
                text="Text 2",
                metadata={"source_path": "doc2.pdf", "page": 20},
            ),
            RetrievalResult(
                chunk_id="chunk_003",
                score=0.75,
                text="Text 3",
                metadata={"source_path": "doc3.pdf", "page": 30},
            ),
        ]
        citations = generator.generate(results)
        assert len(citations) == 3
        assert citations[0].id == 1
        assert citations[1].id == 2
        assert citations[2].id == 3
        assert citations[0].source == "doc1.pdf"
        assert citations[1].source == "doc2.pdf"
        assert citations[2].source == "doc3.pdf"

    def test_generate_with_source_field(self):
        """测试使用 source 字段而非 source_path。"""
        generator = CitationGenerator()
        results = [
            RetrievalResult(
                chunk_id="chunk_001",
                score=0.95,
                text="Sample text",
                metadata={"source": "Custom Source", "source_path": "doc.pdf"},
            )
        ]
        citations = generator.generate(results)
        assert citations[0].source == "Custom Source"

    def test_generate_without_page(self):
        """测试不包含页码的检索结果。"""
        generator = CitationGenerator()
        results = [
            RetrievalResult(
                chunk_id="chunk_001",
                score=0.95,
                text="Sample text",
                metadata={"source_path": "doc.md"},
            )
        ]
        citations = generator.generate(results)
        assert citations[0].page is None

    def test_generate_with_missing_source_path(self):
        """测试缺少 source_path 的检索结果。"""
        generator = CitationGenerator()
        results = [
            RetrievalResult(
                chunk_id="chunk_001",
                score=0.95,
                text="Sample text",
                metadata={},
            )
        ]
        citations = generator.generate(results)
        assert citations[0].source == "unknown"

    def test_generate_preserves_order(self):
        """测试引用序号与检索结果顺序一致。"""
        generator = CitationGenerator()
        results = [
            RetrievalResult(
                chunk_id="chunk_003",
                score=0.75,
                text="Text 3",
                metadata={"source_path": "doc3.pdf"},
            ),
            RetrievalResult(
                chunk_id="chunk_001",
                score=0.95,
                text="Text 1",
                metadata={"source_path": "doc1.pdf"},
            ),
            RetrievalResult(
                chunk_id="chunk_002",
                score=0.85,
                text="Text 2",
                metadata={"source_path": "doc2.pdf"},
            ),
        ]
        citations = generator.generate(results)
        # 引用顺序应与检索结果顺序一致
        assert citations[0].chunk_id == "chunk_003"
        assert citations[1].chunk_id == "chunk_001"
        assert citations[2].chunk_id == "chunk_002"
        assert [c.id for c in citations] == [1, 2, 3]


class TestStructuredContent:
    """测试 StructuredContent 数据类。"""

    def test_basic_creation(self):
        """测试基本创建。"""
        from src.core.response.citation_generator import StructuredContent, Citation

        citations = [
            Citation(
                id=1,
                source="doc.pdf",
                page=10,
                chunk_id="chunk_001",
                score=0.95,
                text="Sample text",
            )
        ]
        content = StructuredContent(
            markdown="RAG system combines retrieval and generation [1].",
            citations=citations,
        )
        assert content.markdown == "RAG system combines retrieval and generation [1]."
        assert len(content.citations) == 1
        assert content.citations[0].id == 1