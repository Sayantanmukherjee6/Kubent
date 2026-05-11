"""Data models for the predictor subsystem.

Lightweight, frozen dataclasses — no pydantic, no external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


# ---------------------------------------------------------------------------
# Risk levels used by the predictor
# ---------------------------------------------------------------------------

class RiskLevel(str, Enum):
    """Predicted risk level for an incident."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Predictor event model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PredictorEvent:
    """A predicted incident event emitted by the heuristic engine.

    Attributes:
        timestamp:      When this prediction was made (UTC).
        service_name:   The Kubernetes service at risk.
        risk_level:     Predicted risk level.
        pattern:        Human-readable description of the detected pattern.
        trigger_count:  Number of triggering events in the rolling window.
        related_hash:   SHA-256 fingerprint of the related IncidentEvent.
        metadata:       Optional extra key-value pairs.
    """

    timestamp: datetime
    service_name: str
    risk_level: RiskLevel
    pattern: str
    trigger_count: int
    related_hash: str = ""
    metadata: dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        return (
            f"PredictorEvent(risk={self.risk_level.value}, "
            f"service={self.service_name}, "
            f"pattern={self.pattern}, "
            f"count={self.trigger_count})"
        )
