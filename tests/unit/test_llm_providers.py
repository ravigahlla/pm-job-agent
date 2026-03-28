"""Unit tests for LLM provider implementations and the get_llm_client() factory.

SDK calls are never made — each test patches sys.modules with MagicMock objects so the
real anthropic / openai / google.genai / ollama packages are not required to run this suite.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from pm_job_agent.config.settings import get_settings
from pm_job_agent.models.llm import StubLLM, _require_key, get_llm_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sdk_mock(**attrs: Any) -> MagicMock:
    """Build a MagicMock with named attributes pre-set."""
    m = MagicMock()
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


# ---------------------------------------------------------------------------
# Factory: get_llm_client()
# ---------------------------------------------------------------------------


class TestGetLLMClientFactory:
    def test_stub_provider_returns_stub_llm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEFAULT_LLM_PROVIDER", "stub")
        get_settings.cache_clear()
        client = get_llm_client()
        assert isinstance(client, StubLLM)

    def test_unknown_provider_raises_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEFAULT_LLM_PROVIDER", "unicorn")
        get_settings.cache_clear()
        with pytest.raises(ValueError, match="unicorn"):
            get_llm_client()

    def test_anthropic_missing_api_key_raises_value_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEFAULT_LLM_PROVIDER", "anthropic")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        get_settings.cache_clear()
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            get_llm_client()

    def test_openai_missing_api_key_raises_value_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEFAULT_LLM_PROVIDER", "openai")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        get_settings.cache_clear()
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            get_llm_client()

    def test_gemini_missing_api_key_raises_value_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEFAULT_LLM_PROVIDER", "gemini")
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        get_settings.cache_clear()
        with pytest.raises(ValueError, match="GOOGLE_API_KEY"):
            get_llm_client()

    def test_require_key_raises_on_none(self) -> None:
        with pytest.raises(ValueError, match="MY_KEY"):
            _require_key(None, "MY_KEY", "testprovider")

    def test_stub_generate_contains_marker(self) -> None:
        result = StubLLM().generate("hello", system_prompt="ignored")
        assert "[stub-llm]" in result


# ---------------------------------------------------------------------------
# AnthropicLLM
# ---------------------------------------------------------------------------


class TestAnthropicLLM:
    """SDK import is patched via sys.modules before AnthropicLLM is instantiated."""

    def _make_mock_sdk(self, response_text: str = "anthropic response") -> MagicMock:
        content_block = MagicMock()
        content_block.text = response_text
        message = MagicMock()
        message.content = [content_block]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = message
        mock_sdk = MagicMock()
        mock_sdk.Anthropic.return_value = mock_client
        return mock_sdk, mock_client

    def test_generate_returns_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_sdk, _ = self._make_mock_sdk("hello from claude")
        monkeypatch.setitem(sys.modules, "anthropic", mock_sdk)
        from pm_job_agent.models.providers.anthropic import AnthropicLLM

        llm = AnthropicLLM(api_key="test-key", model="claude-3-5-haiku-20241022")
        assert llm.generate("test prompt") == "hello from claude"

    def test_system_prompt_passed_as_top_level_param(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_sdk, mock_client = self._make_mock_sdk()
        monkeypatch.setitem(sys.modules, "anthropic", mock_sdk)
        from pm_job_agent.models.providers.anthropic import AnthropicLLM

        llm = AnthropicLLM(api_key="key", model="model")
        llm.generate("prompt", system_prompt="be helpful")
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "be helpful"

    def test_no_system_key_when_system_prompt_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_sdk, mock_client = self._make_mock_sdk()
        monkeypatch.setitem(sys.modules, "anthropic", mock_sdk)
        from pm_job_agent.models.providers.anthropic import AnthropicLLM

        llm = AnthropicLLM(api_key="key", model="model")
        llm.generate("prompt")
        call_kwargs = mock_client.messages.create.call_args.kwargs
        # Anthropic raises if you pass an empty system string — we must omit the key entirely.
        assert "system" not in call_kwargs

    def test_missing_sdk_raises_import_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "anthropic", None)  # type: ignore[arg-type]
        # Remove cached module so the lazy import fires fresh.
        monkeypatch.delitem(sys.modules, "pm_job_agent.models.providers.anthropic", raising=False)
        with pytest.raises(ImportError, match="pip install"):
            from pm_job_agent.models.providers.anthropic import AnthropicLLM  # noqa: F401

            AnthropicLLM(api_key="k", model="m")


# ---------------------------------------------------------------------------
# OpenAILLM
# ---------------------------------------------------------------------------


class TestOpenAILLM:
    def _make_mock_sdk(self, response_text: str = "openai response") -> tuple[MagicMock, MagicMock]:
        choice = MagicMock()
        choice.message.content = response_text
        completion = MagicMock()
        completion.choices = [choice]
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = completion
        mock_sdk = MagicMock()
        mock_sdk.OpenAI.return_value = mock_client
        return mock_sdk, mock_client

    def test_generate_returns_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_sdk, _ = self._make_mock_sdk("hello from gpt")
        monkeypatch.setitem(sys.modules, "openai", mock_sdk)
        from pm_job_agent.models.providers.openai import OpenAILLM

        llm = OpenAILLM(api_key="key", model="gpt-4o-mini")
        assert llm.generate("test") == "hello from gpt"

    def test_system_prompt_prepended_as_system_role(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_sdk, mock_client = self._make_mock_sdk()
        monkeypatch.setitem(sys.modules, "openai", mock_sdk)
        from pm_job_agent.models.providers.openai import OpenAILLM

        llm = OpenAILLM(api_key="key", model="gpt-4o-mini")
        llm.generate("user msg", system_prompt="you are helpful")
        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        assert messages[0] == {"role": "system", "content": "you are helpful"}
        assert messages[1] == {"role": "user", "content": "user msg"}

    def test_no_system_message_when_system_prompt_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_sdk, mock_client = self._make_mock_sdk()
        monkeypatch.setitem(sys.modules, "openai", mock_sdk)
        from pm_job_agent.models.providers.openai import OpenAILLM

        llm = OpenAILLM(api_key="key", model="gpt-4o-mini")
        llm.generate("user msg")
        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"


# ---------------------------------------------------------------------------
# GeminiLLM
# ---------------------------------------------------------------------------


class TestGeminiLLM:
    def _make_mock_genai(self, response_text: str = "gemini response") -> MagicMock:
        mock_response = MagicMock()
        mock_response.text = response_text
        mock_models = MagicMock()
        mock_models.generate_content.return_value = mock_response
        mock_client_instance = MagicMock()
        mock_client_instance.models = mock_models
        mock_genai = MagicMock()
        mock_genai.Client.return_value = mock_client_instance
        return mock_genai, mock_client_instance

    def test_generate_returns_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_genai, _ = self._make_mock_genai("hello from gemini")
        monkeypatch.setitem(sys.modules, "google.genai", mock_genai)
        monkeypatch.delitem(
            sys.modules, "pm_job_agent.models.providers.gemini", raising=False
        )
        from pm_job_agent.models.providers.gemini import GeminiLLM

        llm = GeminiLLM(api_key="key", model="gemini-1.5-flash")
        assert llm.generate("test") == "hello from gemini"

    def test_system_prompt_sets_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_genai, mock_client_instance = self._make_mock_genai()
        mock_config = MagicMock()
        mock_genai.types.GenerateContentConfig.return_value = mock_config
        monkeypatch.setitem(sys.modules, "google.genai", mock_genai)
        monkeypatch.delitem(
            sys.modules, "pm_job_agent.models.providers.gemini", raising=False
        )
        from pm_job_agent.models.providers.gemini import GeminiLLM

        llm = GeminiLLM(api_key="key", model="gemini-1.5-flash")
        llm.generate("prompt", system_prompt="be a PM assistant")
        mock_genai.types.GenerateContentConfig.assert_called_once_with(
            system_instruction="be a PM assistant"
        )
        call_kwargs = mock_client_instance.models.generate_content.call_args.kwargs
        assert call_kwargs["config"] == mock_config

    def test_no_config_when_system_prompt_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_genai, mock_client_instance = self._make_mock_genai()
        monkeypatch.setitem(sys.modules, "google.genai", mock_genai)
        monkeypatch.delitem(
            sys.modules, "pm_job_agent.models.providers.gemini", raising=False
        )
        from pm_job_agent.models.providers.gemini import GeminiLLM

        llm = GeminiLLM(api_key="key", model="gemini-1.5-flash")
        llm.generate("prompt")
        call_kwargs = mock_client_instance.models.generate_content.call_args.kwargs
        assert call_kwargs["config"] is None


# ---------------------------------------------------------------------------
# OllamaLLM
# ---------------------------------------------------------------------------


class TestOllamaLLM:
    def _make_mock_sdk(self, response_text: str = "ollama response") -> tuple[MagicMock, MagicMock]:
        mock_response = MagicMock()
        mock_response.message.content = response_text
        mock_client_instance = MagicMock()
        mock_client_instance.chat.return_value = mock_response
        mock_sdk = MagicMock()
        mock_sdk.Client.return_value = mock_client_instance
        return mock_sdk, mock_client_instance

    def test_generate_returns_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_sdk, _ = self._make_mock_sdk("hello from llama")
        monkeypatch.setitem(sys.modules, "ollama", mock_sdk)
        from pm_job_agent.models.providers.ollama import OllamaLLM

        llm = OllamaLLM(model="llama3.2", host="http://localhost:11434")
        assert llm.generate("test") == "hello from llama"

    def test_host_passed_to_client_constructor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_sdk, _ = self._make_mock_sdk()
        monkeypatch.setitem(sys.modules, "ollama", mock_sdk)
        from pm_job_agent.models.providers.ollama import OllamaLLM

        OllamaLLM(model="llama3.2", host="http://my-server:11434")
        mock_sdk.Client.assert_called_once_with(host="http://my-server:11434")

    def test_system_prompt_included_as_system_role(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_sdk, mock_client_instance = self._make_mock_sdk()
        monkeypatch.setitem(sys.modules, "ollama", mock_sdk)
        from pm_job_agent.models.providers.ollama import OllamaLLM

        llm = OllamaLLM(model="llama3.2", host="http://localhost:11434")
        llm.generate("tell me about PM roles", system_prompt="you are a career coach")
        messages = mock_client_instance.chat.call_args.kwargs["messages"]
        assert messages[0] == {"role": "system", "content": "you are a career coach"}
        assert messages[1] == {"role": "user", "content": "tell me about PM roles"}
