"""llama.cpp provider — calls a local llama.cpp server via OpenAI-compatible API."""

from typing import Any

import httpx

from src.config.settings import Settings
from src.providers.base import AnalysisResult, BaseLlmProvider


class LlamaCppProvider(BaseLlmProvider):
    """LLM provider backed by a local llama.cpp server."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.llama_cpp_base_url.rstrip("/")
        self._model = settings.llama_cpp_model_name

    async def analyze(self, log_context: str) -> AnalysisResult:
        """Send log context to llama.cpp and parse the JSON response."""
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": log_context},
            ],
            "temperature": 0.0,
            "max_tokens": 1024,
        }

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            body = response.json()

        content: str = body["choices"][0]["message"]["content"]
        return self._parse_json(content)
