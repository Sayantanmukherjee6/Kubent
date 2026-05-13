"""Data models for the metric subsystem."""

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class MetricSample:
    """A single metric sample from a Kubernetes-style service.

    Attributes:
        timestamp: When this sample was recorded.
        service_name: Name of the Kubernetes service.
        cpu_usage: CPU usage as a percentage (0-100).
        memory_usage: Memory usage as a percentage (0-100).
        latency_ms: P50 request latency in milliseconds.
        error_rate: Fraction of requests that errored (0.0-1.0).
        source: Human-readable identifier for the metric source.
    """

    timestamp: datetime
    service_name: str
    cpu_usage: float
    memory_usage: float
    latency_ms: float
    error_rate: float
    source: str
