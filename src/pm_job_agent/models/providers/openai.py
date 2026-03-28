"""OpenAI ChatCompletion provider. Requires: pip install 'pm-job-agent[openai]'"""

from __future__ import annotations


class OpenAILLM:
    """Wraps the OpenAI chat completions API behind the LLMClient protocol."""

    def __init__(self, api_key: str, model: str) -> None:
        try:
            import openai
        except ImportError as exc:
            raise ImportError(
                "OpenAI SDK not found. Run: pip install 'pm-job-agent[openai]'"
            ) from exc
        self._client = openai.OpenAI(api_key=api_key)
        self._model = model

    def generate(self, user_prompt: str, *, system_prompt: str = "") -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=1024,
        )
        return response.choices[0].message.content
