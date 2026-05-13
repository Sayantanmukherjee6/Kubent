"""Prediction rules for the statistical metric predictor.

Each PredictionRule defines a condition that, when met, triggers a
MetricPredictionEvent.  Rules are evaluated after the built-in anomaly,
threshold, and OOM checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from src.core.metrics.events import MetricPredictionType, MetricSeverity
from src.core.metrics.models import MetricSample

if TYPE_CHECKING:
    from src.core.metrics.predictor import RollingWindow


@dataclass(frozen=True)
class PredictionRule:
    """A single prediction rule.

    Attributes:
        name:             Unique rule identifier.
        metric:           Which metric to check ("cpu", "memory", "latency").
        prediction_type:  Type of event to emit when triggered.
        severity:         Severity of the emitted event.
        threshold_value:  Threshold that triggers the rule.
        message_template: Format string with {current} and {threshold}.
        condition_fn:     Optional custom predicate(sample, windows) -> bool.
    """

    name: str
    metric: str
    prediction_type: MetricPredictionType
    severity: MetricSeverity
    threshold_value: float
    message_template: str
    condition_fn: Callable[[MetricSample, dict[str, RollingWindow]], bool] | None = None

    def evaluate(self, sample: MetricSample, windows: dict[str, RollingWindow]) -> bool:
        """Return True if this rule should trigger."""
        if self.condition_fn is not None:
            return self.condition_fn(sample, windows)

        win = windows.get(self.metric)
        if win is None or win.size() < 2:
            return False

        current = (
            sample.cpu_usage if self.metric == "cpu" else
            sample.memory_usage if self.metric == "memory" else
            sample.latency_ms
        )
        return current >= self.threshold_value


class PredictionRules:
    """Collection of built-in prediction rules."""

    BUILTIN_RULES: tuple[PredictionRule, ...] = (
        PredictionRule(
            name="high_cpu",
            metric="cpu",
            prediction_type=MetricPredictionType.PREDICTED_CPU_BREACH,
            severity=MetricSeverity.HIGH,
            threshold_value=95.0,
            message_template="CPU at {current:.1f}% exceeds critical threshold of {threshold:.0f}%",
        ),
        PredictionRule(
            name="high_memory",
            metric="memory",
            prediction_type=MetricPredictionType.PREDICTED_MEMORY_BREACH,
            severity=MetricSeverity.HIGH,
            threshold_value=97.0,
            message_template="Memory at {current:.1f}% exceeds critical threshold of {threshold:.0f}%",
        ),
    )
