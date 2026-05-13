"""Statistical metric predictor — lightweight forecasting without ML.

Uses only stdlib: statistics, math, asyncio, collections.deque, dataclasses.

Supported methods:
    - Moving average (rolling)
    - Median baseline
    - Standard deviation spread analysis
    - Z-score anomaly detection (|z| > 2.5)
    - Linear trend forecasting (slope-based)

Workflow:
    1. Each MetricSample is stored in a per-service rolling window.
    2. On every process(sample) call the predictor evaluates:
       a. Z-score anomaly detection for CPU, memory, latency
       b. Linear trend forecasting against configured thresholds
       c. OOM risk heuristic (rising memory + near threshold + rising latency)
    3. Any triggered rules produce MetricPredictionEvent instances.
"""

from __future__ import annotations

import asyncio
import math
import statistics
from collections import deque
from datetime import datetime, timezone

from src.core.metrics.events import (
    MetricPredictionEvent,
    MetricPredictionType,
    MetricSeverity,
)
from src.core.metrics.models import MetricSample
from src.core.metrics.rules import PredictionRule, PredictionRules


class RollingWindow:
    """Bounded deque-based rolling window for a single metric series.

    Attributes:
        values:  deque of float values (bounded by max_size).
        max_size: Maximum number of samples retained.
    """

    def __init__(self, max_size: int = 100) -> None:
        self.max_size = max_size
        self.values: deque[float] = deque(maxlen=max_size)

    def add(self, value: float) -> None:
        """Add a new value to the window."""
        self.values.append(value)

    def size(self) -> int:
        return len(self.values)

    # ------------------------------------------------------------------
    # Statistical methods
    # ------------------------------------------------------------------

    @staticmethod
    def moving_average(values: list[float], window: int = 10) -> float:
        """Compute a simple moving average over the last *window* values."""
        if not values:
            return 0.0
        recent = values[-window:] if len(values) >= window else values
        return statistics.mean(recent)

    @staticmethod
    def median(values: list[float]) -> float:
        """Return the median as a stable baseline."""
        if not values:
            return 0.0
        return statistics.median(values)

    @staticmethod
    def std_dev(values: list[float]) -> float:
        """Return population/ sample standard deviation (0 if < 2 values)."""
        if len(values) < 2:
            return 0.0
        return statistics.stdev(values)

    def z_score(self, value: float) -> float:
        """Compute the z-score of *value* relative to the window."""
        sd = self.std_dev(list(self.values))
        if sd == 0:
            return 0.0
        return (value - self.median(list(self.values))) / sd

    @staticmethod
    def linear_trend(values: list[float]) -> tuple[float, float]:
        """Simple linear regression: returns (slope, intercept).

        Uses least-squares fit over indices [0, 1, ..., n-1].
        If fewer than 2 values, slope=0 and intercept=mean.
        """
        n = len(values)
        if n < 2:
            return 0.0, values[0] if values else 0.0
        x_mean = (n - 1) / 2.0
        y_mean = statistics.mean(values)
        numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        if denominator == 0:
            return 0.0, y_mean
        slope = numerator / denominator
        intercept = y_mean - slope * x_mean
        return slope, intercept

    def forecast(self, steps: int = 5) -> float:
        """Predict value *steps* ahead using linear trend.

        future = current + slope * steps  (simplified).
        """
        if len(self.values) < 2:
            return self.moving_average(list(self.values))
        slope, _ = self.linear_trend(list(self.values))
        return list(self.values)[-1] + slope * steps


class _PredictionCooldown:
    """Lightweight in-memory cooldown tracker per (service, prediction_type).

    Suppresses repeated identical prediction events for a configurable duration
    (seconds) or sample count. Uses a simple dict — no external dependencies.
    """

    def __init__(self, seconds: float = 30.0, samples: int = 0) -> None:
        self._seconds = seconds
        self._samples = samples
        # Key: (service, prediction_type) -> (last_timestamp, last_sample_count)
        self._last: dict[tuple[str, str], tuple[datetime, int]] = {}
        self._sample_counter: int = 0

    def _key(self, service: str, pred_type: str) -> tuple[str, str]:
        return (service, pred_type)

    def is_cooldown_active(self, service: str, pred_type: str, now: datetime) -> bool:
        """Return True if the prediction is still within cooldown (should be suppressed)."""
        key = self._key(service, pred_type)
        if key not in self._last:
            return False
        last_ts, last_count = self._last[key]
        elapsed = (now - last_ts).total_seconds()
        if self._seconds > 0 and elapsed < self._seconds:
            return True
        if self._samples > 0 and (self._sample_counter - last_count) < self._samples:
            return True
        return False

    def record(self, service: str, pred_type: str, now: datetime) -> None:
        """Record that a prediction was emitted."""
        key = self._key(service, pred_type)
        self._last[key] = (now, self._sample_counter)
        self._sample_counter += 1

    def reset(self) -> None:
        self._last.clear()
        self._sample_counter = 0


class MetricPredictor:
    """Statistical metric predictor that processes MetricSample objects.

    For each incoming sample it:
      1. Stores the sample in a per-service rolling window (CPU, memory, latency).
      2. Runs z-score anomaly detection on all three metrics.
      3. Runs linear trend forecasting against configured thresholds.
      4. Evaluates OOM risk heuristic.

    Duplicate prediction events are suppressed via a per-service/per-type cooldown
    (default 30 seconds).

    Args:
        window_size:          Max samples per metric series per service.
        cpu_threshold:        CPU % threshold for breach prediction.
        memory_threshold:     Memory % threshold for breach prediction.
        anomaly_z_threshold:  Z-score magnitude to trigger anomaly (default 2.5).
        rules:                Custom PredictionRule instances; defaults to built-ins.
        cooldown_seconds:     Seconds to suppress duplicate predictions (default 30).
        cooldown_samples:     Sample count to suppress duplicates (0 = disabled).
    """

    def __init__(
        self,
        window_size: int = 100,
        cpu_threshold: float = 85.0,
        memory_threshold: float = 90.0,
        anomaly_z_threshold: float = 2.5,
        rules: tuple[PredictionRule, ...] | None = None,
        cooldown_seconds: float = 30.0,
        cooldown_samples: int = 0,
    ) -> None:
        self._window_size = window_size
        self._cpu_threshold = cpu_threshold
        self._memory_threshold = memory_threshold
        self._anomaly_z_threshold = anomaly_z_threshold
        self._rules: tuple[PredictionRule, ...] = rules or PredictionRules.BUILTIN_RULES
        # Per-service: {service_name: {"cpu": RollingWindow, "memory": ..., "latency": ...}}
        self._windows: dict[str, dict[str, RollingWindow]] = {}
        self._lock = asyncio.Lock()
        self._cooldown = _PredictionCooldown(
            seconds=cooldown_seconds, samples=cooldown_samples
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def process(self, sample: MetricSample) -> list[MetricPredictionEvent]:
        """Process a single MetricSample and return any prediction events.

        Async-safe via asyncio.Lock.  Returns zero or more
        MetricPredictionEvent instances.
        """
        async with self._lock:
            svc = sample.service_name
            if svc not in self._windows:
                self._windows[svc] = {
                    "cpu": RollingWindow(max_size=self._window_size),
                    "memory": RollingWindow(max_size=self._window_size),
                    "latency": RollingWindow(max_size=self._window_size),
                }

            windows = self._windows[svc]
            windows["cpu"].add(sample.cpu_usage)
            windows["memory"].add(sample.memory_usage)
            windows["latency"].add(sample.latency_ms)

            events: list[MetricPredictionEvent] = []
            now = sample.timestamp or datetime.now(timezone.utc)

            # 1. Anomaly detection via z-score
            events.extend(self._check_anomalies(svc, sample, now, windows))

            # 2. Threshold forecasting via linear trend
            events.extend(self._check_threshold_forecasts(svc, sample, now, windows))

            # 3. OOM risk heuristic
            events.extend(self._check_oom_risk(svc, sample, now, windows))

            # 4. Custom rules
            events.extend(self._evaluate_rules(svc, sample, now, windows))

            # 5. Apply cooldown — suppress duplicate predictions
            events = self._apply_cooldown(svc, events, now)

            return events

    # ------------------------------------------------------------------
    # Internal: cooldown
    # ------------------------------------------------------------------

    def _apply_cooldown(
        self,
        svc: str,
        events: list[MetricPredictionEvent],
        now: datetime,
    ) -> list[MetricPredictionEvent]:
        """Filter out events still within cooldown; record emitted ones."""
        result: list[MetricPredictionEvent] = []
        for event in events:
            if self._cooldown.is_cooldown_active(
                svc, event.prediction_type.value, now
            ):
                continue  # suppressed
            result.append(event)
            self._cooldown.record(svc, event.prediction_type.value, now)
        return result

    async def reset_service(self, service_name: str) -> None:
        """Clear all rolling windows for a specific service."""
        async with self._lock:
            self._windows.pop(service_name, None)

    async def reset_all(self) -> None:
        """Clear all rolling windows."""
        async with self._lock:
            self._windows.clear()

    async def reset_cooldown(self) -> None:
        """Clear all cooldown state."""
        async with self._lock:
            self._cooldown.reset()

    @property
    def cpu_threshold(self) -> float:
        return self._cpu_threshold

    @property
    def memory_threshold(self) -> float:
        return self._memory_threshold

    # ------------------------------------------------------------------
    # Internal: anomaly detection
    # ------------------------------------------------------------------

    def _check_anomalies(
        self,
        svc: str,
        sample: MetricSample,
        now: datetime,
        windows: dict[str, RollingWindow],
    ) -> list[MetricPredictionEvent]:
        """Check z-score anomaly detection for all three metrics."""
        events: list[MetricPredictionEvent] = []

        checks = [
            (MetricPredictionType.CPU_ANOMALY, "cpu", sample.cpu_usage, self._cpu_threshold),
            (MetricPredictionType.MEMORY_ANOMALY, "memory", sample.memory_usage, self._memory_threshold),
            (MetricPredictionType.LATENCY_ANOMALY, "latency", sample.latency_ms, 0.0),
        ]

        for pred_type, metric_key, value, thresh in checks:
            win = windows[metric_key]
            if win.size() < 3:
                continue  # Need at least 3 samples for meaningful z-score
            z = win.z_score(value)
            if abs(z) > self._anomaly_z_threshold:
                severity = MetricSeverity.HIGH if abs(z) > 3.5 else MetricSeverity.MEDIUM
                events.append(
                    MetricPredictionEvent(
                        timestamp=now,
                        service_name=svc,
                        prediction_type=pred_type,
                        severity=severity,
                        message=f"Anomalous {pred_type.value.replace('_', ' ').lower()} detected (z={z:.2f})",
                        current_value=value,
                        predicted_value=value,
                        threshold=thresh,
                        metadata={"z_score": f"{z:.2f}", "window_size": str(win.size())},
                    )
                )

        return events

    # ------------------------------------------------------------------
    # Internal: threshold forecasting
    # ------------------------------------------------------------------

    def _check_threshold_forecasts(
        self,
        svc: str,
        sample: MetricSample,
        now: datetime,
        windows: dict[str, RollingWindow],
    ) -> list[MetricPredictionEvent]:
        """Check linear trend forecasts against configured thresholds."""
        events: list[MetricPredictionEvent] = []

        # CPU threshold forecast
        cpu_win = windows["cpu"]
        if cpu_win.size() >= 5:
            predicted_cpu = cpu_win.forecast(steps=10)
            if predicted_cpu > self._cpu_threshold and sample.cpu_usage < self._cpu_threshold:
                severity = MetricSeverity.HIGH if predicted_cpu > self._cpu_threshold * 1.1 else MetricSeverity.MEDIUM
                events.append(
                    MetricPredictionEvent(
                        timestamp=now,
                        service_name=svc,
                        prediction_type=MetricPredictionType.PREDICTED_CPU_BREACH,
                        severity=severity,
                        message=f"CPU predicted to breach {self._cpu_threshold:.0f}% threshold (forecast: {predicted_cpu:.1f}%)",
                        current_value=sample.cpu_usage,
                        predicted_value=predicted_cpu,
                        threshold=self._cpu_threshold,
                        metadata={"forecast_steps": "10"},
                    )
                )

        # Memory threshold forecast
        mem_win = windows["memory"]
        if mem_win.size() >= 5:
            predicted_mem = mem_win.forecast(steps=10)
            if predicted_mem > self._memory_threshold and sample.memory_usage < self._memory_threshold:
                severity = MetricSeverity.HIGH if predicted_mem > self._memory_threshold * 1.1 else MetricSeverity.MEDIUM
                events.append(
                    MetricPredictionEvent(
                        timestamp=now,
                        service_name=svc,
                        prediction_type=MetricPredictionType.PREDICTED_MEMORY_BREACH,
                        severity=severity,
                        message=f"Memory predicted to breach {self._memory_threshold:.0f}% threshold (forecast: {predicted_mem:.1f}%)",
                        current_value=sample.memory_usage,
                        predicted_value=predicted_mem,
                        threshold=self._memory_threshold,
                        metadata={"forecast_steps": "10"},
                    )
                )

        return events

    # ------------------------------------------------------------------
    # Internal: OOM risk heuristic
    # ------------------------------------------------------------------

    def _check_oom_risk(
        self,
        svc: str,
        sample: MetricSample,
        now: datetime,
        windows: dict[str, RollingWindow],
    ) -> list[MetricPredictionEvent]:
        """Simple OOM risk heuristic.

        IF memory rising steadily AND memory near threshold AND latency increasing
        THEN emit PREDICTED_OOM.
        """
        events: list[MetricPredictionEvent] = []
        mem_win = windows["memory"]
        lat_win = windows["latency"]

        if mem_win.size() < 10 or lat_win.size() < 5:
            return events

        # Check memory is rising (positive slope)
        mem_slope, _ = mem_win.linear_trend(list(mem_win.values))
        if mem_slope <= 0:
            return events

        # Check memory is near threshold (> 80% of threshold)
        if sample.memory_usage < self._memory_threshold * 0.8:
            return events

        # Check latency is increasing (positive slope)
        lat_slope, _ = lat_win.linear_trend(list(lat_win.values))
        if lat_slope <= 0:
            return events

        severity = MetricSeverity.CRITICAL if sample.memory_usage > self._memory_threshold * 0.9 else MetricSeverity.HIGH
        predicted_oom = mem_win.forecast(steps=10)

        events.append(
            MetricPredictionEvent(
                timestamp=now,
                service_name=svc,
                prediction_type=MetricPredictionType.PREDICTED_OOM,
                severity=severity,
                message=f"OOM risk detected: memory rising ({mem_slope:.3f}/sample), "
                        f"latency increasing ({lat_slope:.3f}/sample), "
                        f"current={sample.memory_usage:.1f}%",
                current_value=sample.memory_usage,
                predicted_value=predicted_oom,
                threshold=self._memory_threshold,
                metadata={
                    "memory_slope": f"{mem_slope:.4f}",
                    "latency_slope": f"{lat_slope:.4f}",
                },
            )
        )

        return events

    # ------------------------------------------------------------------
    # Internal: custom rules evaluation
    # ------------------------------------------------------------------

    def _evaluate_rules(
        self,
        svc: str,
        sample: MetricSample,
        now: datetime,
        windows: dict[str, RollingWindow],
    ) -> list[MetricPredictionEvent]:
        """Evaluate any custom PredictionRule instances."""
        events: list[MetricPredictionEvent] = []
        for rule in self._rules:
            if not rule.evaluate(sample, windows):
                continue
            events.append(
                MetricPredictionEvent(
                    timestamp=now,
                    service_name=svc,
                    prediction_type=rule.prediction_type,
                    severity=rule.severity,
                    message=rule.message_template.format(
                        current=sample.cpu_usage if rule.metric == "cpu" else
                                sample.memory_usage if rule.metric == "memory" else
                                sample.latency_ms,
                        threshold=rule.threshold_value,
                    ),
                    current_value=(
                        sample.cpu_usage if rule.metric == "cpu" else
                        sample.memory_usage if rule.metric == "memory" else
                        sample.latency_ms
                    ),
                    predicted_value=0.0,
                    threshold=rule.threshold_value,
                )
            )
        return events
