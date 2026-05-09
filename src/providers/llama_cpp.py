"""llama.cpp provider — calls a local llama.cpp server via OpenAI-compatible API."""

import json
from typing import Any

import httpx

from src.config.settings import Settings
from src.providers.base import AnalysisResult, BaseLlmProvider

_SYSTEM_PROMPT: str = (
    "You are an observability assistant. Analyze the provided log context and "
    "return a JSON object with exactly these keys:\n"
    "  - root_cause: string\n"
    "  - severity: string (one of: critical, high, medium, low)\n"
    "  - remediation_suggestions: array of strings\n"
    "  - preventive_actions: array of strings\n"
    "Return ONLY valid JSON. No markdown, no explanation."
)


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
                {"role": "system", "content": _SYSTEM_PROMPT},
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

    @staticmethod
    def _parse_json(raw: str) -> AnalysisResult:
        """Extract JSON from the model output, stripping markdown fences if present."""
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            # Strip ```json ... ``` or ``` ... ```
            lines = cleaned.splitlines()
            lines = lines[1:]  # remove opening fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        data = json.loads(cleaned)
        return AnalysisResult(
            root_cause=data["root_cause"],
            severity=data["severity"],
            remediation_suggestions=data["remediation_suggestions"],
            preventive_actions=data["preventive_actions"],
        )
