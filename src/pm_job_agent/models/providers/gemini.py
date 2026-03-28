"""Google Gemini provider. Requires: pip install 'pm-job-agent[gemini]'

Uses google-genai (v1.0+), not the older google-generativeai package.
Import path: `import google.genai as genai`
"""

from __future__ import annotations


class GeminiLLM:
    """Wraps the Google Gemini generate_content API behind the LLMClient protocol."""

    def __init__(self, api_key: str, model: str) -> None:
        try:
            import importlib
            genai = importlib.import_module("google.genai")
        except ImportError as exc:
            raise ImportError(
                "Google GenAI SDK not found. Run: pip install 'pm-job-agent[gemini]'"
            ) from exc
        self._client = genai.Client(api_key=api_key)
        self._genai = genai  # held for access to genai.types in generate()
        self._model = model

    def generate(self, user_prompt: str, *, system_prompt: str = "") -> str:
        config = None
        if system_prompt:
            config = self._genai.types.GenerateContentConfig(system_instruction=system_prompt)
        response = self._client.models.generate_content(
            model=self._model,
            contents=user_prompt,
            config=config,
        )
        return response.text
