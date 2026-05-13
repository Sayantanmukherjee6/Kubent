"""Mock metric source — generates realistic Kubernetes-style metrics asynchronously.

Simulates CPU, memory, latency, and error-rate metrics for multiple services.
Metrics naturally trend upward or downward over time to simulate real workload
patterns.

Usage
-----

.. code-block:: python

    from src.config.settings import Settings
    from src.core.metrics.factory import create_metric_source

    settings = Settings()
    source = create_metric_source(settings)
    await source.start()
    async for sample in source.stream():
        print(sample.service_name, sample.cpu_usage)
    await source.stop()
"""

from __future__ import annotations

import asyncio
import math
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List

from src.config.settings import Settings
from src.core.metrics.base import BaseMetricSource
from src.core.metrics.models import MetricSample


@dataclass
class _ServiceState:
    """Internal tracking state for a single service's metric progression."""

    cpu: float = 50.0
    memory: float = 50.0
    latency: float = 100.0
    error_rate: float = 0.01
    # Trend direction per metric (-1 = downward, 0 = neutral, 1 = upward)
    cpu_trend: int = 1
    memory_trend: int = 1
    latency_trend: int = 1
    error_trend: int = 0
    # Step counter for deterministic progression
    step: int = 0


class MockMetricSource(BaseMetricSource):
    """Generates synthetic Kubernetes-style metrics and streams them.

    Lifecycle:
        1. ``start()`` — initializes service states, then enters a loop that
           periodically generates metric samples for all configured services.
        2. ``stream()`` — yields ``MetricSample`` objects as they are generated.
           Runs until ``stop()`` is called.
        3. ``stop()`` — signals the background generator and streamer to exit.

    Metric behavior:
        - Each service has independent CPU, memory, latency, and error-rate values.
        - Values naturally trend upward or downward using a simple random-walk
          with momentum (trends persist for several steps before flipping).
        - Values are clamped to realistic ranges:
            * CPU: 5-95%
            * Memory: 30-95%
            * Latency: 20-800ms
            * Error rate: 0.0-0.15 (0-15%)
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._services: List[str] = list(settings.mock.services)
        self._interval: float = getattr(settings, "mock_log_interval", 1.0)
        self._running = False
        self._queue: asyncio.Queue[MetricSample] = asyncio.Queue()
        self._generator_task: asyncio.Task[None] | None = None
        # Per-service state
        self._states: Dict[str, _ServiceState] = {}
        for svc in self._services:
            self._states[svc] = _ServiceState()

    @property
    def name(self) -> str:
        return f"mock-metrics:{','.join(self._services)}"

    async def start(self) -> None:
        """Initialize service states and begin streaming."""
        if self._running:
            return

        self._running = True
        # Reset all states to defaults
        for svc in self._services:
            self._states[svc] = _ServiceState()

        self._generator_task = asyncio.create_task(
            self._background_generator(),
        )

    async def stop(self) -> None:
        """Stop streaming and clean up."""
        self._running = False
        if self._generator_task is not None:
            self._generator_task.cancel()
            try:
                await self._generator_task
            except asyncio.CancelledError:
                pass
            self._generator_task = None

    async def stream(self):
        """Async generator that yields MetricSample objects.

        Samples are produced by the background generator task and placed
        into an internal queue. This generator drains the queue, yielding
        each sample as it arrives.
        """
        # Produce initial samples for all services immediately
        for svc in self._services:
            state = self._states[svc]
            ts = datetime.now(timezone.utc)
            sample = MetricSample(
                timestamp=ts,
                service_name=svc,
                cpu_usage=round(state.cpu, 2),
                memory_usage=round(state.memory, 2),
                latency_ms=round(state.latency, 2),
                error_rate=round(state.error_rate, 4),
                source=self.name,
            )
            yield sample

        # Drain the queue while running
        while self._running:
            try:
                sample = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                yield sample
            except asyncio.TimeoutError:
                continue

    async def _background_generator(self) -> None:
        """Periodically advance metric states and push samples to the queue."""
        while self._running:
            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                return

            for svc in self._services:
                state = self._states[svc]
                self._advance_state(state)
                ts = datetime.now(timezone.utc)
                sample = MetricSample(
                    timestamp=ts,
                    service_name=svc,
                    cpu_usage=round(state.cpu, 2),
                    memory_usage=round(state.memory, 2),
                    latency_ms=round(state.latency, 2),
                    error_rate=round(state.error_rate, 4),
                    source=self.name,
                )
                await self._queue.put(sample)

    def _advance_state(self, state: _ServiceState) -> None:
        """Advance one service's metrics by one step using trend-based random walk."""
        state.step += 1

        # Flip trends periodically (every 6 steps) for natural-looking patterns
        if state.step % 6 == 0:
            state.cpu_trend = random.choice([-1, 0, 1])
            state.memory_trend = random.choice([-1, 0, 1])
            state.latency_trend = random.choice([-1, 0, 1])
            state.error_trend = random.choice([-1, 0, 1])

        # CPU: realistic range 5-95%
        cpu_delta = state.cpu_trend * (2.0 + math.sin(state.step * 0.3) * 1.5)
        state.cpu = max(5.0, min(95.0, state.cpu + cpu_delta))

        # Memory: slower changes, range 30-95%
        mem_delta = state.memory_trend * (1.0 + math.sin(state.step * 0.2) * 0.8)
        state.memory = max(30.0, min(95.0, state.memory + mem_delta))

        # Latency: more volatile, range 20-800ms
        lat_delta = state.latency_trend * (10.0 + math.sin(state.step * 0.4) * 15.0)
        state.latency = max(20.0, min(800.0, state.latency + lat_delta))

        # Error rate: small changes, range 0.0-0.15
        err_delta = state.error_trend * (0.003 + math.sin(state.step * 0.25) * 0.005)
        state.error_rate = max(0.0, min(0.15, state.error_rate + err_delta))
