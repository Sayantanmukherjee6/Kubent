"""Scenario-based metric simulation for realistic demo demonstrations.

Provides deterministic, correlated metric scenarios that naturally trigger
predictor alerts: CPU/memory breach predictions, OOM risk, anomaly detection,
and latency degradation.

Scenarios are service-aware — the same scenario produces different metric
profiles depending on which service it targets.

Usage
-----

.. code-block:: python

    from src.core.metrics.scenarios import ScenarioEngine

    engine = ScenarioEngine(scenarios=["steady_cpu_growth", "memory_leak"])
    samples = engine.generate(service="payment-service", total_steps=50)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class _SvcState:
    """Per-service internal state for a single scenario."""
    cpu: float = 50.0
    memory: float = 50.0
    latency: float = 100.0
    error_rate: float = 0.01


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

class _ScenarioBase:
    """Base class for a metric scenario. Subclasses implement ``advance``."""

    name: str = "base"
    description: str = ""

    def advance(self, state: _SvcState, step: int) -> None:
        raise NotImplementedError


class SteadyCpuGrowth(_ScenarioBase):
    """CPU steadily climbs from ~40% toward 95%, triggering CPU breach predictions.

    Correlation: as CPU rises, latency increases proportionally.
    Typical for: gateway services under growing traffic load.
    """
    name = "steady_cpu_growth"
    description = ("CPU steadily grows from 40 to ~93%% over 60 steps; "
                   "latency correlates upward.")

    def advance(self, state: _SvcState, step: int) -> None:
        progress = min(step / 55.0, 1.0)  # reaches max at step 55
        target_cpu = 40.0 + progress * 53.0  # 40 → 93
        state.cpu = state.cpu * 0.7 + target_cpu * 0.3  # smooth convergence
        # Correlation: CPU ↑ → latency ↑
        base_lat = 80.0 + (state.cpu - 40.0) * 1.2
        state.latency = max(50.0, min(600.0, base_lat))
        state.error_rate = max(0.001, min(0.08, (state.cpu - 60.0) * 0.003))


class MemoryLeak(_ScenarioBase):
    """Memory slowly leaks from ~55% toward 95%, triggering OOM predictions.

    Correlation: memory ↑ → latency ↑ (GC pressure), error_rate ↑ near threshold.
    Typical for: auth-service with unbounded caches or session stores.
    """
    name = "memory_leak"
    description = ("Memory leaks from 55 to ~93%% over 60 steps; "
                   "OOM risk triggers when memory > 72%% + latency rising.")

    def advance(self, state: _SvcState, step: int) -> None:
        progress = min(step / 55.0, 1.0)
        target_mem = 55.0 + progress * 38.0  # 55 → 93
        state.memory = state.memory * 0.7 + target_mem * 0.3
        # Correlation: memory ↑ → latency ↑ (GC pressure)
        base_lat = 100.0 + (state.memory - 50.0) * 2.0
        state.latency = max(60.0, min(700.0, base_lat))
        # Error rate spikes near OOM threshold
        if state.memory > 80.0:
            state.error_rate = min(0.12, (state.memory - 80.0) * 0.01)


class LatencySpike(_ScenarioBase):
    """Intermittent latency spikes with brief recovery periods.

    Correlation: latency spikes → error_rate spikes simultaneously.
    Typical for: payment-service with downstream dependency timeouts.
    """
    name = "latency_spike"
    description = ("Latency spikes to 500-700ms every ~15 steps; "
                   "error_rate correlates during spikes.")

    def advance(self, state: _SvcState, step: int) -> None:
        cycle = step % 20
        if 5 <= cycle < 12:
            # Spike phase
            spike_intensity = math.sin((cycle - 5) / 7.0 * math.pi)
            target_lat = 100.0 + spike_intensity * 600.0
            state.latency = state.latency * 0.6 + target_lat * 0.4
            state.error_rate = min(0.15, spike_intensity * 0.12)
        else:
            # Recovery phase
            state.latency = state.latency * 0.85 + 80.0 * 0.15
            state.error_rate = max(0.005, state.error_rate * 0.7)
        # CPU slightly elevated during spikes
        state.cpu = max(20.0, min(80.0, 40.0 + (state.latency - 80.0) * 0.06))


class CascadingFailure(_ScenarioBase):
    """Cascading failure: one service fails → others degrade.

    Phase 1 (steps 0-10): normal operation.
    Phase 2 (steps 10-25): primary service degrades, latency rises.
    Phase 3 (steps 25-40): cascading — CPU/memory rise across services.
    Phase 4 (steps 40-55): recovery begins.

    Correlation: error_rate ↑ → latency ↑ → CPU ↑ (retry storms).
    Typical for: multi-service cascade when a dependency fails.
    """
    name = "cascading_failure"
    description = ("Multi-phase cascade: normal → degrade → cascade → recover.")

    def advance(self, state: _SvcState, step: int) -> None:
        if step < 10:
            # Phase 1: Normal
            state.cpu = state.cpu * 0.9 + 35.0 * 0.1
            state.memory = state.memory * 0.9 + 45.0 * 0.1
            state.latency = state.latency * 0.9 + 80.0 * 0.1
            state.error_rate = max(0.001, state.error_rate * 0.8)

        elif step < 25:
            # Phase 2: Degradation — latency and error_rate rise
            progress = (step - 10) / 15.0
            target_lat = 80.0 + progress * 400.0
            target_err = progress * 0.08
            state.latency = state.latency * 0.7 + target_lat * 0.3
            state.error_rate = max(state.error_rate, target_err)
            # CPU starts climbing due to retries
            state.cpu = min(85.0, 35.0 + progress * 30.0)

        elif step < 40:
            # Phase 3: Cascade — everything degrades
            progress = (step - 25) / 15.0
            target_cpu = 65.0 + progress * 25.0
            target_mem = 60.0 + progress * 30.0
            target_lat = 480.0 + progress * 200.0
            state.cpu = state.cpu * 0.7 + target_cpu * 0.3
            state.memory = state.memory * 0.7 + target_mem * 0.3
            state.latency = state.latency * 0.7 + target_lat * 0.3
            state.error_rate = min(0.15, 0.08 + progress * 0.07)

        else:
            # Phase 4: Recovery — gradual return to normal
            progress = min((step - 40) / 15.0, 1.0)
            state.cpu = state.cpu * (1.0 - progress * 0.6) + 35.0 * (progress * 0.6)
            state.memory = state.memory * (1.0 - progress * 0.5) + 45.0 * (progress * 0.5)
            state.latency = state.latency * (1.0 - progress * 0.7) + 80.0 * (progress * 0.7)
            state.error_rate = max(0.005, state.error_rate * (1.0 - progress * 0.8))


class RecoveryPhase(_ScenarioBase):
    """Post-incident recovery: metrics gradually return to healthy levels.

    Starts from elevated/degraded values and smoothly converges back to baseline.
    Useful for demonstrating that the predictor stops firing after remediation.

    Correlation: as latency ↓, error_rate ↓; CPU/memory stabilize.
    """
    name = "recovery_phase"
    description = ("Metrics recover from degraded state back to healthy baselines.")

    def advance(self, state: _SvcState, step: int) -> None:
        progress = min(step / 40.0, 1.0)
        # Convergence targets (healthy baselines)
        target_cpu = 35.0
        target_mem = 45.0
        target_lat = 80.0
        target_err = 0.005

        decay = 1.0 - progress ** 2  # quadratic recovery for realism
        state.cpu = state.cpu * decay + target_cpu * (1.0 - decay)
        state.memory = state.memory * decay + target_mem * (1.0 - decay)
        state.latency = state.latency * decay + target_lat * (1.0 - decay)
        state.error_rate = max(target_err, state.error_rate * decay)


# ---------------------------------------------------------------------------
# Scenario engine
# ---------------------------------------------------------------------------

# Default scenario assignments per service type for demo realism
DEFAULT_SERVICE_SCENARIOS: Dict[str, List[str]] = {
    "gateway": ["steady_cpu_growth"],
    "payment-service": ["latency_spike"],
    "auth-service": ["memory_leak"],
}

# All registered scenarios by name
ALL_SCENARIOS: Dict[str, _ScenarioBase] = {}
for _cls in (SteadyCpuGrowth, MemoryLeak, LatencySpike, CascadingFailure, RecoveryPhase):
    ALL_SCENARIOS[_cls.name] = _cls()


class ScenarioEngine:
    """Manages scenario-based metric generation for one or more services.

    Each service can have multiple scenarios active simultaneously. The engine
    advances all scenarios for a step and combines their effects additively
    (with clamping to realistic ranges).

    Args:
        scenarios: List of scenario names to activate. If empty, uses defaults.
        services: List of service names. If None, uses default services.
    """

    def __init__(self, scenarios: List[str] | None = None,
                 services: List[str] | None = None) -> None:
        self._services: List[str] = services or [
            "auth-service", "payment-service", "gateway",
            "inventory-service", "user-api", "order-processor",
        ]
        # Resolve scenarios: explicit list, or per-service defaults
        if scenarios:
            self._active_scenarios: List[_ScenarioBase] = []
            for s in scenarios:
                if s not in ALL_SCENARIOS:
                    raise ValueError(f"Unknown scenario: {s!r}. Available: {list(ALL_SCENARIOS.keys())}")
                self._active_scenarios.append(ALL_SCENARIOS[s])
        else:
            # Per-service defaults
            self._active_scenarios = []
            for svc in self._services:
                svc_scenarios = DEFAULT_SERVICE_SCENARIOS.get(svc, ["steady_cpu_growth"])
                for sname in svc_scenarios:
                    if sname in ALL_SCENARIOS:
                        self._active_scenarios.append(ALL_SCENARIOS[sname])

        # Per-service states keyed by (service, scenario_name) to allow multiple scenarios per service
        self._states: Dict[str, _SvcState] = {}
        self._step: int = 0

    def reset(self) -> None:
        """Reset all states and step counter."""
        self._states.clear()
        self._step = 0

    def get_state(self, service: str) -> _SvcState:
        """Get or create state for a service."""
        key = service
        if key not in self._states:
            self._states[key] = _SvcState()
        return self._states[key]

    def advance(self, service: str) -> _SvcState:
        """Advance all active scenarios for one step and return the combined state."""
        state = self.get_state(service)

        if len(self._active_scenarios) == 1:
            # Single scenario: use direct sub-state (no blending needed)
            scenario = self._active_scenarios[0]
            sub_key = f"{service}:{scenario.name}"
            sub_state = self._states.get(sub_key)
            if sub_state is None:
                sub_state = _SvcState()
                self._states[sub_key] = sub_state
            scenario.advance(sub_state, self._step)
            state.cpu = sub_state.cpu
            state.memory = sub_state.memory
            state.latency = sub_state.latency
            state.error_rate = sub_state.error_rate
        else:
            # Multiple scenarios: blend their effects
            for scenario in self._active_scenarios:
                sub_key = f"{service}:{scenario.name}"
                sub_state = self._states.get(sub_key)
                if sub_state is None:
                    sub_state = _SvcState()
                    self._states[sub_key] = sub_state

                orig_cpu, orig_mem, orig_lat, orig_err = (
                    sub_state.cpu, sub_state.memory, sub_state.latency, sub_state.error_rate
                )
                scenario.advance(sub_state, self._step)

                state.cpu += (sub_state.cpu - orig_cpu) * 0.3
                state.memory += (sub_state.memory - orig_mem) * 0.3
                state.latency += (sub_state.latency - orig_lat) * 0.3
                state.error_rate += max(0, sub_state.error_rate - orig_err)

        # Clamp to realistic ranges
        state.cpu = max(5.0, min(95.0, state.cpu))
        state.memory = max(30.0, min(95.0, state.memory))
        state.latency = max(20.0, min(800.0, state.latency))
        state.error_rate = max(0.0, min(0.15, state.error_rate))

        self._step += 1
        return state

    def get_step(self) -> int:
        return self._step

    @staticmethod
    def list_scenarios() -> List[str]:
        """Return all available scenario names."""
        return sorted(ALL_SCENARIOS.keys())

    @staticmethod
    def get_scenario_info(name: str) -> dict | None:
        """Return info dict for a scenario, or None if not found."""
        if name in ALL_SCENARIOS:
            s = ALL_SCENARIOS[name]
            return {"name": s.name, "description": s.description}
        return None
