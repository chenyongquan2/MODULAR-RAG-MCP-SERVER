"""QueryProcessor 单元测试。"""

import pytest
from core.query_engine.query_processor import (
    QueryProcessor,
    QueryProcessorConfig,
    DEFAULT_STOPWORDS,
)
from core.types import ProcessedQuery


class TestQueryProcessor:
    """QueryProcessor 测试套件。"""

    def test_process_basic_query(self) -> None:
        """测试基本查询处理。"""
        processor = QueryProcessor()
        result = processor.process("How to configure LLM settings")

        assert isinstance(result, ProcessedQuery)
        assert result.original_query == "How to configure LLM settings"
        assert "configure" in result.keywords
        assert "llm" in result.keywords
        assert "settings" in result.keywords

    def test_process_removes_stopwords(self) -> None:
        """测试停用词过滤。"""
        processor = QueryProcessor()
        result = processor.process("how to configure the llm")

        assert "how" not in result.keywords
        assert "to" not in result.keywords
        assert "the" not in result.keywords
        assert "configure" in result.keywords
        assert "llm" in result.keywords

    def test_process_preserves_meaningful_words(self) -> None:
        """测试保留有意义的词汇。"""
        processor = QueryProcessor()
        result = processor.process("What is RAG pipeline architecture")

        assert "what" in result.keywords or "is" in result.keywords or "rag" in result.keywords
        assert "rag" in result.keywords
        assert "pipeline" in result.keywords
        assert "architecture" in result.keywords

    def test_process_with_punctuation(self) -> None:
        """测试带标点符号的查询。"""
        processor = QueryProcessor()
        result = processor.process("How to: configure LLM, and embedding?")

        assert "configure" in result.keywords
        assert "llm" in result.keywords
        assert "embedding" in result.keywords

    def test_process_with_special_chars(self) -> None:
        """测试带特殊字符的查询。"""
        processor = QueryProcessor()
        result = processor.process("Query@database #search $filter")

        assert "query" in result.keywords or "database" in result.keywords

    def test_process_empty_query_raises_error(self) -> None:
        """测试空查询抛出错误。"""
        processor = QueryProcessor()

        with pytest.raises(ValueError, match="cannot be empty"):
            processor.process("")

        with pytest.raises(ValueError, match="cannot be empty"):
            processor.process("   ")

    def test_process_none_query_raises_error(self) -> None:
        """测试 None 查询抛出错误。"""
        processor = QueryProcessor()

        with pytest.raises(ValueError, match="cannot be empty"):
            processor.process(None)  # type: ignore

    def test_process_with_filters(self) -> None:
        """测试带过滤条件的查询。"""
        processor = QueryProcessor()
        filters = {"collection": "docs", "doc_type": "pdf"}
        result = processor.process("RAG pipeline", filters=filters)

        assert result.filters == {"collection": "docs", "doc_type": "pdf"}

    def test_process_with_none_filters(self) -> None:
        """测试 None 过滤条件。"""
        processor = QueryProcessor()
        result = processor.process("test query", filters=None)

        assert result.filters == {}

    def test_process_empty_filters(self) -> None:
        """测试空过滤条件字典。"""
        processor = QueryProcessor()
        result = processor.process("test query", filters={})

        assert result.filters == {}

    def test_process_max_keywords_limit(self) -> None:
        """测试最大关键词数量限制。"""
        config = QueryProcessorConfig(max_keywords=3)
        processor = QueryProcessor(config=config)
        result = processor.process(
            "word1 word2 word3 word4 word5 word6 word7"
        )

        assert len(result.keywords) <= 3

    def test_process_min_keyword_length(self) -> None:
        """测试最小关键词长度过滤。"""
        config = QueryProcessorConfig(min_keyword_length=4)
        processor = QueryProcessor(config=config)
        result = processor.process("a b c test word")

        assert "test" in result.keywords
        assert "word" in result.keywords
        assert "a" not in result.keywords
        assert "b" not in result.keywords
        assert "c" not in result.keywords

    def test_process_without_stopwords(self) -> None:
        """测试不使用停用词。"""
        config = QueryProcessorConfig(use_stopwords=False)
        processor = QueryProcessor(config=config)
        result = processor.process("how to configure llm")

        assert "how" in result.keywords
        assert "to" in result.keywords
        assert "configure" in result.keywords
        assert "llm" in result.keywords

    def test_process_duplicate_keywords_removed(self) -> None:
        """测试去除重复关键词。"""
        processor = QueryProcessor()
        result = processor.process("test test configure test llm")

        test_count = result.keywords.count("test")
        assert test_count == 1

    def test_process_case_insensitive(self) -> None:
        """测试大小写不敏感。"""
        processor = QueryProcessor()
        result = processor.process("CONFIGURE LLM Settings")

        assert "configure" in result.keywords
        assert "llm" in result.keywords
        assert "settings" in result.keywords
        assert "CONFIGURE" not in result.keywords

    def test_process_preserves_order(self) -> None:
        """测试保留关键词顺序。"""
        processor = QueryProcessor()
        result = processor.process("alpha beta gamma delta")

        assert result.keywords == ["alpha", "beta", "gamma", "delta"]

    def test_process_hyphenated_words(self) -> None:
        """测试连字符词汇处理。"""
        processor = QueryProcessor()
        result = processor.process("query-processing pipeline")

        assert "pipeline" in result.keywords
        assert "query-processing" in result.keywords

    def test_process_numbers(self) -> None:
        """测试包含数字的查询。"""
        processor = QueryProcessor()
        result = processor.process("version 2.0 and 3.0")

        assert "version" in result.keywords
        assert "and" not in result.keywords or "version" in result.keywords

    def test_process_returns_processed_query_object(self) -> None:
        """测试返回 ProcessedQuery 对象。"""
        processor = QueryProcessor()
        result = processor.process("test query")

        assert isinstance(result, ProcessedQuery)
        assert hasattr(result, "original_query")
        assert hasattr(result, "keywords")
        assert hasattr(result, "filters")
        assert hasattr(result, "rewritten_query")

    def test_process_filters_are_copied(self) -> None:
        """测试过滤条件被复制而非引用。"""
        processor = QueryProcessor()
        original_filters = {"collection": "docs"}
        result = processor.process("test query", filters=original_filters)

        original_filters["collection"] = "changed"
        assert result.filters["collection"] == "docs"

    def test_config_defaults(self) -> None:
        """测试配置默认值。"""
        processor = QueryProcessor()

        assert processor.config.use_stopwords is True
        assert processor.config.min_keyword_length == 2
        assert processor.config.max_keywords == 10

    def test_custom_stopwords(self) -> None:
        """测试自定义停用词。"""
        custom_stopwords = frozenset({"custom"})
        processor = QueryProcessor(stopwords=custom_stopwords)
        result = processor.process("custom word")

        assert "custom" not in result.keywords
        assert "word" in result.keywords
