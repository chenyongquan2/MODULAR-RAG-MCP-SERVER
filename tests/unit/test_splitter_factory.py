"""Unit tests for Splitter Factory and Base Splitter.

Test Coverage:
- Factory pattern: strategy registration, creation, and routing
- Configuration-driven instantiation
- Error handling for unknown/missing strategies
- Validation logic in BaseSplitter
"""

from typing import Any, List, Optional
from unittest.mock import MagicMock

import pytest

from src.libs.splitter.base_splitter import BaseSplitter
from src.libs.splitter.splitter_factory import SplitterFactory


class FakeSplitter(BaseSplitter):
    """Fake Splitter for testing.

    Splits text by sentences (period + space) for reproducible testing.
    """

    def __init__(
        self,
        settings: Any = None,
        strategy_name: str = "fake",
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        **kwargs: Any,
    ):
        """Initialize fake Splitter.

        Args:
            settings: Optional settings (unused in fake).
            strategy_name: Strategy name to report.
            chunk_size: Max chunk size.
            chunk_overlap: Overlap between chunks.
            **kwargs: Additional parameters (unused).
        """
        self.settings = settings
        self._strategy_name = strategy_name
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self.call_count = 0
        self.last_text: str = ""

    def split_text(
        self,
        text: str,
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[str]:
        """Split text by sentences (period followed by space or end).

        简单按句号切分，用于测试。
        """
        self.validate_text(text)
        self.call_count += 1
        self.last_text = text

        # Split by ". " and keep non-empty chunks
        parts = text.split(". ")
        chunks = []
        for i, part in enumerate(parts):
            chunk = part.strip()
            # Re-add period except for the last part if it already ends with one
            if chunk and i < len(parts) - 1 and not chunk.endswith("."):
                chunk += "."
            if chunk:
                chunks.append(chunk)
        return chunks if chunks else [text]

    def get_strategy_name(self) -> str:
        """Return configured strategy name."""
        return self._strategy_name

    def get_chunk_size(self) -> int:
        """Return configured chunk size."""
        return self._chunk_size

    def get_chunk_overlap(self) -> int:
        """Return configured chunk overlap."""
        return self._chunk_overlap


class TestBaseSplitter:
    """Tests for BaseSplitter abstract class."""

    def test_validate_text_success(self):
        """Valid text string should pass validation."""
        splitter = FakeSplitter()
        # Should not raise
        splitter.validate_text("Hello world.")

    def test_validate_text_multiline(self):
        """Multi-line text should pass validation."""
        splitter = FakeSplitter()
        splitter.validate_text("Line 1\nLine 2\nLine 3")

    def test_validate_text_empty_string(self):
        """Empty string should raise ValueError."""
        splitter = FakeSplitter()
        with pytest.raises(ValueError, match="empty or whitespace"):
            splitter.validate_text("")

    def test_validate_text_whitespace_only(self):
        """Whitespace-only string should raise ValueError."""
        splitter = FakeSplitter()
        with pytest.raises(ValueError, match="empty or whitespace"):
            splitter.validate_text("   \n\t  ")

    def test_validate_text_non_string(self):
        """Non-string input should raise ValueError."""
        splitter = FakeSplitter()
        with pytest.raises(ValueError, match="must be a string"):
            splitter.validate_text(123)  # type: ignore

    def test_validate_text_none(self):
        """None input should raise ValueError."""
        splitter = FakeSplitter()
        with pytest.raises(ValueError, match="must be a string"):
            splitter.validate_text(None)  # type: ignore

    def test_validate_text_list(self):
        """List input should raise ValueError."""
        splitter = FakeSplitter()
        with pytest.raises(ValueError, match="must be a string"):
            splitter.validate_text(["hello"])  # type: ignore

    def test_get_strategy_name_implemented(self):
        """FakeSplitter should return configured strategy name."""
        splitter = FakeSplitter(strategy_name="recursive")
        assert splitter.get_strategy_name() == "recursive"

    def test_get_strategy_name_not_implemented(self):
        """BaseSplitter without override should raise NotImplementedError."""

        class IncompleteSplitter(BaseSplitter):
            def split_text(
                self,
                text: str,
                trace: Optional[Any] = None,
                **kwargs: Any,
            ) -> List[str]:
                return [text]

        incomplete = IncompleteSplitter()
        with pytest.raises(
            NotImplementedError, match="must implement get_strategy_name"
        ):
            incomplete.get_strategy_name()

    def test_get_chunk_size_implemented(self):
        """FakeSplitter should return configured chunk size."""
        splitter = FakeSplitter(chunk_size=512)
        assert splitter.get_chunk_size() == 512

    def test_get_chunk_size_not_implemented(self):
        """BaseSplitter without override should raise NotImplementedError."""

        class IncompleteSplitter(BaseSplitter):
            def split_text(
                self,
                text: str,
                trace: Optional[Any] = None,
                **kwargs: Any,
            ) -> List[str]:
                return [text]

        incomplete = IncompleteSplitter()
        with pytest.raises(
            NotImplementedError, match="must implement get_chunk_size"
        ):
            incomplete.get_chunk_size()

    def test_get_chunk_overlap_implemented(self):
        """FakeSplitter should return configured chunk overlap."""
        splitter = FakeSplitter(chunk_overlap=100)
        assert splitter.get_chunk_overlap() == 100

    def test_get_chunk_overlap_not_implemented(self):
        """BaseSplitter without override should raise NotImplementedError."""

        class IncompleteSplitter(BaseSplitter):
            def split_text(
                self,
                text: str,
                trace: Optional[Any] = None,
                **kwargs: Any,
            ) -> List[str]:
                return [text]

        incomplete = IncompleteSplitter()
        with pytest.raises(
            NotImplementedError, match="must implement get_chunk_overlap"
        ):
            incomplete.get_chunk_overlap()


class TestFakeSplitter:
    """Tests for FakeSplitter implementation."""

    def test_split_single_sentence(self):
        """Single sentence should return one chunk."""
        splitter = FakeSplitter()
        result = splitter.split_text("Hello world.")

        assert len(result) == 1
        assert isinstance(result[0], str)

    def test_split_multiple_sentences(self):
        """Multiple sentences should be split into chunks."""
        splitter = FakeSplitter()
        result = splitter.split_text("First sentence. Second sentence. Third sentence.")

        assert len(result) == 3

    def test_split_deterministic(self):
        """Same input should produce same output."""
        splitter = FakeSplitter()
        text = "Deterministic test. Should be stable."

        result1 = splitter.split_text(text)
        result2 = splitter.split_text(text)

        assert result1 == result2

    def test_split_increments_call_count(self):
        """Each split call should increment the counter."""
        splitter = FakeSplitter()
        assert splitter.call_count == 0

        splitter.split_text("Test one.")
        assert splitter.call_count == 1

        splitter.split_text("Test two.")
        assert splitter.call_count == 2

    def test_split_records_last_text(self):
        """split_text() should record the text for inspection."""
        splitter = FakeSplitter()
        text = "Remember this text."
        splitter.split_text(text)

        assert splitter.last_text == text

    def test_split_validates_input(self):
        """split_text() should call validate_text and raise on invalid input."""
        splitter = FakeSplitter()

        with pytest.raises(ValueError, match="empty or whitespace"):
            splitter.split_text("")

        with pytest.raises(ValueError, match="must be a string"):
            splitter.split_text(42)  # type: ignore

    def test_split_returns_non_empty_chunks(self):
        """All returned chunks should be non-empty strings."""
        splitter = FakeSplitter()
        result = splitter.split_text("Chunk one. Chunk two. Chunk three.")

        assert all(isinstance(c, str) for c in result)
        assert all(len(c) > 0 for c in result)


class TestSplitterFactory:
    """Tests for SplitterFactory."""

    def setup_method(self):
        """Reset factory registry before each test."""
        SplitterFactory._PROVIDERS.clear()

    def test_register_provider_success(self):
        """Registering valid provider should succeed."""
        SplitterFactory.register_provider("fake", FakeSplitter)
        assert "fake" in SplitterFactory._PROVIDERS
        assert SplitterFactory._PROVIDERS["fake"] == FakeSplitter

    def test_register_provider_case_insensitive(self):
        """Strategy names should be normalized to lowercase."""
        SplitterFactory.register_provider("Recursive", FakeSplitter)
        assert "recursive" in SplitterFactory._PROVIDERS

    def test_register_provider_invalid_class(self):
        """Registering non-BaseSplitter class should raise ValueError."""

        class NotASplitter:
            pass

        with pytest.raises(ValueError, match="must inherit from BaseSplitter"):
            SplitterFactory.register_provider(
                "invalid", NotASplitter,  # type: ignore
            )

    def test_list_providers_empty(self):
        """list_providers should return empty list when no providers registered."""
        assert SplitterFactory.list_providers() == []

    def test_list_providers_sorted(self):
        """list_providers should return sorted provider names."""
        SplitterFactory.register_provider("semantic", FakeSplitter)
        SplitterFactory.register_provider("fixed", FakeSplitter)
        SplitterFactory.register_provider("recursive", FakeSplitter)

        providers = SplitterFactory.list_providers()
        assert providers == ["fixed", "recursive", "semantic"]

    def test_create_success(self):
        """Creating registered strategy should succeed."""
        SplitterFactory.register_provider("fake", FakeSplitter)

        settings = MagicMock()
        settings.splitter.strategy = "fake"

        splitter = SplitterFactory.create(settings)

        assert isinstance(splitter, FakeSplitter)
        assert splitter.settings == settings

    def test_create_case_insensitive(self):
        """Strategy lookup should be case-insensitive."""
        SplitterFactory.register_provider("fake", FakeSplitter)

        settings = MagicMock()
        settings.splitter.strategy = "FAKE"

        splitter = SplitterFactory.create(settings)
        assert isinstance(splitter, FakeSplitter)

    def test_create_with_overrides(self):
        """Factory should pass override kwargs to provider constructor."""
        SplitterFactory.register_provider("fake", FakeSplitter)

        settings = MagicMock()
        settings.splitter.strategy = "fake"

        splitter = SplitterFactory.create(
            settings, strategy_name="custom-strategy",
        )
        assert splitter.get_strategy_name() == "custom-strategy"

    def test_create_unknown_strategy(self):
        """Creating unregistered strategy should raise clear error."""
        SplitterFactory.register_provider("fake", FakeSplitter)

        settings = MagicMock()
        settings.splitter.strategy = "unknown"

        with pytest.raises(ValueError) as exc_info:
            SplitterFactory.create(settings)

        error_message = str(exc_info.value)
        assert "Unsupported Splitter strategy: 'unknown'" in error_message
        assert "Available strategies:" in error_message

    def test_create_missing_strategy_config(self):
        """Missing strategy in settings should raise clear error."""
        settings = MagicMock()
        del settings.splitter  # Simulate missing config

        with pytest.raises(ValueError) as exc_info:
            SplitterFactory.create(settings)

        error_message = str(exc_info.value)
        assert "Missing required configuration" in error_message
        assert "settings.splitter.strategy" in error_message
        assert "settings.yaml" in error_message

    def test_create_provider_instantiation_failure(self):
        """Provider constructor errors should be wrapped in RuntimeError."""

        class BrokenSplitter(BaseSplitter):
            def __init__(self, settings: Any, **kwargs: Any):
                raise ValueError("Intentional init error")

            def split_text(
                self,
                text: str,
                trace: Optional[Any] = None,
                **kwargs: Any,
            ) -> List[str]:
                return [text]

        SplitterFactory.register_provider("broken", BrokenSplitter)

        settings = MagicMock()
        settings.splitter.strategy = "broken"

        with pytest.raises(RuntimeError) as exc_info:
            SplitterFactory.create(settings)

        error_message = str(exc_info.value)
        assert "Failed to instantiate Splitter strategy 'broken'" in error_message
        assert "Intentional init error" in error_message

    def test_create_no_providers_registered(self):
        """Creating strategy when registry is empty should show helpful message."""
        settings = MagicMock()
        settings.splitter.strategy = "recursive"

        with pytest.raises(ValueError) as exc_info:
            SplitterFactory.create(settings)

        error_message = str(exc_info.value)
        assert "Unsupported Splitter strategy: 'recursive'" in error_message
        assert "Available strategies: none" in error_message

    def test_create_and_split_roundtrip(self):
        """Factory-created splitter should produce valid chunks."""
        SplitterFactory.register_provider("fake", FakeSplitter)

        settings = MagicMock()
        settings.splitter.strategy = "fake"

        splitter = SplitterFactory.create(settings)
        chunks = splitter.split_text("Hello world. This is a test.")

        assert len(chunks) >= 1
        assert all(isinstance(c, str) for c in chunks)
        assert all(len(c) > 0 for c in chunks)

    def test_create_override_chunk_size(self):
        """Factory should allow overriding chunk_size via kwargs."""
        SplitterFactory.register_provider("fake", FakeSplitter)

        settings = MagicMock()
        settings.splitter.strategy = "fake"

        splitter = SplitterFactory.create(settings, chunk_size=512)
        assert splitter.get_chunk_size() == 512

    def test_create_override_chunk_overlap(self):
        """Factory should allow overriding chunk_overlap via kwargs."""
        SplitterFactory.register_provider("fake", FakeSplitter)

        settings = MagicMock()
        settings.splitter.strategy = "fake"

        splitter = SplitterFactory.create(settings, chunk_overlap=50)
        assert splitter.get_chunk_overlap() == 50
