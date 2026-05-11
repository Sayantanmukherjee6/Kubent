"""Heuristic-based incident prediction engine.

Deterministic, lightweight, bounded-memory predictor that tracks rolling
windows of IncidentEvent occurrences and emits PredictorEvent predictions
when heuristic thresholds are exceeded.

Supported patterns:
    - repeated_http_5xx:      Repeated HTTP 5xx errors
    - repeated_timeout:       Repeated timeout events
    - repeated_oomkilled:     Repeated OOMKilled events
    - repeated_conn_refused:  Repeated connection refused errors
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.core.predictor.models import PredictorEvent, RiskLevel
from src.core.watcher.models import IncidentEvent


# ---------------------------------------------------------------------------
# Heuristic rule definition
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HeuristicRule:
    """A single heuristic detection rule.

    Attributes:
        name:           Unique rule identifier.
        patterns:       Substring patterns to match against event_hash.
        threshold:      Number of occurrences in window to trigger.
        risk_level:     Predicted risk level when triggered.
        description:    Human-readable description for PredictorEvent.
    """

    name: str
    patterns: tuple[str, ...]
    threshold: int
    risk_level: RiskLevel
    description: str


# ---------------------------------------------------------------------------
# Per-service rolling window tracker
# ---------------------------------------------------------------------------

@dataclass
class _ServiceWindow:
    """Bounded deque tracking recent incident fingerprints per service."""

    max_size: int = 200
    _deque: deque = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._deque is None:
            object.__setattr__(self, '_deque', deque(maxlen=self.max_size))

    def push(self, fingerprint: str) -> None:
        self._deque.append(fingerprint)

    def count_matching(self, pattern: str) -> int:
        return sum(1 for fp in self._deque if pattern in fp)

    def clear(self) -> None:
        self._deque.clear()


# ---------------------------------------------------------------------------
# Heuristic predictor engine
# ---------------------------------------------------------------------------

class HeuristicPredictor:
    """Deterministic heuristic prediction engine over IncidentEvents.

    Uses a rolling-window approach with bounded memory (deque-based).
    Async-safe via asyncio.Lock.  No ML, no forecasting, no queues,
    no databases.

    Args:
        window_size:      Max events per service in the rolling window.
        rules:            Custom heuristic rules; defaults to built-ins.
    """

    # Built-in heuristic rules — deterministic, no randomness
    DEFAULT_RULES: tuple[HeuristicRule, ...] = (
        HeuristicRule(
            name="repeated_http_5xx",
            patterns=("HTTP5xx", "500 ", "502 ", "503 ", "504 "),
            threshold=3,
            risk_level=RiskLevel.HIGH,
            description="Repeated HTTP 5xx error spikes detected",
        ),
        HeuristicRule(
            name="repeated_timeout",
            patterns=("Timeout", "timed out", "deadline exceeded"),
            threshold=3,
            risk_level=RiskLevel.HIGH,
            description="Repeated timeout events detected",
        ),
        HeuristicRule(
            name="repeated_oomkilled",
            patterns=("OOMKilled", "OutOfMemoryKill", "OOM"),
            threshold=2,
            risk_level=RiskLevel.CRITICAL,
            description="Repeated OOMKilled events detected",
        ),
        HeuristicRule(
            name="repeated_conn_refused",
            patterns=("ConnectionRefused", "connection refused", "ECONNREFUSED"),
            threshold=3,
            risk_level=RiskLevel.HIGH,
            description="Repeated connection refused errors detected",
        ),
    )

    def __init__(
        self,
        window_size: int = 200,
        rules: tuple[HeuristicRule, ...] | None = None,
    ) -> None:
        self._window_size = window_size
        self._rules: tuple[HeuristicRule, ...] = rules or self.DEFAULT_RULES
        self._windows: dict[str, _ServiceWindow] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def process(self, incident: IncidentEvent) -> list[PredictorEvent]:
        """Process a single IncidentEvent and return any predictions.

        Async-safe via asyncio.Lock.  Returns zero or more PredictorEvents
        when heuristic thresholds are exceeded in the rolling window.
        """
        async with self._lock:
            svc = incident.service_name
            if svc not in self._windows:
                self._windows[svc] = _ServiceWindow(max_size=self._window_size)

            window = self._windows[svc]
            window.push(incident.error_type)

            predictions: list[PredictorEvent] = []
            now = datetime.now(timezone.utc)

            for rule in self._rules:
                count = self._count_matches(window, rule)
                if count >= rule.threshold:
                    predictions.append(
                        PredictorEvent(
                            timestamp=now,
                            service_name=svc,
                            risk_level=rule.risk_level,
                            pattern=rule.description,
                            trigger_count=count,
                            related_hash=incident.event_hash,
                        )
                    )

            return predictions

    async def reset_service(self, service_name: str) -> None:
        """Clear the rolling window for a specific service."""
        async with self._lock:
            self._windows.pop(service_name, None)

    async def reset_all(self) -> None:
        """Clear all rolling windows."""
        async with self._lock:
            self._windows.clear()

    @property
    def rules(self) -> tuple[HeuristicRule, ...]:
        """Read-only access to configured heuristic rules."""
        return self._rules

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _count_matches(window: _ServiceWindow, rule: HeuristicRule) -> int:
        """Count window entries matching any pattern in the rule."""
        total = 0
        for pat in rule.patterns:
            total += window.count_matching(pat)
        return total
