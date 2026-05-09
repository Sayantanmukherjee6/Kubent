"""Abstract base class for LLM providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class AnalysisResult:
    """Structured result returned by the LLM after analyzing logs."""

    root_cause: str
    severity: str
    remediation_suggestions: list[str]
    preventive_actions: list[str]


class BaseLlmProvider(ABC):
    """Abstract interface that all LLM providers must implement."""

    @abstractmethod
    async def analyze(self, log_context: str) -> AnalysisResult:
        """Send log context to the LLM and return structured analysis.

        Args:
            log_context: The log lines or error context to analyze.

        Returns:
            Structured analysis with root cause, severity, remediation,
            and preventive actions.
        """
