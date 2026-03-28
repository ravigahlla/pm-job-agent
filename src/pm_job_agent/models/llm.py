"""Swappable LLM interface. Agent code should depend on LLMClient, not vendor SDKs."""

from __future__ import annotations

import importlib
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    def generate(self, user_prompt: str, *, system_prompt: str = "") -> str:
        """Return model text for the given prompts."""
        ...


class StubLLM:
    """Deterministic stand-in for CI and local runs without API keys."""

    def generate(self, user_prompt: str, *, system_prompt: str = "") -> str:
        _ = system_prompt
        return (
            "[stub-llm] No remote LLM call was made. "
            f"User prompt length={len(user_prompt)} chars. "
            "Configure a provider in .env to use Anthropic, OpenAI, Gemini, or Ollama."
        )


def _import_provider(module_path: str, class_name: str, extra: str) -> Any:
    """Lazy-import a provider class; surface a clear install hint if the SDK is missing."""
    try:
        mod = importlib.import_module(module_path)
    except ImportError as exc:
        raise ImportError(
            f"Provider '{extra}' requires extra dependencies. "
            f"Run: pip install 'pm-job-agent[{extra}]'"
        ) from exc
    return getattr(mod, class_name)


def _require_key(secret: Any, env_var: str, provider: str) -> str:
    """Unwrap a SecretStr API key or raise a clear error if it is not set."""
    if secret is None:
        raise ValueError(
            f"DEFAULT_LLM_PROVIDER={provider!r} requires {env_var} to be set in .env"
        )
    return secret.get_secret_value()


def get_llm_client() -> LLMClient:
    """Resolve and return the configured LLM client.

    Controlled entirely by DEFAULT_LLM_PROVIDER in .env.
    Provider SDKs are imported lazily — only the selected one is loaded.
    """
    from pm_job_agent.config.settings import get_settings

    settings = get_settings()
    provider = (settings.default_llm_provider or "stub").lower()

    if provider == "stub":
        return StubLLM()

    if provider == "anthropic":
        cls = _import_provider(
            "pm_job_agent.models.providers.anthropic", "AnthropicLLM", "anthropic"
        )
        key = _require_key(settings.anthropic_api_key, "ANTHROPIC_API_KEY", "anthropic")
        return cls(api_key=key, model=settings.anthropic_model)

    if provider == "openai":
        cls = _import_provider(
            "pm_job_agent.models.providers.openai", "OpenAILLM", "openai"
        )
        key = _require_key(settings.openai_api_key, "OPENAI_API_KEY", "openai")
        return cls(api_key=key, model=settings.openai_model)

    if provider == "gemini":
        cls = _import_provider(
            "pm_job_agent.models.providers.gemini", "GeminiLLM", "gemini"
        )
        key = _require_key(settings.google_api_key, "GOOGLE_API_KEY", "gemini")
        return cls(api_key=key, model=settings.gemini_model)

    if provider == "ollama":
        cls = _import_provider(
            "pm_job_agent.models.providers.ollama", "OllamaLLM", "ollama"
        )
        # Ollama is local — no API key, but the server must be running at ollama_base_url.
        return cls(model=settings.ollama_model, host=settings.ollama_base_url)

    raise ValueError(
        f"Unknown LLM provider {provider!r}. "
        "Set DEFAULT_LLM_PROVIDER to: stub | anthropic | openai | gemini | ollama"
    )
