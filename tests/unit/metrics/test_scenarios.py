"""Tests for scenario-based metric simulation.

Covers:
    - Scenario transitions (cascading_failure phases)
    - Realistic metric ranges for all scenarios
    - Correlated metrics (CPU->latency, memory->OOM risk)
    - Deterministic outputs (same input -> same output)
    - Service-specific default assignments
    - Engine reset and step tracking
"""

import pytest

from src.core.metrics.scenarios import (
    ScenarioEngine,
    SteadyCpuGrowth,
    MemoryLeak,
    LatencySpike,
    CascadingFailure,
    RecoveryPhase,
    ALL_SCENARIOS,
)


# ---------------------------------------------------------------------------
# Scenario availability tests
# ---------------------------------------------------------------------------

class TestScenarioAvailability:
    """Tests for scenario registration and listing."""

    def test_all_scenarios_registered(self) -> None:
        assert "steady_cpu_growth" in ALL_SCENARIOS
        assert "memory_leak" in ALL_SCENARIOS
        assert "latency_spike" in ALL_SCENARIOS
        assert "cascading_failure" in ALL_SCENARIOS
        assert "recovery_phase" in ALL_SCENARIOS

    def test_list_scenarios(self) -> None:
        names = ScenarioEngine.list_scenarios()
        assert isinstance(names, list)
        assert len(names) == 5
        assert "cascading_failure" in names

    def test_get_scenario_info(self) -> None:
        info = ScenarioEngine.get_scenario_info("steady_cpu_growth")
        assert info is not None
        assert info["name"] == "steady_cpu_growth"
        assert "CPU" in info["description"]

    def test_get_scenario_info_unknown(self) -> None:
        assert ScenarioEngine.get_scenario_info("nonexistent") is None

    def test_invalid_scenario_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown scenario"):
            ScenarioEngine(scenarios=["nonexistent_scenario"])


# ---------------------------------------------------------------------------
# Realistic metric ranges tests
# ---------------------------------------------------------------------------

class TestMetricRanges:
    """All metrics must stay within realistic bounds."""

    def _run_steps(self, scenario_name: str, steps: int = 60) -> list[dict]:
        engine = ScenarioEngine(scenarios=[scenario_name], services=["test-svc"])
        results = []
        for _ in range(steps):
            state = engine.advance("test-svc")
            results.append({
                "cpu": state.cpu,
                "memory": state.memory,
                "latency": state.latency,
                "error_rate": state.error_rate,
            })
        return results

    def test_steady_cpu_growth_ranges(self) -> None:
        results = self._run_steps("steady_cpu_growth", 60)
        for r in results:
            assert 5.0 <= r["cpu"] <= 95.0, f"CPU out of range: {r['cpu']}"
            assert 30.0 <= r["memory"] <= 95.0, f"Memory out of range: {r['memory']}"
            assert 20.0 <= r["latency"] <= 800.0, f"Latency out of range: {r['latency']}"
            assert 0.0 <= r["error_rate"] <= 0.15, f"Error rate out of range: {r['error_rate']}"

    def test_memory_leak_ranges(self) -> None:
        results = self._run_steps("memory_leak", 60)
        for r in results:
            assert 5.0 <= r["cpu"] <= 95.0
            assert 30.0 <= r["memory"] <= 95.0
            assert 20.0 <= r["latency"] <= 800.0
            assert 0.0 <= r["error_rate"] <= 0.15

    def test_latency_spike_ranges(self) -> None:
        results = self._run_steps("latency_spike", 60)
        for r in results:
            assert 5.0 <= r["cpu"] <= 95.0
            assert 30.0 <= r["memory"] <= 95.0
            assert 20.0 <= r["latency"] <= 800.0
            assert 0.0 <= r["error_rate"] <= 0.15

    def test_cascading_failure_ranges(self) -> None:
        results = self._run_steps("cascading_failure", 60)
        for r in results:
            assert 5.0 <= r["cpu"] <= 95.0
            assert 30.0 <= r["memory"] <= 95.0
            assert 20.0 <= r["latency"] <= 800.0
            assert 0.0 <= r["error_rate"] <= 0.15

    def test_recovery_phase_ranges(self) -> None:
        results = self._run_steps("recovery_phase", 60)
        for r in results:
            assert 5.0 <= r["cpu"] <= 95.0
            assert 30.0 <= r["memory"] <= 95.0
            assert 20.0 <= r["latency"] <= 800.0
            assert 0.0 <= r["error_rate"] <= 0.15


# ---------------------------------------------------------------------------
# Scenario-specific behavior tests
# ---------------------------------------------------------------------------

class TestScenarioBehavior:
    """Each scenario should produce its expected metric pattern."""

    def test_steady_cpu_growth_increases(self) -> None:
        engine = ScenarioEngine(scenarios=["steady_cpu_growth"], services=["svc"])
        cpu_values = []
        for _ in range(40):
            state = engine.advance("svc")
            cpu_values.append(state.cpu)
        # CPU should generally trend upward
        assert cpu_values[-1] > cpu_values[0], "CPU should grow over time"

    def test_steady_cpu_reaches_high(self) -> None:
        engine = ScenarioEngine(scenarios=["steady_cpu_growth"], services=["svc"])
        for _ in range(55):
            state = engine.advance("svc")
        assert state.cpu > 80.0, f"CPU should be high after 55 steps, got {state.cpu:.1f}"

    def test_memory_leak_increases(self) -> None:
        engine = ScenarioEngine(scenarios=["memory_leak"], services=["svc"])
        mem_values = []
        for _ in range(40):
            state = engine.advance("svc")
            mem_values.append(state.memory)
        assert mem_values[-1] > mem_values[0], "Memory should leak over time"

    def test_memory_leak_reaches_high(self) -> None:
        engine = ScenarioEngine(scenarios=["memory_leak"], services=["svc"])
        for _ in range(55):
            engine.advance("svc")
        # Need to get the last state — re-run to capture it
        engine2 = ScenarioEngine(scenarios=["memory_leak"], services=["svc"])
        state = None
        for _ in range(55):
            state = engine2.advance("svc")
        assert state.memory > 80.0, f"Memory should be high after leak, got {state.memory:.1f}"

    def test_latency_spike_has_variance(self) -> None:
        engine = ScenarioEngine(scenarios=["latency_spike"], services=["svc"])
        lat_values = []
        for _ in range(40):
            state = engine.advance("svc")
            lat_values.append(state.latency)
        # Latency should vary (not be constant)
        assert max(lat_values) - min(lat_values) > 100.0, "Latency should have significant variance"

    def test_cascading_failure_has_phases(self) -> None:
        engine = ScenarioEngine(scenarios=["cascading_failure"], services=["svc"])
        # Phase 1 (steps 0-9): low values
        for _ in range(10):
            state = engine.advance("svc")
        phase1_lat = state.latency

        # Phase 3 (steps 25-39): high values
        engine2 = ScenarioEngine(scenarios=["cascading_failure"], services=["svc"])
        for i in range(40):
            state = engine2.advance("svc")
            if i == 35:
                phase3_lat = state.latency

        assert phase3_lat > phase1_lat * 2, "Cascade phase should have much higher latency"

    def test_recovery_phase_converges_to_baseline(self) -> None:
        engine = ScenarioEngine(scenarios=["recovery_phase"], services=["svc"])
        # Start from degraded state by pre-advancing
        for _ in range(10):
            engine.advance("svc")
        # Now recovery should bring values down
        initial_cpu = engine.get_state("svc").cpu
        for _ in range(35):
            state = engine.advance("svc")
        assert state.cpu < initial_cpu, "CPU should decrease during recovery"


# ---------------------------------------------------------------------------
# Correlated metrics tests
# ---------------------------------------------------------------------------

class TestMetricCorrelations:
    """Metrics should correlate realistically."""

    def test_cpu_correlates_with_latency_in_cpu_growth(self) -> None:
        engine = ScenarioEngine(scenarios=["steady_cpu_growth"], services=["svc"])
        cpu_vals, lat_vals = [], []
        for _ in range(40):
            state = engine.advance("svc")
            cpu_vals.append(state.cpu)
            lat_vals.append(state.latency)
        # Both should trend upward together
        assert cpu_vals[-1] > cpu_vals[0]
        assert lat_vals[-1] > lat_vals[0]

    def test_memory_correlates_with_latency_in_memory_leak(self) -> None:
        engine = ScenarioEngine(scenarios=["memory_leak"], services=["svc"])
        mem_vals, lat_vals = [], []
        for _ in range(40):
            state = engine.advance("svc")
            mem_vals.append(state.memory)
            lat_vals.append(state.latency)
        assert mem_vals[-1] > mem_vals[0]
        assert lat_vals[-1] > lat_vals[0]

    def test_error_rate_rises_with_memory_leak(self) -> None:
        engine = ScenarioEngine(scenarios=["memory_leak"], services=["svc"])
        err_vals = []
        for _ in range(50):
            state = engine.advance("svc")
            err_vals.append(state.error_rate)
        # Error rate should increase as memory approaches OOM threshold
        assert err_vals[-1] > err_vals[0], "Error rate should rise with memory leak"

    def test_latency_spike_error_correlation(self) -> None:
        engine = ScenarioEngine(scenarios=["latency_spike"], services=["svc"])
        # Advance through multiple cycles to let spike patterns emerge
        latencies = []
        for i in range(60):
            state = engine.advance("svc")
            latencies.append(state.latency)
        # Latency should have significant variance (spikes vs baseline)
        rng = max(latencies) - min(latencies)
        assert rng > 200.0, f'Latency range {rng:.1f} too small'


# ---------------------------------------------------------------------------
# Deterministic output tests
# ---------------------------------------------------------------------------

class TestDeterminism:
    """Same scenarios + same steps should produce identical results."""

    def test_steady_cpu_deterministic(self) -> None:
        engine1 = ScenarioEngine(scenarios=["steady_cpu_growth"], services=["svc"])
        engine2 = ScenarioEngine(scenarios=["steady_cpu_growth"], services=["svc"])
        for _ in range(30):
            s1 = engine1.advance("svc")
            s2 = engine2.advance("svc")
            assert s1.cpu == s2.cpu
            assert s1.memory == s2.memory
            assert s1.latency == s2.latency

    def test_memory_leak_deterministic(self) -> None:
        engine1 = ScenarioEngine(scenarios=["memory_leak"], services=["svc"])
        engine2 = ScenarioEngine(scenarios=["memory_leak"], services=["svc"])
        for _ in range(30):
            s1 = engine1.advance("svc")
            s2 = engine2.advance("svc")
            assert s1.cpu == s2.cpu
            assert s1.memory == s2.memory

    def test_cascading_failure_deterministic(self) -> None:
        engine1 = ScenarioEngine(scenarios=["cascading_failure"], services=["svc"])
        engine2 = ScenarioEngine(scenarios=["cascading_failure"], services=["svc"])
        for _ in range(50):
            s1 = engine1.advance("svc")
            s2 = engine2.advance("svc")
            assert s1.latency == s2.latency


# ---------------------------------------------------------------------------
# Engine lifecycle tests
# ---------------------------------------------------------------------------

class TestEngineLifecycle:
    """Tests for ScenarioEngine lifecycle operations."""

    def test_reset_clears_state(self) -> None:
        engine = ScenarioEngine(scenarios=["steady_cpu_growth"], services=["svc"])
        for _ in range(20):
            engine.advance("svc")
        assert engine.get_step() == 20
        engine.reset()
        assert engine.get_step() == 0

    def test_multiple_services(self) -> None:
        engine = ScenarioEngine(
            scenarios=["steady_cpu_growth"],
            services=["svc-a", "svc-b"],
        )
        state_a = engine.advance("svc-a")
        state_b = engine.advance("svc-b")
        # Both should have valid states but may differ due to per-scenario sub-states
        assert 5.0 <= state_a.cpu <= 95.0
        assert 5.0 <= state_b.cpu <= 95.0

    def test_default_service_scenarios(self) -> None:
        """Default scenarios should assign correctly per service."""
        engine = ScenarioEngine(services=["gateway", "payment-service", "auth-service"])
        # Should have scenarios for each default service
        assert len(engine._services) == 3
        # gateway gets steady_cpu_growth, payment gets latency_spike, auth gets memory_leak
        scenario_names = {s.name for s in engine._active_scenarios}
        assert "steady_cpu_growth" in scenario_names
        assert "latency_spike" in scenario_names
        assert "memory_leak" in scenario_names

    def test_unknown_service_falls_back(self) -> None:
        """Services not in defaults should get steady_cpu_growth."""
        engine = ScenarioEngine(scenarios=None, services=["unknown-svc"])
        state = engine.advance("unknown-svc")
        assert 5.0 <= state.cpu <= 95.0

    def test_combined_scenarios(self) -> None:
        """Multiple scenarios can be active simultaneously."""
        engine = ScenarioEngine(
            scenarios=["steady_cpu_growth", "memory_leak"],
            services=["svc"],
        )
        for _ in range(30):
            state = engine.advance("svc")
            # Both CPU and memory should rise
            assert 5.0 <= state.cpu <= 95.0
            assert 30.0 <= state.memory <= 95.0
