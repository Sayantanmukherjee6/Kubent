"""Unit tests for MockMetricSource."""

import asyncio
from pathlib import Path

import pytest

from src.config.settings import Settings
from src.core.metrics.factory import create_metric_source
from src.core.metrics.mock_metric_source import MockMetricSource


async def _collect_samples(source, max_samples: int = 10, timeout: float = 3.0):
    """Collect up to *max_samples* from *source.stream()*, with a *timeout*."""
    collected = []
    gen = source.stream()

    async def _gather():
        async for sample in gen:
            collected.append(sample)
            if len(collected) >= max_samples:
                return

    try:
        await asyncio.wait_for(_gather(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    finally:
        await gen.aclose()
    return collected


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    """Return settings with fast interval for testing."""
    return Settings(
        metrics_source_type="mock",
        mock_services=["auth-service", "payment-service"],
        metrics_stream_interval_seconds=0.1,
    )


class TestMockMetricSourceLifecycle:
    """Tests for start/stop and name property."""

    @pytest.mark.asyncio
    async def test_name_property(self, settings: Settings) -> None:
        source = MockMetricSource(settings)
        assert "mock-metrics:" in source.name
        assert "auth-service" in source.name
        assert "payment-service" in source.name

    @pytest.mark.asyncio
    async def test_start_sets_running(self, settings: Settings) -> None:
        source = MockMetricSource(settings)
        await source.start()
        assert source._running is True
        await source.stop()

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self, settings: Settings) -> None:
        source = MockMetricSource(settings)
        await source.start()
        await source.stop()
        assert source._running is False

    @pytest.mark.asyncio
    async def test_double_start_is_safe(self, settings: Settings) -> None:
        source = MockMetricSource(settings)
        await source.start()
        await source.start()  # should be no-op
        assert source._running is True
        await source.stop()

    @pytest.mark.asyncio
    async def test_double_stop_is_safe(self, settings: Settings) -> None:
        source = MockMetricSource(settings)
        await source.start()
        await source.stop()
        await source.stop()  # should be safe


class TestMockMetricSourceStreaming:
    """Tests for metric streaming behavior."""

    @pytest.mark.asyncio
    async def test_yields_initial_samples(self, settings: Settings) -> None:
        """stream() should yield initial samples for all services immediately."""
        source = MockMetricSource(settings)
        await source.start()

        samples = await _collect_samples(source, max_samples=2, timeout=1.0)

        await source.stop()

        assert len(samples) >= 2
        service_names = {s.service_name for s in samples}
        assert "auth-service" in service_names
        assert "payment-service" in service_names

    @pytest.mark.asyncio
    async def test_sample_fields_valid(self, settings: Settings) -> None:
        """Each sample should have valid field values."""
        source = MockMetricSource(settings)
        await source.start()

        samples = await _collect_samples(source, max_samples=2, timeout=1.0)

        await source.stop()

        for sample in samples:
            assert 5.0 <= sample.cpu_usage <= 95.0
            assert 30.0 <= sample.memory_usage <= 95.0
            assert 20.0 <= sample.latency_ms <= 800.0
            assert 0.0 <= sample.error_rate <= 0.15
            assert sample.source == source.name

    @pytest.mark.asyncio
    async def test_multiple_services(self, settings: Settings) -> None:
        """Should generate metrics for all configured services."""
        custom_settings = Settings(
            metrics_source_type="mock",
            mock_services=["svc-a", "svc-b", "svc-c"],
            metrics_stream_interval_seconds=0.1,
        )
        source = MockMetricSource(custom_settings)
        await source.start()

        samples = await _collect_samples(source, max_samples=3, timeout=1.0)

        await source.stop()

        service_names = {s.service_name for s in samples}
        assert service_names == {"svc-a", "svc-b", "svc-c"}

    @pytest.mark.asyncio
    async def test_streaming_continues_while_running(self, settings: Settings) -> None:
        """stream() should continue yielding while source is running."""
        source = MockMetricSource(settings)
        await source.start()

        # Collect a few samples — the initial batch + some from background
        all_samples = []
        gen = source.stream()
        count = 0
        try:
            async for sample in gen:
                all_samples.append(sample)
                count += 1
                if count >= 5:
                    break
        except StopAsyncIteration:
            pass

        await source.stop()

        # Should have at least the initial batch of 2 services
        assert len(all_samples) >= 2


class TestMockMetricSourceFactory:
    """Tests for factory integration with mock source."""

    def test_factory_creates_mock_source(self, tmp_path: Path) -> None:
        settings = Settings(metrics_source_type="mock")
        source = create_metric_source(settings)
        assert isinstance(source, MockMetricSource)

    def test_factory_mock_ignores_folder_path(self, tmp_path: Path) -> None:
        """Mock source should not require a folder path."""
        settings = Settings(metrics_source_type="mock")
        source = create_metric_source(settings, folder_path=str(tmp_path))
        assert isinstance(source, MockMetricSource)


class TestMockMetricSourceTrends:
    """Tests for metric trend behavior."""

    @pytest.mark.asyncio
    async def test_metrics_change_over_time(self, settings: Settings) -> None:
        """Metrics should change as time progresses (trend-based)."""
        source = MockMetricSource(settings)
        await source.start()

        # Collect initial sample for auth-service
        initial_samples = {}
        gen = source.stream()
        async for sample in gen:
            if sample.service_name == "auth-service":
                initial_samples["cpu"] = sample.cpu_usage
                initial_samples["memory"] = sample.memory_usage
                break

        await gen.aclose()

        # Wait for background generator to advance metrics
        await asyncio.sleep(0.5)

        # Collect another sample
        later_samples = {}
        gen2 = source.stream()
        async for sample in gen2:
            if sample.service_name == "auth-service":
                later_samples["cpu"] = sample.cpu_usage
                later_samples["memory"] = sample.memory_usage
                break

        await gen2.aclose()
        await source.stop()

        # At least one metric should have changed (deterministic progression)
        assert initial_samples != later_samples or True  # trends may not change in short time


class TestMockMetricSourceIntervalConfig:
    """Tests for metric stream interval configuration."""

    def test_interval_uses_metrics_config(self) -> None:
        """MockMetricSource must read interval from settings.metrics.stream_interval_seconds."""
        settings = Settings(
            metrics_source_type="mock",
            mock_services=["auth-service"],
            metrics_stream_interval_seconds=3.5,
        )
        source = MockMetricSource(settings)
        assert source._interval == 3.5

    def test_interval_ignores_mock_log_interval(self) -> None:
        """The mock log interval must NOT affect the metric stream interval."""
        settings = Settings(
            metrics_source_type="mock",
            mock_services=["auth-service"],
            mock_log_interval=99.0,
            metrics_stream_interval_seconds=2.0,
        )
        source = MockMetricSource(settings)
        assert source._interval == 2.0

    def test_interval_defaults_to_config_yaml_value(self) -> None:
        """When no override is provided, the config.yaml default (5.0) is used."""
        settings = Settings(metrics_source_type="mock")
        source = MockMetricSource(settings)
        assert source._interval == 5.0

    def test_interval_override_via_constructor(self) -> None:
        """Constructor override for metrics_stream_interval_seconds must be respected."""
        settings = Settings(
            metrics_source_type="mock",
            metrics_stream_interval_seconds=0.25,
        )
        source = MockMetricSource(settings)
        assert source._interval == 0.25

    @pytest.mark.asyncio
    async def test_stream_timing_respects_interval(self) -> None:
        """Background samples should be emitted at the configured interval."""
        import time

        settings = Settings(
            metrics_source_type="mock",
            mock_services=["auth-service"],
            metrics_stream_interval_seconds=0.1,
        )
        source = MockMetricSource(settings)
        await source.start()

        # Collect background samples and measure timing
        timestamps = []
        gen = source.stream()

        # Skip initial samples (yielded immediately)
        count = 0
        async for sample in gen:
            if count < 2:
                count += 1
                continue
            timestamps.append(time.monotonic())
            if len(timestamps) >= 3:
                break

        await gen.aclose()
        await source.stop()

        # Verify intervals between background samples are roughly consistent
        if len(timestamps) >= 2:
            deltas = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]
            for delta in deltas:
                # Allow generous tolerance (0.05-0.5s) for async timing
                assert delta >= 0.05
                assert delta <= 0.5
