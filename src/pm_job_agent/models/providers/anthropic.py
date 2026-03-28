"""Anthropic Claude provider. Requires: pip install 'pm-job-agent[anthropic]'"""

from __future__ import annotations


class AnthropicLLM:
    """Wraps the Anthropic messages API behind the LLMClient protocol."""

    def __init__(self, api_key: str, model: str) -> None:
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "Anthropic SDK not found. Run: pip install 'pm-job-agent[anthropic]'"
            ) from exc
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def generate(self, user_prompt: str, *, system_prompt: str = "") -> str:
        # Anthropic takes system as a top-level param, not a message role.
        kwargs: dict = {
            "model": self._model,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        message = self._client.messages.create(**kwargs)
        return message.content[0].text
