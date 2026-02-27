"""Unit tests for LLM Reranker.

This module tests the LLM-based reranker implementation with mocked LLM
calls to ensure deterministic, fast test execution without external
dependencies.

Test Coverage:
- Factory creation with backend='llm'
- Prompt template loading (default path, custom path, fallback)
- LLM call and score parsing (multiple formats)
- Reranking logic (correct sorting by LLM scores)
- Graceful degradation on LLM failure
- TraceContext integration
"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

import pytest

from src.core.settings import Settings
from src.libs.reranker.base_reranker import BaseReranker
from src.libs.reranker.llm_reranker import LLMReranker
from src.libs.reranker.reranker_factory import RerankerFactory


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_settings():
    """Create mock settings for LLM reranker."""
    settings = Mock(spec=Settings)
    settings.rerank = Mock()
    settings.rerank.backend = "llm"
    settings.rerank.model = "test-model"
    settings.llm = Mock()
    settings.llm.provider = "openai"
    settings.llm.model = "gpt-4"
    return settings


@pytest.fixture
def mock_llm():
    """Create a mock LLM instance."""
    llm = Mock()
    llm.chat = Mock()
    llm.get_backend_name = Mock(return_value="openai")
    llm.get_model_name = Mock(return_value="gpt-4")
    return llm


@pytest.fixture
def sample_candidates():
    """Create sample candidate documents."""
    return [
        {
            "id": "doc1",
            "text": "This is about RAG systems and retrieval.",
            "score": 0.8,
        },
        {
            "id": "doc2",
            "text": "Completely unrelated content about cooking.",
            "score": 0.9,
        },
        {
            "id": "doc3",
            "text": "RAG combines retrieval with generation.",
            "score": 0.7,
        },
    ]


# ============================================================================
# Test Factory Creation
# ============================================================================


def test_factory_creates_llm_reranker(mock_settings, mock_llm):
    """Test that factory creates LLMReranker when backend='llm'."""
    with patch("src.libs.llm.llm_factory.LLMFactory.create", return_value=mock_llm):
        reranker = RerankerFactory.create(mock_settings)

        assert isinstance(reranker, LLMReranker)
        assert reranker.backend_name == "llm"


def test_factory_lists_llm_provider():
    """Test that 'llm' is listed in available providers."""
    providers = RerankerFactory.list_providers()
    assert "llm" in providers


# ============================================================================
# Test Initialization
# ============================================================================


def test_llm_reranker_init_with_injected_llm(mock_settings, mock_llm):
    """Test initialization with injected LLM instance."""
    with patch.object(LLMReranker, "_load_prompt", return_value="test prompt"):
        reranker = LLMReranker(settings=mock_settings, llm=mock_llm)

        assert reranker.llm is mock_llm
        assert reranker.backend_name == "llm"
        assert reranker.model_name == "gpt-4"


def test_llm_reranker_init_creates_llm_from_factory(mock_settings, mock_llm):
    """Test initialization creates LLM from factory if not injected."""
    with patch("src.libs.llm.llm_factory.LLMFactory.create", return_value=mock_llm):
        with patch.object(LLMReranker, "_load_prompt", return_value="test prompt"):
            reranker = LLMReranker(settings=mock_settings)

            assert reranker.llm is mock_llm


# ============================================================================
# Test Prompt Loading
# ============================================================================


def test_load_prompt_from_default_path(mock_settings, mock_llm, tmp_path):
    """Test loading prompt from default path."""
    # Create temporary prompt file
    prompt_file = tmp_path / "rerank.txt"
    prompt_file.write_text("Test prompt: {query} | {passage}")

    reranker = LLMReranker(
        settings=mock_settings, llm=mock_llm, prompt_path=str(prompt_file)
    )

    assert "Test prompt:" in reranker.prompt_template
    assert "{query}" in reranker.prompt_template
    assert "{passage}" in reranker.prompt_template


def test_load_prompt_with_custom_path(mock_settings, mock_llm, tmp_path):
    """Test loading prompt from custom path."""
    # Create custom prompt file
    custom_prompt = tmp_path / "custom_rerank.txt"
    custom_prompt.write_text("Custom: {query} -- {passage}")

    reranker = LLMReranker(
        settings=mock_settings, llm=mock_llm, prompt_path=str(custom_prompt)
    )

    assert "Custom:" in reranker.prompt_template


def test_load_prompt_fallback_on_missing_file(mock_settings, mock_llm):
    """Test fallback to default template when file not found."""
    reranker = LLMReranker(
        settings=mock_settings, llm=mock_llm, prompt_path="/nonexistent/path.txt"
    )

    # Should use fallback template
    assert "{query}" in reranker.prompt_template
    assert "{passage}" in reranker.prompt_template
    assert "relevance" in reranker.prompt_template.lower()


# ============================================================================
# Test Score Parsing
# ============================================================================


@pytest.mark.parametrize(
    "response,expected_score",
    [
        ("7", 0.7),  # Simple integer
        ("8.5", 0.85),  # Decimal
        ("Score: 6", 0.6),  # With prefix
        ("Relevance score: 9", 0.9),  # With label
        ("The score is 5/10", 0.5),  # With fraction notation
        ("10", 1.0),  # Max score
        ("0", 0.0),  # Min score
        ("3.14", 0.314),  # Decimal (normalized)
        ("Score is 12", 1.0),  # Above max (clamped)
    ],
)
def test_parse_score_formats(mock_settings, mock_llm, response, expected_score):
    """Test parsing various score formats from LLM responses."""
    reranker = LLMReranker(settings=mock_settings, llm=mock_llm)
    parsed_score = reranker._parse_score(response)

    assert parsed_score is not None
    assert abs(parsed_score - expected_score) < 0.01


def test_parse_score_handles_invalid_response(mock_settings, mock_llm):
    """Test parsing returns None for invalid responses."""
    reranker = LLMReranker(settings=mock_settings, llm=mock_llm)

    assert reranker._parse_score("No number here") is None
    assert reranker._parse_score("") is None
    assert reranker._parse_score("N/A") is None


# ============================================================================
# Test Reranking Logic
# ============================================================================


def test_rerank_sorts_by_llm_scores(mock_settings, mock_llm, sample_candidates):
    """Test that reranking correctly sorts candidates by LLM scores."""
    # Mock LLM to return different scores for each candidate
    mock_llm.chat.side_effect = [
        "8",  # doc1: high relevance
        "2",  # doc2: low relevance
        "9",  # doc3: highest relevance
    ]

    reranker = LLMReranker(settings=mock_settings, llm=mock_llm)
    reranked = reranker.rerank("What is RAG?", sample_candidates)

    # Should be sorted: doc3 (0.9) > doc1 (0.8) > doc2 (0.2)
    assert reranked[0]["id"] == "doc3"
    assert reranked[1]["id"] == "doc1"
    assert reranked[2]["id"] == "doc2"

    # Check scores were added
    assert reranked[0]["rerank_score"] == 0.9
    assert reranked[1]["rerank_score"] == 0.8
    assert reranked[2]["rerank_score"] == 0.2


def test_rerank_preserves_original_scores(mock_settings, mock_llm, sample_candidates):
    """Test that original scores are preserved in output."""
    mock_llm.chat.side_effect = ["5", "6", "7"]

    reranker = LLMReranker(settings=mock_settings, llm=mock_llm)
    reranked = reranker.rerank("test query", sample_candidates)

    # Check original scores preserved
    for original, reranked_item in zip(sample_candidates, reranked):
        # Find matching candidate by id
        matching = next(r for r in reranked if r["id"] == original["id"])
        assert matching["original_score"] == original["score"]


def test_rerank_adds_metadata(mock_settings, mock_llm, sample_candidates):
    """Test that reranking adds required metadata fields."""
    mock_llm.chat.side_effect = ["7", "8", "9"]

    reranker = LLMReranker(settings=mock_settings, llm=mock_llm)
    reranked = reranker.rerank("test query", sample_candidates)

    for candidate in reranked:
        assert "rerank_score" in candidate
        assert "original_score" in candidate
        assert candidate["reranked_by"] == "llm"


def test_rerank_handles_empty_candidates(mock_settings, mock_llm):
    """Test reranking with empty candidate list."""
    reranker = LLMReranker(settings=mock_settings, llm=mock_llm)
    reranked = reranker.rerank("test query", [])

    assert reranked == []


def test_rerank_validates_inputs(mock_settings, mock_llm):
    """Test that rerank validates inputs properly."""
    reranker = LLMReranker(settings=mock_settings, llm=mock_llm)

    # Test empty query
    with pytest.raises(ValueError, match="non-empty string"):
        reranker.rerank("", [{"id": "1", "text": "test", "score": 0.5}])

    # Test whitespace-only query
    with pytest.raises(ValueError, match="non-empty string"):
        reranker.rerank("   ", [{"id": "1", "text": "test", "score": 0.5}])


def test_rerank_truncates_long_passages(mock_settings, mock_llm):
    """Test that long passages are truncated to avoid token limits."""
    long_text = "x" * 5000  # 5000 chars
    candidates = [{"id": "1", "text": long_text, "score": 0.5}]

    mock_llm.chat.return_value = "7"

    reranker = LLMReranker(settings=mock_settings, llm=mock_llm)
    reranker.rerank("test", candidates)

    # Check that LLM was called with truncated text (max 2000 chars)
    call_args = mock_llm.chat.call_args
    prompt = call_args[1]["messages"][0]["content"]
    # The passage in the prompt should be truncated
    assert len(prompt) < 5000  # Much shorter than original


# ============================================================================
# Test Graceful Degradation
# ============================================================================


def test_rerank_falls_back_on_llm_exception(mock_settings, mock_llm, sample_candidates):
    """Test graceful fallback when LLM call raises exception."""
    # Mock LLM to raise exception
    mock_llm.chat.side_effect = RuntimeError("LLM service unavailable")

    reranker = LLMReranker(settings=mock_settings, llm=mock_llm)
    reranked = reranker.rerank("test query", sample_candidates)

    # Should return original order
    assert len(reranked) == len(sample_candidates)
    assert reranked[0]["id"] == sample_candidates[0]["id"]

    # Should mark as fallback
    for candidate in reranked:
        assert candidate["reranked_by"] == "none"
        assert "rerank_fallback_reason" in candidate


def test_rerank_falls_back_on_score_parse_failure(
    mock_settings, mock_llm, sample_candidates
):
    """Test fallback to original score when LLM returns unparseable response."""
    # Mock LLM to return invalid score
    mock_llm.chat.return_value = "Invalid response with no numbers"

    reranker = LLMReranker(settings=mock_settings, llm=mock_llm)
    reranked = reranker.rerank("test query", sample_candidates[:1])

    # Should use original score
    assert reranked[0]["rerank_score"] == sample_candidates[0]["score"]


# ============================================================================
# Test TraceContext Integration
# ============================================================================


def test_rerank_records_trace_on_success(mock_settings, mock_llm, sample_candidates):
    """Test that successful reranking records trace data."""
    mock_llm.chat.side_effect = ["8", "6", "9"]
    mock_trace = Mock()

    reranker = LLMReranker(settings=mock_settings, llm=mock_llm)
    reranker.rerank("test query", sample_candidates, trace=mock_trace)

    # Check trace was recorded
    mock_trace.record_stage.assert_called_once()
    call_args = mock_trace.record_stage.call_args

    assert call_args[0][0] == "rerank_llm"  # stage name
    assert call_args[1]["method"] == "llm"
    assert call_args[1]["provider"] == "openai"
    assert call_args[1]["model"] == "gpt-4"
    assert call_args[1]["details"]["input_count"] == 3
    assert call_args[1]["details"]["output_count"] == 3


def test_rerank_records_trace_on_failure(mock_settings, mock_llm, sample_candidates):
    """Test that failed reranking records trace with error info."""
    mock_llm.chat.side_effect = RuntimeError("LLM error")
    mock_trace = Mock()

    reranker = LLMReranker(settings=mock_settings, llm=mock_llm)
    reranker.rerank("test query", sample_candidates, trace=mock_trace)

    # Check trace recorded failure
    mock_trace.record_stage.assert_called_once()
    call_args = mock_trace.record_stage.call_args

    assert call_args[1]["error"] is not None
    assert call_args[1]["fallback"] is True


# ============================================================================
# Test Backend Name and Model Name
# ============================================================================


def test_get_backend_name(mock_settings, mock_llm):
    """Test get_backend_name returns 'llm'."""
    reranker = LLMReranker(settings=mock_settings, llm=mock_llm)
    assert reranker.get_backend_name() == "llm"


def test_get_model_name_from_llm(mock_settings, mock_llm):
    """Test that model name is retrieved from LLM instance."""
    mock_llm.get_model_name.return_value = "gpt-4-turbo"

    reranker = LLMReranker(settings=mock_settings, llm=mock_llm)
    assert reranker.model_name == "gpt-4-turbo"


# ============================================================================
# Test LLM Call Parameters
# ============================================================================


def test_rerank_calls_llm_with_correct_parameters(
    mock_settings, mock_llm, sample_candidates
):
    """Test that LLM is called with correct parameters."""
    mock_llm.chat.return_value = "7"

    reranker = LLMReranker(settings=mock_settings, llm=mock_llm)
    reranker.rerank("test query", sample_candidates[:1])

    # Check LLM call parameters
    call_args = mock_llm.chat.call_args
    assert call_args[1]["max_tokens"] == 10
    assert call_args[1]["temperature"] == 0.0


def test_rerank_constructs_prompt_correctly(mock_settings, mock_llm, tmp_path):
    """Test that prompt is correctly constructed with query and passage."""
    # Create custom prompt template
    prompt_file = tmp_path / "test_prompt.txt"
    prompt_file.write_text("Query: {query}\nPassage: {passage}\nScore:")

    mock_llm.chat.return_value = "8"

    reranker = LLMReranker(
        settings=mock_settings, llm=mock_llm, prompt_path=str(prompt_file)
    )
    reranker.rerank(
        "What is AI?", [{"id": "1", "text": "AI is artificial intelligence", "score": 0.5}]
    )

    # Check prompt construction
    call_args = mock_llm.chat.call_args
    prompt = call_args[1]["messages"][0]["content"]

    assert "What is AI?" in prompt
    assert "AI is artificial intelligence" in prompt
