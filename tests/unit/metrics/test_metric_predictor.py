"""Unit tests for the statistical metric predictor subsystem.

Deterministic tests covering:
    - RollingWindow statistical methods (moving average, median, std_dev)
    - Z-score anomaly detection
    - Linear trend forecasting
    - Threshold prediction (CPU / memory breach)
    - OOM prediction heuristic
    - Rolling window bounded memory
    - Multi-service isolation
    - Prediction event generation
"""

from datetime import datetime, timezone
import statistics

import pytest

from src.core.metrics.events import (
    MetricPredictionEvent,
    MetricPredictionType,
    MetricSeverity,
)
from src.core.metrics.models import MetricSample
from src.core.metrics.predictor import MetricPredictor, RollingWindow
from src.core.metrics.rules import PredictionRule, PredictionRules


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sample(
    service: str = "test-svc",
    cpu: float = 50.0,
    memory: float = 60.0,
    latency: float = 100.0,
    error_rate: float = 0.01,
    ts: datetime | None = None,
) -> MetricSample:
    return MetricSample(
        timestamp=ts or datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        service_name=service,
        cpu_usage=cpu,
        memory_usage=memory,
        latency_ms=latency,
        error_rate=error_rate,
        source="test",
    )


# ---------------------------------------------------------------------------
# RollingWindow tests
# ---------------------------------------------------------------------------

class TestRollingWindow:
    """Tests for the RollingWindow class."""

    def test_add_and_size(self) -> None:
        win = RollingWindow(max_size=10)
        assert win.size() == 0
        win.add(1.0)
        win.add(2.0)
        assert win.size() == 2

    def test_bounded_memory(self) -> None:
        """Window should not grow beyond max_size."""
        win = RollingWindow(max_size=5)
        for i in range(20):
            win.add(float(i))
        assert win.size() == 5
        assert list(win.values) == [15.0, 16.0, 17.0, 18.0, 19.0]

    def test_moving_average_empty(self) -> None:
        assert RollingWindow.moving_average([], window=5) == 0.0

    def test_moving_average_fewer_than_window(self) -> None:
        vals = [10.0, 20.0, 30.0]
        assert RollingWindow.moving_average(vals, window=10) == 20.0

    def test_moving_average_exact_window(self) -> None:
        vals = [10.0, 20.0, 30.0, 40.0, 50.0]
        assert RollingWindow.moving_average(vals, window=5) == 30.0

    def test_moving_average_uses_recent(self) -> None:
        vals = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        # window=3 should use last 3: 8, 9, 10 -> mean = 9.0
        assert RollingWindow.moving_average(vals, window=3) == 9.0

    def test_median_empty(self) -> None:
        assert RollingWindow.median([]) == 0.0

    def test_median_odd(self) -> None:
        assert RollingWindow.median([1.0, 3.0, 5.0]) == 3.0

    def test_median_even(self) -> None:
        assert RollingWindow.median([1.0, 3.0]) == 2.0

    def test_std_dev_empty(self) -> None:
        assert RollingWindow.std_dev([]) == 0.0

    def test_std_dev_single(self) -> None:
        assert RollingWindow.std_dev([5.0]) == 0.0

    def test_std_dev_known(self) -> None:
        vals = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        # sample stdev of this known list
        assert abs(RollingWindow.std_dev(vals) - 2.138) < 0.01

    def test_z_score_zero_when_single_value(self) -> None:
        win = RollingWindow()
        win.add(50.0)
        assert win.z_score(50.0) == 0.0

    def test_z_score_high_value(self) -> None:
        """A value far from the median should have a high z-score."""
        win = RollingWindow()
        for _ in range(20):
            win.add(50.0)
        win.add(100.0)  # outlier
        z = win.z_score(100.0)
        assert abs(z) > 2.0

    def test_linear_trend_constant(self) -> None:
        vals = [5.0, 5.0, 5.0, 5.0]
        slope, intercept = RollingWindow.linear_trend(vals)
        assert slope == 0.0
        assert intercept == 5.0

    def test_linear_trend_increasing(self) -> None:
        vals = [10.0, 20.0, 30.0, 40.0, 50.0]
        slope, _ = RollingWindow.linear_trend(vals)
        assert slope > 0

    def test_linear_trend_decreasing(self) -> None:
        vals = [50.0, 40.0, 30.0, 20.0, 10.0]
        slope, _ = RollingWindow.linear_trend(vals)
        assert slope < 0

    def test_linear_trend_single(self) -> None:
        slope, intercept = RollingWindow.linear_trend([42.0])
        assert slope == 0.0
        assert intercept == 42.0

    def test_forecast_increasing(self) -> None:
        win = RollingWindow()
        for i in range(10):
            win.add(50.0 + i * 2.0)  # steadily increasing
        forecast = win.forecast(steps=5)
        assert forecast > list(win.values)[-1]

    def test_forecast_decreasing(self) -> None:
        win = RollingWindow()
        for i in range(10):
            win.add(90.0 - i * 2.0)  # steadily decreasing
        forecast = win.forecast(steps=5)
        assert forecast < list(win.values)[-1]

    def test_forecast_fewer_than_2(self) -> None:
        win = RollingWindow()
        win.add(50.0)
        result = win.forecast(steps=5)
        assert result == 50.0


# ---------------------------------------------------------------------------
# Z-score anomaly detection tests
# ---------------------------------------------------------------------------

class TestZScoreAnomalyDetection:
    """Tests for z-score based anomaly detection."""

    @pytest.mark.asyncio
    async def test_no_anomaly_with_stable_values(self) -> None:
        predictor = MetricPredictor(anomaly_z_threshold=2.5)
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i in range(20):
            sample = _make_sample(cpu=50.0 + (i % 3), memory=60.0, latency=100.0, ts=ts)
            events = await predictor.process(sample)
            anomaly_events = [e for e in events if "Anomalous" in e.message]
            # After many stable samples, no anomalies expected
            assert len(anomaly_events) == 0

    @pytest.mark.asyncio
    async def test_cpu_anomaly_detected(self) -> None:
        predictor = MetricPredictor(anomaly_z_threshold=2.5)
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # Feed stable values first
        for i in range(20):
            await predictor.process(_make_sample(cpu=50.0, memory=60.0, latency=100.0, ts=ts))
        # Now inject a massive spike
        events = await predictor.process(_make_sample(cpu=99.9, memory=60.0, latency=100.0, ts=ts))
        cpu_anomalies = [e for e in events if e.prediction_type == MetricPredictionType.CPU_ANOMALY]
        assert len(cpu_anomalies) >= 1

    @pytest.mark.asyncio
    async def test_memory_anomaly_detected(self) -> None:
        predictor = MetricPredictor(anomaly_z_threshold=2.5)
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i in range(20):
            await predictor.process(_make_sample(cpu=50.0, memory=60.0, latency=100.0, ts=ts))
        events = await predictor.process(_make_sample(cpu=50.0, memory=99.9, latency=100.0, ts=ts))
        mem_anomalies = [e for e in events if e.prediction_type == MetricPredictionType.MEMORY_ANOMALY]
        assert len(mem_anomalies) >= 1

    @pytest.mark.asyncio
    async def test_latency_anomaly_detected(self) -> None:
        predictor = MetricPredictor(anomaly_z_threshold=2.5)
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i in range(20):
            await predictor.process(_make_sample(cpu=50.0, memory=60.0, latency=100.0, ts=ts))
        events = await predictor.process(_make_sample(cpu=50.0, memory=60.0, latency=999.0, ts=ts))
        lat_anomalies = [e for e in events if e.prediction_type == MetricPredictionType.LATENCY_ANOMALY]
        assert len(lat_anomalies) >= 1

    @pytest.mark.asyncio
    async def test_no_anomaly_with_few_samples(self) -> None:
        """Z-score needs at least 3 samples."""
        predictor = MetricPredictor(anomaly_z_threshold=2.5)
        for i in range(2):
            events = await predictor.process(_make_sample(cpu=50.0, memory=60.0, latency=100.0))
            anomaly_events = [e for e in events if "Anomalous" in e.message]
            assert len(anomaly_events) == 0


# ---------------------------------------------------------------------------
# Threshold prediction tests
# ---------------------------------------------------------------------------

class TestThresholdPrediction:
    """Tests for CPU and memory threshold breach forecasting."""

    @pytest.mark.asyncio
    async def test_cpu_breach_prediction(self) -> None:
        predictor = MetricPredictor(
            cpu_threshold=85.0,
            memory_threshold=90.0,
            window_size=100,
        )
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # Feed steadily increasing CPU values (from 72 to ~84 over 25 samples)
        for i in range(25):
            cpu = 72.0 + i * 0.48  # ends at ~84.0
            await predictor.process(_make_sample(cpu=cpu, memory=50.0, latency=100.0, ts=ts))
        events = await predictor.process(_make_sample(cpu=84.0, memory=50.0, latency=100.0, ts=ts))
        cpu_breaches = [e for e in events if e.prediction_type == MetricPredictionType.PREDICTED_CPU_BREACH]
        assert len(cpu_breaches) >= 1

    @pytest.mark.asyncio
    async def test_memory_breach_prediction(self) -> None:
        predictor = MetricPredictor(
            cpu_threshold=85.0,
            memory_threshold=90.0,
            window_size=100,
        )
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # Feed steadily increasing memory values (from 75 to ~89 over 20 samples)
        for i in range(20):
            mem = 75.0 + i * 0.75  # ends at ~89.25
            await predictor.process(_make_sample(cpu=50.0, memory=mem, latency=100.0, ts=ts))
        events = await predictor.process(_make_sample(cpu=50.0, memory=88.0, latency=100.0, ts=ts))
        mem_breaches = [e for e in events if e.prediction_type == MetricPredictionType.PREDICTED_MEMORY_BREACH]
        assert len(mem_breaches) >= 1

    @pytest.mark.asyncio
    async def test_no_breach_when_below_threshold(self) -> None:
        predictor = MetricPredictor(cpu_threshold=85.0, memory_threshold=90.0)
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i in range(20):
            await predictor.process(_make_sample(cpu=30.0 + i * 0.5, memory=40.0, latency=100.0, ts=ts))
        events = await predictor.process(_make_sample(cpu=39.0, memory=40.0, latency=100.0, ts=ts))
        breaches = [e for e in events if "breach" in e.prediction_type.value.lower()]
        assert len(breaches) == 0

    @pytest.mark.asyncio
    async def test_no_breach_when_already_above(self) -> None:
        """Should not predict breach if already above threshold."""
        predictor = MetricPredictor(cpu_threshold=85.0, memory_threshold=90.0)
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i in range(20):
            await predictor.process(_make_sample(cpu=90.0, memory=50.0, latency=100.0, ts=ts))
        events = await predictor.process(_make_sample(cpu=91.0, memory=50.0, latency=100.0, ts=ts))
        cpu_breaches = [e for e in events if e.prediction_type == MetricPredictionType.PREDICTED_CPU_BREACH]
        assert len(cpu_breaches) == 0


# ---------------------------------------------------------------------------
# OOM prediction tests
# ---------------------------------------------------------------------------

class TestOomPrediction:
    """Tests for OOM risk heuristic."""

    @pytest.mark.asyncio
    async def test_oom_detected_with_rising_memory_and_latency(self) -> None:
        predictor = MetricPredictor(memory_threshold=90.0)
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # Feed rising memory (near threshold) + rising latency
        for i in range(15):
            mem = 73.0 + i * 1.0  # rises from 73 to 87
            lat = 100.0 + i * 5.0  # rises from 100 to 170
            await predictor.process(_make_sample(cpu=50.0, memory=mem, latency=lat, ts=ts))
        events = await predictor.process(_make_sample(cpu=50.0, memory=86.0, latency=175.0, ts=ts))
        oom_events = [e for e in events if e.prediction_type == MetricPredictionType.PREDICTED_OOM]
        assert len(oom_events) >= 1

    @pytest.mark.asyncio
    async def test_no_oom_when_memory_not_rising(self) -> None:
        predictor = MetricPredictor(memory_threshold=90.0)
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # Stable memory at high level
        for i in range(15):
            await predictor.process(_make_sample(cpu=50.0, memory=85.0, latency=100.0 + i * 2.0, ts=ts))
        events = await predictor.process(_make_sample(cpu=50.0, memory=85.0, latency=130.0, ts=ts))
        oom_events = [e for e in events if e.prediction_type == MetricPredictionType.PREDICTED_OOM]
        assert len(oom_events) == 0

    @pytest.mark.asyncio
    async def test_no_oom_when_memory_too_low(self) -> None:
        predictor = MetricPredictor(memory_threshold=90.0)
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i in range(15):
            mem = 50.0 + i * 1.0  # rises from 50 to 64 (below 80% of 90 = 72)
            lat = 100.0 + i * 5.0
            await predictor.process(_make_sample(cpu=50.0, memory=mem, latency=lat, ts=ts))
        events = await predictor.process(_make_sample(cpu=50.0, memory=64.0, latency=170.0, ts=ts))
        oom_events = [e for e in events if e.prediction_type == MetricPredictionType.PREDICTED_OOM]
        assert len(oom_events) == 0

    @pytest.mark.asyncio
    async def test_no_oom_when_latency_not_rising(self) -> None:
        predictor = MetricPredictor(memory_threshold=90.0)
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i in range(15):
            mem = 73.0 + i * 1.0
            lat = 100.0 - i * 2.0  # decreasing latency
            await predictor.process(_make_sample(cpu=50.0, memory=mem, latency=lat, ts=ts))
        events = await predictor.process(_make_sample(cpu=50.0, memory=86.0, latency=70.0, ts=ts))
        oom_events = [e for e in events if e.prediction_type == MetricPredictionType.PREDICTED_OOM]
        assert len(oom_events) == 0


# ---------------------------------------------------------------------------
# Multi-service isolation tests
# ---------------------------------------------------------------------------

class TestMultiServiceIsolation:
    """Tests that each service has independent rolling windows."""

    @pytest.mark.asyncio
    async def test_service_isolation(self) -> None:
        predictor = MetricPredictor(
            cpu_threshold=85.0,
            memory_threshold=90.0,
            window_size=100,
        )
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)

        # Service A: stable CPU at 30
        for i in range(25):
            await predictor.process(_make_sample(service="svc-a", cpu=30.0, memory=50.0, latency=100.0, ts=ts))

        # Service B: rising CPU toward threshold
        for i in range(25):
            cpu = 72.0 + i * 0.48
            await predictor.process(_make_sample(service="svc-b", cpu=cpu, memory=50.0, latency=100.0, ts=ts))

        # Check: svc-a should NOT have CPU breach predictions
        events_a = await predictor.process(_make_sample(service="svc-a", cpu=30.0, memory=50.0, latency=100.0, ts=ts))
        svc_a_breaches = [e for e in events_a if e.service_name == "svc-a" and "CPU" in e.prediction_type.value]
        assert len(svc_a_breaches) == 0

        # Check: svc-b SHOULD have CPU breach predictions
        events_b = await predictor.process(_make_sample(service="svc-b", cpu=84.0, memory=50.0, latency=100.0, ts=ts))
        svc_b_breaches = [e for e in events_b if e.service_name == "svc-b" and "CPU" in e.prediction_type.value]
        assert len(svc_b_breaches) >= 1

    @pytest.mark.asyncio
    async def test_reset_service(self) -> None:
        predictor = MetricPredictor(window_size=100)
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i in range(20):
            await predictor.process(_make_sample(service="svc-a", cpu=50.0, memory=60.0, latency=100.0, ts=ts))
        await predictor.reset_service("svc-a")
        assert "svc-a" not in predictor._windows

    @pytest.mark.asyncio
    async def test_reset_all(self) -> None:
        predictor = MetricPredictor(window_size=100)
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for svc in ["svc-a", "svc-b"]:
            for _ in range(5):
                await predictor.process(_make_sample(service=svc, cpu=50.0, memory=60.0, latency=100.0, ts=ts))
        assert len(predictor._windows) == 2
        await predictor.reset_all()
        assert len(predictor._windows) == 0


# ---------------------------------------------------------------------------
# Prediction event generation tests
# ---------------------------------------------------------------------------

class TestPredictionEventGeneration:
    """Tests for MetricPredictionEvent correctness."""

    @pytest.mark.asyncio
    async def test_event_has_correct_fields(self) -> None:
        predictor = MetricPredictor(
            cpu_threshold=85.0,
            memory_threshold=90.0,
            window_size=100,
        )
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)

        # Feed rising CPU to trigger breach prediction
        for i in range(25):
            await predictor.process(_make_sample(cpu=72.0 + i * 0.48, memory=50.0, latency=100.0, ts=ts))

        events = await predictor.process(_make_sample(cpu=84.0, memory=50.0, latency=100.0, ts=ts))
        cpu_breaches = [e for e in events if e.prediction_type == MetricPredictionType.PREDICTED_CPU_BREACH]

        assert len(cpu_breaches) >= 1
        event = cpu_breaches[0]
        assert isinstance(event, MetricPredictionEvent)
        assert event.service_name == "test-svc"
        assert event.threshold == 85.0
        assert event.current_value == pytest.approx(84.0, abs=0.1)
        assert isinstance(event.severity, MetricSeverity)
        assert isinstance(event.metadata, dict)

    @pytest.mark.asyncio
    async def test_event_severity_for_high_breach(self) -> None:
        predictor = MetricPredictor(cpu_threshold=85.0, memory_threshold=90.0, window_size=100)
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)

        for i in range(25):
            await predictor.process(_make_sample(cpu=72.0 + i * 0.48, memory=50.0, latency=100.0, ts=ts))

        events = await predictor.process(_make_sample(cpu=84.0, memory=50.0, latency=100.0, ts=ts))
        cpu_breaches = [e for e in events if e.prediction_type == MetricPredictionType.PREDICTED_CPU_BREACH]

        assert len(cpu_breaches) >= 1
        # predicted > 85 * 1.1 = 93.5 -> HIGH, otherwise MEDIUM
        assert cpu_breaches[0].severity in (MetricSeverity.MEDIUM, MetricSeverity.HIGH)

    @pytest.mark.asyncio
    async def test_oom_event_severity(self) -> None:
        predictor = MetricPredictor(memory_threshold=90.0, window_size=100)
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)

        for i in range(15):
            mem = 73.0 + i * 1.0
            lat = 100.0 + i * 5.0
            await predictor.process(_make_sample(cpu=50.0, memory=mem, latency=lat, ts=ts))

        events = await predictor.process(_make_sample(cpu=50.0, memory=86.0, latency=175.0, ts=ts))
        oom_events = [e for e in events if e.prediction_type == MetricPredictionType.PREDICTED_OOM]

        assert len(oom_events) >= 1
        # 86 < 90 * 0.9 = 81 -> False, so 86 > 81 -> CRITICAL
        assert oom_events[0].severity == MetricSeverity.CRITICAL

    @pytest.mark.asyncio
    async def test_no_events_for_normal_values(self) -> None:
        predictor = MetricPredictor()
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i in range(10):
            events = await predictor.process(_make_sample(cpu=50.0, memory=50.0, latency=100.0, ts=ts))
            assert len(events) == 0

    @pytest.mark.asyncio
    async def test_event_str_representation(self) -> None:
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        event = MetricPredictionEvent(
            timestamp=ts,
            service_name="test-svc",
            prediction_type=MetricPredictionType.PREDICTED_CPU_BREACH,
            severity=MetricSeverity.HIGH,
            message="CPU predicted to breach 85% threshold",
            current_value=80.0,
            predicted_value=92.0,
            threshold=85.0,
        )
        s = str(event)
        assert "PREDICTED_CPU_BREACH" in s
        assert "test-svc" in s
        assert "high" in s


# ---------------------------------------------------------------------------
# Rolling window bounded memory test (standalone)
# ---------------------------------------------------------------------------

class TestRollingWindowBoundedMemory:
    """Tests that rolling windows enforce bounded memory."""

    def test_window_respects_max_size(self) -> None:
        win = RollingWindow(max_size=3)
        win.add(1.0)
        win.add(2.0)
        win.add(3.0)
        win.add(4.0)  # should evict 1.0
        assert win.size() == 3
        assert list(win.values) == [2.0, 3.0, 4.0]

    def test_statistics_use_bounded_data(self) -> None:
        win = RollingWindow(max_size=5)
        for i in range(100):
            win.add(float(i))
        # Only last 5 values should be used
        assert win.size() == 5
        ma = win.moving_average(list(win.values), window=10)
        assert ma == statistics.mean([95.0, 96.0, 97.0, 98.0, 99.0])


# ---------------------------------------------------------------------------
# PredictionRule tests
# ---------------------------------------------------------------------------

class TestPredictionRules:
    """Tests for the PredictionRule and PredictionRules classes."""

    def test_high_cpu_rule_triggers(self) -> None:
        rule = PredictionRules.BUILTIN_RULES[0]  # high_cpu, threshold=95.0
        sample = _make_sample(cpu=96.0, memory=50.0, latency=100.0)
        win = RollingWindow()
        win.add(90.0)
        win.add(91.0)
        windows = {"cpu": win}
        assert rule.evaluate(sample, windows) is True

    def test_high_cpu_rule_does_not_trigger(self) -> None:
        rule = PredictionRules.BUILTIN_RULES[0]
        sample = _make_sample(cpu=80.0, memory=50.0, latency=100.0)
        win = RollingWindow()
        win.add(70.0)
        win.add(71.0)
        windows = {"cpu": win}
        assert rule.evaluate(sample, windows) is False

    def test_high_memory_rule_triggers(self) -> None:
        rule = PredictionRules.BUILTIN_RULES[1]  # high_memory, threshold=97.0
        sample = _make_sample(cpu=50.0, memory=98.0, latency=100.0)
        win = RollingWindow()
        win.add(95.0)
        win.add(96.0)
        windows = {"memory": win}
        assert rule.evaluate(sample, windows) is True

    def test_custom_condition_fn(self) -> None:
        def custom_fn(sample, windows):
            return sample.error_rate > 0.5

        rule = PredictionRule(
            name="custom",
            metric="cpu",
            prediction_type=MetricPredictionType.CPU_ANOMALY,
            severity=MetricSeverity.HIGH,
            threshold_value=0.0,
            message_template="Custom: {current:.1f}",
            condition_fn=custom_fn,
        )
        sample = _make_sample(error_rate=0.6)
        windows = {"cpu": RollingWindow()}
        assert rule.evaluate(sample, windows) is True

        sample_low_error = _make_sample(error_rate=0.1)
        assert rule.evaluate(sample_low_error, windows) is False


# ---------------------------------------------------------------------------
# MetricPredictionEvent tests
# ---------------------------------------------------------------------------

class TestMetricPredictionEvent:
    """Tests for the MetricPredictionEvent dataclass."""

    def test_frozen(self) -> None:
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        event = MetricPredictionEvent(
            timestamp=ts,
            service_name="svc",
            prediction_type=MetricPredictionType.CPU_ANOMALY,
            severity=MetricSeverity.MEDIUM,
            message="test",
            current_value=50.0,
            predicted_value=60.0,
            threshold=85.0,
        )
        with pytest.raises(Exception):
            event.service_name = "other"

    def test_all_prediction_types_exist(self) -> None:
        expected = {
            "PREDICTED_CPU_BREACH",
            "PREDICTED_MEMORY_BREACH",
            "PREDICTED_OOM",
            "CPU_ANOMALY",
            "MEMORY_ANOMALY",
            "LATENCY_ANOMALY",
        }
        actual = {e.value for e in MetricPredictionType}
        assert actual == expected

    def test_all_severity_levels_exist(self) -> None:
        expected = {"low", "medium", "high", "critical"}
        actual = {s.value for s in MetricSeverity}
        assert actual == expected
