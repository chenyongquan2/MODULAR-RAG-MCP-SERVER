"""Unit tests for Cross-Encoder Reranker.

This module tests the Cross-Encoder reranker implementation with mocked
Cross-Encoder model to ensure deterministic, fast test execution without
external dependencies.

Test Coverage:
- Factory creation with backend='cross_encoder'
- Model lazy-loading and caching
- Score normalization (min-max)
- Reranking logic (correct sorting by Cross-Encoder scores)
- Graceful degradation on model failure
- TraceContext integration
- Import error handling (sentence-transformers not installed)
"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

import pytest

from src.core.settings import RerankSettings, Settings
from src.libs.reranker.base_reranker import BaseReranker
from src.libs.reranker.cross_encoder_reranker import CrossEncoderReranker
from src.libs.reranker.reranker_factory import RerankerFactory


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_settings():
    """Create mock settings for Cross-Encoder reranker.

    ``rerank`` 用真实的 ``RerankSettings`` dataclass 而非裸 ``Mock()``:
    ``CrossEncoderReranker`` 现在真的会读 ``batch_size``(此前硬编码 32,属
    宪法原则二禁止的硬编码可调参数),裸 Mock 会让它返回一个 Mock 对象。
    用真实 dataclass 还能保证本测试无法与真实配置结构漂移。
    """
    settings = Mock(spec=Settings)
    settings.rerank = RerankSettings(
        backend="cross_encoder",
        model="cross-encoder/ms-marco-MiniLM-L-6-v2",
        batch_size=32,  # 保持本文件既有断言的期望值
    )
    return settings


@pytest.fixture
def mock_cross_encoder_model():
    """Create a mock Cross-Encoder model."""
    model = Mock()
    model.predict = Mock()
    return model


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


def test_factory_creates_cross_encoder_reranker(mock_settings, mock_cross_encoder_model):
    """Test that factory creates CrossEncoderReranker when backend='cross_encoder'."""
    # Inject mock model to avoid loading real model
    reranker = RerankerFactory.create(mock_settings, model=mock_cross_encoder_model)

    assert isinstance(reranker, CrossEncoderReranker)
    assert reranker.backend_name == "cross_encoder"


def test_factory_lists_cross_encoder_provider():
    """Test that 'cross_encoder' is listed in available providers."""
    providers = RerankerFactory.list_providers()
    assert "cross_encoder" in providers


# ============================================================================
# Test Initialization
# ============================================================================


def test_cross_encoder_init_with_default_settings(mock_settings):
    """Test initialization with default settings."""
    reranker = CrossEncoderReranker(settings=mock_settings)

    assert reranker.model_name == "cross-encoder/ms-marco-MiniLM-L-6-v2"
    assert reranker.max_length == 512
    assert reranker.batch_size == 32
    assert reranker.backend_name == "cross_encoder"


def test_cross_encoder_init_with_custom_params(mock_settings):
    """Test initialization with custom parameters."""
    reranker = CrossEncoderReranker(
        settings=mock_settings,
        max_length=256,
        batch_size=16,
    )

    assert reranker.max_length == 256
    assert reranker.batch_size == 16


def test_cross_encoder_init_with_injected_model(mock_settings, mock_cross_encoder_model):
    """Test initialization with injected model instance."""
    reranker = CrossEncoderReranker(
        settings=mock_settings,
        model=mock_cross_encoder_model,
    )

    assert reranker._model is mock_cross_encoder_model


# ============================================================================
# Test Model Lazy Loading
# ============================================================================


def test_model_lazy_loading(mock_settings):
    """Test that model is lazy-loaded on first access."""
    mock_model = Mock()

    # Create a fake CrossEncoder class
    fake_cross_encoder = Mock(return_value=mock_model)

    # Patch the property to inject mock
    reranker = CrossEncoderReranker(settings=mock_settings)

    # Verify model not loaded yet
    assert reranker._model is None

    # Mock the import and instantiation
    with patch.dict("sys.modules", {"sentence_transformers": Mock(CrossEncoder=fake_cross_encoder)}):
        # Access model property triggers loading
        loaded_model = reranker.model

        # Model should be loaded now
        assert loaded_model is mock_model


def test_model_loading_caches_instance(mock_settings):
    """Test that model is loaded only once and cached."""
    # Inject mock model directly
    mock_model = Mock()
    reranker = CrossEncoderReranker(settings=mock_settings, model=mock_model)

    # Access model multiple times
    model1 = reranker.model
    model2 = reranker.model

    # Should be the same instance
    assert model1 is model2
    assert model1 is mock_model


def test_model_loading_raises_import_error_if_library_missing(mock_settings):
    """Test that ImportError is raised if sentence-transformers is not installed.

    注意 import 必须被**主动模拟成失败**（把 sys.modules 里对应项设为 None,
    Python 会对它抛 ImportError）。本测试早先没有这一步,靠的是环境里真的
    没装 sentence-transformers —— 那意味着依赖一旦装上,它就不再测「库缺失」,
    而是去真连 HuggingFace 下载模型（退避重试数分钟后抛网络错误）。

    这个分支仍然是**可达**的:启动期的 RerankerFactory.probe_backend 用
    find_spec 只证明模块找得到、不执行模块,装坏了的依赖（例如 Windows 上
    torch 的 DLL 加载失败）会通过探测但在真正 import 时炸。
    """
    reranker = CrossEncoderReranker(settings=mock_settings)

    # sys.modules[name] = None 是标准的「模拟该模块不可导入」手法
    with patch.dict("sys.modules", {"sentence_transformers": None}):
        with pytest.raises(ImportError, match="sentence-transformers is required"):
            _ = reranker.model


def test_model_loading_raises_runtime_error_on_failure(mock_settings):
    """Test that RuntimeError is raised if model loading fails."""
    # Create a fake module with failing CrossEncoder
    fake_module = Mock()
    fake_module.CrossEncoder = Mock(side_effect=RuntimeError("Model download failed"))

    reranker = CrossEncoderReranker(settings=mock_settings)

    with patch.dict("sys.modules", {"sentence_transformers": fake_module}):
        with pytest.raises(RuntimeError, match="Failed to load Cross-Encoder model"):
            _ = reranker.model


# ============================================================================
# Test Reranking Logic
# ============================================================================


def test_rerank_sorts_by_cross_encoder_scores(
    mock_settings, mock_cross_encoder_model, sample_candidates
):
    """Test that reranking correctly sorts candidates by Cross-Encoder scores."""
    # Mock Cross-Encoder to return different scores for each candidate
    # Scores: doc1=8.0, doc2=2.0, doc3=9.0 (raw scores)
    # After normalization: doc1=0.857, doc2=0.0, doc3=1.0
    mock_cross_encoder_model.predict.return_value = [8.0, 2.0, 9.0]

    reranker = CrossEncoderReranker(
        settings=mock_settings,
        model=mock_cross_encoder_model,
    )
    reranked = reranker.rerank("What is RAG?", sample_candidates)

    # Should be sorted: doc3 (1.0) > doc1 (0.857) > doc2 (0.0)
    assert reranked[0]["id"] == "doc3"
    assert reranked[1]["id"] == "doc1"
    assert reranked[2]["id"] == "doc2"

    # Check normalized scores
    assert reranked[0]["rerank_score"] > reranked[1]["rerank_score"]
    assert reranked[1]["rerank_score"] > reranked[2]["rerank_score"]


def test_rerank_normalizes_scores_correctly(
    mock_settings, mock_cross_encoder_model, sample_candidates
):
    """Test that raw scores are normalized to [0, 1] range."""
    # Raw scores in range [-5, 10]
    mock_cross_encoder_model.predict.return_value = [-5.0, 0.0, 10.0]

    reranker = CrossEncoderReranker(
        settings=mock_settings,
        model=mock_cross_encoder_model,
    )
    reranked = reranker.rerank("test query", sample_candidates)

    # Check normalization: min=-5 -> 0, max=10 -> 1, mid=0 -> 0.333
    assert abs(reranked[2]["rerank_score"] - 0.0) < 0.01  # min score
    assert abs(reranked[0]["rerank_score"] - 1.0) < 0.01  # max score
    assert 0.0 <= reranked[1]["rerank_score"] <= 1.0  # mid score


def test_rerank_handles_single_candidate(
    mock_settings, mock_cross_encoder_model
):
    """Test reranking with a single candidate."""
    mock_cross_encoder_model.predict.return_value = [5.0]

    candidates = [{"id": "doc1", "text": "Single document", "score": 0.8}]

    reranker = CrossEncoderReranker(
        settings=mock_settings,
        model=mock_cross_encoder_model,
    )
    reranked = reranker.rerank("query", candidates)

    assert len(reranked) == 1
    assert reranked[0]["rerank_score"] == 0.5  # Default for single candidate


def test_rerank_handles_uniform_scores(
    mock_settings, mock_cross_encoder_model, sample_candidates
):
    """Test reranking when all candidates have the same score."""
    # All scores are identical
    mock_cross_encoder_model.predict.return_value = [5.0, 5.0, 5.0]

    reranker = CrossEncoderReranker(
        settings=mock_settings,
        model=mock_cross_encoder_model,
    )
    reranked = reranker.rerank("test query", sample_candidates)

    # All normalized scores should be 0.5
    for candidate in reranked:
        assert candidate["rerank_score"] == 0.5


def test_rerank_preserves_original_scores(
    mock_settings, mock_cross_encoder_model, sample_candidates
):
    """Test that original scores are preserved in output."""
    mock_cross_encoder_model.predict.return_value = [1.0, 2.0, 3.0]

    reranker = CrossEncoderReranker(
        settings=mock_settings,
        model=mock_cross_encoder_model,
    )
    reranked = reranker.rerank("test query", sample_candidates)

    # Check original scores preserved
    for original, reranked_item in zip(sample_candidates, reranked):
        # Find matching candidate by id
        matching = next(r for r in reranked if r["id"] == original["id"])
        assert matching["original_score"] == original["score"]


def test_rerank_adds_metadata(
    mock_settings, mock_cross_encoder_model, sample_candidates
):
    """Test that reranking adds required metadata fields."""
    mock_cross_encoder_model.predict.return_value = [7.0, 8.0, 9.0]

    reranker = CrossEncoderReranker(
        settings=mock_settings,
        model=mock_cross_encoder_model,
    )
    reranked = reranker.rerank("test query", sample_candidates)

    for candidate in reranked:
        assert "rerank_score" in candidate
        assert "original_score" in candidate
        assert candidate["reranked_by"] == "cross_encoder"


def test_rerank_handles_empty_candidates(mock_settings, mock_cross_encoder_model):
    """Test reranking with empty candidate list."""
    reranker = CrossEncoderReranker(
        settings=mock_settings,
        model=mock_cross_encoder_model,
    )
    reranked = reranker.rerank("test query", [])

    assert reranked == []


def test_rerank_validates_inputs(mock_settings, mock_cross_encoder_model):
    """Test that rerank validates inputs properly."""
    reranker = CrossEncoderReranker(
        settings=mock_settings,
        model=mock_cross_encoder_model,
    )

    # Test empty query
    with pytest.raises(ValueError, match="non-empty string"):
        reranker.rerank("", [{"id": "1", "text": "test", "score": 0.5}])

    # Test whitespace-only query
    with pytest.raises(ValueError, match="non-empty string"):
        reranker.rerank("   ", [{"id": "1", "text": "test", "score": 0.5}])


def test_rerank_calls_model_with_correct_parameters(
    mock_settings, mock_cross_encoder_model, sample_candidates
):
    """Test that Cross-Encoder is called with correct parameters."""
    mock_cross_encoder_model.predict.return_value = [7.0, 8.0, 9.0]

    reranker = CrossEncoderReranker(
        settings=mock_settings,
        model=mock_cross_encoder_model,
    )
    reranker.rerank("What is AI?", sample_candidates)

    # Check model.predict call
    call_args = mock_cross_encoder_model.predict.call_args

    # First argument should be list of (query, text) pairs
    pairs = call_args[0][0]
    assert len(pairs) == 3
    assert all(pair[0] == "What is AI?" for pair in pairs)
    assert pairs[0][1] == sample_candidates[0]["text"]
    assert pairs[1][1] == sample_candidates[1]["text"]
    assert pairs[2][1] == sample_candidates[2]["text"]

    # Check kwargs
    assert call_args[1]["batch_size"] == 32
    assert call_args[1]["show_progress_bar"] is False


# ============================================================================
# Test Graceful Degradation
# ============================================================================


def test_rerank_falls_back_on_import_error(mock_settings, sample_candidates):
    """Test graceful fallback when sentence-transformers is not installed."""
    # Create reranker without injecting model
    reranker = CrossEncoderReranker(settings=mock_settings)

    # Patch the import to simulate missing library at runtime
    with patch.object(
        type(reranker),
        "model",
        new_callable=lambda: property(
            lambda self: (_ for _ in ()).throw(
                ImportError("sentence-transformers is required")
            )
        ),
    ):
        reranked = reranker.rerank("test query", sample_candidates)

        # Should return original order
        assert len(reranked) == len(sample_candidates)
        assert reranked[0]["id"] == sample_candidates[0]["id"]

        # Should mark as fallback
        for candidate in reranked:
            assert candidate["reranked_by"] == "none"
            assert "rerank_fallback_reason" in candidate


def test_rerank_falls_back_on_model_exception(
    mock_settings, mock_cross_encoder_model, sample_candidates
):
    """Test graceful fallback when model.predict raises exception."""
    # Mock model.predict to raise exception
    mock_cross_encoder_model.predict.side_effect = RuntimeError(
        "Model inference failed"
    )

    reranker = CrossEncoderReranker(
        settings=mock_settings,
        model=mock_cross_encoder_model,
    )
    reranked = reranker.rerank("test query", sample_candidates)

    # Should return original order
    assert len(reranked) == len(sample_candidates)
    assert reranked[0]["id"] == sample_candidates[0]["id"]

    # Should mark as fallback
    for candidate in reranked:
        assert candidate["reranked_by"] == "none"
        assert "rerank_fallback_reason" in candidate


# ============================================================================
# Test TraceContext Integration
# ============================================================================


def test_rerank_records_trace_on_success(
    mock_settings, mock_cross_encoder_model, sample_candidates
):
    """Test that successful reranking records trace data."""
    mock_cross_encoder_model.predict.return_value = [8.0, 6.0, 9.0]
    mock_trace = Mock()

    reranker = CrossEncoderReranker(
        settings=mock_settings,
        model=mock_cross_encoder_model,
    )
    reranker.rerank("test query", sample_candidates, trace=mock_trace)

    # Check trace was recorded
    mock_trace.record_stage.assert_called_once()
    call_args = mock_trace.record_stage.call_args

    assert call_args[0][0] == "rerank_cross_encoder"  # stage name
    assert call_args[1]["method"] == "cross_encoder"
    assert call_args[1]["provider"] == "sentence_transformers"
    assert call_args[1]["model"] == "cross-encoder/ms-marco-MiniLM-L-6-v2"
    assert call_args[1]["details"]["input_count"] == 3
    assert call_args[1]["details"]["output_count"] == 3


def test_rerank_records_trace_on_failure(
    mock_settings, mock_cross_encoder_model, sample_candidates
):
    """Test that failed reranking records trace with error info."""
    mock_cross_encoder_model.predict.side_effect = RuntimeError("Model error")
    mock_trace = Mock()

    reranker = CrossEncoderReranker(
        settings=mock_settings,
        model=mock_cross_encoder_model,
    )
    reranker.rerank("test query", sample_candidates, trace=mock_trace)

    # Check trace recorded failure
    mock_trace.record_stage.assert_called_once()
    call_args = mock_trace.record_stage.call_args

    assert call_args[1]["error"] is not None
    assert call_args[1]["fallback"] is True


# ============================================================================
# Test Backend Name
# ============================================================================


def test_get_backend_name(mock_settings, mock_cross_encoder_model):
    """Test get_backend_name returns 'cross_encoder'."""
    reranker = CrossEncoderReranker(
        settings=mock_settings,
        model=mock_cross_encoder_model,
    )
    assert reranker.get_backend_name() == "cross_encoder"
