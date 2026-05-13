"""Abstract base class for metric sources."""

from abc import ABC, abstractmethod

from src.core.metrics.models import MetricSample


class BaseMetricSource(ABC):
    """Abstract interface for all metric sources.

    Every concrete metric source (mock, folder, Prometheus, etc.)
    must implement this interface so downstream consumers can treat
    all sources uniformly.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of this metric source."""

    @abstractmethod
    async def start(self) -> None:
        """Initialize the source and begin streaming."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop streaming and clean up resources."""

    @abstractmethod
    async def stream(self):
        """Yield MetricSample objects as they become available.

        This is an async generator that runs until ``stop()`` is called.
        """
