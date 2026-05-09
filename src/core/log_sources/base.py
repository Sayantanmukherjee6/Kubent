"""Abstract base class for log sources."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class LogLine:
    """A single log line with metadata."""

    text: str
    source: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __str__(self) -> str:
        return self.text


class BaseLogSource(ABC):
    """Abstract interface for all log sources.

    Every concrete log source (mock file, Kubernetes, Loki, etc.)
    must implement this interface so downstream consumers can treat
    all sources uniformly.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of this log source."""

    @abstractmethod
    async def start(self) -> None:
        """Initialize the source and begin streaming."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop streaming and clean up resources."""

    @abstractmethod
    async def stream(self):
        """Yield LogLine objects as they become available.

        This is an async generator that runs until ``stop()`` is called.
        """
