"""Unit tests for LLM Factory and Base LLM.

Test Coverage:
- Factory pattern: provider registration, creation, and routing
- Configuration-driven instantiation
- Error handling for unknown/missing providers
- Validation logic in BaseLLM
"""

from typing import Any, List, Optional
from unittest.mock import MagicMock

import pytest

from src.libs.llm.base_llm import BaseLLM
from src.libs.llm.llm_factory import LLMFactory


class FakeLLM(BaseLLM):
    """Fake LLM provider for testing.

    Returns deterministic fake responses for reproducible testing.
    """

    def __init__(
        self, settings: Any = None, model_name: str = "fake-model", **kwargs: Any
    ):
        """Initialize fake LLM provider.

        Args:
            settings: Optional settings (unused in fake).
            model_name: Model name to report.
            **kwargs: Additional parameters (unused).
        """
        self.settings = settings
        self._model_name = model_name
        self.call_count = 0
        self.last_messages: List[dict[str, str]] = []

    def chat(
        self,
        messages: List[dict[str, str]],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> str:
        """Generate fake response."""
        self.validate_messages(messages)
        self.call_count += 1
        self.last_messages = messages

        # Return deterministic fake response based on last user message
        last_content = messages[-1].get("content", "")
        return f"Fake response to: {last_content}"

    def get_model_name(self) -> str:
        """Return configured model name."""
        return self._model_name


class TestBaseLLM:
    """Tests for BaseLLM abstract class."""

    def test_validate_messages_success(self):
        """Valid message list should pass validation."""
        llm = FakeLLM()
        # Should not raise
        llm.validate_messages([{"role": "user", "content": "hello"}])

    def test_validate_messages_multiple(self):
        """Multiple valid messages should pass validation."""
        llm = FakeLLM()
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
        ]
        llm.validate_messages(messages)

    def test_validate_messages_empty_list(self):
        """Empty list should raise ValueError."""
        llm = FakeLLM()
        with pytest.raises(ValueError, match="cannot be empty"):
            llm.validate_messages([])

    def test_validate_messages_non_dict(self):
        """Non-dict entries should raise ValueError."""
        llm = FakeLLM()
        with pytest.raises(ValueError, match="not a dict"):
            llm.validate_messages(["not a dict"])  # type: ignore

    def test_validate_messages_missing_role(self):
        """Messages without 'role' key should raise ValueError."""
        llm = FakeLLM()
        with pytest.raises(ValueError, match="missing required key 'role'"):
            llm.validate_messages([{"content": "hello"}])

    def test_validate_messages_missing_content(self):
        """Messages without 'content' key should raise ValueError."""
        llm = FakeLLM()
        with pytest.raises(ValueError, match="missing required key 'content'"):
            llm.validate_messages([{"role": "user"}])

    def test_get_model_name_implemented(self):
        """FakeLLM should return configured model name."""
        llm = FakeLLM(model_name="gpt-4o")
        assert llm.get_model_name() == "gpt-4o"

    def test_get_model_name_not_implemented(self):
        """BaseLLM without override should raise NotImplementedError."""

        class IncompleteLLM(BaseLLM):
            def chat(
                self,
                messages: List[dict[str, str]],
                trace: Optional[Any] = None,
                **kwargs: Any,
            ) -> str:
                return "ok"

        incomplete = IncompleteLLM()
        with pytest.raises(NotImplementedError, match="must implement get_model_name"):
            incomplete.get_model_name()


class TestFakeLLM:
    """Tests for FakeLLM provider implementation."""

    def test_chat_single_message(self):
        """Chat with single message should return response."""
        llm = FakeLLM()
        result = llm.chat([{"role": "user", "content": "hello"}])

        assert isinstance(result, str)
        assert "hello" in result

    def test_chat_multi_turn(self):
        """Chat with multi-turn messages should use last message."""
        llm = FakeLLM()
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "What is 1+1?"},
            {"role": "assistant", "content": "2"},
            {"role": "user", "content": "And 2+2?"},
        ]
        result = llm.chat(messages)

        assert "And 2+2?" in result

    def test_chat_increments_call_count(self):
        """Each chat call should increment the counter."""
        llm = FakeLLM()
        assert llm.call_count == 0

        llm.chat([{"role": "user", "content": "test1"}])
        assert llm.call_count == 1

        llm.chat([{"role": "user", "content": "test2"}])
        assert llm.call_count == 2

    def test_chat_records_last_messages(self):
        """Chat should record the messages for inspection."""
        llm = FakeLLM()
        messages = [{"role": "user", "content": "remember this"}]
        llm.chat(messages)

        assert llm.last_messages == messages

    def test_chat_validates_input(self):
        """chat() should call validate_messages and raise on invalid input."""
        llm = FakeLLM()

        with pytest.raises(ValueError, match="cannot be empty"):
            llm.chat([])

        with pytest.raises(ValueError, match="missing required key 'role'"):
            llm.chat([{"content": "no role"}])


class TestLLMFactory:
    """Tests for LLMFactory."""

    def setup_method(self):
        """Reset factory registry before each test."""
        LLMFactory._PROVIDERS.clear()

    def test_register_provider_success(self):
        """Registering valid provider should succeed."""
        LLMFactory.register_provider("fake", FakeLLM)
        assert "fake" in LLMFactory._PROVIDERS
        assert LLMFactory._PROVIDERS["fake"] == FakeLLM

    def test_register_provider_case_insensitive(self):
        """Provider names should be normalized to lowercase."""
        LLMFactory.register_provider("Azure", FakeLLM)
        assert "azure" in LLMFactory._PROVIDERS

    def test_register_provider_invalid_class(self):
        """Registering non-BaseLLM class should raise ValueError."""

        class NotAnLLM:
            pass

        with pytest.raises(ValueError, match="must inherit from BaseLLM"):
            LLMFactory.register_provider("invalid", NotAnLLM)  # type: ignore

    def test_list_providers_empty(self):
        """list_providers should return empty list when no providers registered."""
        assert LLMFactory.list_providers() == []

    def test_list_providers_sorted(self):
        """list_providers should return sorted provider names."""
        LLMFactory.register_provider("zebra", FakeLLM)
        LLMFactory.register_provider("alpha", FakeLLM)
        LLMFactory.register_provider("beta", FakeLLM)

        providers = LLMFactory.list_providers()
        assert providers == ["alpha", "beta", "zebra"]

    def test_create_success(self):
        """Creating registered provider should succeed."""
        LLMFactory.register_provider("fake", FakeLLM)

        settings = MagicMock()
        settings.llm.provider = "fake"

        llm = LLMFactory.create(settings)

        assert isinstance(llm, FakeLLM)
        assert llm.settings == settings

    def test_create_case_insensitive(self):
        """Provider lookup should be case-insensitive."""
        LLMFactory.register_provider("fake", FakeLLM)

        settings = MagicMock()
        settings.llm.provider = "FAKE"

        llm = LLMFactory.create(settings)
        assert isinstance(llm, FakeLLM)

    def test_create_with_overrides(self):
        """Factory should pass override kwargs to provider constructor."""
        LLMFactory.register_provider("fake", FakeLLM)

        settings = MagicMock()
        settings.llm.provider = "fake"

        llm = LLMFactory.create(settings, model_name="custom-model")
        assert llm.get_model_name() == "custom-model"

    def test_create_unknown_provider(self):
        """Creating unregistered provider should raise clear error."""
        LLMFactory.register_provider("fake", FakeLLM)

        settings = MagicMock()
        settings.llm.provider = "unknown"

        with pytest.raises(ValueError) as exc_info:
            LLMFactory.create(settings)

        error_message = str(exc_info.value)
        assert "Unsupported LLM provider: 'unknown'" in error_message
        assert "Available providers:" in error_message

    def test_create_missing_provider_config(self):
        """Missing provider in settings should raise clear error."""
        settings = MagicMock()
        del settings.llm  # Simulate missing config

        with pytest.raises(ValueError) as exc_info:
            LLMFactory.create(settings)

        error_message = str(exc_info.value)
        assert "Missing required configuration" in error_message
        assert "settings.llm.provider" in error_message
        assert "settings.yaml" in error_message

    def test_create_provider_instantiation_failure(self):
        """Provider constructor errors should be wrapped in RuntimeError."""

        class BrokenLLM(BaseLLM):
            def __init__(self, settings: Any, **kwargs: Any):
                raise ValueError("Intentional init error")

            def chat(
                self,
                messages: List[dict[str, str]],
                trace: Optional[Any] = None,
                **kwargs: Any,
            ) -> str:
                return "ok"

        LLMFactory.register_provider("broken", BrokenLLM)

        settings = MagicMock()
        settings.llm.provider = "broken"

        with pytest.raises(RuntimeError) as exc_info:
            LLMFactory.create(settings)

        error_message = str(exc_info.value)
        assert "Failed to instantiate LLM provider 'broken'" in error_message
        assert "Intentional init error" in error_message

    def test_create_no_providers_registered(self):
        """Creating provider when registry is empty should show helpful message."""
        settings = MagicMock()
        settings.llm.provider = "openai"

        with pytest.raises(ValueError) as exc_info:
            LLMFactory.create(settings)

        error_message = str(exc_info.value)
        assert "Unsupported LLM provider: 'openai'" in error_message
        assert "Available providers: none" in error_message
