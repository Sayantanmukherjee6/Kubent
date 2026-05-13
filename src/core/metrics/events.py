"""Data models for the statistical metric predictor subsystem.

Lightweight, frozen dataclasses — no pydantic, no external dependencies.
Uses only stdlib: dataclasses, datetime, enum.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


# ---------------------------------------------------------------------------
# Prediction types
# ---------------------------------------------------------------------------

class MetricPredictionType(StrEnum):
    """Types of metric predictions emitted by the statistical predictor."""

    PREDICTED_CPU_BREACH = "PREDICTED_CPU_BREACH"
    PREDICTED_MEMORY_BREACH = "PREDICTED_MEMORY_BREACH"
    PREDICTED_OOM = "PREDICTED_OOM"
    CPU_ANOMALY = "CPU_ANOMALY"
    MEMORY_ANOMALY = "MEMORY_ANOMALY"
    LATENCY_ANOMALY = "LATENCY_ANOMALY"


# ---------------------------------------------------------------------------
# Severity levels (separate from watcher severity)
# ---------------------------------------------------------------------------

class MetricSeverity(StrEnum):
    """Severity for metric prediction events."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Prediction event model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MetricPredictionEvent:
    """A statistical prediction event emitted by the metric predictor.

    Attributes:
        timestamp:      When this prediction was made (UTC).
        service_name:   The Kubernetes service at risk.
        prediction_type: Type of prediction (e.g. CPU_BREACH, OOM).
        severity:       Severity level of the prediction.
        message:        Human-readable description.
        current_value:  The latest observed metric value.
        predicted_value: Forecasted value at threshold breach time.
        threshold:      The threshold that may be breached.
        metadata:       Optional extra key-value pairs.
    """

    timestamp: datetime
    service_name: str
    prediction_type: MetricPredictionType
    severity: MetricSeverity
    message: str
    current_value: float
    predicted_value: float
    threshold: float
    metadata: dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        return (
            f"MetricPredictionEvent(type={self.prediction_type.value}, "
            f"service={self.service_name}, severity={self.severity.value}, "
            f"current={self.current_value:.1f}, predicted={self.predicted_value:.1f}, "
            f"threshold={self.threshold:.1f})"
        )
