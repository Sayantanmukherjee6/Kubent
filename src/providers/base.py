"""Abstract base class for LLM providers."""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class AnalysisResult:
    """Structured result returned by the LLM after analyzing logs."""

    root_cause: str
    severity: str
    remediation_suggestions: list[str]
    preventive_actions: list[str]


_SYSTEM_PROMPT: str = (
    "You are an observability assistant. Analyze the provided log context and "
    "return a JSON object with exactly these keys:\n"
    "  - root_cause: string\n"
    "  - severity: string (one of: critical, high, medium, low)\n"
    "  - remediation_suggestions: array of strings\n"
    "  - preventive_actions: array of strings\n"
    "Return ONLY valid JSON. No markdown, no explanation."
)


class BaseLlmProvider(ABC):
    """Abstract interface that all LLM providers must implement."""

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

    @property
    def system_prompt(self) -> str:
        """Return the system prompt used for analysis."""
        return _SYSTEM_PROMPT

    @abstractmethod
    async def analyze(self, log_context: str) -> AnalysisResult:
        """Send log context to the LLM and return structured analysis.

        Args:
            log_context: The log lines or error context to analyze.

        Returns:
            Structured analysis with root cause, severity, remediation,
            and preventive actions.
        """
