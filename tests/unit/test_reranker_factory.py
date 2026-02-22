"""Unit tests for Reranker Factory and Base Reranker.

Test Coverage:
- NoneReranker: preserves original order, passthrough behavior
- Factory pattern: backend registration, creation, and routing
- Configuration-driven instantiation
- Error handling for unknown/missing backends
- Validation logic in BaseReranker
"""

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from src.libs.reranker.base_reranker import BaseReranker, NoneReranker
from src.libs.reranker.reranker_factory import RerankerFactory


class FakeReranker(BaseReranker):
    """Fake Reranker for testing.

    Reverses the candidate order for deterministic testing.
    """

    def __init__(
        self,
        settings: Any = None,
        backend_name: str = "fake",
        **kwargs: Any,
    ):
        """Initialize fake Reranker."""
        self.settings = settings
        self._backend_name = backend_name
        self.call_count = 0
        self.last_query: str = ""

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Reverse candidate order for testing."""
        self.validate_inputs(query, candidates)
        self.call_count += 1
        self.last_query = query
        return list(reversed(candidates))

    def get_backend_name(self) -> str:
        """Return configured backend name."""
        return self._backend_name


# ===========================================================================
# NoneReranker Tests
# ===========================================================================


class TestNoneReranker:
    """Tests for NoneReranker passthrough behavior."""

    def _make_candidates(self) -> List[Dict[str, Any]]:
        """Create sample candidates for testing."""
        return [
            {"id": "1", "text": "First item", "score": 0.9},
            {"id": "2", "text": "Second item", "score": 0.8},
            {"id": "3", "text": "Third item", "score": 0.7},
        ]

    def test_preserves_order(self):
        """NoneReranker should not change candidate order."""
        reranker = NoneReranker()
        candidates = self._make_candidates()
        result = reranker.rerank("test query", candidates)

        assert [r["id"] for r in result] == ["1", "2", "3"]

    def test_preserves_scores(self):
        """NoneReranker should not modify scores."""
        reranker = NoneReranker()
        candidates = self._make_candidates()
        result = reranker.rerank("test query", candidates)

        assert [r["score"] for r in result] == [0.9, 0.8, 0.7]

    def test_preserves_all_fields(self):
        """NoneReranker should preserve all candidate fields."""
        reranker = NoneReranker()
        candidates = self._make_candidates()
        result = reranker.rerank("test query", candidates)

        for original, returned in zip(candidates, result):
            assert original == returned

    def test_returns_new_list(self):
        """NoneReranker should return a new list, not the same object."""
        reranker = NoneReranker()
        candidates = self._make_candidates()
        result = reranker.rerank("test query", candidates)

        assert result is not candidates

    def test_single_candidate(self):
        """NoneReranker should handle a single candidate."""
        reranker = NoneReranker()
        result = reranker.rerank(
            "test", [{"id": "1", "text": "only one", "score": 1.0}],
        )
        assert len(result) == 1
        assert result[0]["id"] == "1"

    def test_backend_name(self):
        """NoneReranker should report 'none' as backend."""
        reranker = NoneReranker()
        assert reranker.get_backend_name() == "none"


# ===========================================================================
# BaseReranker Validation Tests
# ===========================================================================


class TestBaseRerankerValidation:
    """Tests for BaseReranker validation methods."""

    def test_validate_inputs_success(self):
        """Valid inputs should pass validation."""
        reranker = NoneReranker()
        reranker.validate_inputs(
            "test query",
            [{"id": "1", "text": "hello", "score": 0.9}],
        )

    def test_validate_inputs_empty_query(self):
        """Empty query should raise ValueError."""
        reranker = NoneReranker()
        with pytest.raises(ValueError, match="non-empty string"):
            reranker.validate_inputs(
                "", [{"id": "1"}],
            )

    def test_validate_inputs_whitespace_query(self):
        """Whitespace-only query should raise ValueError."""
        reranker = NoneReranker()
        with pytest.raises(ValueError, match="non-empty string"):
            reranker.validate_inputs(
                "   \t  ", [{"id": "1"}],
            )

    def test_validate_inputs_non_string_query(self):
        """Non-string query should raise ValueError."""
        reranker = NoneReranker()
        with pytest.raises(ValueError, match="non-empty string"):
            reranker.validate_inputs(
                123, [{"id": "1"}],  # type: ignore
            )

    def test_validate_inputs_empty_candidates(self):
        """Empty candidates list should raise ValueError."""
        reranker = NoneReranker()
        with pytest.raises(ValueError, match="cannot be empty"):
            reranker.validate_inputs("query", [])

    def test_validate_inputs_non_dict_candidate(self):
        """Non-dict candidate should raise ValueError."""
        reranker = NoneReranker()
        with pytest.raises(ValueError, match="not a dict"):
            reranker.validate_inputs("query", ["not_a_dict"])  # type: ignore

    def test_get_backend_name_not_implemented(self):
        """BaseReranker without override should raise NotImplementedError."""

        class IncompleteReranker(BaseReranker):
            def rerank(self, query, candidates, trace=None, **kwargs):
                return candidates

        incomplete = IncompleteReranker()
        with pytest.raises(
            NotImplementedError, match="must implement get_backend_name"
        ):
            incomplete.get_backend_name()


# ===========================================================================
# Factory Tests
# ===========================================================================


class TestRerankerFactory:
    """Tests for RerankerFactory."""

    def setup_method(self):
        """Reset factory registry before each test."""
        RerankerFactory._PROVIDERS.clear()

    def test_register_provider_success(self):
        """Registering valid provider should succeed."""
        RerankerFactory.register_provider("fake", FakeReranker)
        assert "fake" in RerankerFactory._PROVIDERS

    def test_register_provider_case_insensitive(self):
        """Backend names should be normalized to lowercase."""
        RerankerFactory.register_provider("LLM", FakeReranker)
        assert "llm" in RerankerFactory._PROVIDERS

    def test_register_provider_invalid_class(self):
        """Registering non-BaseReranker class should raise ValueError."""

        class NotAReranker:
            pass

        with pytest.raises(ValueError, match="must inherit from BaseReranker"):
            RerankerFactory.register_provider(
                "invalid", NotAReranker,  # type: ignore
            )

    def test_list_providers_empty(self):
        """list_providers should return empty when no providers registered."""
        assert RerankerFactory.list_providers() == []

    def test_list_providers_sorted(self):
        """list_providers should return sorted provider names."""
        RerankerFactory.register_provider("none", NoneReranker)
        RerankerFactory.register_provider("llm", FakeReranker)
        RerankerFactory.register_provider("cross_encoder", FakeReranker)

        providers = RerankerFactory.list_providers()
        assert providers == ["cross_encoder", "llm", "none"]

    def test_create_none_reranker(self):
        """backend=none should create NoneReranker."""
        RerankerFactory.register_provider("none", NoneReranker)

        settings = MagicMock()
        settings.rerank.backend = "none"

        reranker = RerankerFactory.create(settings)
        assert isinstance(reranker, NoneReranker)

    def test_create_fake_reranker(self):
        """Creating registered backend should succeed."""
        RerankerFactory.register_provider("fake", FakeReranker)

        settings = MagicMock()
        settings.rerank.backend = "fake"

        reranker = RerankerFactory.create(settings)
        assert isinstance(reranker, FakeReranker)
        assert reranker.settings == settings

    def test_create_case_insensitive(self):
        """Backend lookup should be case-insensitive."""
        RerankerFactory.register_provider("fake", FakeReranker)

        settings = MagicMock()
        settings.rerank.backend = "FAKE"

        reranker = RerankerFactory.create(settings)
        assert isinstance(reranker, FakeReranker)

    def test_create_unknown_backend(self):
        """Creating unregistered backend should raise clear error."""
        RerankerFactory.register_provider("none", NoneReranker)

        settings = MagicMock()
        settings.rerank.backend = "unknown"

        with pytest.raises(ValueError) as exc_info:
            RerankerFactory.create(settings)

        error_message = str(exc_info.value)
        assert "Unsupported Reranker backend: 'unknown'" in error_message
        assert "Available backends:" in error_message

    def test_create_missing_backend_config(self):
        """Missing backend in settings should raise clear error."""
        settings = MagicMock()
        del settings.rerank

        with pytest.raises(ValueError) as exc_info:
            RerankerFactory.create(settings)

        error_message = str(exc_info.value)
        assert "Missing required configuration" in error_message
        assert "settings.rerank.backend" in error_message

    def test_create_provider_instantiation_failure(self):
        """Provider constructor errors should be wrapped in RuntimeError."""

        class BrokenReranker(BaseReranker):
            def __init__(self, settings: Any, **kwargs: Any):
                raise ValueError("Intentional init error")

            def rerank(self, query, candidates, trace=None, **kwargs):
                return candidates

        RerankerFactory.register_provider("broken", BrokenReranker)

        settings = MagicMock()
        settings.rerank.backend = "broken"

        with pytest.raises(RuntimeError) as exc_info:
            RerankerFactory.create(settings)

        error_message = str(exc_info.value)
        assert "Failed to instantiate Reranker backend 'broken'" in error_message

    def test_create_no_providers_registered(self):
        """Creating backend when registry is empty should show helpful message."""
        settings = MagicMock()
        settings.rerank.backend = "llm"

        with pytest.raises(ValueError) as exc_info:
            RerankerFactory.create(settings)

        error_message = str(exc_info.value)
        assert "Unsupported Reranker backend: 'llm'" in error_message

    def test_none_backend_does_not_change_order(self):
        """End-to-end: backend=none should preserve candidate order."""
        RerankerFactory.register_provider("none", NoneReranker)

        settings = MagicMock()
        settings.rerank.backend = "none"

        reranker = RerankerFactory.create(settings)
        candidates = [
            {"id": "a", "text": "First", "score": 0.5},
            {"id": "b", "text": "Second", "score": 0.9},
            {"id": "c", "text": "Third", "score": 0.1},
        ]
        result = reranker.rerank("test query", candidates)

        assert [r["id"] for r in result] == ["a", "b", "c"]
        assert [r["score"] for r in result] == [0.5, 0.9, 0.1]

    def test_create_and_rerank_roundtrip(self):
        """Factory-created reranker should support full rerank roundtrip."""
        RerankerFactory.register_provider("fake", FakeReranker)

        settings = MagicMock()
        settings.rerank.backend = "fake"

        reranker = RerankerFactory.create(settings)
        candidates = [
            {"id": "1", "text": "First", "score": 0.9},
            {"id": "2", "text": "Second", "score": 0.8},
        ]
        result = reranker.rerank("test query", candidates)

        # FakeReranker reverses order
        assert [r["id"] for r in result] == ["2", "1"]
