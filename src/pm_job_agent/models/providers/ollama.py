"""Ollama local provider. Requires: pip install 'pm-job-agent[ollama]' and a running Ollama server."""

from __future__ import annotations


class OllamaLLM:
    """Wraps the Ollama chat API behind the LLMClient protocol.

    Ollama runs locally — no API key needed, but the server must be reachable at
    OLLAMA_BASE_URL (default: http://localhost:11434). Pull your model first with
    `ollama pull <model>` before running the agent.
    """

    def __init__(self, model: str, host: str) -> None:
        try:
            import ollama
        except ImportError as exc:
            raise ImportError(
                "Ollama SDK not found. Run: pip install 'pm-job-agent[ollama]'"
            ) from exc
        self._client = ollama.Client(host=host)
        self._model = model

    def generate(self, user_prompt: str, *, system_prompt: str = "") -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        response = self._client.chat(model=self._model, messages=messages)
        return response.message.content
