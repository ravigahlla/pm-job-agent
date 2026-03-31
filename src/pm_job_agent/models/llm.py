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
    """Unwrap a SecretStr API key or raise a clear error if it is not set or empty."""
    value = secret.get_secret_value() if secret is not None else ""
    if not value.strip():
        raise ValueError(
            f"DEFAULT_LLM_PROVIDER={provider!r} requires {env_var} to be set in .env"
        )
    return value


def _build_client(provider: str, model_override: str, settings: Any) -> LLMClient:
    """Instantiate an LLMClient for the given provider.

    `model_override` is used when non-empty, otherwise the provider's configured
    default model from settings is used. This is the single place that maps provider
    name → SDK class, so both get_llm_client() and get_scoring_llm_client() stay in sync.
    """
    if provider == "stub":
        return StubLLM()

    if provider == "anthropic":
        cls = _import_provider(
            "pm_job_agent.models.providers.anthropic", "AnthropicLLM", "anthropic"
        )
        key = _require_key(settings.anthropic_api_key, "ANTHROPIC_API_KEY", "anthropic")
        model = model_override or settings.anthropic_model
        return cls(api_key=key, model=model)

    if provider == "openai":
        cls = _import_provider(
            "pm_job_agent.models.providers.openai", "OpenAILLM", "openai"
        )
        key = _require_key(settings.openai_api_key, "OPENAI_API_KEY", "openai")
        model = model_override or settings.openai_model
        return cls(api_key=key, model=model)

    if provider == "gemini":
        cls = _import_provider(
            "pm_job_agent.models.providers.gemini", "GeminiLLM", "gemini"
        )
        key = _require_key(settings.google_api_key, "GOOGLE_API_KEY", "gemini")
        model = model_override or settings.gemini_model
        return cls(api_key=key, model=model)

    if provider == "ollama":
        cls = _import_provider(
            "pm_job_agent.models.providers.ollama", "OllamaLLM", "ollama"
        )
        model = model_override or settings.ollama_model
        return cls(model=model, host=settings.ollama_base_url)

    raise ValueError(
        f"Unknown LLM provider {provider!r}. "
        "Set DEFAULT_LLM_PROVIDER to: stub | anthropic | openai | gemini | ollama"
    )


def get_llm_client() -> LLMClient:
    """Resolve and return the configured LLM client.

    Controlled entirely by DEFAULT_LLM_PROVIDER in .env.
    Provider SDKs are imported lazily — only the selected one is loaded.
    """
    from pm_job_agent.config.settings import get_settings

    settings = get_settings()
    provider = (settings.default_llm_provider or "stub").lower()
    return _build_client(provider, model_override="", settings=settings)


def get_llm_client_for_provider(provider: str) -> LLMClient:
    """Construct a client for the named provider, using settings for all other config.

    Intended for CLI --provider overrides so callers don't need to touch .env.
    Raises ValueError for unknown provider names (same error as _build_client).
    """
    from pm_job_agent.config.settings import get_settings

    return _build_client(provider.lower(), model_override="", settings=get_settings())


def get_scoring_llm_client() -> LLMClient:
    """Resolve and return the LLM client used for job scoring.

    Uses SCORING_LLM_PROVIDER and SCORING_MODEL when set; otherwise inherits
    DEFAULT_LLM_PROVIDER and the provider's configured default model. This lets
    scoring use a cheap model (Haiku, GPT-4o-mini) while generation uses a
    higher-quality one — controlled entirely via .env without code changes.
    """
    from pm_job_agent.config.settings import get_settings

    settings = get_settings()
    provider = (settings.scoring_llm_provider or settings.default_llm_provider or "stub").lower()
    model_override = settings.scoring_model or ""
    return _build_client(provider, model_override=model_override, settings=settings)
