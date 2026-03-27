"""Swappable LLM interface. Agent code should depend on LLMClient, not vendor SDKs."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


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
            "Configure a provider in .env when you wire OpenAI, Anthropic, or Gemini."
        )


def get_llm_client() -> LLMClient:
    """Resolve LLM from settings. Phase 1: always stub until provider modules exist."""
    from pm_job_agent.config.settings import get_settings

    settings = get_settings()
    provider = (settings.default_llm_provider or "stub").lower()
    if provider == "stub":
        return StubLLM()
    raise NotImplementedError(
        f"LLM provider {provider!r} is not implemented yet. Set DEFAULT_LLM_PROVIDER=stub."
    )
