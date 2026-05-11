"""OpenAI provider — calls the OpenAI API (or any compatible endpoint)."""

from typing import Any

import httpx

from src.config.settings import Settings
from src.providers.base import AnalysisResult, BaseLlmProvider
from src.providers.retry import retry


class OpenAiProvider(BaseLlmProvider):
    """LLM provider backed by the OpenAI API."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.openai_base_url.rstrip("/")
        self._model = settings.openai_model_name
        self._api_key = settings.openai_api_key

    async def analyze(self, log_context: str) -> AnalysisResult:
        """Send log context to OpenAI and parse the JSON response."""
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": log_context},
            ],
            "temperature": 0.0,
            "max_tokens": 1024,
        }

        headers: dict[str, str] = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        async def _call() -> dict:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                return response.json()

        body = await retry(_call)

        content: str = body["choices"][0]["message"]["content"]
        return self._parse_json(content)
