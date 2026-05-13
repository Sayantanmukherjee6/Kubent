"""Mock metric source — generates realistic Kubernetes-style metrics asynchronously.

Supports two modes:
1. **Legacy random-walk mode** (default): trend-based random walk with sinusoidal modulation.
2. **Scenario mode**: deterministic, correlated scenarios that naturally trigger predictor alerts.

Scenario mode is activated by setting ``metrics.scenarios`` in config.yaml or via
the ``scenarios`` parameter on construction.

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
from datetime import datetime, timezone
from typing import Dict, List

from src.config.settings import Settings
from src.core.metrics.base import BaseMetricSource
from src.core.metrics.models import MetricSample
from src.core.metrics.scenarios import ScenarioEngine


class _ServiceState:
    """Internal tracking state for a single service's metric progression (legacy mode)."""

    def __init__(self) -> None:
        self.cpu: float = 50.0
        self.memory: float = 50.0
        self.latency: float = 100.0
        self.error_rate: float = 0.01
        self.cpu_trend: int = 1
        self.memory_trend: int = 1
        self.latency_trend: int = 1
        self.error_trend: int = 0
        self.step: int = 0


class MockMetricSource(BaseMetricSource):
    """Generates synthetic Kubernetes-style metrics and streams them.

    Two generation modes:

    **Scenario mode** (when ``settings.metrics.scenarios`` is non-empty):
        Uses deterministic, correlated scenarios from ``src.core.metrics.scenarios``.
        Each service gets scenario-driven metrics that naturally trigger predictor alerts.

    **Legacy mode** (default):
        Uses trend-based random walk with sinusoidal modulation.

    Lifecycle:
        1. ``start()`` — initializes service states or scenario engine, then enters a loop.
        2. ``stream()`` — yields ``MetricSample`` objects as they are generated.
        3. ``stop()`` — signals the background generator and streamer to exit.
    """

    def __init__(self, settings: Settings, scenarios: List[str] | None = None) -> None:
        self._settings = settings
        self._services: List[str] = list(settings.mock.services)
        self._interval: float = settings.metrics.stream_interval_seconds
        self._running = False
        self._queue: asyncio.Queue[MetricSample] = asyncio.Queue()

        # Determine mode
        config_scenarios = getattr(settings.metrics, "scenarios", None) or []
        if scenarios is not None:
            self._scenarios: List[str] = scenarios
        elif config_scenarios:
            self._scenarios = list(config_scenarios)
        else:
            self._scenarios = []

        # Initialize either scenario engine or legacy states
        if self._scenarios:
            self._engine = ScenarioEngine(
                scenarios=self._scenarios,
                services=self._services,
            )
            self._legacy_states: Dict[str, _ServiceState] = {}
        else:
            self._engine = None
            self._legacy_states: Dict[str, _ServiceState] = {}
            for svc in self._services:
                self._legacy_states[svc] = _ServiceState()

        self._generator_task: asyncio.Task[None] | None = None

    @property
    def name(self) -> str:
        if self._scenarios:
            return f"mock-metrics:{','.join(self._services)}[scenarios:{','.join(self._scenarios)}]"
        return f"mock-metrics:{','.join(self._services)}"

    async def start(self) -> None:
        """Initialize states and begin streaming."""
        if self._running:
            return

        self._running = True

        if self._engine is not None:
            self._engine.reset()
        else:
            for svc in self._services:
                if svc in self._legacy_states:
                    self._legacy_states[svc] = _ServiceState()

        self._generator_task = asyncio.create_task(self._background_generator())

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
        """Async generator that yields MetricSample objects."""
        # Produce initial samples for all services immediately
        for svc in self._services:
            sample = self._make_sample(svc)
            yield sample

        # Drain the queue while running
        while self._running:
            try:
                sample = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                yield sample
            except asyncio.TimeoutError:
                continue

    def _make_sample(self, svc: str) -> MetricSample:
        """Create a MetricSample from the current state of a service."""
        if self._engine is not None:
            state = self._engine.get_state(svc)
        else:
            state = self._legacy_states.get(svc)
            if state is None:
                return self._empty_sample(svc)

        ts = datetime.now(timezone.utc)
        return MetricSample(
            timestamp=ts,
            service_name=svc,
            cpu_usage=round(state.cpu, 2),
            memory_usage=round(state.memory, 2),
            latency_ms=round(state.latency, 2),
            error_rate=round(state.error_rate, 4),
            source=self.name,
        )

    @staticmethod
    def _empty_sample(svc: str) -> MetricSample:
        return MetricSample(
            timestamp=datetime.now(timezone.utc),
            service_name=svc,
            cpu_usage=50.0,
            memory_usage=50.0,
            latency_ms=100.0,
            error_rate=0.01,
            source="mock-metrics",
        )

    async def _background_generator(self) -> None:
        """Periodically advance metric states and push samples to the queue."""
        while self._running:
            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                return

            for svc in self._services:
                if self._engine is not None:
                    self._engine.advance(svc)
                else:
                    state = self._legacy_states.get(svc)
                    if state is not None:
                        self._advance_legacy(state)

                sample = self._make_sample(svc)
                await self._queue.put(sample)

    def _advance_legacy(self, state: _ServiceState) -> None:
        """Advance one service's metrics by one step (legacy random-walk mode)."""
        state.step += 1

        if state.step % 6 == 0:
            import random
            state.cpu_trend = random.choice([-1, 0, 1])
            state.memory_trend = random.choice([-1, 0, 1])
            state.latency_trend = random.choice([-1, 0, 1])
            state.error_trend = random.choice([-1, 0, 1])

        cpu_delta = state.cpu_trend * (2.0 + math.sin(state.step * 0.3) * 1.5)
        state.cpu = max(5.0, min(95.0, state.cpu + cpu_delta))

        mem_delta = state.memory_trend * (1.0 + math.sin(state.step * 0.2) * 0.8)
        state.memory = max(30.0, min(95.0, state.memory + mem_delta))

        lat_delta = state.latency_trend * (10.0 + math.sin(state.step * 0.4) * 15.0)
        state.latency = max(20.0, min(800.0, state.latency + lat_delta))

        err_delta = state.error_trend * (0.003 + math.sin(state.step * 0.25) * 0.005)
        state.error_rate = max(0.0, min(0.15, state.error_rate + err_delta))
